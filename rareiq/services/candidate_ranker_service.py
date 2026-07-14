from __future__ import annotations

from typing import Any


class CandidateRankerService:
    def __init__(self, fusion_service: Any) -> None:
        self.fusion_service = fusion_service

    def rank(
        self,
        *,
        visual_candidates: list[dict[str, Any]],
        ocr_payload: dict[str, Any] | None,
        quality: dict[str, Any] | None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for candidate in visual_candidates:
            key = self._key(candidate)
            if not key:
                continue
            item = merged.setdefault(key, dict(candidate))
            item["visual_similarity"] = max(
                float(item.get("visual_similarity") or 0.0),
                float(
                    candidate.get("visual_score")
                    or candidate.get("score")
                    or 0.0
                ),
            )

        ocr_payload = ocr_payload or {}
        ocr_text = str(ocr_payload.get("text") or "").strip().lower()
        collector_number = str(
            ocr_payload.get("collector_number") or ""
        ).strip().lower()
        detected_language = str(
            ocr_payload.get("language") or ""
        ).strip().lower()

        ranked = []
        for item in merged.values():
            name = str(
                item.get("name")
                or item.get("printed_name")
                or ""
            ).lower()
            number = str(item.get("collector_number") or "").lower()
            language = str(item.get("language") or "").lower()

            signals = {
                "visual_similarity": item.get("visual_similarity", 0.0),
                "collector_number": (
                    1.0
                    if collector_number and number
                    and collector_number == number
                    else 0.0
                ),
                "ocr_name": self._text_overlap(ocr_text, name),
                "language": (
                    1.0
                    if detected_language and language
                    and detected_language in language
                    else 0.5
                    if not detected_language
                    else 0.0
                ),
                "layout": float(item.get("layout_score") or 0.72),
                "color_profile": float(item.get("color_score") or 0.72),
                "rarity_hint": float(item.get("rarity_score") or 0.5),
            }
            fusion = self.fusion_service.score(signals)
            ranked_item = dict(item)
            ranked_item.update({
                "signals": signals,
                "fusion": fusion,
                "fused_score": fusion["confidence"],
                "decision": fusion["decision"],
                "quality_score": float(
                    (quality or {}).get("score") or 0.0
                ),
            })
            ranked.append(ranked_item)

        ranked.sort(
            key=lambda candidate: candidate.get("fused_score", 0.0),
            reverse=True,
        )
        return ranked[:max(1, int(limit))]

    @staticmethod
    def _key(candidate: dict[str, Any]) -> str:
        return str(
            candidate.get("id")
            or "|".join(
                [
                    str(candidate.get("set_id") or ""),
                    str(candidate.get("collector_number") or ""),
                    str(candidate.get("language") or ""),
                ]
            )
        ).strip("|")

    @staticmethod
    def _text_overlap(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if right in left or left in right:
            return 1.0
        left_tokens = {token for token in left.split() if len(token) > 1}
        right_tokens = {token for token in right.split() if len(token) > 1}
        if not left_tokens or not right_tokens:
            return 0.0
        union = len(left_tokens | right_tokens)
        return len(left_tokens & right_tokens) / union if union else 0.0
