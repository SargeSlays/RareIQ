from __future__ import annotations

from typing import Any


class RecognitionDiagnosticsService:
    def analyze(
        self,
        *,
        quality: dict[str, Any],
        candidates: list[dict[str, Any]],
        ocr_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        reasons = []
        recommendation = None

        if quality.get("score", 0.0) < 0.48:
            reasons.append("Image quality is below the recommended threshold.")
            recommendation = (
                quality.get("recommendation")
                or "Reposition the card and scan again."
            )

        if not candidates:
            reasons.append("No visual candidates were returned.")
            recommendation = recommendation or (
                "Confirm artwork is indexed or download the missing reference."
            )
        elif candidates[0].get("fused_score", 0.0) < 0.68:
            reasons.append("The strongest candidate is not decisive.")
            recommendation = recommendation or (
                "Reduce glare and keep the collector number visible."
            )

        if not (ocr_payload or {}).get("text"):
            reasons.append("OCR returned no usable text.")
            recommendation = recommendation or (
                "Move the card closer and improve text-region lighting."
            )

        return {
            "status": "attention" if reasons else "healthy",
            "reasons": reasons,
            "recommendation": recommendation,
        }
