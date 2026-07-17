from __future__ import annotations

import numpy as np

from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.candidate_ranker_service import CandidateRankerService
from rareiq.services.recognition_fusion_service import RecognitionFusionService
from rareiq.services.recognition_service import RecognitionService


def test_rectified_1000_by_1400_crop_bypasses_raw_camera_roi(monkeypatch) -> None:
    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)

    def fail_if_called(frame):
        raise AssertionError("raw-camera ROI must not run for a rectified crop")

    monkeypatch.setattr(RecognitionService, "_card_roi", fail_if_called)

    assert RecognitionService._prepare_card(crop) is crop


def test_raw_camera_frame_uses_existing_roi_path(monkeypatch) -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    expected = np.zeros((17, 19, 3), dtype=np.uint8)
    calls = []

    def fake_roi(value):
        calls.append(value)
        return expected

    monkeypatch.setattr(RecognitionService, "_card_roi", fake_roi)

    assert RecognitionService._prepare_card(frame) is expected
    assert len(calls) == 1
    assert calls[0] is frame


def test_full_card_geometry_matches_active_index_fingerprint_contract() -> None:
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    card[:250, :] = (255, 255, 255)
    card[300:850, 100:900] = (190, 80, 25)
    card[1000:, :] = (40, 120, 220)

    indexed_fingerprint = ArtworkIndexService.fingerprint(card)
    query_fingerprint = ArtworkIndexService.fingerprint(
        RecognitionService._prepare_card(card)
    )

    assert query_fingerprint == indexed_fingerprint


def test_chinese_language_aliases_match_zh_cn() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())

    for detected in ("Chinese", "Simplified Chinese", "zh-cn", "zh_cn"):
        ranked = ranker.rank(
            visual_candidates=[{
                "id": "horsea",
                "name": "Horsea",
                "score": 0.70,
                "source": "artwork_index",
                "language": "zh-cn",
            }],
            ocr_payload={"text": "", "language": detected},
            quality=None,
        )
        assert ranked[0]["signals"]["language"] == 1.0


def test_horsea_live_fingerprint_beats_previous_wrong_candidate() -> None:
    # Fingerprints captured from the Update 13 diagnostic session. The query is
    # the untouched 1000x1400 live Horsea crop; both records are from the active
    # artwork index.
    live_full_card = "ba4b64b570a49cbd"
    correct_horsea = "df6f6495f2b490c6"
    previous_wrong = "95c87792e02cb8f9"

    correct_distance = ArtworkIndexService.hamming(
        live_full_card, correct_horsea
    )
    wrong_distance = ArtworkIndexService.hamming(
        live_full_card, previous_wrong
    )

    assert correct_distance == 18
    assert wrong_distance == 23
    assert 1.0 - correct_distance / 64.0 > 1.0 - wrong_distance / 64.0
