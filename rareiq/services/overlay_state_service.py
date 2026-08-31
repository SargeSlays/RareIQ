from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from copy import deepcopy
from typing import Any


def current_intelligence_theme(theme: dict[str, Any]) -> dict[str, Any]:
    """Migrate the untouched stock theme, preserving deliberate custom styling."""
    previous = {"accent_color": "#a6e8ce", "secondary_color": "#4f9f83",
                "background_color": "#080d0a", "text_color": "#f5f2e9"}
    result = deepcopy(theme)
    if theme.get("preset", "rareiq") == "rareiq" and all(
        str(theme.get(key, "")).lower() == value for key, value in previous.items()
    ):
        result.update({"accent_color": "#8be8ca", "secondary_color": "#48b995",
                       "background_color": "#18222e", "text_color": "#f4f7fa"})
        if result.get("corner_radius") == 12:
            result["corner_radius"] = 4
    return result


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
            return deepcopy(self._state)

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._state.update(deepcopy(payload))
            self._state["updated_at"] = time.time()
            self._persist_presentation()
            return deepcopy(self._state)

    def reset(self) -> dict[str, Any]:
        with self._lock:
            for key in ("broadcast_graphic", "production_screen"):
                surface = self._state[key]
                surface.update({
                    "visible": False,
                    "generation": int(surface.get("generation") or 0) + 1,
                })
            self._state["broadcast_graphic"]["preview"] = False
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
            return deepcopy(self._state)

    def _restore_presentation(self) -> None:
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._state["pokedex_on_air"] = payload.get("pokedex_on_air") is True
            current = payload.get("pokedex_current")
            self._state["pokedex_current"] = current if isinstance(current, dict) else None
            graphic = payload.get("broadcast_graphic")
            if isinstance(graphic, dict):
                self._state["broadcast_graphic"].update(graphic)
            screen = payload.get("production_screen")
            if isinstance(screen, dict):
                self._state["production_screen"].update(screen)
            theme = payload.get("rare_intelligence_theme")
            if isinstance(theme, dict):
                self._state["rare_intelligence_theme"] = current_intelligence_theme(theme)
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
                "rare_intelligence_theme": self._state.get("rare_intelligence_theme"),
                "updated_at": time.time(),
            }, indent=2), encoding="utf-8")
            os.replace(temporary, self._state_path)
        except Exception:
            return
