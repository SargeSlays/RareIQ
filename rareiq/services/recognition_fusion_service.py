from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecognitionWeights:
    visual_similarity: float = 0.42
    collector_number: float = 0.20
    ocr_name: float = 0.12
    language: float = 0.08
    layout: float = 0.07
    color_profile: float = 0.06
    rarity_hint: float = 0.05


class RecognitionFusionService:
    """Combines independent signals into one transparent score."""

    def __init__(self, weights: RecognitionWeights | None = None) -> None:
        self.weights = weights or RecognitionWeights()

    @staticmethod
    def _clamp(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def score(self, signals: dict[str, Any]) -> dict[str, Any]:
        contributions = {}
        total = 0.0

        for name, weight in self.weights.__dict__.items():
            raw = self._clamp(signals.get(name))
            weighted = raw * weight
            contributions[name] = {
                "raw": round(raw, 4),
                "weight": round(weight, 4),
                "weighted": round(weighted, 4),
            }
            total += weighted

        confidence = round(max(0.0, min(1.0, total)), 4)
        decision = (
            "verified"
            if confidence >= 0.90
            else "candidate"
            if confidence >= 0.68
            else "uncertain"
        )

        return {
            "confidence": confidence,
            "decision": decision,
            "contributions": contributions,
        }

    def rank(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ranked = []
        for candidate in candidates:
            item = dict(candidate)
            fusion = self.score(item.get("signals") or {})
            item["fusion"] = fusion
            item["fused_score"] = fusion["confidence"]
            ranked.append(item)

        ranked.sort(
            key=lambda item: item.get("fused_score", 0.0),
            reverse=True,
        )
        return ranked
