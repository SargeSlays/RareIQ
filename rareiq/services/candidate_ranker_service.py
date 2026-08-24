from __future__ import annotations

from typing import Any


ARTWORK_SOURCES = {
    "artwork_index",
    "global_visual_index",
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

    @staticmethod
    def _collector_number_score(observed: Any, candidate: Any) -> float:
        """Compare the complete printed fraction without inventing an exact match."""
        left = str(observed or "").strip().lower()
        right = str(candidate or "").strip().lower()
        if not left or not right:
            return 0.0

        def parts(value: str) -> tuple[str, str | None]:
            numerator, separator, denominator = value.partition("/")
            numerator = numerator.lstrip("0") or "0"
            if not separator:
                return numerator, None
            return numerator, denominator.lstrip("0") or "0"

        left_number, left_total = parts(left)
        right_number, right_total = parts(right)
        if left_number != right_number:
            return 0.0
        if left_total is not None and right_total is not None:
            return 1.0 if left_total == right_total else 0.0
        # A numerator-only read is useful retrieval evidence, but must not satisfy
        # the exact-identifier lock used by RecognitionService.
        return 0.65

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
            if candidate is not item and candidate.get("verification_strong"):
                for evidence_key in (
                    "verification_strong",
                    "verification_score",
                    "artwork_verification_strong",
                    "artwork_verification_score",
                    "orb_matches",
                    "homography_inliers",
                    "inlier_ratio",
                    "structural_similarity",
                    "lower_structural_similarity",
                    "reference_readable",
                    "image_path",
                    "reference_image",
                    "local_image",
                ):
                    if candidate.get(evidence_key) is not None:
                        item[evidence_key] = candidate.get(evidence_key)
                item["retrieval_only"] = False
            for evidence_key in (
                "printed_code",
                "printed_code_match",
                "printed_code_match_mode",
                "printed_code_matching_frames",
                "printed_code_distance",
            ):
                if candidate.get(evidence_key) is not None:
                    item[evidence_key] = candidate.get(evidence_key)

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
                    max(
                        raw_score,
                        float(candidate.get("verification_score") or 0.0)
                        if candidate.get("verification_strong")
                        else 0.0,
                    )
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
        printed_code = str(
            ocr_payload.get("printed_code")
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

            name_aliases = {
                str(value).strip().lower()
                for value in (
                    item.get("name"),
                    item.get("printed_name"),
                    item.get("english_name"),
                    item.get("canonical_name"),
                    item.get("pokemon_name"),
                )
                if str(value or "").strip()
            }

            number = str(
                item.get(
                    "collector_number"
                )
                or ""
            ).lower()
            candidate_printed_code = str(
                item.get("printed_code")
                or ""
            ).strip().lower()

            language = self._canonical_language(
                item.get(
                    "language"
                )
            )

            collector_signal = self._collector_number_score(
                collector_number,
                number,
            )
            collector_fraction_exact = bool(
                collector_signal == 1.0
                and "/" in collector_number
                and "/" in number
            )

            signals = {
                "visual_similarity": (
                    item.get(
                        "visual_similarity",
                        0.0,
                    )
                ),
                "collector_number": (
                    collector_signal
                    if collector_number and number
                    else 1.0
                    if (
                            printed_code
                            and candidate_printed_code
                            and printed_code == candidate_printed_code
                            and item.get("printed_code_match") is True
                    )
                    else 0.0
                ),
                "ocr_name": (
                    max(
                        (
                            self._text_overlap(ocr_text, name)
                            for name in name_aliases
                        ),
                        default=0.0,
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
                "collector_fraction_exact": collector_fraction_exact,
            })

            ranked.append(
                ranked_item
            )

        ranked.sort(
            key=lambda candidate: (
                bool(candidate.get("printed_code_match")),
                bool(
                    candidate.get("verification_strong")
                    and candidate.get("collector_fraction_exact")
                ),
                bool(
                    candidate.get("verification_strong")
                    and candidate.get("artwork_verification_strong")
                ),
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
