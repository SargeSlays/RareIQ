from rareiq.services.recognition_fusion_service import RecognitionFusionService


def test_high_confidence_match_is_verified():
    engine = RecognitionFusionService()
    result = engine.score({
        "visual_similarity": 1.0,
        "collector_number": 1.0,
        "ocr_name": 1.0,
        "language": 1.0,
        "layout": 1.0,
        "color_profile": 1.0,
        "rarity_hint": 1.0,
    })
    assert result["decision"] == "verified"
    assert result["confidence"] == 1.0


def test_low_confidence_match_is_uncertain():
    engine = RecognitionFusionService()
    result = engine.score({})
    assert result["decision"] == "uncertain"
    assert result["confidence"] == 0.0
