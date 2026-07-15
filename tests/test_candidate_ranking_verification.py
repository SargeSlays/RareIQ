from __future__ import annotations

from rareiq.services.candidate_ranker_service import (
    CandidateRankerService,
)
from rareiq.services.recognition_fusion_service import (
    RecognitionFusionService,
)
from rareiq.services.recognition_service import (
    RecognitionService,
)


def test_ocr_candidate_cannot_become_visual_match() -> None:
    ranker = CandidateRankerService(
        RecognitionFusionService()
    )

    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "ocr:garbled",
                "name": "garbled",
                "score": 0.95,
                "source": "ocr_provisional",
            },
            {
                "id": "pokipair-card",
                "name": "Real card",
                "score": 0.97,
                "visual_score": 0.97,
                "source": "artwork_index",
                "image_path": "card.webp",
            },
        ],
        ocr_payload={
            "text": "",
            "collector_number": None,
            "language": "Unknown",
        },
        quality={
            "score": 0.8,
        },
    )

    assert ranked[0][
        "id"
    ] == "pokipair-card"

    assert ranked[1][
        "visual_similarity"
    ] == 0.0

    assert ranked[1][
        "fused_score"
    ] <= 0.42


def test_mojibake_ocr_name_is_rejected() -> None:
    assert not RecognitionService._usable_ocr_identity(
        "a²©è«",
        None,
    )


def test_collector_number_keeps_ocr_candidate_valid() -> None:
    assert RecognitionService._usable_ocr_identity(
        None,
        "084/204",
    )
