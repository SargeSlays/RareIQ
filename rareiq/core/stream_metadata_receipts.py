"""Bounded metadata request fingerprints; no credentials or provider metadata.

Atomic mutations merge under a shared per-path process lock. This is deliberately
not a cross-process writer protocol; the backend owns its one production store.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import os
from pathlib import Path
import re
import stat
import threading
from uuid import uuid4

from rareiq.core.platform_credentials import _owner_only
from rareiq.core.runtime_paths import _resolved


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")
_INVALID = "metadata_recovery_storage_invalid"
_UNAVAILABLE = "metadata_recovery_storage_unavailable"


class StreamMetadataReceiptStore:
    MAX_BYTES = 65536
    MAX_RECEIPTS = 128

    def __init__(self, path):
        try:
            requested = Path(path)
            if not requested.is_absolute():
                raise ValueError()
            # Resolve the parent but retain the final name, so lstat can reject
            # a final symlink rather than silently following it to its target.
            self.path = _resolved(requested.parent) / requested.name
            source = _resolved(Path(__file__)).parents[2]
            if self.path == source or source in self.path.parents or not requested.name:
                raise ValueError()
        except Exception:
            raise ValueError(_INVALID) from None
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(os.path.normcase(str(self.path)), threading.RLock())

    @staticmethod
    def _regular(info):
        return stat.S_ISREG(info.st_mode) and not bool(getattr(info, "st_file_attributes", 0) & 0x400)

    def _load(self):
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            # Windows can report FILE_NOT_FOUND when an ancestor is a regular
            # file. Distinguish a new store from an unusable parent before any
            # credential access or provider request is allowed.
            for parent in self.path.parents:
                try:
                    ancestor = parent.stat()
                except FileNotFoundError:
                    continue
                except OSError:
                    raise ValueError(_UNAVAILABLE) from None
                if not stat.S_ISDIR(ancestor.st_mode):
                    raise ValueError(_UNAVAILABLE)
                return OrderedDict()
            raise ValueError(_UNAVAILABLE)
        except OSError:
            raise ValueError(_UNAVAILABLE) from None
        if not self._regular(info) or info.st_size > self.MAX_BYTES:
            raise ValueError(_INVALID)
        descriptor = None
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
            opened = os.fstat(descriptor)
            if not self._regular(opened) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError(_INVALID)
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = None
                raw = handle.read(self.MAX_BYTES + 1)
        except ValueError:
            raise
        except OSError:
            raise ValueError(_UNAVAILABLE) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(raw) > self.MAX_BYTES:
            raise ValueError(_INVALID)

        def unique(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError()
                value[key] = item
            return value
        try:
            value = json.loads(raw, object_pairs_hook=unique)
            if (not isinstance(value, dict) or set(value) != {"version", "receipts"}
                    or type(value["version"]) is not int or value["version"] != 1
                    or not isinstance(value["receipts"], list) or len(value["receipts"]) > self.MAX_RECEIPTS):
                raise ValueError()
            records = OrderedDict()
            for item in value["receipts"]:
                if (not isinstance(item, dict) or set(item) != {"platform", "request_id", "fingerprint", "state"}
                        or item["platform"] not in ("twitch", "youtube", "kick")
                        or not isinstance(item["request_id"], str) or not _ID.fullmatch(item["request_id"])
                        or not isinstance(item["fingerprint"], str) or not _FINGERPRINT.fullmatch(item["fingerprint"])
                        or item["state"] not in ("reserved", "applied")):
                    raise ValueError()
                key = (item["platform"], item["request_id"])
                if key in records:
                    raise ValueError()
                records[key] = {"fingerprint": item["fingerprint"], "state": item["state"]}
            return records
        except Exception:
            raise ValueError(_INVALID) from None

    def load(self):
        with self._lock:
            return self._load()

    def _persist(self, records):
        raw = json.dumps({"version": 1, "receipts": [
            {"platform": key[0], "request_id": key[1], "fingerprint": receipt["fingerprint"], "state": receipt["state"]}
            for key, receipt in records.items()]}, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        if len(records) > self.MAX_RECEIPTS or len(raw) > self.MAX_BYTES:
            raise ValueError(_INVALID)
        temporary = self.path.with_name("." + self.path.name + "." + uuid4().hex + ".tmp")
        descriptor = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            _owner_only(temporary)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                current = self.path.lstat()
            except FileNotFoundError:
                current = None
            if current is not None and not self._regular(current):
                raise ValueError(_INVALID)
            os.replace(temporary, self.path)
        except Exception as exc:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ValueError(_INVALID if str(exc) == _INVALID else _UNAVAILABLE) from None

    def reserve(self, key, fingerprint, *, maximum=128, protected=()):
        with self._lock:
            records = self._load()
            if key in records:
                if records[key]["fingerprint"] != fingerprint:
                    raise ValueError("request_id_conflict")
                return dict(records[key]), False
            maximum = min(maximum, self.MAX_RECEIPTS)
            if len(records) >= maximum:
                for old_key, record in list(records.items()):
                    if record["state"] == "applied" and old_key not in protected:
                        del records[old_key]
                        break
                else:
                    raise ValueError("receipt_capacity_reached")
            receipt = {"fingerprint": fingerprint, "state": "reserved"}
            records[key] = receipt
            self._persist(records)
            return dict(receipt), True

    def finish(self, key, fingerprint, state):
        with self._lock:
            records = self._load()
            receipt = records.get(key)
            if receipt is None or receipt["fingerprint"] != fingerprint or state not in ("reserved", "applied"):
                raise ValueError(_INVALID)
            if receipt["state"] != state:
                receipt["state"] = state
                self._persist(records)

    def remove(self, key):
        with self._lock:
            records = self._load()
            if key in records:
                del records[key]
                self._persist(records)
