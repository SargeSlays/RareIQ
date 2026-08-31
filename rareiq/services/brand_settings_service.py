from __future__ import annotations

import json
from typing import Any

from rareiq.core.storage import storage


LEGACY_BRAND_COLORS = {
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
}

DEFAULT_BRAND = {
    "creator_name": "RareIQ Creator",
    "logo_url": "",
    "primary": "#8be8ca",
    "secondary": "#48b995",
    "intelligence": "#b5c0cc",
    "gold": "#f2b84b",
    "danger": "#ed6a70",
    "background": "#0b1016",
    "panel": "#18222e",
    "border": "#3a4b60",
    "text": "#f4f7fa",
    "muted": "#b5c0cc",
    "font_heading": "Space Grotesk",
    "font_body": "Inter",
    "font_numbers": "JetBrains Mono",
    "watermark_opacity": 0.72,
    "overlay_theme": "rareiq-core",
}


def current_brand(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade only an untouched old palette; never overwrite custom colors."""
    result = {**DEFAULT_BRAND, **{key: value for key, value in payload.items() if key in DEFAULT_BRAND}}
    if all(str(payload.get(key, "")).lower() == value.lower() for key, value in LEGACY_BRAND_COLORS.items()):
        result.update({key: DEFAULT_BRAND[key] for key in LEGACY_BRAND_COLORS})
    return result


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
                self._settings = current_brand(payload)
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
