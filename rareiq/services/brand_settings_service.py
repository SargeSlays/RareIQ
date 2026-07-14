from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rareiq.core.storage import storage


DEFAULT_BRAND = {
    "creator_name": "RareIQ Creator",
    "logo_url": "",
    "primary": "#56D8FF",
    "secondary": "#41E695",
    "intelligence": "#9D78FF",
    "gold": "#F8C35D",
    "danger": "#EF5C68",
    "background": "#071019",
    "panel": "#0E1A28",
    "border": "#22364D",
    "text": "#EAF2F8",
    "muted": "#86A0B8",
    "font_heading": "Space Grotesk",
    "font_body": "Inter",
    "font_numbers": "JetBrains Mono",
    "watermark_opacity": 0.72,
    "overlay_theme": "rareiq-core",
}


class BrandSettingsService:
    def __init__(self) -> None:
        self.path = storage.get_path("config_path") / "brand_settings.json"
        self._settings = dict(DEFAULT_BRAND)
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.save(self._settings)
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self._settings.update(payload)
        except Exception:
            pass

    def get(self) -> dict[str, Any]:
        return dict(self._settings)

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_BRAND)
        for key, value in payload.items():
            if key in allowed:
                self._settings[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "brand": self.get()}
