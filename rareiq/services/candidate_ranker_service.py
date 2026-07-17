from __future__ import annotations

from typing import Any


ARTWORK_SOURCES = {
    "artwork_index",
    "pokipair",
    "pokipair_visual_index",
}

OCR_SOURCES = {
    "ocr",
    "ocr_provisional",
}


class CandidateRankerService:
    def __init__(
        self,
        fusion_service: Any,
    ) -> None:
        self.fusion_service = fusion_service

    @staticmethod
    def _canonical_language(value: Any) -> str:
        normalized = str(value or "").strip().lower().replace("_", "-")
        aliases = {
            "chinese": "zh-cn",
            "simplified chinese": "zh-cn",
            "zh-cn": "zh-cn",
        }
        return aliases.get(normalized, normalized)

    def rank(
        self,
        *,
        visual_candidates: list[
            dict[str, Any]
        ],
        ocr_payload: dict[
            str,
            Any,
        ] | None,
        quality: dict[
            str,
            Any,
        ] | None,
        limit: int = 10,
    ) -> list[
        dict[str, Any]
    ]:
        merged: dict[
            str,
            dict[str, Any],
        ] = {}

        for candidate in visual_candidates:
            key = self._key(
                candidate
            )

            if not key:
                continue

            item = merged.setdefault(
                key,
                dict(
                    candidate
                ),
            )

            source = str(
                candidate.get(
                    "source",
                    ""
                )
            ).lower()

            raw_score = float(
                candidate.get(
                    "visual_score"
                )
                or candidate.get(
                    "score"
                )
                or 0.0
            )

            if source in OCR_SOURCES:
                visual_similarity = 0.0
                item[
                    "ocr_candidate_score"
                ] = max(
                    float(
                        item.get(
                            "ocr_candidate_score"
                        )
                        or 0.0
                    ),
                    raw_score,
                )

            else:
                visual_similarity = (
                    raw_score
                )

            item[
                "visual_similarity"
            ] = max(
                float(
                    item.get(
                        "visual_similarity"
                    )
                    or 0.0
                ),
                visual_similarity,
            )

        ocr_payload = (
            ocr_payload
            or {}
        )

        ocr_text = str(
            ocr_payload.get(
                "text"
            )
            or ""
        ).strip().lower()

        collector_number = str(
            ocr_payload.get(
                "collector_number"
            )
            or ""
        ).strip().lower()

        detected_language = self._canonical_language(
            ocr_payload.get(
                "language"
            )
        )

        ranked = []

        for item in merged.values():
            source = str(
                item.get(
                    "source",
                    ""
                )
            ).lower()

            name = str(
                item.get(
                    "name"
                )
                or item.get(
                    "printed_name"
                )
                or ""
            ).lower()

            number = str(
                item.get(
                    "collector_number"
                )
                or ""
            ).lower()

            language = self._canonical_language(
                item.get(
                    "language"
                )
            )

            signals = {
                "visual_similarity": (
                    item.get(
                        "visual_similarity",
                        0.0,
                    )
                ),
                "collector_number": (
                    1.0
                    if (
                        collector_number
                        and number
                        and collector_number
                        == number
                    )
                    else 0.0
                ),
                "ocr_name": (
                    self._text_overlap(
                        ocr_text,
                        name,
                    )
                ),
                "language": (
                    1.0
                    if (
                        detected_language
                        and language
                        and detected_language == language
                    )
                    else 0.5
                    if not detected_language
                    else 0.0
                ),
                "layout": float(
                    item.get(
                        "layout_score"
                    )
                    or 0.72
                ),
                "color_profile": float(
                    item.get(
                        "color_score"
                    )
                    or 0.72
                ),
                "rarity_hint": float(
                    item.get(
                        "rarity_score"
                    )
                    or 0.5
                ),
            }

            fusion = (
                self.fusion_service.score(
                    signals
                )
            )

            visual_similarity = float(
                signals[
                    "visual_similarity"
                ]
            )

            fused_score = float(
                fusion[
                    "confidence"
                ]
            )

            if source in ARTWORK_SOURCES:
                fused_score = max(
                    fused_score,
                    visual_similarity
                    * 0.88,
                )
                verified = bool(item.get("verification_strong"))
                identity_agreement = max(
                    float(signals["ocr_name"]),
                    float(signals["collector_number"]),
                )
                if not verified:
                    fused_score = min(
                        fused_score,
                        0.49 if identity_agreement == 0.0 else 0.59,
                    )
                    item["retrieval_only"] = True

            elif source in OCR_SOURCES:
                fused_score = min(
                    fused_score,
                    0.42,
                )

            ranked_item = dict(
                item
            )

            ranked_item.update({
                "signals": signals,
                "fusion": fusion,
                "fused_score": round(
                    fused_score,
                    4,
                ),
                "decision": (
                    "verified"
                    if fused_score >= 0.84
                    else "candidate"
                    if fused_score >= 0.60
                    else "uncertain"
                ),
                "quality_score": float(
                    (
                        quality
                        or {}
                    ).get(
                        "score"
                    )
                    or 0.0
                ),
            })

            ranked.append(
                ranked_item
            )

        ranked.sort(
            key=lambda candidate: (
                float(
                    candidate.get(
                        "fused_score",
                        0.0,
                    )
                ),
                float(
                    candidate.get(
                        "visual_similarity",
                        0.0,
                    )
                ),
                str(candidate.get("id") or ""),
            ),
            reverse=True,
        )

        return ranked[
            :max(
                1,
                int(
                    limit
                ),
            )
        ]

    @staticmethod
    def _key(
        candidate: dict[
            str,
            Any,
        ],
    ) -> str:
        return str(
            candidate.get(
                "id"
            )
            or "|".join(
                [
                    str(
                        candidate.get(
                            "set_id"
                        )
                        or ""
                    ),
                    str(
                        candidate.get(
                            "collector_number"
                        )
                        or ""
                    ),
                    str(
                        candidate.get(
                            "language"
                        )
                        or ""
                    ),
                ]
            )
        ).strip(
            "|"
        )

    @staticmethod
    def _text_overlap(
        left: str,
        right: str,
    ) -> float:
        if not left or not right:
            return 0.0

        if (
            right in left
            or left in right
        ):
            return 1.0

        left_tokens = {
            token
            for token in left.split()
            if len(
                token
            ) > 1
        }

        right_tokens = {
            token
            for token in right.split()
            if len(
                token
            ) > 1
        }

        if (
            not left_tokens
            or not right_tokens
        ):
            return 0.0

        union = len(
            left_tokens
            | right_tokens
        )

        return (
            len(
                left_tokens
                & right_tokens
            )
            / union
            if union
            else 0.0
        )
