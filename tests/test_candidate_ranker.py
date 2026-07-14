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
