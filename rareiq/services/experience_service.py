from __future__ import annotations
from typing import Any


class ExperienceService:
    MEDIUM_VALUE_THRESHOLD = 25.0
    GRAIL_VALUE_THRESHOLD = 150.0
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

    @staticmethod
    def hit_tier(card: dict[str, Any]) -> str:
        """Normalize a verified card into a conservative broadcast hit tier."""
        return ExperienceService.hit_decision(card)["tier"]

    @staticmethod
    def hit_decision(
        card: dict[str, Any], *, medium_value_threshold: float | None = None,
        grail_value_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Classify a verified hit and retain the evidence used by the overlay."""
        override = str(card.get("hit_tier") or "").strip().lower().replace("_", "-")
        if override in {"standard", "low", "medium", "grail"}:
            return {"tier": override, "reason": "operator_override", "market_value": None}

        rarity = str(card.get("rarity") or card.get("rarity_tier") or "").lower()
        chase = str(card.get("chase_status") or "").lower()
        if "grail" in rarity or "grail" in chase:
            return {"tier": "grail", "reason": "grail_catalog_classification", "market_value": None}

        market_value = None
        pricing = card.get("pricing") if isinstance(card.get("pricing"), dict) else {}
        for value in (
            card.get("market_price"), card.get("raw_market"), card.get("raw_value"),
            pricing.get("market"), pricing.get("mid"), pricing.get("high"),
        ):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                market_value = parsed
                break
        medium_threshold = float(medium_value_threshold if medium_value_threshold is not None else ExperienceService.MEDIUM_VALUE_THRESHOLD)
        grail_threshold = float(grail_value_threshold if grail_value_threshold is not None else ExperienceService.GRAIL_VALUE_THRESHOLD)
        if market_value is not None and market_value >= grail_threshold:
            return {"tier": "grail", "reason": "verified_market_value", "market_value": market_value}
        if market_value is not None and market_value >= medium_threshold:
            return {"tier": "medium", "reason": "verified_market_value", "market_value": market_value}
        if rarity in {"sar", "sir", "ex"} or any(token in rarity for token in (
            "special art", "special illustration", "illustration rare",
            "double rare", "ultra rare", "hyper rare", "secret rare",
            " sar", "sir", " ex", "gold",
        )):
            return {"tier": "medium", "reason": "catalog_rarity", "market_value": market_value}
        if "rare" in rarity:
            return {"tier": "low", "reason": "catalog_rarity", "market_value": market_value}
        return {"tier": "standard", "reason": "no_qualifying_hit_evidence", "market_value": market_value}

    def for_card(self, card: dict[str, Any]) -> dict[str, Any]:
        rarity = str(card.get("rarity") or "COMMON").upper()
        experience = dict(self._EXPERIENCES.get(rarity, self._EXPERIENCES["COMMON"]))
        tier = self.hit_tier(card)
        presentation = {
            "standard": {"reaction_copy": "CARD REVEALED", "intensity": 1},
            "low": {"reaction_copy": "RARE PULL", "intensity": 2},
            "medium": {"reaction_copy": "YES! BIG HIT", "intensity": 3},
            "grail": {"reaction_copy": "GRAIL HIT", "intensity": 4},
        }[tier]
        experience.update(
            hit_tier=tier,
            reaction_copy=presentation["reaction_copy"],
            intensity=presentation["intensity"],
            audio_enabled=False,
            audio_source="user-supplied",
        )
        return experience
