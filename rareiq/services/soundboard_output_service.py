"""Ephemeral audio transport state. No device driver or second capture needed."""
from __future__ import annotations

import math
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


class SoundboardOutputService:
    LEASE_SECONDS = 4.0
    MAX_PUBLISHERS = 8
    MAX_VOICES = 16

    def __init__(self, clock: Callable[[], float] = time.monotonic, *, settings_path: Path | None = None):
        self._clock = clock
        self._lock = threading.Lock()
        self._publishers: dict[str, dict[str, Any]] = {}
        self._receivers: set[str] = set()
        self._settings_path = settings_path
        self._settings = {"enabled": False, "local_monitor": True, "revision": 0}
        if settings_path is not None:
            try:
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
                if (isinstance(saved, dict) and type(saved.get("enabled")) is bool
                        and type(saved.get("local_monitor")) is bool
                        and type(saved.get("revision")) is int and saved["revision"] >= 0):
                    self._settings = {key: saved[key] for key in self._settings}
            except (OSError, ValueError, TypeError):
                pass

    def settings(self) -> dict:
        with self._lock:
            return dict(self._settings)

    def _persist_settings(self, value: dict) -> None:
        if self._settings_path is None:
            return
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._settings_path.with_suffix(self._settings_path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(self._settings_path)

    def configure_settings(self, payload: dict) -> dict:
        if any(key not in {"enabled", "local_monitor"} or type(value) is not bool for key, value in payload.items()):
            raise ValueError("Audio routing settings must be boolean enabled/local_monitor values")
        with self._lock:
            updated = {**self._settings, **payload}
            if updated != self._settings:
                updated["revision"] += 1
                self._persist_settings(updated)
                self._settings = updated
            return dict(self._settings)

    def _expire(self, now: float) -> None:
        self._publishers = {key: value for key, value in self._publishers.items() if now - value["at"] < self.LEASE_SECONDS}

    def publish(self, owner: str, sequence: int, voices: list[dict], assets: dict[str, dict]) -> dict:
        if not owner or len(owner) > 80 or len(voices) > self.MAX_VOICES:
            raise ValueError("Invalid audio session or too many simultaneous sounds")
        normalized = []
        seen = set()
        for voice in voices:
            identifier = str(voice.get("id") or "")
            asset = assets.get(str(voice.get("asset_id") or ""))
            if not identifier or len(identifier) > 80 or identifier in seen or not asset or asset.get("kind") != "audio":
                raise ValueError("Sound must reference an available audio asset and a unique playback ID")
            position, volume = float(voice.get("position", 0)), float(voice.get("volume", 1))
            if not all(math.isfinite(value) for value in (position, volume)) or position < 0 or not 0 <= volume <= 1:
                raise ValueError("Invalid audio position or volume")
            seen.add(identifier)
            normalized.append({"id": f"{owner}:{identifier}", "url": asset["url"], "position": position, "volume": volume})
        with self._lock:
            now = self._clock()
            self._expire(now)
            previous = self._publishers.get(owner)
            if previous and sequence <= previous["sequence"]:
                return {"ok": True, "accepted": False, "receivers": len(self._receivers), "settings": dict(self._settings)}
            if not previous and len(self._publishers) >= self.MAX_PUBLISHERS:
                raise ValueError("Too many active soundboard sessions")
            self._publishers[owner] = {"sequence": sequence, "at": now, "voices": normalized}
            return {"ok": True, "accepted": True, "receivers": len(self._receivers), "settings": dict(self._settings)}

    def snapshot(self) -> dict:
        with self._lock:
            now = self._clock()
            self._expire(now)
            voices = [{**voice, "position": voice["position"] + now - session["at"]}
                      for session in self._publishers.values() for voice in session["voices"]]
            return {"voices": voices, "receivers": len(self._receivers), "lease_seconds": self.LEASE_SECONDS}

    def connect(self, receiver: str) -> None:
        with self._lock:
            if len(self._receivers) >= 32:
                raise ValueError("Too many audio receivers")
            self._receivers.add(receiver)

    def disconnect(self, receiver: str) -> None:
        with self._lock:
            self._receivers.discard(receiver)
