"""Local rehearsal latch. No media, publishing, provider, or recording actions.

One backend owns the store. Its synchronous latch is also used by native Start
reservations; an entry preflight therefore runs only after publishing is blocked.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from uuid import uuid4

from rareiq.core.platform_credentials import _owner_only
from rareiq.core.runtime_paths import _resolved


CHECKS = (
    ("video", "Video and layouts"), ("audio_live", "Live audio"),
    ("audio_vod", "VOD audio"), ("guests", "Guests and backstage"),
    ("screens", "Screens and sources"), ("transitions", "Transitions and cues"),
    ("recovery", "Source loss and recovery"),
)
STATUSES = frozenset({"not_tested", "passed", "needs_attention"})
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_HEX = re.compile(r"[a-f0-9]{32}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_MODES = frozenset({"production", "entering", "rehearsal", "recovery_required"})
_STORAGE = frozenset({"rehearsal_storage_invalid", "rehearsal_storage_unavailable", "rehearsal_storage_changed", "rehearsal_recovery_interrupted"})


class RehearsalError(ValueError):
    def __init__(self, reason, status=409):
        self.reason, self.status = reason, status
        super().__init__(reason)


class RehearsalService:
    MAX_BYTES = 131072
    MAX_RECEIPTS = 64
    MAX_HISTORY = 128
    IDLE_TIMEOUT_SECONDS = 10

    def __init__(self, path, *, idle_provider, exit_idle_provider=None):
        self._path_error = None
        try:
            requested = Path(path)
            if not requested.is_absolute() or not requested.name:
                raise ValueError()
            self.path = _resolved(requested.parent) / requested.name
            source = _resolved(Path(__file__)).parents[2]
            if self.path == source or source in self.path.parents:
                raise ValueError()
        except Exception:
            # Keep the dashboard available to explain invalid configuration;
            # this instance must never recover or write through an unsafe path.
            self.path = None
            self._path_error = "rehearsal_storage_invalid"
        self._lock = threading.RLock()
        self._operations = asyncio.Lock()
        self._publishing_work = 0
        self._idle_provider = idle_provider
        self._exit_idle_provider = exit_idle_provider or idle_provider
        self._storage_error = None
        self._disk_token = None
        self._marker_path = self.path.with_name("." + self.path.name + ".recovering.json") if self.path is not None else None
        self._marker_pending = False
        self._state = {"version": 1, "mode": "production", "revision": 0,
                       "generation": uuid4().hex, "checks": dict.fromkeys(dict(CHECKS), "not_tested"),
                       "receipts": [], "history": []}
        if self._path_error:
            self._block(self._path_error)
            return
        try:
            marker, _ = self._read(self._marker_path)
            if marker is not None:
                self._state = marker
                self._marker_pending = True
                self._block("rehearsal_recovery_interrupted")
                return
            document, token = self._read()
            if document is not None:
                self._state, self._disk_token = document, token
                if document["mode"] == "entering" or any(item["state"] == "pending" and item["action"] in {"exit", "recover"} for item in document["receipts"]):
                    self._state["mode"] = "recovery_required"
                    self._state["reason"] = "rehearsal_interrupted"
        except RehearsalError as exc:
            self._block(exc.reason)

    @staticmethod
    def _regular(info):
        return stat.S_ISREG(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400)

    @staticmethod
    def _document(value):
        fields = {"version", "mode", "revision", "generation", "checks", "receipts", "history"}
        if (not isinstance(value, dict) or set(value) - (fields | {"reason"}) or not fields <= set(value)
                or type(value["version"]) is not int or value["version"] != 1
                or value["mode"] not in _MODES or type(value["revision"]) is not int
                or not 0 <= value["revision"] <= 2**53 - 1
                or not isinstance(value["generation"], str) or not _HEX.fullmatch(value["generation"])
                or not isinstance(value["checks"], dict) or set(value["checks"]) != set(dict(CHECKS))
                or any(status not in STATUSES for status in value["checks"].values())
                or "reason" in value and value["reason"] not in _STORAGE | {"rehearsal_interrupted", "rehearsal_idle_unavailable"}
                or not isinstance(value["receipts"], list) or len(value["receipts"]) > RehearsalService.MAX_RECEIPTS
                or not isinstance(value["history"], list) or len(value["history"]) > RehearsalService.MAX_HISTORY):
            raise ValueError()
        if (value["mode"] == "recovery_required" and "reason" not in value
                or value["mode"] != "recovery_required" and "reason" in value):
            raise ValueError()
        ids = set()
        for item in value["receipts"]:
            if (not isinstance(item, dict) or set(item) != {"request_id", "fingerprint", "action", "state", "reason"}
                    or not isinstance(item["request_id"], str) or not _ID.fullmatch(item["request_id"])
                    or item["request_id"] in ids or not isinstance(item["fingerprint"], str)
                    or not _HASH.fullmatch(item["fingerprint"]) or item["action"] not in {"enter", "exit", "mark", "recover"}
                    or item["state"] not in {"pending", "done", "failed"}
                    or item["reason"] not in {None, "rehearsal_production_busy", "rehearsal_encoding_active", "rehearsal_idle_unavailable"}):
                raise ValueError()
            ids.add(item["request_id"])
        for item in value["history"]:
            if (not isinstance(item, dict) or set(item) != {"action", "outcome", "revision", "at", "actor_kind", "attribution"}
                    or item["action"] not in {"enter", "exit", "mark", "recover"}
                    or item["outcome"] not in {"requested", "succeeded", "blocked"}
                    or type(item["revision"]) is not int or not 0 <= item["revision"] <= value["revision"]
                    or type(item["at"]) not in (int, float) or not 0 <= item["at"] <= 1e12
                    or item["actor_kind"] != "local_operator" or item["attribution"] != "unverified"):
                raise ValueError()
        return value

    def _read(self, path=None):
        path = self.path if path is None else path
        try:
            info = path.lstat()
        except FileNotFoundError:
            for parent in path.parents:
                try:
                    ancestor = parent.stat()
                except FileNotFoundError:
                    continue
                except OSError:
                    raise RehearsalError("rehearsal_storage_unavailable", 503) from None
                if not stat.S_ISDIR(ancestor.st_mode):
                    raise RehearsalError("rehearsal_storage_unavailable", 503)
                return None, None
            raise RehearsalError("rehearsal_storage_unavailable", 503)
        except OSError:
            raise RehearsalError("rehearsal_storage_unavailable", 503) from None
        if not self._regular(info) or info.st_size > self.MAX_BYTES:
            raise RehearsalError("rehearsal_storage_invalid", 503)
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            if not self._regular(opened) or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise RehearsalError("rehearsal_storage_invalid", 503)
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                raw = handle.read(self.MAX_BYTES + 1)
            if len(raw) > self.MAX_BYTES:
                raise RehearsalError("rehearsal_storage_invalid", 503)
        except OSError:
            raise RehearsalError("rehearsal_storage_unavailable", 503) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        try:
            value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            return self._document(value), hashlib.sha256(raw).hexdigest()
        except Exception:
            raise RehearsalError("rehearsal_storage_invalid", 503) from None

    def _block(self, reason):
        self._state["mode"], self._state["reason"] = "recovery_required", reason
        if reason in _STORAGE:
            self._storage_error = reason

    def _verify(self):
        if self._storage_error:
            return
        try:
            _, token = self._read()
            if token != self._disk_token:
                raise RehearsalError("rehearsal_storage_changed", 503)
        except RehearsalError as exc:
            self._block(exc.reason)

    def _snapshot(self):
        mode = self._state["mode"]
        result = {"mode": mode, "active": mode != "production", "publishing_allowed": mode == "production" and not self._storage_error and not self._marker_pending,
                  "revision": self._state["revision"], "generation": self._state["generation"],
                  "publishing_work_pending": self._publishing_work > 0,
                  "checks": [{"id": key, "label": label, "status": self._state["checks"][key]} for key, label in CHECKS]}
        if self._state.get("reason"):
            result["reason"] = self._state["reason"]
        return result

    def snapshot(self):
        with self._lock:
            self._verify()
            return self._snapshot()

    def publishing_allowed(self):
        with self._lock:
            self._verify()
            return self._state["mode"] == "production" and not self._storage_error and not self._marker_pending

    @contextmanager
    def publishing_lease(self):
        """Reserve a production-only action without holding a lock across awaits."""
        with self._lock:
            if not self.publishing_allowed():
                raise RehearsalError("rehearsal_publishing_blocked")
            self._publishing_work += 1
        try:
            yield
        finally:
            with self._lock:
                self._publishing_work -= 1

    @contextmanager
    def local_encoding_lease(self, generation):
        """Atomically reserve local encoding before an exit can observe idle."""
        with self._lock:
            self._verify()
            if self._state["mode"] != "rehearsal" or generation != self._state["generation"]:
                raise RehearsalError("rehearsal_generation_conflict")
            if any(item["state"] == "pending" and item["action"] in {"exit", "recover"} for item in self._state["receipts"]):
                raise RehearsalError("rehearsal_production_busy")
            yield

    def _parent(self):
        # A replacement junction/symlink must not redirect a write or recovery.
        if _resolved(self.path.parent) != self.path.parent:
            raise RehearsalError("rehearsal_storage_changed", 503)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not stat.S_ISDIR(self.path.parent.stat().st_mode):
            raise RehearsalError("rehearsal_storage_unavailable", 503)
        if os.name == "nt":
            _owner_only(self.path.parent)

    def _canonical_parent(self):
        if _resolved(self.path.parent) != self.path.parent:
            raise RehearsalError("rehearsal_storage_changed", 503)

    def _persist(self, candidate):
        self._verify()
        if self._storage_error:
            raise RehearsalError(self._storage_error, 503)
        raw = json.dumps(candidate, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(raw) > self.MAX_BYTES:
            self._block("rehearsal_storage_invalid")
            raise RehearsalError("rehearsal_storage_invalid", 503)
        temporary = self.path.with_name("." + self.path.name + "." + uuid4().hex + ".tmp")
        descriptor = None
        try:
            self._parent()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            _owner_only(temporary)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            self._verify()
            if self._storage_error:
                raise RehearsalError(self._storage_error, 503)
            self._canonical_parent()
            os.replace(temporary, self.path)
            self._disk_token = hashlib.sha256(raw).hexdigest()
            self._state = candidate
        except Exception as exc:
            reason = exc.reason if isinstance(exc, RehearsalError) else "rehearsal_storage_unavailable"
            self._block(reason)
            raise RehearsalError(reason, 503) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _prepare(self, action, request_id, expected_revision, generation=None, *, allow_recovery=False, **fields):
        if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
            raise RehearsalError("invalid_rehearsal_request_id", 400)
        if type(expected_revision) is not int or not 0 <= expected_revision < 2**53 - 2:
            raise RehearsalError("invalid_rehearsal_revision", 400)
        if action != "enter" and (not isinstance(generation, str) or not _HEX.fullmatch(generation)):
            raise RehearsalError("invalid_rehearsal_generation", 400)
        fingerprint = hashlib.sha256(json.dumps([action, expected_revision, generation, fields], sort_keys=True).encode()).hexdigest()
        self._verify()
        if self._path_error or self._storage_error and not allow_recovery:
            raise RehearsalError(self._path_error or self._storage_error, 503)
        previous = next((item for item in self._state["receipts"] if item["request_id"] == request_id), None)
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise RehearsalError("rehearsal_request_conflict")
            if previous["state"] == "failed":
                raise RehearsalError(previous["reason"])
            if previous["state"] == "pending":
                raise RehearsalError("rehearsal_interrupted")
            return None
        if expected_revision != self._state["revision"]:
            raise RehearsalError("rehearsal_revision_conflict")
        if action != "enter" and generation != self._state["generation"]:
            raise RehearsalError("rehearsal_generation_conflict")
        return {"request_id": request_id, "fingerprint": fingerprint, "action": action, "state": "pending", "reason": None}

    @staticmethod
    def _event(candidate, action, outcome):
        candidate["history"].append({"action": action, "outcome": outcome, "revision": candidate["revision"],
                                     "at": time.time(), "actor_kind": "local_operator", "attribution": "unverified"})
        candidate["history"] = candidate["history"][-RehearsalService.MAX_HISTORY:]

    async def _idle(self, provider):
        try:
            async def observe():
                value = provider()
                return await value if inspect.isawaitable(value) else value
            result = await asyncio.wait_for(observe(), self.IDLE_TIMEOUT_SECONDS)
            if not isinstance(result, dict) or type(result.get("ready")) is not bool:
                return None
            return result["ready"]
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    async def enter(self, request_id, expected_revision):
        async with self._operations:
            with self._lock:
                receipt = self._prepare("enter", request_id, expected_revision)
                if receipt is None:
                    return self._snapshot()
                if self._state["mode"] != "production":
                    raise RehearsalError("rehearsal_already_active")
                if self._publishing_work:
                    raise RehearsalError("rehearsal_production_busy")
                prior = deepcopy(self._state)
                candidate = deepcopy(self._state)
                candidate.update(mode="entering", revision=candidate["revision"] + 1, generation=uuid4().hex,
                                 checks=dict.fromkeys(dict(CHECKS), "not_tested"))
                candidate.pop("reason", None)
                candidate["receipts"] = (candidate["receipts"] + [receipt])[-self.MAX_RECEIPTS:]
                self._event(candidate, "enter", "requested")
                # Gate first, including when the durable write itself fails.
                self._state["mode"] = "entering"
                self._persist(candidate)
            try:
                ready = await self._idle(self._idle_provider)
            except asyncio.CancelledError:
                with self._lock:
                    self._block("rehearsal_interrupted")
                raise
            with self._lock:
                candidate = deepcopy(self._state)
                candidate["revision"] += 1
                receipt = candidate["receipts"][-1]
                if ready is True:
                    candidate["mode"], receipt["state"] = "rehearsal", "done"
                    self._event(candidate, "enter", "succeeded")
                elif ready is False:
                    candidate["mode"] = "production"
                    candidate["generation"], candidate["checks"] = prior["generation"], prior["checks"]
                    receipt.update(state="failed", reason="rehearsal_production_busy")
                    self._event(candidate, "enter", "blocked")
                else:
                    candidate.update(mode="recovery_required", reason="rehearsal_idle_unavailable")
                    receipt.update(state="failed", reason="rehearsal_idle_unavailable")
                    self._event(candidate, "enter", "blocked")
                self._persist(candidate)
                if ready is not True:
                    raise RehearsalError(receipt["reason"])
                return self._snapshot()

    async def exit(self, request_id, expected_revision, generation):
        async with self._operations:
            with self._lock:
                receipt = self._prepare("exit", request_id, expected_revision, generation)
                if receipt is None:
                    return self._snapshot()
                if self._state["mode"] not in {"rehearsal", "recovery_required"}:
                    raise RehearsalError("rehearsal_not_active")
                candidate = deepcopy(self._state)
                candidate["revision"] += 1
                candidate["receipts"] = (candidate["receipts"] + [receipt])[-self.MAX_RECEIPTS:]
                self._event(candidate, "exit", "requested")
                self._persist(candidate)
            ready = await self._idle(self._exit_idle_provider)
            with self._lock:
                self._verify()
                if self._storage_error:
                    raise RehearsalError(self._storage_error, 503)
                candidate = deepcopy(self._state)
                candidate["revision"] += 1
                receipt = candidate["receipts"][-1]
                if ready is True:
                    candidate["mode"] = "production"
                    candidate.pop("reason", None)
                    receipt["state"] = "done"
                    self._event(candidate, "exit", "succeeded")
                else:
                    receipt.update(state="failed", reason="rehearsal_encoding_active" if ready is False else "rehearsal_idle_unavailable")
                    self._event(candidate, "exit", "blocked")
                # Publication opens only after the production state is durable.
                self._persist(candidate)
                if ready is not True:
                    raise RehearsalError(receipt["reason"])
                return self._snapshot()

    async def mark(self, check_id, status, request_id, expected_revision, generation):
        if not isinstance(check_id, str) or check_id not in dict(CHECKS) or not isinstance(status, str) or status not in STATUSES:
            raise RehearsalError("invalid_rehearsal_check", 400)
        async with self._operations:
            with self._lock:
                receipt = self._prepare("mark", request_id, expected_revision, generation, check_id=check_id, status=status)
                if receipt is None:
                    return self._snapshot()
                if self._state["mode"] != "rehearsal":
                    raise RehearsalError("rehearsal_not_ready")
                candidate = deepcopy(self._state)
                candidate["revision"] += 1
                candidate["checks"][check_id] = status
                receipt["state"] = "done"
                candidate["receipts"] = (candidate["receipts"] + [receipt])[-self.MAX_RECEIPTS:]
                self._event(candidate, "mark", "succeeded")
                self._persist(candidate)
                return self._snapshot()

    def _recovery_marker(self, candidate):
        """A crash between quarantine and replacement must not look like first use."""
        marker, _ = self._read(self._marker_path)
        if marker is not None:
            self._marker_pending = True
            return
        raw = json.dumps(candidate, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        temporary = self._marker_path.with_name("." + self._marker_path.name + "." + uuid4().hex + ".tmp")
        descriptor = None
        try:
            self._parent()
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            _owner_only(temporary)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            # A concurrently introduced marker is never overwritten.
            if self._marker_path.exists() or self._marker_path.is_symlink():
                raise RehearsalError("rehearsal_storage_changed", 503)
            self._canonical_parent()
            os.rename(temporary, self._marker_path)
            self._marker_pending = True
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _preserve(self, path):
        """Rename only the named file/link; never read or follow its contents."""
        self._canonical_parent()
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if not self._regular(info) and not stat.S_ISLNK(info.st_mode):
            raise RehearsalError("rehearsal_storage_invalid", 503)
        if self._regular(info):
            _owner_only(path)
        archive = path.with_name(".rehearsal-state-corrupt-" + uuid4().hex + ".json")
        if archive.exists() or archive.is_symlink():
            raise RehearsalError("rehearsal_storage_changed", 503)
        self._canonical_parent()
        os.rename(path, archive)

    async def recover(self, request_id, expected_revision, generation):
        """Explicit operator recovery; retain the broken file and never start media."""
        async with self._operations:
            with self._lock:
                receipt = self._prepare("recover", request_id, expected_revision, generation, allow_recovery=True)
                if receipt is None:
                    return self._snapshot()
                if self._state["mode"] != "recovery_required":
                    raise RehearsalError("rehearsal_recovery_not_required")
            ready = await self._idle(self._exit_idle_provider)
            with self._lock:
                if ready is not True:
                    raise RehearsalError("rehearsal_encoding_active" if ready is False else "rehearsal_idle_unavailable")
                candidate = deepcopy(self._state)
                candidate.update(mode="recovery_required", reason="rehearsal_recovery_interrupted",
                                 revision=candidate["revision"] + 1, generation=uuid4().hex)
                candidate["receipts"] = (candidate["receipts"] + [receipt])[-self.MAX_RECEIPTS:]
                self._event(candidate, "recover", "requested")
                try:
                    self._parent()
                    try:
                        self._read(self._marker_path)
                        marker_invalid = False
                    except RehearsalError:
                        marker_invalid = True
                    if marker_invalid:
                        # Keep the broken marker blocking while a replacement
                        # main-file latch is committed. It is then safe to
                        # preserve the marker itself, even if recovery crashes.
                        self._preserve(self.path)
                        self._disk_token, self._storage_error = None, None
                        self._persist(candidate)
                        self._preserve(self._marker_path)
                    else:
                        self._recovery_marker(candidate)
                        self._preserve(self.path)
                        self._disk_token, self._storage_error = None, None
                    candidate.update(mode="production")
                    candidate.pop("reason", None)
                    candidate["receipts"][-1]["state"] = "done"
                    self._event(candidate, "recover", "succeeded")
                    self._persist(candidate)
                    self._canonical_parent()
                    self._marker_path.unlink(missing_ok=True)
                    self._marker_pending = False
                except Exception as exc:
                    reason = exc.reason if isinstance(exc, RehearsalError) else "rehearsal_storage_unavailable"
                    self._block(reason)
                    raise RehearsalError(reason, 503) from None
                return self._snapshot()
