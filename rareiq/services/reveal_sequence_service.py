from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from rareiq.services.experience_service import ExperienceService


class RevealSequenceService:
    """Pack-aware, browser-source-safe suspense and reaction state."""

    DEFAULT_COPY = {
        "standard": "Aww — next pack!",
        "low": "Nice pull!",
        "medium": "YES! BIG HIT!",
        "grail": "OH MY GOD — GRAIL HIT!",
    }

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path
        self._lock = threading.RLock()
        self._config = {
            "enabled": True, "expected_cards": 6, "rare_slot": 6,
            "build_suspense": True, "reaction_copy": dict(self.DEFAULT_COPY),
            "custom_grail_preset": "none", "audio_enabled": False,
            "animations_enabled": True, "animation_intensity": 75,
            "animation_duration_ms": 3200, "particles_enabled": True,
            "flash_enabled": True, "minimum_animation_tier": "low",
            "medium_value_threshold": 25.0, "grail_value_threshold": 150.0,
            "arming_delay_ms": 0,
        }
        self._pack_number = 1
        self._cards: list[dict[str, Any]] = []
        self._revision = 0
        self._armed_until: float | None = None
        self._animation_cancelled = False
        self._history: list[dict[str, Any]] = []
        self._replay_item: dict[str, Any] | None = None
        self._load_config()

    def _load_config(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path else {}
            if isinstance(payload, dict):
                config = payload.get("config") if isinstance(payload.get("config"), dict) else payload
                self.configure(config, persist=False)
                history = payload.get("history") if isinstance(payload.get("history"), list) else []
                self._history = [self._sanitize_history_item(item) for item in history if isinstance(item, dict)][:20]
        except (OSError, ValueError, TypeError):
            return

    @staticmethod
    def _sanitize_history_item(item: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "reveal_id", "position", "pack_number", "card_name", "collector_number",
            "rarity", "hit_tier", "reference_image_url", "hit_reason", "market_value",
            "verified_at",
        }
        clean = {key: item.get(key) for key in allowed if key in item}
        clean["reveal_id"] = str(clean.get("reveal_id") or "")[:120]
        clean["card_name"] = str(clean.get("card_name") or "Verified card")[:180]
        clean["hit_tier"] = str(clean.get("hit_tier") or "standard") if str(clean.get("hit_tier") or "standard") in {"standard", "low", "medium", "grail"} else "standard"
        try:
            clean["verified_at"] = float(clean.get("verified_at") or 0)
        except (TypeError, ValueError):
            clean["verified_at"] = 0.0
        return clean

    def _persist(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = {"version": 2, "config": self._config, "history": self._history[:20]}
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def configure(self, payload: dict[str, Any], persist: bool = True) -> dict[str, Any]:
        with self._lock:
            if "enabled" in payload:
                self._config["enabled"] = bool(payload["enabled"])
            if "build_suspense" in payload:
                self._config["build_suspense"] = bool(payload["build_suspense"])
            expected = max(1, min(30, int(payload.get("expected_cards", self._config["expected_cards"]))))
            rare_slot = max(1, min(expected, int(payload.get("rare_slot", self._config["rare_slot"]))))
            self._config.update(expected_cards=expected, rare_slot=rare_slot)
            if isinstance(payload.get("reaction_copy"), dict):
                self._config["reaction_copy"].update({
                    key: str(value)[:120] for key, value in payload["reaction_copy"].items()
                    if key in self.DEFAULT_COPY and str(value).strip()
                })
            preset = str(payload.get("custom_grail_preset", self._config["custom_grail_preset"]))
            self._config["custom_grail_preset"] = preset[:80]
            self._config["audio_enabled"] = bool(payload.get("audio_enabled", False))
            if "animations_enabled" in payload:
                self._config["animations_enabled"] = bool(payload["animations_enabled"])
            if "particles_enabled" in payload:
                self._config["particles_enabled"] = bool(payload["particles_enabled"])
            if "flash_enabled" in payload:
                self._config["flash_enabled"] = bool(payload["flash_enabled"])
            self._config["animation_intensity"] = max(0, min(100, int(payload.get("animation_intensity", self._config["animation_intensity"]))))
            self._config["animation_duration_ms"] = max(1200, min(10000, int(payload.get("animation_duration_ms", self._config["animation_duration_ms"]))))
            tier = str(payload.get("minimum_animation_tier", self._config["minimum_animation_tier"])).lower()
            self._config["minimum_animation_tier"] = tier if tier in {"low", "medium", "grail"} else "low"
            medium_threshold = max(0.0, min(1000000.0, float(payload.get("medium_value_threshold", self._config["medium_value_threshold"]))))
            grail_threshold = max(medium_threshold, min(1000000.0, float(payload.get("grail_value_threshold", self._config["grail_value_threshold"]))))
            self._config.update(medium_value_threshold=medium_threshold, grail_value_threshold=grail_threshold)
            self._config["arming_delay_ms"] = max(0, min(15000, int(payload.get("arming_delay_ms", self._config["arming_delay_ms"]))))
            if persist:
                self._persist()
            return self.snapshot()

    def advance(self, card: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not self._config["enabled"]:
                return self.snapshot()
            if card.get("provisional") or card.get("verified") is False or str(card.get("verification_state") or "").upper() in {"PROVISIONAL", "CANDIDATE", "PENDING"}:
                return self.snapshot() | {"animation_blocked": True, "animation_block_reason": "verified_identity_required"}
            decision = ExperienceService.hit_decision(
                card,
                medium_value_threshold=float(self._config["medium_value_threshold"]),
                grail_value_threshold=float(self._config["grail_value_threshold"]),
            )
            tier = str(decision["tier"])
            position = len(self._cards) + 1
            rare_slot = int(self._config["rare_slot"])
            suspense = max(0, min(100, round(position / rare_slot * 100))) if self._config["build_suspense"] else 0
            is_rare_slot = position >= rare_slot
            phase = "reaction" if is_rare_slot or tier in {"low", "medium", "grail"} else "build"
            item = {
                "position": position, "card_name": card.get("english_name") or card.get("card_name"),
                "collector_number": card.get("collector_number"), "rarity": card.get("rarity"),
                "hit_tier": tier, "reference_image_url": card.get("reference_image_url"),
                "hit_reason": decision.get("reason"), "market_value": decision.get("market_value"),
                "verified_at": time.time(),
            }
            item["reveal_id"] = f"{int(item['verified_at'] * 1000)}-{self._pack_number}-{position}"
            self._cards.append(item)
            self._cards = self._cards[-30:]
            self._animation_cancelled = False
            self._replay_item = None
            self._armed_until = time.time() + (int(self._config["arming_delay_ms"]) / 1000) if phase == "reaction" else None
            if phase == "reaction":
                self._history.insert(0, dict(item) | {"pack_number": self._pack_number})
                self._history = self._history[:20]
                self._persist()
            self._revision += 1
            return self._state(phase, suspense, item)

    def release_animation(self) -> dict[str, Any]:
        with self._lock:
            if self._cards:
                self._armed_until = 0.0
                self._animation_cancelled = False
                self._revision += 1
            return self.snapshot()

    def cancel_animation(self) -> dict[str, Any]:
        with self._lock:
            if self._cards:
                self._armed_until = None
                self._animation_cancelled = True
                self._revision += 1
            return self.snapshot()

    def replay_animation(self, reveal_id: str) -> dict[str, Any]:
        with self._lock:
            match = next((item for item in self._history if item.get("reveal_id") == reveal_id), None)
            if match is None:
                return self.snapshot() | {"replay_error": "reveal_not_found"}
            self._replay_item = dict(match)
            self._armed_until = 0.0
            self._animation_cancelled = False
            self._revision += 1
            return self._state("reaction", 100, self._replay_item)

    def next_pack(self) -> dict[str, Any]:
        with self._lock:
            self._pack_number += 1
            self._cards = []
            self._armed_until = None
            self._animation_cancelled = False
            self._replay_item = None
            self._revision += 1
            return self._state("ready", 0, None)

    def _state(self, phase: str, suspense: int, current: dict[str, Any] | None) -> dict[str, Any]:
        tier = str((current or {}).get("hit_tier") or "standard")
        tier_rank = {"standard": 0, "low": 1, "medium": 2, "grail": 3}
        now = time.time()
        if phase == "reaction" and self._armed_until is not None and self._armed_until > 0 and self._armed_until <= now:
            self._armed_until = 0.0
            self._revision += 1
        armed = bool(phase == "reaction" and self._armed_until is not None and self._armed_until > now and not self._animation_cancelled)
        countdown_ms = max(0, round((self._armed_until - now) * 1000)) if armed and self._armed_until is not None else 0
        animation_ready = bool(
            phase == "reaction" and not armed and not self._animation_cancelled and self._config["animations_enabled"]
            and tier_rank.get(tier, 0) >= tier_rank.get(str(self._config["minimum_animation_tier"]), 1)
        )
        return {
            "enabled": bool(self._config["enabled"]), "phase": phase,
            "pack_number": self._pack_number, "position": len(self._cards),
            "expected_cards": self._config["expected_cards"], "rare_slot": self._config["rare_slot"],
            "suspense_percent": suspense, "current_card": current,
            "reaction_tier": tier if phase == "reaction" else None,
            "reaction_copy": self._config["reaction_copy"].get(tier) if phase == "reaction" else None,
            "arming": {"active": armed, "countdown_ms": countdown_ms, "cancelled": self._animation_cancelled},
            "custom_grail_preset": self._config["custom_grail_preset"] if tier == "grail" else "none",
            "audio_enabled": bool(self._config["audio_enabled"]),
            "animation": {
                "active": animation_ready, "preset": tier if animation_ready else "none",
                "intensity": self._config["animation_intensity"],
                "duration_ms": self._config["animation_duration_ms"],
                "particles": bool(self._config["particles_enabled"]),
                "flash": bool(self._config["flash_enabled"]),
            },
            "sequence": [dict(item) for item in self._cards], "history": [dict(item) for item in self._history],
            "is_replay": bool(self._replay_item), "revision": self._revision,
            "updated_at": time.time(), "config": dict(self._config),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            current = self._replay_item or (self._cards[-1] if self._cards else None)
            phase = "reaction" if current and (current["position"] >= self._config["rare_slot"] or current["hit_tier"] in {"low", "medium", "grail"}) else "build" if current else "ready"
            suspense = max(0, min(100, round(len(self._cards) / self._config["rare_slot"] * 100))) if current and self._config["build_suspense"] else 0
            return self._state(phase, suspense, current)
