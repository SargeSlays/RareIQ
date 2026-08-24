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


def test_invalid_collector_number_is_not_identity_evidence() -> None:
    assert not RecognitionService._valid_collector_number("0501/070")
    assert RecognitionService._valid_collector_number("239/204")


def test_hash_only_candidate_is_capped_below_verified_candidate() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "hash-only",
                "name": "Unrelated",
                "score": 0.95,
                "source": "artwork_index",
                "verification_strong": False,
            },
            {
                "id": "verified",
                "name": "Unknown",
                "score": 0.70,
                "source": "artwork_index",
                "verification_strong": True,
            },
        ],
        ocr_payload={"text": "", "collector_number": None, "language": "Unknown"},
        quality=None,
    )
    assert ranked[0]["id"] == "verified"
    failed = next(item for item in ranked if item["id"] == "hash-only")
    assert failed["fused_score"] <= 0.49
    assert failed["retrieval_only"] is True


def test_chinese_printed_name_remains_ocr_evidence_with_english_display_name() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[{
            "id": "crocalor-157",
            "name": "Crocalor",
            "english_name": "Crocalor",
            "printed_name": "炙烫鳄",
            "collector_number": "157",
            "language": "zh-cn",
            "score": 0.79,
            "source": "pokipair",
            "verification_strong": True,
        }],
        ocr_payload={
            "text": "炙烫鳄 HP 110",
            "collector_number": None,
            "language": "Chinese",
        },
        quality={"score": 0.46},
    )
    assert ranked[0]["name"] == "Crocalor"
    assert ranked[0]["signals"]["ocr_name"] == 1.0
    assert ranked[0]["signals"]["language"] == 1.0


def test_complete_collector_fraction_rejects_same_numerator_wrong_total() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "italian-slowpoke",
                "name": "Slowpoke",
                "collector_number": "029/120",
                "visual_score": 0.92,
                "source": "global_visual_index",
                "verification_strong": True,
            },
            {
                "id": "english-slowpoke",
                "name": "Slowpoke",
                "collector_number": "29/84",
                "visual_score": 0.90,
                "source": "global_visual_index",
                "verification_strong": True,
            },
        ],
        ocr_payload={
            "text": "",
            "collector_number": "029/084",
            "language": "Unknown",
        },
        quality={"score": 0.8},
    )

    assert ranked[0]["id"] == "english-slowpoke"
    assert ranked[0]["signals"]["collector_number"] == 1.0
    assert ranked[0]["collector_fraction_exact"] is True
    wrong = next(item for item in ranked if item["id"] == "italian-slowpoke")
    assert wrong["signals"]["collector_number"] == 0.0
    assert wrong["collector_fraction_exact"] is False


def test_numerator_only_collector_evidence_cannot_claim_exact_fraction() -> None:
    assert CandidateRankerService._collector_number_score("029", "29/84") == 0.65
    assert CandidateRankerService._collector_number_score("029/084", "29/84") == 1.0
    assert CandidateRankerService._collector_number_score("029/084", "029/120") == 0.0


def test_verified_duplicate_promotes_global_candidate_evidence() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "me5-29",
                "name": "Slowpoke",
                "collector_number": "29/84",
                "visual_score": 0.83,
                "source": "global_visual_index",
                "retrieval_only": True,
            },
            {
                "id": "me5-29",
                "name": "Slowpoke",
                "collector_number": "29/84",
                "score": 0.91,
                "verification_score": 0.90,
                "verification_strong": True,
                "image_path": "slowpoke.png",
                "source": "global_visual_index",
            },
        ],
        ocr_payload={"collector_number": "029/084", "language": "Unknown"},
        quality=None,
    )

    assert len(ranked) == 1
    assert ranked[0]["verification_strong"] is True
    assert ranked[0]["retrieval_only"] is False
    assert ranked[0]["image_path"] == "slowpoke.png"
    assert ranked[0]["visual_similarity"] == 0.91


def test_unique_verified_full_fraction_resolves_shared_art_family() -> None:
    correct = {
        "id": "me5-29",
        "verification_strong": True,
        "collector_fraction_exact": True,
    }
    sibling = {
        "id": "me05-029",
        "verification_strong": True,
        "collector_fraction_exact": False,
    }

    assert RecognitionService._unique_verified_collector_fraction(
        correct, [correct, sibling]
    )
    assert not RecognitionService._unique_verified_collector_fraction(
        correct, [correct, {**sibling, "collector_fraction_exact": True}]
    )
    assert RecognitionService._exact_collector_fraction_match(
        "029/084", "29/84"
    )
    assert not RecognitionService._exact_collector_fraction_match(
        "029/084", "029/120"
    )
    assert not RecognitionService._exact_collector_fraction_match("029", "29/84")


def test_exhaustive_fallback_keeps_directly_verified_hint() -> None:
    merged = RecognitionService._merge_reference_matches(
        [{
            "id": "me5-29",
            "score": 0.91,
            "verification_strong": True,
            "image_path": "slowpoke.png",
        }],
        [{
            "id": "proof-only",
            "score": 0.49,
            "verification_strong": False,
            "image_path": "proof.png",
        }],
        limit=10,
    )

    assert [item["id"] for item in merged] == ["me5-29", "proof-only"]


def test_unique_verified_fraction_survives_shared_art_consistency_guard() -> None:
    exact = {
        "variant_ambiguity": True,
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "unique_verified_collector_fraction": True,
        "candidates": [{"id": "me5-29", "collector_number": "29/84"}],
    }
    RecognitionService._enforce_payload_printed_code_consistency(exact)
    assert exact["recognition_locked"] is True
    assert exact["verification_state"] == "VERIFIED"

    ambiguous = {
        **exact,
        "unique_verified_collector_fraction": False,
    }
    RecognitionService._enforce_payload_printed_code_consistency(ambiguous)
    assert ambiguous["recognition_locked"] is False
    assert ambiguous["verification_state"] == "SEARCHING"
