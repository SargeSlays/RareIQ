from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any


class OverlayStateService:
    def __init__(self, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._state_path = state_path or (
            Path(__file__).resolve().parents[1] / "data" / "overlay_presentation.json"
        )
        self._state: dict[str, Any] = {
            "status": "ready",
            "current_card": None,
            "pack_number": 1,
            "pack_total": 0.0,
            "box_total": 0.0,
            "session_total": 0.0,
            "confidence": 0.0,
            "reaction": None,
            "pokedex_on_air": False,
            "pokedex_current": None,
            "broadcast_graphic": {"visible": False, "kind": "lower-third", "style": "glass", "title": "", "subtitle": "", "accent": "cyan", "image_url": "", "duration_ms": 0, "generation": 0},
            "production_screen": {"visible": False, "mode": "starting-soon", "title": "Starting Soon", "message": "The stream will begin shortly.", "countdown_seconds": 300, "started_at": 0.0, "accent": "cyan", "generation": 0},
            "updated_at": time.time(),
        }
        self._restore_presentation()

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state.update(payload)
            self._state["updated_at"] = time.time()
            self._persist_presentation()
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
                "pokedex_on_air": False,
                "pokedex_current": None,
                "updated_at": time.time(),
            })
            self._persist_presentation()
            return dict(self._state)

    def _restore_presentation(self) -> None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._state["pokedex_on_air"] = bool(payload.get("pokedex_on_air", False))
            current = payload.get("pokedex_current")
            self._state["pokedex_current"] = current if isinstance(current, dict) else None
            graphic = payload.get("broadcast_graphic")
            if isinstance(graphic, dict):
                self._state["broadcast_graphic"].update(graphic)
            screen = payload.get("production_screen")
            if isinstance(screen, dict):
                self._state["production_screen"].update(screen)
        except Exception:
            return

    def _persist_presentation(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            temporary.write_text(json.dumps({
                "version": 1,
                "pokedex_on_air": bool(self._state.get("pokedex_on_air")),
                "pokedex_current": self._state.get("pokedex_current"),
                "broadcast_graphic": self._state.get("broadcast_graphic"),
                "production_screen": self._state.get("production_screen"),
                "updated_at": time.time(),
            }, indent=2), encoding="utf-8")
            os.replace(temporary, self._state_path)
        except Exception:
            return
