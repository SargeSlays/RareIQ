from __future__ import annotations

import cv2
import numpy as np

from rareiq.services.pack_artwork_recognition_service import PackArtworkRecognitionService


def _pack(color: tuple[int, int, int], accent: tuple[int, int, int]) -> np.ndarray:
    image = np.full((720, 1280, 3), (15, 18, 24), dtype=np.uint8)
    cv2.rectangle(image, (420, 60), (860, 660), color, -1)
    cv2.circle(image, (640, 230), 120, accent, -1)
    cv2.putText(image, "PACK", (495, 500), cv2.FONT_HERSHEY_SIMPLEX, 2.3, (245, 245, 245), 10)
    return image


def test_pack_focus_extracts_portrait_wrapper_from_workspace():
    image = _pack((30, 20, 160), (210, 60, 220))
    focused = PackArtworkRecognitionService._focus(image)
    assert focused.shape == (640, 480, 3)
    # The extracted image should be dominated by wrapper pixels, not the dark table.
    assert float(focused.mean()) > float(image.mean()) * 1.35


def test_pack_reference_enroll_identify_and_reload(tmp_path):
    service = PackArtworkRecognitionService(tmp_path / "pack-art")
    pitch_black = _pack((30, 20, 160), (210, 60, 220))

    learned = service.enroll(pitch_black, {
        "set_id": "me05", "set_name": "Pitch Black", "language": "English"
    })
    assert learned["ok"] is True
    assert service.status()["reference_count"] == 1
    assert service.status()["references"][0]["set_id"] == "me05"
    reference = service.status()["references"][0]
    assert reference["id"]
    assert reference["image_url"].startswith("/api/recognition/pack-reference/")
    assert service.rename_reference(reference["id"], "Pitch Black · Test wrapper") is True
    assert service.reference_summary(reference["id"])["pack_label"] == "Pitch Black · Test wrapper"
    profile = service.update_reference_profile(reference["id"], 6, 5)
    assert profile == {"expected_cards": 6, "rare_slot": 5}
    assert service.reference_summary(reference["id"])["pack_profile"] == profile

    assert service.observe_reference_profile(reference["id"], 6, 5)["suggested_profile"] is None
    assert service.observe_reference_profile(reference["id"], 8, 7)["suggested_profile"] is None
    learned_profile = service.observe_reference_profile(reference["id"], 8, 7)
    assert learned_profile["suggested_profile"] == {"expected_cards": 8, "rare_slot": 7}
    assert learned_profile["confidence"] >= 0.66

    result = service.identify(pitch_black.copy())
    assert result["ok"] is True
    assert result["match"]["set_id"] == "me05"
    assert service.status()["last_match"]["set_id"] == "me05"
    assert service.reference_path(learned["reference"]["id"]) is not None
    service.identify(np.zeros_like(pitch_black))
    assert service.status()["last_match"]["set_id"] == "me05"

    reloaded = PackArtworkRecognitionService(tmp_path / "pack-art")
    assert reloaded.status()["reference_count"] == 1
    assert reloaded.reference_summary(reference["id"])["pack_profile"] == profile
    assert reloaded.reference_summary(reference["id"])["profile_learning"]["suggested_profile"] == {"expected_cards": 8, "rare_slot": 7}
    assert reloaded.identify(pitch_black)["match"]["set_name"] == "Pitch Black"


def test_pack_recognition_rejects_unrelated_and_ambiguous_frames(tmp_path):
    service = PackArtworkRecognitionService(tmp_path / "pack-art")
    reference = _pack((30, 20, 160), (210, 60, 220))
    service.enroll(reference, {"set_id": "me05", "set_name": "Pitch Black"})

    unrelated = _pack((20, 170, 30), (30, 220, 220))
    assert service.identify(unrelated)["ok"] is False

    service.enroll(reference, {"set_id": "other", "set_name": "Other Set"})
    ambiguous = service.identify(reference)
    assert ambiguous["ok"] is False
    assert ambiguous["match"] is None
    assert ambiguous["candidate"]["score"] >= service.MIN_SCORE


def test_multiple_views_of_same_set_reinforce_instead_of_compete(tmp_path):
    service = PackArtworkRecognitionService(tmp_path / "pack-art")
    reference = _pack((30, 20, 160), (210, 60, 220))
    set_info = {"set_id": "me05", "set_name": "Pitch Black", "language": "English", "provider": "tcgdex"}
    service.enroll(reference, set_info)
    service.enroll(reference.copy(), set_info)
    result = service.identify(reference)
    assert result["ok"] is True
    assert result["match"]["set_id"] == "me05"
