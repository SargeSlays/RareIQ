from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.global_visual_index_service import GlobalVisualIndexService
import threading


def test_catalog_text_search_ranks_exact_identity_and_supports_combined_terms(tmp_path):
    service = ArtworkIndexService(tmp_path / "index.json")
    service._records = [
        {"id": "me05-013", "english_name": "Goldeen", "set_name": "Pitch Black", "set_id": "me05", "collector_number": "013/084", "language": "English"},
        {"id": "other-013", "english_name": "Goldeen", "set_name": "Legacy Water", "set_id": "old", "collector_number": "013/100", "language": "English"},
        {"id": "me05-047", "english_name": "Koraidon", "set_name": "Pitch Black", "set_id": "me05", "collector_number": "047/084", "language": "English"},
    ]

    assert service.text_search("me05-013")[0]["id"] == "me05-013"
    assert service.text_search("goldeen pitch black")[0]["id"] == "me05-013"
    assert service.text_search("047/084")[0]["english_name"] == "Koraidon"
    assert service.text_search("x") == []


def test_global_catalog_text_search_uses_complete_visual_records():
    service = GlobalVisualIndexService.__new__(GlobalVisualIndexService)
    service._lock = threading.RLock()
    service._records = [
        {"id": "me05-013", "name": "Goldeen", "set_name": "Pitch Black", "set_id": "me05", "collector_number": "013/084", "language": "English"},
        {"id": "me05-047", "name": "Koraidon", "set_name": "Pitch Black", "set_id": "me05", "collector_number": "047/084", "language": "English"},
    ]
    assert service.text_search("Goldeen")[0]["id"] == "me05-013"
    assert service.text_search("Koraidon Pitch Black")[0]["collector_number"] == "047/084"
    assert service.text_search("Koraidon 047/084")[0]["id"] == "me05-047"
    assert service.text_search("Koraidon 47/84")[0]["id"] == "me05-047"


def test_global_catalog_text_search_normalizes_ocr_collector_zero_padding():
    service = GlobalVisualIndexService.__new__(GlobalVisualIndexService)
    service._lock = threading.RLock()
    service._records = [
        {
            "id": "me5-53",
            "name": "Nickit",
            "set_name": "Pitch Black",
            "set_id": "me5",
            "collector_number": "53/84",
            "language": "English",
            "reference_image_url": "/api/catalog-engine/image/en_me5/me5-53.png",
        },
    ]

    result = service.text_search("Nickit 053/084")

    assert [candidate["id"] for candidate in result] == ["me5-53"]
