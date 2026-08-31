"""Curated set-hit browser source. Draft edits never mutate the published strip."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote, urlsplit

from rareiq.services.media_storage import atomic_json


THEMES = {
    "midnight": {"label": "Midnight · violet / ice", "accent": "#bb9bff", "secondary": "#78dce8", "background": "#111121"},
    "prism": {"label": "Prism · rose / aqua", "accent": "#f5a8df", "secondary": "#83e5db", "background": "#181529"},
    "ember": {"label": "Ember · coral / gold", "accent": "#ff9b7c", "secondary": "#f5d27e", "background": "#211419"},
    "electric": {"label": "Electric · gold / blue", "accent": "#ffe18a", "secondary": "#85baff", "background": "#151a26"},
    "forest": {"label": "Forest · mint / lime", "accent": "#8be8ca", "secondary": "#c6e98a", "background": "#101e1d"},
    "ocean": {"label": "Ocean · ice / lavender", "accent": "#8edfff", "secondary": "#b6adff", "background": "#101b2c"},
}


class RevisionConflict(ValueError):
    pass


def _text(value, label, maximum=120, *, optional=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid {label}")
    value = value.strip()
    if not value and not optional:
        raise ValueError(f"Choose {label}")
    return value


def image_path(value):
    """Only local catalog artwork; no external URLs, credentials or path traversal."""
    value = _text(value, "catalog image", 500, optional=True)
    if not value:
        return ""
    decoded = unquote(value)
    parts = urlsplit(decoded)
    if parts.scheme or parts.netloc or parts.query or parts.fragment or "\\" in decoded or "%" in decoded:
        raise ValueError("Use local catalog artwork")
    if any(p in {".", ".."} for p in decoded.split("/")) or not re.fullmatch(
        r"/api/(?:catalog-engine/image/[^/]+/[^/]+|artwork-index/image/[^/]+)", decoded
    ):
        raise ValueError("Use local catalog artwork")
    return value


def theme_for(config):
    key = config["theme"]
    if key == "auto":
        name = config["set_name"].casefold()
        key = next((theme for words, theme in [
            (("black", "night", "phantom", "shadow"), "midnight"),
            (("prism", "stellar", "crystal", "shining"), "prism"),
            (("fire", "flame", "rival", "inferno"), "ember"),
            (("spark", "electric", "thunder", "lightning"), "electric"),
            (("ocean", "surf", "aqua", "tide"), "ocean"),
        ] if any(word in name for word in words)), "forest")
    result = {"key": key, **THEMES[key]}
    for field in ("accent", "secondary"):
        if config[field]:
            result[field] = config[field]
    return result


def validate_config(value):
    fields = {"set_id", "set_name", "language", "theme", "accent", "secondary", "cards_per_page", "seconds_per_page", "case_hits", "top_hits"}
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError("Invalid set-chase settings")
    config = {key: _text(value.get(key), key.replace("_", " ")) for key in ("set_id", "set_name", "language")}
    config["theme"] = value.get("theme", "auto")
    if not isinstance(config["theme"], str) or config["theme"] not in {"auto", *THEMES}:
        raise ValueError("Unknown set theme")
    for key in ("accent", "secondary"):
        color = value.get(key, "")
        if not isinstance(color, str) or (color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
            raise ValueError("Use six-digit theme colors")
        config[key] = color.lower()
    for key, default, low, high in (("cards_per_page", 4, 3, 4), ("seconds_per_page", 8, 4, 30)):
        number = value.get(key, default)
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f"{key} must be {low}–{high}")
        config[key] = number
    seen = set()
    for group in ("case_hits", "top_hits"):
        rows = value.get(group, [])
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError("Each hit group supports up to 32 cards")
        config[group] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Invalid card")
            card = {key: _text(row.get(key), f"card {key}", 120, optional=key == "collector_number")
                    for key in ("id", "name", "set_id", "language", "collector_number")}
            if card["set_id"] != config["set_id"] or card["language"].casefold() != config["language"].casefold():
                raise ValueError("All cards must belong to the selected set and language")
            if card["id"] in seen:
                raise ValueError("A card is already in this rotation")
            seen.add(card["id"])
            card["image_url"] = image_path(row.get("image_url", ""))
            config[group].append(card)
    return config


class SetChaseService:
    def __init__(self, path: Path, *, clock=time.time):
        self.path, self.clock = Path(path), clock
        self._lock = threading.RLock()
        self._error = None
        self._state = {"version": 1, "revision": 0, "draft": None, "program": None, "visible": False, "started_at_ms": 0}
        try:
            if self.path.exists():
                if self.path.stat().st_size > 256_000:
                    raise ValueError("Oversized saved state")
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                if saved.get("version") != 1 or type(saved.get("revision")) is not int or saved["revision"] < 0:
                    raise ValueError("Invalid saved state")
                self._state.update(revision=saved["revision"],
                    draft=validate_config(saved["draft"]) if saved.get("draft") else None,
                    program=validate_config(saved["program"]) if saved.get("program") else None)
                # Restore content, not live publication. Restart is always off air.
        except (ValueError, OSError, TypeError, AttributeError):
            self._error = "Saved Set Chase settings could not be loaded. Restore a valid backup before editing."

    def snapshot(self, *, preview=False):
        with self._lock:
            config = self._state["draft" if preview else "program"]
            return {"ok": not self._error, "error": self._error, "revision": self._state["revision"],
                    "visible": bool(config) if preview else self._state["visible"], "config": deepcopy(config),
                    "theme": theme_for(config) if config else None,
                    "started_at_ms": self._state["started_at_ms"], "server_now_ms": int(self.clock() * 1000)}

    def settings(self):
        with self._lock:
            return {"ok": not self._error, "error": self._error, **deepcopy(self._state), "themes": deepcopy(THEMES)}

    def change(self, action, revision, config=None):
        with self._lock:
            if self._error:
                raise ValueError(self._error)
            if type(revision) is not int or revision != self._state["revision"]:
                raise RevisionConflict("Settings changed in another window. Reload before editing.")
            next_state = deepcopy(self._state)
            if action == "draft":
                next_state["draft"] = validate_config(config)
            elif action == "take":
                draft = self._state["draft"]
                if not draft or not (draft["case_hits"] or draft["top_hits"]):
                    raise ValueError("Add at least one card before publishing")
                next_state.update(program=deepcopy(draft), visible=True, started_at_ms=int(self.clock() * 1000))
            elif action == "hide":
                next_state["visible"] = False
            else:
                raise ValueError("Unknown set-chase action")
            next_state["revision"] += 1
            atomic_json(self.path, next_state)  # Commit before acknowledging or changing live state.
            self._state = next_state
            return self.settings()
