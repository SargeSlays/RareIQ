import threading

import numpy as np

from rareiq.services.global_visual_index_service import GlobalVisualIndexService


def _service(records, matrix):
    service = object.__new__(GlobalVisualIndexService)
    service._lock = threading.RLock()
    service._records = records
    service._matrix = np.asarray(matrix, dtype=np.float32)
    service._feature = lambda _image: np.asarray([1.0, 0.0], dtype=np.float32)
    return service


def test_search_image_ranks_only_inside_locked_set():
    service = _service(
        [
            {"id": "wrong", "set_id": "other", "set_name": "Other", "language": "English"},
            {"id": "mankey", "set_id": "me05", "set_name": "Pitch Black", "language": "English"},
            {"id": "spanish", "set_id": "me05", "set_name": "Pitch Black", "language": "Spanish"},
        ],
        [[1.0, 0.0], [0.8, 0.2], [0.9, 0.1]],
    )

    result = service.search_image(
        np.zeros((4, 4, 3), dtype=np.uint8),
        limit=15,
        set_id="me05",
        set_name="Pitch Black",
        language="English",
    )

    assert result["ok"] is True
    assert result["set_filter_applied"] is True
    assert result["filtered_records"] == 1
    assert [match["id"] for match in result["matches"]] == ["mankey"]


def test_search_image_does_not_fall_back_when_locked_set_is_missing():
    service = _service(
        [{"id": "wrong", "set_id": "other", "language": "English"}],
        [[1.0, 0.0]],
    )

    result = service.search_image(
        np.zeros((4, 4, 3), dtype=np.uint8),
        set_id="me05",
        language="English",
    )

    assert result["ok"] is False
    assert result["matches"] == []
    assert result["filtered_records"] == 0


def test_search_image_normalizes_and_filters_complete_collector_fraction():
    service = _service(
        [
            {"id": "wrong-total", "collector_number": "053/120", "language": "English"},
            {"id": "nickit", "collector_number": "53/84", "language": "English"},
            {"id": "wrong-language", "collector_number": "053/084", "language": "Spanish"},
        ],
        [[1.0, 0.0], [0.8, 0.2], [0.9, 0.1]],
    )

    result = service.search_image(
        np.zeros((4, 4, 3), dtype=np.uint8),
        collector_number="053/084",
        language="English",
    )

    assert result["ok"] is True
    assert result["filtered_records"] == 1
    assert [match["id"] for match in result["matches"]] == ["nickit"]


def test_name_recovery_ranks_exact_names_and_excludes_color_similar_cards():
    service = _service([
        {"id": "wrong", "name": "Tropius"},
        {"id": "other-form", "name": "Galarian Slowpoke"},
        {"id": "old", "canonical_name": "Slowpoke"},
        {"id": "current", "printed_name": "Slowpoke"},
    ], [[1., 0.], [.99, .01], [.7, .3], [.9, .1]])
    result = service.search_image(np.zeros((4, 4, 3), dtype=np.uint8), card_name="  SLOWPOKE  ")
    assert result["filtered_records"] == 2
    assert [item["id"] for item in result["matches"]] == ["current", "old"]
    missing = service.search_image(np.zeros((4, 4, 3), dtype=np.uint8), card_name="Not in catalog")
    assert missing["matches"] == []


def test_auto_set_recognition_runs_number_first_global_visual_shortlist():
    from types import SimpleNamespace
    from rareiq.services.recognition_service import RecognitionService

    service = RecognitionService(lambda event: None)
    calls = []
    def retrieve(image, **filters):
        calls.append(filters)
        return {"matches": [{"id": "nickit", "collector_number": "53/84", "retrieval_only": True}]}
    service.global_visual_index = SimpleNamespace(search_image=retrieve)
    service.artwork_index = SimpleNamespace(search_hinted=lambda *args, **kwargs: {"matches": []})
    retrieved, verified, timings = service._lookup_identifier_visual_candidates(
        np.zeros((4, 4, 3), dtype=np.uint8), "053/084",
    )
    # No noisy OCR language filter may exclude the exact printed fraction.
    assert calls == [{"limit": 15, "collector_number": "053/084"}]
    assert retrieved[0]["id"] == "nickit"
    assert verified == []  # retrieval alone still cannot earn visual authority
    assert timings["identifier_visual_hits"] == 1


def test_recognition_uses_locked_set_language_after_filtered_retrieval():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "rareiq"
        / "services"
        / "recognition_service.py"
    ).read_text(encoding="utf-8")

    assert 'locked_language = str(active_set.get("language")' in source
    assert "global_visual_candidates" in source
    assert "language = locked_language" in source


def test_set_locked_printed_identity_is_presentable_but_not_auto_verified():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "rareiq"
        / "services"
        / "recognition_service.py"
    ).read_text(encoding="utf-8")

    assert 'leading["retrieval_only"] = False' in source
    assert 'leading["provisional"] = True' in source
    assert 'leading["set_locked_identity_agreement"] = True' in source


def test_locked_set_mismatch_rejects_decisive_language_and_total_conflicts():
    from rareiq.services.recognition_service import RecognitionService

    mismatch = RecognitionService._locked_set_mismatch(
        "131/151",
        "Chinese",
        {"set_id": "me05", "name": "Pitch Black", "language": "English"},
        [
            {"collector_number": "030/120"},
            {"collector_number": "30/84"},
        ],
    )

    assert mismatch is not None
    assert mismatch["locked_set_name"] == "Pitch Black"
    assert mismatch["observed_collector_number"] == "131/151"


def test_locked_set_total_disagreement_can_reconcile_the_same_local_number():
    from rareiq.services.recognition_service import RecognitionService

    assert RecognitionService._locked_set_mismatch(
        "030/999",
        "English",
        {"set_id": "me05", "name": "Pitch Black", "language": "English"},
        [{"collector_number": "030/120"}],
    ) is None


def test_language_detection_ignores_isolated_cjk_ocr_noise():
    from rareiq.services.recognition_service import RecognitionService

    english_footer = (
        "Electrike 70 Collect Draw a card. Tackle 30 weakness resistance "
        "retreat It stores static electricity in its fur 水 023/084"
    )
    assert RecognitionService._language_from_text(english_footer) == "English"
    assert RecognitionService._language_from_text("拉普拉斯 背起 水流利刃") == "Chinese"
    assert RecognitionService._language_from_text("ラプラス なみのり") == "Japanese"
