from __future__ import annotations
from typing import Any


class ExperienceService:
    _EXPERIENCES = {
        "COMMON": {
            "duration_ms": 850,
            "sound": "common",
            "screen_fx": False,
            "border_style": "scan",
        },
        "RARE": {
            "duration_ms": 1300,
            "sound": "rare",
            "screen_fx": False,
            "border_style": "rare",
        },
        "DOUBLE RARE": {
            "duration_ms": 2400,
            "sound": "double",
            "screen_fx": True,
            "border_style": "double",
        },
        "ILLUSTRATION RARE": {
            "duration_ms": 3600,
            "sound": "illustration",
            "screen_fx": True,
            "border_style": "illustration",
        },
        "GRAIL": {
            "duration_ms": 6000,
            "sound": "grail",
            "screen_fx": True,
            "border_style": "greninja_grail",
        },
    }

    def for_card(self, card: dict[str, Any]) -> dict[str, Any]:
        return dict(self._EXPERIENCES.get(card["rarity"], self._EXPERIENCES["COMMON"]))
