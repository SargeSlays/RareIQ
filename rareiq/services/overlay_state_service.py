from __future__ import annotations

import threading
import time
from typing import Any


class OverlayStateService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "status": "ready",
            "current_card": None,
            "pack_number": 1,
            "pack_total": 0.0,
            "box_total": 0.0,
            "session_total": 0.0,
            "confidence": 0.0,
            "reaction": None,
            "updated_at": time.time(),
        }

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state.update(payload)
            self._state["updated_at"] = time.time()
            return dict(self._state)

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._state.update({
                "status": "ready",
                "current_card": None,
                "pack_number": 1,
                "pack_total": 0.0,
                "box_total": 0.0,
                "session_total": 0.0,
                "confidence": 0.0,
                "reaction": None,
                "updated_at": time.time(),
            })
            return dict(self._state)
