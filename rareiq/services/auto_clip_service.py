from __future__ import annotations

import json
import math
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from rareiq.services.experience_service import ExperienceService
from rareiq.services.instant_replay_service import InstantReplayService
from rareiq.services.media_storage import atomic_json


class AutoClipService:
    """Verified-pull clips from the existing Program buffer; never arms on boot."""

    TIERS = {"standard": 0, "low": 1, "medium": 2, "grail": 3}
    DEFAULTS = {"minimum_tier": "medium", "pre_seconds": 5, "post_seconds": 3}
    MAX_PENDING = 3

    def __init__(self, replay: InstantReplayService, config_path: Path) -> None:
        self.replay, self.config_path = replay, config_path
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._config = dict(self.DEFAULTS)
        self._enabled = False
        self._armed_at = 0.0
        self._last_generation = -1
        self._pending: list[dict[str, Any]] = []
        self._saving: dict[str, Any] | None = None
        self._saved_count = 0
        self._last_result: dict[str, Any] | None = None
        try:
            self._config = self._validate(json.loads(config_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass

    @classmethod
    def _validate(cls, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("minimum_tier") not in cls.TIERS:
            raise ValueError("invalid_auto_clip_settings")
        result = {"minimum_tier": payload["minimum_tier"]}
        for key, maximum in (("pre_seconds", 10), ("post_seconds", 6)):
            value = payload.get(key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid_auto_clip_settings")
            result[key] = value
        return result

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._enabled or self._saving:
                return {"updated": False, "reason": "disarm_auto_clip_before_editing"}
            try:
                config = self._validate(payload)
                if config["pre_seconds"] + config["post_seconds"] > self.replay.buffer_seconds - 2:
                    raise ValueError("invalid_auto_clip_settings")
                atomic_json(self.config_path, config)
            except (TypeError, ValueError):
                return {"updated": False, "reason": "invalid_auto_clip_settings"}
            except OSError:
                return {"updated": False, "reason": "auto_clip_settings_unavailable"}
            self._config = config
            return {"updated": True, **self.snapshot()}

    def arm(self, enabled: bool, *, baseline_generation: int = -1) -> dict[str, Any]:
        with self._lock:
            if enabled and not self._enabled:
                if self._saving:
                    return {"updated": False, "reason": "auto_clip_save_finishing"}
                self._cancel = threading.Event()
                self._armed_at = time.time()
                self._last_generation = max(self._last_generation, baseline_generation)
            if not enabled:
                self._cancel.set()
                if self._pending or self._saving:
                    self._last_result = {"created": False, "reason": "auto_clip_cancelled"}
                self._pending.clear()
            self._enabled = enabled
            return {"updated": True, **self.snapshot()}

    @staticmethod
    def verified(snapshot: dict[str, Any]) -> bool:
        card = snapshot.get("primary_candidate")
        return bool(
            isinstance(card, dict) and card and not card.get("provisional")
            and snapshot.get("verification_state") == "VERIFIED"
            and all(snapshot.get(key) is True for key in (
                "has_reference_evidence", "identity_consistent", "recognition_locked", "result_current", "card_present",
            ))
            and not snapshot.get("identity_conflicts")
        )

    def observe(self, snapshot: dict[str, Any]) -> None:
        """Event-loop safe: validate and enqueue references only, no encoding or IO."""
        with self._lock:
            if not self._enabled or not self.verified(snapshot):
                return
            try:
                generation = int(snapshot["generation"])
                updated = float(snapshot["updated_at"])
                if generation < 0 or not math.isfinite(updated) or not max(self._armed_at, time.time() - 2) <= updated <= time.time() + 1:
                    return
            except (KeyError, TypeError, ValueError, OverflowError):
                return
            if generation <= self._last_generation:
                return
            # One attempt per physical-card generation, including reported skips.
            self._last_generation = generation
            card = snapshot["primary_candidate"]
            tier = ExperienceService.hit_decision(card)["tier"]
            if self.TIERS[tier] < self.TIERS[self._config["minimum_tier"]]:
                return
            name = str(card.get("english_name") or card.get("name") or card.get("card_name") or "Verified pull")[:60]
            if len(self._pending) + bool(self._saving) >= self.MAX_PENDING:
                self._last_result = {"created": False, "reason": "auto_clip_queue_full", "name": name}
                return
            now = time.time()
            start, end = now - self._config["pre_seconds"], now + self._config["post_seconds"]
            window = self.replay.buffer_window(start, now)
            if not self._complete_window(window["frames"], start, now):
                self._last_result = {"created": False, "reason": "auto_clip_buffer_warming", "name": name}
                return
            self._pending.append({"start": start, "end": end, "epoch": window["epoch"], "generation": generation, "name": name, "tier": tier, "slot_id": window["frames"][-1][1], "cancel": self._cancel})

    def _complete_window(self, frames: list, start: float, end: float) -> bool:
        tolerance = max(.5, 2 / self.replay.fps)
        return bool(
            frames and frames[0][0] - start <= tolerance and end - frames[-1][0] <= tolerance
            and len({frame[1] for frame in frames}) == 1
            and all(0 < b[0] - a[0] <= tolerance for a, b in zip(frames, frames[1:]))
        )

    def process_pending(self) -> None:
        with self._lock:
            if not self._enabled or self._saving or not self._pending or time.time() < self._pending[0]["end"]:
                return
            job = self._pending.pop(0)
            self._saving = job
        try:
            window = self.replay.buffer_window(job["start"], job["end"])
            if window["epoch"] != job["epoch"] or not self._complete_window(window["frames"], job["start"], job["end"]):
                result = {"created": False, "reason": "auto_clip_buffer_interrupted"}
            else:
                metadata = {key: job[key] for key in ("generation", "tier", "start", "end")}
                result = self.replay.save_frames(window["frames"], job["name"], auto_clip=metadata, cancelled=job["cancel"].is_set)
        except Exception:
            # The worker must stay alive after an encoder/driver failure.
            result = {"created": False, "reason": "auto_clip_save_failed"}
        with self._lock:
            self._saving = None
            self._last_result = {**result, "name": job["name"]}
            if result.get("created"):
                self._saved_count += 1

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="rareiq-auto-clip", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(.2):
            self.process_pending()

    def stop(self) -> None:
        self.arm(False)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled, "config": dict(self._config), "saved_count": self._saved_count,
                "pending_count": len(self._pending), "saving": self._saving is not None,
                "next_due_at": self._pending[0]["end"] if self._pending else None,
                "last_result": deepcopy(self._last_result),
                "fps": self.replay.fps, "audio": False, "format": "mp4", "max_highlights": self.replay.MAX_HIGHLIGHTS,
            }
