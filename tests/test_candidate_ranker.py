from rareiq.services.candidate_ranker_service import CandidateRankerService
from rareiq.services.recognition_fusion_service import RecognitionFusionService


def test_correct_candidate_ranks_first():
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "correct",
                "name": "Suicune ex",
                "score": 0.98,
                "collector_number": "239/204",
                "language": "Chinese",
            },
            {
                "id": "wrong",
                "name": "Different Card",
                "score": 0.74,
                "collector_number": "001/100",
                "language": "English",
            },
        ],
        ocr_payload={
            "text": "Suicune ex",
            "collector_number": "239/204",
            "language": "Chinese",
        },
        quality={"score": 0.9},
    )
    assert ranked[0]["id"] == "correct"


def test_exact_printed_code_beats_unverified_global_visual_noise():
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "wrong-global",
                "name": "Alph Lithograph",
                "score": 0.99,
                "source": "global_visual_index",
            },
            {
                "id": "crocalor-156",
                "name": "Crocalor",
                "collector_number": "156",
                "printed_code": "2301/07",
                "printed_code_match": True,
                "language": "zh-cn",
                "score": 0.5861,
                "source": "pokipair",
                "verification_strong": True,
                "artwork_verification_strong": True,
            },
        ],
        ocr_payload={
            "text": "2301/07",
            "printed_code": "2301/07",
            "language": "Chinese",
        },
        quality={"score": 0.49},
    )

    assert ranked[0]["id"] == "crocalor-156"
    assert ranked[0]["signals"]["collector_number"] == 1.0
    wrong = next(item for item in ranked if item["id"] == "wrong-global")
    assert wrong["fused_score"] <= 0.49


def test_verified_reference_family_beats_unverified_global_visual_noise():
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[
            {
                "id": "wrong-global",
                "name": "Alph Lithograph",
                "score": 0.99,
                "source": "global_visual_index",
            },
            {
                "id": "crocalor-family",
                "name": "Crocalor",
                "collector_number": "156",
                "score": 0.5311,
                "source": "pokipair",
                "verification_strong": True,
                "artwork_verification_strong": True,
            },
        ],
        ocr_payload={"text": "2303/07", "language": "Chinese"},
        quality={"score": 0.49},
    )

    assert ranked[0]["id"] == "crocalor-family"
    assert ranked[0]["decision"] != "verified"
