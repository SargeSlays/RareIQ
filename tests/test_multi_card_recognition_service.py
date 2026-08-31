import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pytest

from rareiq.services.multi_card_recognition_service import (
    MultiCardRecognitionService,
    SixCardGridDetector,
)
from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.vision_service import DetectionResult, VisionService


@pytest.fixture(autouse=True)
def isolated_multi_card_storage(monkeypatch, tmp_path):
    """Regression tests must never load or overwrite the operator's scan history."""
    initialize = MultiCardRecognitionService.__init__

    def isolated_init(self, prototype, history_path=None, presentation_path=None):
        initialize(
            self, prototype,
            history_path=history_path or tmp_path / "temporal.json",
            presentation_path=presentation_path or tmp_path / "presentation.json",
        )

    monkeypatch.setattr(MultiCardRecognitionService, "__init__", isolated_init)


def test_six_card_detector_maps_each_cell_polygon_to_full_frame(monkeypatch):
    calls = []

    def fake_detect(cell):
        calls.append(cell.shape)
        crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
        for y in range(100, 1350, 120):
            cv2.line(crop, (40, y), (960, y), (255, 255, 255), 12)
        cv2.rectangle(crop, (35, 35), (965, 1365), (255, 255, 255), 18)
        return DetectionResult(
            crop=crop,
            polygon=np.array([[.1, .1], [.9, .1], [.9, .9], [.1, .9]], dtype=np.float32),
            confidence=.9,
        )

    monkeypatch.setattr(VisionService, "detect", fake_detect)
    results = SixCardGridDetector.detect(np.zeros((600, 900, 3), dtype=np.uint8))

    assert len(results) == 6
    assert len(calls) == 10
    assert results[0]["slot"] == 1
    assert results[5]["slot"] == 6
    assert all(0 <= coordinate <= 1 for item in results for point in item["polygon"] for coordinate in point)


def test_default_test_storage_is_not_the_operator_data_directory(tmp_path):
    service = MultiCardRecognitionService(_FakePrototype())
    assert service._presentation_path.is_relative_to(tmp_path)
    assert service._temporal_history_path.is_relative_to(tmp_path)


def test_processed_results_are_counted_separately_from_verified_results():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state.update(status="complete", detected_count=2, completed_count=2, slots=[
        {"slot": 1, "status": "review-needed", "card": {"canonical_name": "Armarouge"}},
        {"slot": 2, "status": "verified", "verified": True, "card": {"name": "Nickit"}},
        {"slot": 3, "status": "not-detected", "card": None},
    ])
    result = service.status()
    assert result["completed_count"] == 2
    assert result["verified_count"] == result["review_count"] == 1
    assert result["pending_count"] == 0
    assert result["slots"][0]["output_ready"] is False
    assert result["slots"][1]["output_ready"] is True
    result["slots"][1]["card"]["name"] = "Mutated"
    assert service.status()["slots"][1]["card"]["name"] == "Nickit"


def test_unverified_output_selection_is_rejected_without_changing_existing_output():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [
        {"slot": 1, "status": "verified", "verified": True, "card": {"name": "Nickit"}},
        {"slot": 2, "status": "review-needed", "card": {"canonical_name": "Armarouge"}},
    ]
    assert service.select_slots([1])["ok"] is True
    result = service.select_slots([1, 2])
    assert result["ok"] is False and result["blocked_slots"] == [2]
    assert result["selected_slots"] == [1]
    service._state["slots"][0]["verified"] = False
    assert service.select_slots([])["selected_slots"] == []


@pytest.mark.parametrize("value", [[True], ["1"], [1.5], [0], [13], [None], "1"])
def test_invalid_output_slots_fail_without_a_server_error(value):
    result = MultiCardRecognitionService(_FakePrototype()).select_slots(value)
    assert result["ok"] is False
    assert result["reason"] == "invalid_slots"


@pytest.mark.parametrize("update", [
    {"verified": False}, {"status": "recognizing"}, {"exact_version_unresolved": True},
    {"card": {"name": "Nickit", "exact_version_unresolved": True}},
    {"card": {"name": "Nickit", "provisional": True}}, {"card": {}},
])
def test_output_gate_rejects_unresolved_or_empty_card(update):
    item = {"status": "verified", "verified": True, "card": {"name": "Nickit"}, **update}
    assert MultiCardRecognitionService.output_ready(item) is False


def test_delegated_worker_with_no_candidate_completes_instead_of_crashing():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state.update(status="recognizing", detected_count=1, completed_count=0,
                          slots=[{"slot": 1, "status": "recognizing", "card": None}])
    service._apply_worker_payload(1, {"candidates": [], "recognition_locked": False}, delegated_from=2)
    result = service.status()
    assert result["status"] == "complete"
    assert result["verified_count"] == 0
    assert result["review_count"] == 1


def test_busy_representative_finishes_delegated_slots_too(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    monkeypatch.setattr(service, "_family_first_delegates", lambda _items: {1: [2]})
    monkeypatch.setattr(service._workers[1], "submit_frame", lambda *_args, **_kwargs: "busy")
    crop = np.zeros((40, 30, 3), dtype=np.uint8)
    result = service.capture(crop, max_cards=2, detections=[
        {"slot": slot, "confidence": .9, "polygon": [], "crop": crop}
        for slot in (1, 2)
    ])
    assert result["status"] == "complete"
    assert result["completed_count"] == 2
    assert result["pending_count"] == result["verified_count"] == 0
    assert result["review_count"] == 2
    assert all(slot["status"] == "busy" for slot in result["slots"])


def test_window_fallback_rejects_arm_like_rectangle_before_recognition(monkeypatch):
    arm = np.full((1400, 1000, 3), (105, 145, 195), dtype=np.uint8)
    cv2.line(arm, (80, 180), (880, 980), (25, 35, 45), 24)
    cv2.circle(arm, (520, 700), 170, (30, 40, 50), 18)

    monkeypatch.setattr(
        VisionService,
        "detect",
        lambda _cell: DetectionResult(
            crop=arm,
            polygon=np.array([[.2, .1], [.8, .1], [.8, .9], [.2, .9]], dtype=np.float32),
            confidence=.95,
        ),
    )

    assert SixCardGridDetector.detect(np.zeros((600, 900, 3), dtype=np.uint8)) == []


def test_card_structure_gate_accepts_repeated_card_rules():
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    cv2.rectangle(card, (25, 25), (975, 1375), (255, 255, 255), 16)
    for y in (120, 220, 620, 760, 900, 1040, 1160, 1260, 1340):
        cv2.line(card, (45, y), (955, y), (230, 230, 230), 10)

    score, evidence = SixCardGridDetector._card_structure_score(card)

    assert score >= .44
    assert evidence["horizontal_rules"] >= 9


def test_full_frame_contours_isolate_each_visible_card():
    frame = np.zeros((600, 900, 3), dtype=np.uint8)
    for left, top in ((80, 70), (280, 70), (480, 70), (680, 70),
                      (80, 340), (280, 340), (480, 340), (680, 340)):
        cv2.rectangle(frame, (left, top), (left + 120, top + 168), (235, 235, 235), -1)
        cv2.rectangle(frame, (left, top), (left + 120, top + 168), (255, 255, 255), 4)

    results = SixCardGridDetector._contour_candidates(frame)

    assert len(results) == 8
    assert all(item["crop"].shape == (1400, 1000, 3) for item in results)


def test_three_large_perspective_cards_keep_full_borders_and_physical_order():
    """Three cards >8.5% each must not turn into artwork-only detections."""
    frame = np.full((900, 1600, 3), 25, dtype=np.uint8)
    card = np.full((500, 350, 3), 220, dtype=np.uint8)
    cv2.rectangle(card, (12, 12), (337, 487), (70, 90, 120), -1)
    cv2.rectangle(card, (30, 65), (319, 240), (220, 220, 220), 4)
    for y in (38, 270, 310, 350, 390, 430, 465):
        cv2.line(card, (30, y), (319, y), (235, 235, 235), 4)
    source = np.array([[0, 0], [349, 0], [349, 499], [0, 499]], dtype=np.float32)
    borders = [
        [[160, 240], [450, 230], [435, 650], [120, 660]],
        [[610, 235], [900, 250], [925, 660], [600, 650]],
        [[1060, 245], [1370, 265], [1415, 655], [1090, 650]],
    ]
    for border in borders:
        points = np.array(border, dtype=np.float32)
        # Reproduce the size that was rejected, not a small-card fixture.
        _, (width, height), _ = cv2.minAreaRect(points)
        assert width * height / (1600 * 900) > .085
        transform = cv2.getPerspectiveTransform(source, points)
        warped = cv2.warpPerspective(card, transform, (1600, 900))
        mask = cv2.warpPerspective(np.full((500, 350), 255, dtype=np.uint8), transform, (1600, 900))
        frame[mask > 0] = warped[mask > 0]

    results = SixCardGridDetector.detect(frame, max_cards=12)

    assert len(results) == 3
    for slot, (result, border) in enumerate(zip(results, borders), start=1):
        detected = np.asarray(result["polygon"], dtype=np.float32) * [1600, 900]
        assert result["slot"] == slot
        assert SixCardGridDetector._polygon_iou(detected, border) > .95
        assert result["crop"].shape == (1400, 1000, 3)


def test_large_blank_rectangle_does_not_pass_relaxed_area_gate():
    frame = np.full((900, 1600, 3), 25, dtype=np.uint8)
    cv2.rectangle(frame, (620, 235), (950, 690), (150, 180, 210), -1)
    assert SixCardGridDetector._contour_candidates(frame) == []


@pytest.mark.parametrize("scale", [.5, 1.0, 2.0])
def test_foreshortened_cards_on_textured_table_keep_complete_silhouettes(scale):
    rng = np.random.default_rng(481)
    frame = np.clip(rng.normal(85, 12, (900, 1600, 3)), 0, 255).astype(np.uint8)
    card = np.full((500, 350, 3), 200, dtype=np.uint8)
    cv2.rectangle(card, (16, 16), (333, 483), (120, 155, 185), -1)
    cv2.rectangle(card, (30, 65), (319, 240), (50, 65, 90), -1)
    for y in (42, 265, 310, 350, 400, 450, 478):
        cv2.line(card, (30, y), (320, y), (240, 240, 240), 5)
    source = np.array([[0, 0], [349, 0], [349, 499], [0, 499]], dtype=np.float32)
    borders = [
        [[200, 250], [490, 255], [455, 595], [130, 590]],
        [[600, 265], [890, 280], [885, 650], [560, 635]],
        [[1020, 280], [1300, 290], [1340, 625], [1030, 610]],
    ]
    # The observed foreshortened center card is about 1.14:1, below the
    # edge-only detector's old 1.18 cutoff but still a structured card.
    (_, _), dimensions, _ = cv2.minAreaRect(np.array(borders[1], dtype=np.float32))
    assert 1.08 < max(dimensions) / min(dimensions) < 1.18
    for border in borders:
        transform = cv2.getPerspectiveTransform(source, np.array(border, dtype=np.float32))
        warped = cv2.warpPerspective(card, transform, (1600, 900))
        mask = cv2.warpPerspective(np.full((500, 350), 255, dtype=np.uint8), transform, (1600, 900))
        frame[mask > 0] = warped[mask > 0]
    # Thin highlights/annotations must not merge two complete card silhouettes.
    cv2.line(frame, (450, 263), (650, 272), (255, 255, 255), 2)
    frame = cv2.resize(frame, None, fx=scale, fy=scale)
    results = SixCardGridDetector.detect(frame, max_cards=12)
    assert len(results) == 3
    for result, border in zip(results, borders):
        polygon = np.asarray(result["polygon"], dtype=np.float32) * [1600, 900]
        assert SixCardGridDetector._polygon_iou(polygon, border) > .94
        assert result["boundary_source"] == "silhouette"


def test_foreshortened_blank_silhouette_still_requires_card_structure():
    frame = np.full((900, 1600, 3), 70, dtype=np.uint8)
    cv2.rectangle(frame, (550, 260), (900, 660), (180, 180, 180), -1)
    assert SixCardGridDetector._contour_candidates(frame) == []


def test_nested_artwork_region_is_suppressed_even_with_low_full_card_iou():
    full = np.array([[.2, .2], [.4, .2], [.4, .6], [.2, .6]], dtype=np.float32)
    artwork = np.array([[.23, .25], [.37, .25], [.37, .37], [.23, .37]], dtype=np.float32)
    assert SixCardGridDetector._polygon_iou(full, artwork) < .30
    assert SixCardGridDetector._polygon_containment(full, artwork) > .99


class _FakeWorker:
    def __init__(self, emit):
        self.emit = emit

    def invalidate_before(self, _generation):
        return None

    def submit_frame(self, _frame, *, generation, frame_id, **_kwargs):
        self.emit({
            "type": "recognition_update",
            "payload": {
                "generation": generation,
                "frame_id": frame_id,
                "recognition_locked": True,
                "overall_confidence": .91,
                "database_match": {"name": f"Variant {frame_id}", "collector_number": str(155 + frame_id)},
                "candidates": [],
                "last_latency_ms": 12.5,
                "stage_timings": {"ocr_ms": 4.0, "total_ms": 12.5},
            },
        })
        return "accepted"

    def shutdown(self):
        return None


class _FakePrototype:
    def isolated_copy(self, emit):
        return _FakeWorker(emit)


def _synthetic_reference_image(family_seed: int, variant_seed: int) -> np.ndarray:
    """Build a deterministic full-card fixture with shared art and unique treatment."""
    image = np.full((1400, 1000, 3), (28, 36, 48), dtype=np.uint8)
    cv2.rectangle(image, (24, 24), (975, 1375), (225, 225, 225), 16)
    art_rng = np.random.default_rng(family_seed)
    cv2.rectangle(image, (70, 170), (930, 670), (52, 78, 104), -1)
    for _ in range(180):
        x = int(art_rng.integers(90, 910))
        y = int(art_rng.integers(190, 650))
        radius = int(art_rng.integers(3, 18))
        color = tuple(int(value) for value in art_rng.integers(45, 245, size=3))
        cv2.circle(image, (x, y), radius, color, -1)
    cv2.putText(
        image,
        f"FAMILY {family_seed}",
        (105, 625),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (245, 245, 245),
        4,
        cv2.LINE_AA,
    )

    treatment_rng = np.random.default_rng(variant_seed)
    cv2.rectangle(image, (70, 700), (930, 1300), (38, 44, 58), -1)
    for row in range(10):
        for column in range(14):
            if int(treatment_rng.integers(0, 3)):
                left = 90 + column * 58
                top = 725 + row * 52
                color = tuple(int(value) for value in treatment_rng.integers(70, 255, size=3))
                cv2.rectangle(image, (left, top), (left + 34, top + 28), color, -1)
    cv2.putText(
        image,
        f"VARIANT {variant_seed}",
        (120, 1260),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.3,
        (250, 250, 250),
        4,
        cv2.LINE_AA,
    )
    return image


@pytest.fixture(scope="session")
def deterministic_reference_cards(tmp_path_factory):
    root = tmp_path_factory.mktemp("multi-card-reference-fixtures")
    specifications = [
        ("GEM_PACK_VOL_1", "032", "Crocalor", "04 03/08", None, None, 101, 1),
        ("GEM_PACK_VOL_5", "040", "Sunflora", None, 6, 5, 202, 5),
        ("GEM_PACK_VOL_5", "156", "Crocalor", None, 23, 2, 303, 2),
        ("GEM_PACK_VOL_5", "157", "Crocalor", None, 23, 3, 303, 3),
        ("GEM_PACK_VOL_5", "158", "Crocalor", None, 23, 4, 303, 4),
        ("GEM_PACK_VOL_5", "159", "Crocalor", None, 23, 5, 303, 5),
        ("GEM_PACK_VOL_5", "160", "Crocalor", None, 23, 6, 303, 6),
        ("GEM_PACK_VOL_5", "161", "Crocalor", None, 23, 7, 303, 7),
        ("GEM_PACK_VOL_5", "167", "Quaxwell", None, 24, 6, 404, 6),
        ("GEM_PACK_VOL_5", "168", "Quaxwell", None, 24, 7, 404, 7),
        ("GEM_PACK_VOL_5", "185", "Cetitan", None, 27, 3, 505, 3),
    ]
    records = []
    for set_id, number, name, printed_code, species, variation, family_seed, variant_seed in specifications:
        path = root / f"{set_id}-{number}.png"
        assert cv2.imwrite(str(path), _synthetic_reference_image(family_seed, variant_seed))
        record = {
            "id": f"fixture-{set_id.lower()}-{number}",
            "set_id": set_id,
            "set_name": set_id.replace("_", " ").title(),
            "collector_number": number,
            "canonical_name": name,
            "english_name": name,
            "name": name,
            "reference_image": str(path),
        }
        if printed_code:
            record["printed_code"] = printed_code
        if species is not None:
            record["species_slot"] = species
            record["variation_slot"] = variation
            record["printed_code"] = f"{species:02d}{variation:02d}/07"
        records.append(record)
    return records


@pytest.fixture(autouse=True)
def use_deterministic_reference_cards(monkeypatch, deterministic_reference_cards):
    monkeypatch.setattr(
        MultiCardRecognitionService,
        "_load_reference_cards",
        staticmethod(lambda: [dict(card) for card in deterministic_reference_cards]),
    )


def _reference_crop(service, set_id: str, collector_number: str) -> np.ndarray:
    record = next(
        card for card in service._reference_cards
        if card.get("set_id") == set_id
        and str(card.get("collector_number")) == str(collector_number)
    )
    crop = cv2.imread(str(record["reference_image"]))
    assert crop is not None
    return crop


def test_multi_card_jobs_keep_six_results_isolated(monkeypatch):
    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    monkeypatch.setattr(
        SixCardGridDetector,
        "detect",
        lambda _frame, max_cards=6: [
            {"slot": slot, "confidence": .9, "polygon": [], "crop": crop, "ocr_crop": crop}
            for slot in range(1, max_cards + 1)
        ],
    )
    service = MultiCardRecognitionService(_FakePrototype())
    result = service.capture(np.zeros((600, 900, 3), dtype=np.uint8))

    assert result["ok"] is True
    assert result["detected_count"] == 6
    assert result["completed_count"] == 6
    assert result["status"] == "complete"
    assert [slot["card"]["name"] for slot in result["slots"]] == [
        f"Variant {slot}" for slot in range(1, 7)
    ]
    assert result["worker_latency_summary"]["mean_ms"] == 12.5
    assert "visual_variants_ms" in result["reconciliation_timings"]


def test_unresolved_family_candidate_cannot_remain_verified():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "verified",
            "verified": True,
            "collector_number": "161",
            "printed_code": None,
            "exact_version_unresolved": True,
            "card": {
                "canonical_name": "Crocalor",
                "collector_number": "161",
                "reference_image": "borrowed.png",
            },
        }]
        service._enforce_exact_identity_safety()

    slot = service.status()["slots"][0]
    assert slot["status"] == "review-needed"
    assert slot["verified"] is False
    assert slot["collector_number"] is None
    assert "collector_number" not in slot["card"]
    assert "reference_image" not in slot["card"]


def test_new_capture_drops_selected_slots_that_are_not_detected(monkeypatch, tmp_path):
    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    monkeypatch.setattr(
        SixCardGridDetector,
        "detect",
        lambda _frame, max_cards=6: [
            {"slot": slot, "confidence": .9, "polygon": [], "crop": crop, "ocr_crop": crop}
            for slot in range(1, max_cards + 1)
        ],
    )
    presentation = tmp_path / "multi-card-presentation.json"
    presentation.write_text('{"selected_slots":[4]}', encoding="utf-8")
    service = MultiCardRecognitionService(_FakePrototype(), presentation_path=presentation)

    result = service.capture(np.zeros((600, 900, 3), dtype=np.uint8), max_cards=3)

    assert result["detected_count"] == 3
    assert result["selected_slots"] == []
    assert service.status()["selected_slots"] == []


def test_dominant_family_repairs_single_global_index_escape():
    service = MultiCardRecognitionService(_FakePrototype())
    family = {"name": "Crocalor", "canonical_name": "Crocalor", "set_id": "gem", "score": .7}
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "review-needed", "card": dict(family)}
            for slot in range(1, 6)
        ] + [{"slot": 6, "status": "review-needed", "card": {"name": "Tropical Beach", "set_id": "bwp"}}]
        service._candidate_cache[6] = [
            {"name": "Tropical Beach", "set_id": "bwp", "score": .9},
            {**family, "collector_number": "161", "score": .68},
        ]
        service._reconcile_dominant_family()

    repaired = service.status()["slots"][5]
    assert repaired["card"]["name"] == "Crocalor"
    assert repaired["card"]["collector_number"] == "161"
    assert repaired["family_reconciled"] is True


def test_family_reconciliation_does_not_change_a_mixed_scan():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "review-needed", "card": {"name": f"Card {slot}", "set_id": "mixed"}}
            for slot in range(1, 7)
        ]
        original = [dict(item["card"]) for item in service._state["slots"]]
        service._reconcile_dominant_family()

    assert [item["card"] for item in service.status()["slots"]] == original


def test_missing_canonical_identity_recovers_from_strong_artwork_family(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1, "status": "review-needed", "verified": False,
            "card": {"name": "XY176", "collector_number": "XY176"},
        }]
        monkeypatch.setattr(service, "_best_artwork_family", lambda slot: "Quaxwell")
        monkeypatch.setattr(service, "_best_named_reference", lambda name, slot: {
            "canonical_name": name, "set_id": "GEM_PACK_VOL_5", "collector_number": "168",
        })
        service._reconcile_missing_artwork_families()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Quaxwell"
    assert slot["collector_number"] == "168"
    assert slot["artwork_family_recovered"] is True


def test_shared_ocr_identity_replaces_unrelated_visual_result_without_inventing_version():
    service = MultiCardRecognitionService(_FakePrototype())
    noisy_printed_names = ["文烫鳄", "炙烫鳷", "炙烫", "炙汤鳄", "炙烫鳄"]
    family = {
        "name": "Crocalor",
        "canonical_name": "Crocalor",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "156",
        "reference_image": "crocalor-156.png",
        "language": "zh-cn",
    }
    with service._lock:
        service._state["slots"] = [
            {
                "slot": slot,
                "status": "verified",
                "card": {**family, "collector_number": str(155 + slot)},
                "name_candidate": f"noisy-{slot}",
                "raw_text": [{"text": noisy_printed_names[slot - 1]}, {"text": "110"}],
                "language": "zh-cn",
            }
            for slot in range(1, 6)
        ] + [{
            "slot": 6,
            "status": "review-needed",
            "card": {"name": "Crystal Wall", "canonical_name": "Crystal Wall", "set_id": "xy"},
            "name_candidate": "进化",
            "raw_text": [{"text": "炙烫鳄"}, {"text": "巨声"}],
            "language": "zh-cn",
        }]
        service._reconcile_ocr_identity()

    repaired = service.status()["slots"][5]
    assert repaired["card"]["canonical_name"] == "Crocalor"
    assert repaired["card"]["printed_name"] == "炙烫鳄"
    assert repaired["card"]["exact_version_unresolved"] is True
    assert "collector_number" not in repaired["card"]
    assert "reference_image" not in repaired["card"]
    assert repaired["verified"] is False


def test_repeated_canonical_candidates_beat_weak_generated_filename():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "review-needed",
            "verified": False,
            "card": {"name": "CSV7-generated-name", "set_id": "CSV7", "fused_score": .558},
        }]
        service._candidate_cache[1] = [
            {"name": "CSV7-generated-name", "set_id": "CSV7", "fused_score": .558},
            {"name": "Sunflora", "canonical_name": "Sunflora", "collector_number": "040", "fused_score": .537},
            {"name": "Sunflora", "canonical_name": "Sunflora", "collector_number": "036", "fused_score": .532},
        ]
        service._reconcile_candidate_consensus()

    repaired = service.status()["slots"][0]
    assert repaired["card"]["canonical_name"] == "Sunflora"
    assert repaired["card"]["collector_number"] == "040"
    assert repaired["candidate_family_consensus"] is True
    assert repaired["verified"] is False


def test_named_reference_resolves_missing_gem_pack_vol_1_crocalor():
    service = MultiCardRecognitionService(_FakePrototype())
    record = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_1" and item.get("collector_number") == "032"
    )
    assert record["canonical_name"] == "Crocalor"
    assert record["printed_code"] == "04 03/08"
    service._crop_cache[8] = cv2.imread(str(record["reference_image"]))

    resolved = service._best_named_reference("Crocalor", 8)

    assert resolved is not None
    assert resolved["set_id"] == "GEM_PACK_VOL_1"
    assert resolved["collector_number"] == "032"


def test_unresolved_exception_resolves_from_canonical_candidate_and_own_crop():
    service = MultiCardRecognitionService(_FakePrototype())
    record = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_1" and item.get("collector_number") == "032"
    )
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "review-needed",
            "verified": False,
            "card": {"name": "Wrong version"},
        }]
        service._crop_cache[1] = cv2.imread(str(record["reference_image"]))
        service._candidate_cache[1] = [{
            "name": "Crocalor",
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
        }]
        service._reconcile_unresolved_references()

    repaired = service.status()["slots"][0]
    assert repaired["card"]["set_id"] == "GEM_PACK_VOL_1"
    assert repaired["card"]["collector_number"] == "032"
    assert repaired["verified"] is True
    assert repaired["exception_reference_resolved"] is True


def test_low_confidence_variant_without_footer_stays_provisional():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "verified",
            "verified": True,
            "confidence": .46,
            "printed_code": None,
            "collector_number": "180",
            "card": {
                "name": "Cetitan", "canonical_name": "Cetitan",
                "set_id": "GEM_PACK_VOL_5", "collector_number": "180",
            },
        }]
        service._candidate_cache[1] = [
            {"canonical_name": "Cetitan", "set_id": "GEM_PACK_VOL_5", "collector_number": "180"},
            {"canonical_name": "Cetitan", "set_id": "GEM_PACK_VOL_5", "collector_number": "188"},
        ]
        service._enforce_exact_identity_safety()

    slot = service.status()["slots"][0]
    assert slot["verified"] is False
    assert slot["status"] == "review-needed"
    assert slot["collector_number"] is None
    assert slot["version_safety_reason"] == "weak_visual_variant_without_footer"


def test_verified_variant_displays_catalog_code_not_conflicting_raw_ocr():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1, "status": "verified", "verified": True,
            "confidence": .82, "printed_code": "2406/07",
            "card": {
                "canonical_name": "Quaxwell", "set_id": "GEM_PACK_VOL_5",
                "collector_number": "168", "printed_code": "2407/07",
            },
        }]
        service._enforce_exact_identity_safety()

    slot = service.status()["slots"][0]
    assert slot["printed_code"] == "2407/07"
    assert slot["ocr_printed_code_observed"] == "2406/07"


def test_unresolved_outlier_recovers_from_dominant_family_geometry_without_ocr_name():
    service = MultiCardRecognitionService(_FakePrototype())
    record = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_1" and item.get("collector_number") == "032"
    )
    family = {"name": "Crocalor", "canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5"}
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "verified", "verified": True, "card": dict(family)}
            for slot in range(1, 5)
        ] + [{
            "slot": 5,
            "status": "review-needed",
            "verified": False,
            "card": {"name": "Rayquaza-EX", "set_id": "xyp"},
        }]
        service._crop_cache[5] = cv2.imread(str(record["reference_image"]))
        service._candidate_cache[5] = [{"name": "Rayquaza-EX", "set_id": "xyp"}]
        service._reconcile_unresolved_references()

    repaired = service.status()["slots"][4]
    assert repaired["card"]["set_id"] == "GEM_PACK_VOL_1"
    assert repaired["card"]["collector_number"] == "032"
    assert repaired["dominant_family_reference_recovery"] is True
    assert repaired["verified"] is True


def test_bottom_printed_code_breaks_same_artwork_set_tie():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "review-needed",
            "verified": False,
            "confidence": .71,
            "exact_version_unresolved": True,
            "printed_code": "0605/07",
            "card": {
                "name": "Sunflora",
                "set_id": "CSV7",
                "collector_number": "022",
                "exact_version_unresolved": True,
            },
        }]
        service._candidate_cache[1] = [
            {"name": "Sunflora", "set_id": "CSV7", "collector_number": "022", "fused_score": .605},
            {"name": "Sunflora", "set_id": "GEM_PACK_VOL_5", "collector_number": "040", "printed_code": "0605/07", "fused_score": .587},
        ]
        service._reconcile_printed_codes()

    repaired = service.status()["slots"][0]
    assert repaired["card"]["set_id"] == "GEM_PACK_VOL_5"
    assert repaired["card"]["collector_number"] == "040"
    assert repaired["printed_code"] == "0605/07"
    assert repaired["printed_code_resolved"] is True
    assert repaired["verified"] is True
    assert repaired["exact_version_unresolved"] is False
    assert repaired["card"]["exact_version_unresolved"] is False
    assert repaired["confidence"] == .71


def test_footer_code_resolves_against_full_catalog_not_wrong_visual_shortlist():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "review-needed",
            "verified": False,
            "printed_code": "2406/67",
            "raw_text": [{"text": "2406/07", "score": .96}],
            "card": {"canonical_name": "Crocalor", "collector_number": "161"},
        }]
        service._candidate_cache[1] = [{
            "canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5",
            "collector_number": "161", "printed_code": "2306/07", "fused_score": .8,
        }]
        service._reconcile_printed_codes()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Quaxwell"
    assert slot["card"]["collector_number"] == "167"
    assert slot["printed_code"] == "2406/07"
    assert slot["verified"] is True


def test_conflicting_footer_codes_do_not_verify_a_variant():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "review-needed",
            "verified": False,
            "printed_code": "2001/07",
            "raw_text": [{"text": "2003/07", "score": .93}],
            "card": {"canonical_name": "Applin"},
        }]
        service._reconcile_printed_codes()

    assert service.status()["slots"][0]["verified"] is False


def test_misread_species_prefix_cannot_override_visual_family():
    service = MultiCardRecognitionService(_FakePrototype())
    reference = next(
        card for card in service._reference_cards
        if card.get("canonical_name") == "Cetitan" and card.get("collector_number") == "185"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    with service._lock:
        service._crop_cache[1] = crop
        service._state["slots"] = [{
            "slot": 1, "status": "review-needed", "verified": False,
            "printed_code": "2303/07", "card": {"canonical_name": "Cetitan"},
        }]
        service._candidate_cache[1] = [
            {"canonical_name": "Cetitan", "collector_number": "185", "fused_score": .48},
            {"canonical_name": "Cetitan", "collector_number": "184", "fused_score": .46},
        ]
        service._reconcile_printed_codes()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Cetitan"
    assert slot["artwork_family_preserved"] is True
    assert slot["printed_code_conflict"] == "2303/07"


def test_fast_family_code_conflict_does_not_rescan_reference_images(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    monkeypatch.setattr(service, "_best_artwork_family", lambda *_args: (
        _ for _ in ()
    ).throw(AssertionError("fast family must not rescan artwork")))
    monkeypatch.setattr(service, "_best_named_reference", lambda *_args: (
        _ for _ in ()
    ).throw(AssertionError("conflicting footer must stay provisional")))
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "verified": False,
        "printed_code": "2303/07",
        "artwork_family_fast_path": True,
        "card": {"canonical_name": "Cetitan"},
    }]

    service._reconcile_printed_codes()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Cetitan"
    assert slot["verified"] is False
    assert slot["printed_code_conflict"] == "2303/07"


def test_bottom_code_never_overwrites_batch_resolved_variant():
    service = MultiCardRecognitionService(_FakePrototype())
    with service._lock:
        service._state["slots"] = [{
            "slot": 1,
            "status": "verified",
            "verified": True,
            "batch_variant_resolved": True,
            "printed_code": "2301/07",
            "card": {"name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "158"},
        }]
        service._candidate_cache[1] = [{
            "name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "156",
            "printed_code": "2301/07",
            "fused_score": .9,
        }]
        service._reconcile_printed_codes()

    repaired = service.status()["slots"][0]
    assert repaired["card"]["collector_number"] == "158"
    assert "printed_code_resolved" not in repaired


def test_unique_variant_mode_assigns_one_version_per_slot():
    service = MultiCardRecognitionService(_FakePrototype())
    variants = [
        {"id": f"gem-{number}", "name": "Crocalor", "set_id": "gem", "collector_number": str(number)}
        for number in range(156, 162)
    ]
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "review-needed", "card": {**variants[0], "score": .7}}
            for slot in range(1, 7)
        ]
        for slot in range(1, 7):
            service._candidate_cache[slot] = [
                {**variant, "score": .95 if index == slot - 1 else .55}
                for index, variant in enumerate(variants)
            ]
        service._assign_unique_variants()

    assigned = service.status()["slots"]
    assert [item["card"]["collector_number"] for item in assigned] == [str(number) for number in range(156, 162)]
    assert all(item["unique_variant_assigned"] is True for item in assigned)


def test_visual_family_batch_resolves_exact_local_variant_set():
    service = MultiCardRecognitionService(_FakePrototype())
    crops = [
        _reference_crop(service, "GEM_PACK_VOL_5", str(number))
        for number in range(156, 162)
    ]
    with service._lock:
        service._state["slots"] = [
            {
                "slot": slot,
                "status": "review-needed",
                "card": {
                    "name": "Crocalor",
                    "canonical_name": "Crocalor",
                    "set_id": "GEM_PACK_VOL_5",
                },
            }
            for slot in range(1, 7)
        ] + [{
            "slot": 7,
            "status": "verified",
            "verified": True,
            "card": {
                "name": "Crocalor",
                "canonical_name": "Crocalor",
                "set_id": "GEM_PACK_VOL_5",
            },
        }]
        service._crop_cache = {
            **{slot: crop for slot, crop in enumerate(crops, start=1)},
            7: np.zeros_like(crops[0]),
        }
        service._resolve_visual_variant_families()

    resolved = service.status()["slots"]
    assert [item["card"]["collector_number"] for item in resolved[:6]] == [
        str(number) for number in range(156, 162)
    ]
    assert all(item["batch_variant_resolved"] is True for item in resolved[:6])
    assert resolved[6]["verified"] is False
    assert resolved[6]["family_artwork_conflict"] is True


def test_visual_family_batch_resolves_strong_partial_variant_subset():
    service = MultiCardRecognitionService(_FakePrototype())
    numbers = (156, 159, 161)
    crops = [
        _reference_crop(service, "GEM_PACK_VOL_5", str(number))
        for number in numbers
    ]
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "review-needed", "verified": False, "card": {
                "name": "Crocalor", "canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5",
            }}
            for slot in range(1, 4)
        ]
        service._crop_cache = {slot: crop for slot, crop in enumerate(crops, start=1)}
        service._resolve_visual_variant_families()

    resolved = service.status()["slots"]
    assert [item["card"]["collector_number"] for item in resolved] == [str(number) for number in numbers]
    assert all(item["verified"] is True for item in resolved)
    assert all(item["batch_variant_resolved"] is True for item in resolved)


def test_partial_variant_subset_keeps_weak_assignments_unverified(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    crop = np.zeros((700, 500, 3), dtype=np.uint8)
    with service._lock:
        service._state["slots"] = [
            {"slot": slot, "status": "review-needed", "verified": False, "card": {
                "name": "Crocalor", "canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5",
            }}
            for slot in range(1, 4)
        ]
        service._crop_cache = {slot: crop.copy() for slot in range(1, 4)}
        monkeypatch.setattr(service, "_descriptor_score", lambda *_args: 46.0)
        service._resolve_visual_variant_families()

    unresolved = service.status()["slots"]
    assert all(item["verified"] is False for item in unresolved)
    assert all(item["batch_variant_diagnostics"]["margin_ready"] is False for item in unresolved)
    assert all(item["batch_variant_diagnostics"]["reference_count"] >= 3 for item in unresolved)


def test_family_first_scheduler_runs_one_worker_for_six_shared_artworks():
    service = MultiCardRecognitionService(_FakePrototype())
    crops = [
        _reference_crop(service, "GEM_PACK_VOL_5", str(number))
        for number in range(156, 162)
    ]
    outsider = np.zeros_like(crops[0])
    detections = [
        {"slot": slot, "crop": crop, "confidence": .8 + slot * .01}
        for slot, crop in enumerate([*crops, outsider], start=1)
    ]

    delegates = service._family_first_delegates(detections)

    assert len(delegates) == 1
    representative, siblings = next(iter(delegates.items()))
    assert representative == 6
    assert siblings == [1, 2, 3, 4, 5]
    assert 7 not in siblings


def test_family_first_scheduler_supports_three_shared_artworks():
    service = MultiCardRecognitionService(_FakePrototype())
    crops = [
        _reference_crop(service, "GEM_PACK_VOL_5", str(number))
        for number in (156, 159, 161)
    ]
    detections = [
        {"slot": slot, "crop": crop, "confidence": .85 + slot * .01}
        for slot, crop in enumerate(crops, start=1)
    ]

    delegates = service._family_first_delegates(detections)

    assert len(delegates) == 1
    representative, siblings = next(iter(delegates.items()))
    assert representative == 3
    assert siblings == [1, 2]


def test_delegated_family_result_never_inherits_exact_version_or_lock():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{"slot": 1, "status": "recognizing", "card": None}]
    service._state["detected_count"] = 2
    service._apply_worker_payload(1, {
        "generation": service._job_id,
        "recognition_locked": True,
        "overall_confidence": .91,
        "database_match": {
            "name": "Crocalor", "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5", "collector_number": "161",
        },
        "ocr_collector_number": "161",
        "ocr_printed_code": "2106/07",
        "candidates": [],
    }, delegated_from=3)

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Crocalor"
    assert slot["card"].get("collector_number") is None
    assert slot["collector_number"] is None
    assert slot["printed_code"] is None
    assert slot["verified"] is False
    assert slot["status"] == "review-needed"
    assert slot["exact_version_unresolved"] is True


def test_later_reconciliation_cannot_restore_version_to_unresolved_delegate():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{
        "slot": 1,
        "status": "verified",
        "verified": True,
        "family_first_delegated": True,
        "delegated_from_slot": 2,
        "delegated_family_name": "Crocalor",
        "delegated_family_set_id": "GEM_PACK_VOL_5",
        "delegated_family_set_name": "Gem Pack Vol 5",
        "card": {
            "name": "Rayquaza-EX",
            "canonical_name": "Rayquaza-EX",
            "set_id": "xyp",
            "collector_number": "159",
            "printed_code": "2304/07",
            "reference_image": "wrong.png",
        },
        "collector_number": "159",
        "printed_code": "2304/07",
    }]

    service._enforce_delegated_version_safety()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Crocalor"
    assert slot["card"]["set_id"] == "GEM_PACK_VOL_5"
    assert slot["card"].get("collector_number") is None
    assert slot["card"].get("printed_code") is None
    assert slot["card"].get("reference_image") is None
    assert slot["card"]["recognition_source"] == "shared-family-fast-path"
    assert slot["collector_number"] is None
    assert slot["printed_code"] is None
    assert slot["verified"] is False
    assert slot["status"] == "review-needed"


def test_final_representative_family_replaces_stale_delegated_worker_family():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [
        {
            "slot": 1,
            "status": "verified",
            "verified": True,
            "card": {
                "name": "Crocalor",
                "canonical_name": "Crocalor",
                "set_id": "GEM_PACK_VOL_5",
                "set_name": "Gem Pack Vol 5",
            },
        },
        {
            "slot": 2,
            "status": "verified",
            "verified": True,
            "family_first_delegated": True,
            "delegated_from_slot": 1,
            "delegated_family_name": "Groudon-EX",
            "card": {
                "name": "Groudon-EX",
                "canonical_name": "Groudon-EX",
                "set_id": "xy5",
                "collector_number": "150",
            },
        },
    ]
    service._family_delegates = {1: [2]}

    service._synchronize_delegated_families()
    service._enforce_delegated_version_safety()

    sibling = service.status()["slots"][1]
    assert sibling["card"]["canonical_name"] == "Crocalor"
    assert sibling["card"]["set_id"] == "GEM_PACK_VOL_5"
    assert sibling["delegated_family_synchronized"] is True
    assert sibling["verified"] is False
    assert sibling["exact_version_unresolved"] is True


def test_batch_artwork_family_beats_generic_global_escape():
    service = MultiCardRecognitionService(_FakePrototype())
    service._candidate_cache[1] = [{
        "name": "Champions Festival",
        "source": "global_visual_index",
        "retrieval_only": True,
        "score": 0.91,
    }]
    service._batch_hint_cache[1] = [{
        "canonical_name": "Quaxwell",
        "source": "pokipair",
        "image_path": "quaxwell.png",
    }, {
        "canonical_name": "Quaxwell",
        "source": "pokipair",
        "image_path": "quaxwell-variant.png",
    }]

    assert service._trusted_local_candidate_family(1) == "Quaxwell"


def test_batch_family_uses_nearest_artwork_not_catalog_variant_count():
    service = MultiCardRecognitionService(_FakePrototype())
    service._batch_hint_cache[1] = [
        *[
            {
                "canonical_name": "Bellibolt", "source": "pokipair",
                "image_path": f"bellibolt-{index}.png", "batch_distance": 18 + index,
            }
            for index in range(5)
        ],
        {
            "canonical_name": "Quaxwell", "source": "pokipair",
            "image_path": "quaxwell.png", "batch_distance": 4,
        },
        {
            "canonical_name": "Quaxwell", "source": "pokipair",
            "image_path": "quaxwell-alt.png", "batch_distance": 7,
        },
    ]

    family, votes, _margin = service._batch_candidate_family(1)

    assert family == "Quaxwell"
    assert votes == 2


def test_batch_family_is_published_before_background_worker_finishes():
    class PendingWorker(_FakeWorker):
        def submit_frame(self, *_args, **_kwargs):
            return "accepted"

        def seed_batch_artwork_hints(self, *_args, **_kwargs):
            return None

    class BatchIndex:
        def batch_shortlists(self, _crops):
            candidates = [
                {"canonical_name": "Quaxwell", "source": "pokipair", "image_path": "a.png"},
                {"canonical_name": "Quaxwell", "source": "pokipair", "image_path": "b.png"},
                {"canonical_name": "Quaxwell", "source": "pokipair", "image_path": "c.png"},
            ]
            return {"slots": {1: {"artwork_candidates": candidates}}, "catalog_records_visited": 2, "live_card_count": 1}

    class Prototype:
        artwork_index = BatchIndex()

        def isolated_copy(self, emit):
            return PendingWorker(emit)

    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    service = MultiCardRecognitionService(Prototype())
    result = service.capture(
        np.zeros((600, 900, 3), dtype=np.uint8),
        max_cards=2,
        detections=[{"slot": 1, "confidence": .9, "polygon": [], "crop": crop, "ocr_crop": crop}],
    )

    assert result["slots"][0]["status"] == "recognizing"
    assert result["slots"][0]["card"]["canonical_name"] == "Quaxwell"
    assert result["slots"][0]["batch_family_interim"] is True
    assert result["slots"][0]["fast_candidate_latency_ms"] < 1000


def test_single_batch_hash_collision_cannot_establish_family():
    service = MultiCardRecognitionService(_FakePrototype())
    service._batch_hint_cache[1] = [{
        "canonical_name": "Groudon-EX",
        "source": "pokipair",
        "image_path": "collision.png",
    }]

    assert service._trusted_local_candidate_family(1) == ""


def test_disagreeing_worker_and_batch_families_require_artwork_tiebreaker(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "verified": False,
        "card": {"canonical_name": "Crocalor"},
    }]
    service._candidate_cache[1] = [{
        "canonical_name": "Crocalor",
        "source": "pokipair",
        "verification_strong": True,
        "artwork_verification_strong": True,
        "score": .72,
    }]
    service._batch_hint_cache[1] = [
        {"canonical_name": "Flittle", "source": "pokipair", "image_path": f"f{index}.png"}
        for index in range(3)
    ]
    monkeypatch.setattr(service, "_best_artwork_family", lambda _slot: "Quaxwell")
    monkeypatch.setattr(service, "_best_named_reference", lambda *_args: None)

    service._reconcile_missing_artwork_families()

    slot = service.status()["slots"][0]
    assert slot["card"]["canonical_name"] == "Quaxwell"
    assert slot["family_evidence_conflict"]["worker"] == "Crocalor"
    assert slot["family_evidence_conflict"]["batch"] == "Flittle"
    assert slot["family_conflict_resolved_by_artwork"] is True


def test_visual_interim_does_not_complete_slot_before_background_enrichment():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{"slot": 1, "status": "recognizing", "card": None}]
    service._state["detected_count"] = 1
    service._state["completed_count"] = 0
    service._state["status"] = "recognizing"

    service._apply_worker_payload(1, {
        "recognition_path": "visual-interim",
        "background_enrichment": True,
        "candidates": [{"canonical_name": "Provisional candidate", "score": .8}],
        "overall_confidence": .8,
    })

    state = service.status()
    assert state["slots"][0]["status"] == "recognizing"
    assert state["slots"][0]["background_enrichment"] is True
    assert state["completed_count"] == 0
    assert state["status"] == "recognizing"


def test_late_visual_interim_cannot_regress_or_recount_completed_slot():
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "card": {"canonical_name": "Crocalor"},
    }]
    service._state["detected_count"] = 1
    service._state["completed_count"] = 1
    service._state["status"] = "complete"

    service._apply_worker_payload(1, {
        "recognition_path": "visual-interim",
        "background_enrichment": True,
        "candidates": [{"canonical_name": "Wrong late candidate", "score": .9}],
    })

    state = service.status()
    assert state["slots"][0]["status"] == "review-needed"
    assert state["slots"][0]["card"]["canonical_name"] == "Crocalor"
    assert state["completed_count"] == 1
    assert state["status"] == "complete"


def test_corrupt_persisted_completion_counters_are_not_restored(tmp_path):
    presentation = tmp_path / "presentation.json"
    presentation.write_text(json.dumps({
        "version": 1,
        "selected_slots": [],
        "completed_state": {
            "status": "complete",
            "detected_count": 2,
            "completed_count": 7,
            "slots": [{"slot": 1, "status": "review-needed", "card": {"name": "Crocalor"}}],
        },
    }), encoding="utf-8")

    service = MultiCardRecognitionService(_FakePrototype(), presentation_path=presentation)

    assert service.status()["status"] == "idle"
    assert service.status()["completed_count"] == 0


def test_capture_reuses_precomputed_detections(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    crop = np.zeros((700, 500, 3), dtype=np.uint8)
    detections = [{
        "slot": 1,
        "crop": crop,
        "ocr_crop": crop,
        "confidence": .9,
        "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
    }]
    monkeypatch.setattr(SixCardGridDetector, "detect", lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("detection must not run twice")))

    result = service.capture(
        np.zeros((900, 1200, 3), dtype=np.uint8),
        max_cards=2,
        detections=detections,
    )

    assert result["detected_count"] == 1


def test_trusted_family_fast_path_skips_duplicate_deep_reconciliation(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    service._state = {
        **service._empty_state(),
        "status": "recognizing",
        "detected_count": 1,
        "completed_count": 0,
        "unique_variants": False,
        "slots": [{
            "slot": 1,
            "status": "recognizing",
            "card": None,
            "stage_timings": {"family_shortlist_verified": True},
        }],
    }
    monkeypatch.setattr(service, "_resolve_visual_variant_families", lambda: (
        _ for _ in ()
    ).throw(AssertionError("duplicate variant pass must be skipped")))
    monkeypatch.setattr(service, "_reconcile_unresolved_references", lambda: (
        _ for _ in ()
    ).throw(AssertionError("duplicate reference pass must be skipped")))

    service._update_slot(1, {
        "status": "review-needed",
        "card": {"canonical_name": "Crocalor"},
    })

    timings = service.status()["reconciliation_timings"]
    assert timings["visual_variants_skipped"] is True
    assert timings["unresolved_references_skipped"] is True
    assert timings["visual_variants_ms"] == 0.0
    assert timings["unresolved_references_ms"] == 0.0


def test_temporal_confirmation_requires_two_matching_prior_exact_observations():
    service = MultiCardRecognitionService(_FakePrototype())
    reference = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_5" and item.get("collector_number") == "040"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    descriptor = service._sift_descriptors(crop, treatment=True)
    service._crop_cache[1] = crop
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "verified": False,
        "card": {"name": "Sunflora", "canonical_name": "Sunflora"},
    }]
    service._temporal_history[1] = {
        "card": dict(reference),
        "descriptor": descriptor,
        "confirmations": 1,
    }
    service._apply_temporal_confirmation()
    assert service.status()["slots"][0]["verified"] is False
    assert service.status()["slots"][0]["temporal_confirmation_progress"] == 1
    assert service.status()["slots"][0]["temporal_confirmation_required"] == 2

    service._temporal_history[1]["confirmations"] = 2
    service._apply_temporal_confirmation()
    repaired = service.status()["slots"][0]
    assert repaired["verified"] is True
    assert repaired["card"]["collector_number"] == "040"
    assert repaired["temporal_confirmation"] is True
    assert repaired["temporal_confirmation_progress"] == 2


def test_concurrent_exact_reference_workers_never_share_a_sentinel_crop(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    seen = []

    def fake_matches(name, crop):
        marker = int(crop[0, 0, 0])
        seen.append((name, marker))
        time.sleep(.02)
        return [(50.0, {
            "canonical_name": name,
            "set_id": "test",
            "collector_number": str(marker),
        })]

    monkeypatch.setattr(service, "_named_reference_matches_crop", fake_matches)
    left = np.full((80, 60, 3), 11, dtype=np.uint8)
    right = np.full((80, 60, 3), 22, dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(service.resolve_exact_reference, left, "Applin"),
            pool.submit(service.resolve_exact_reference, right, "Cetitan"),
        ]
        results = [future.result() for future in futures]

    assert sorted(seen) == [("Applin", 11), ("Cetitan", 22)]
    assert results[0]["card"]["collector_number"] == "11"
    assert results[1]["card"]["collector_number"] == "22"
    assert SixCardGridDetector.MAX_CARDS + 1 not in service._crop_cache


def test_temporal_history_persists_and_reloads_without_sift_descriptors(tmp_path):
    history_path = tmp_path / "temporal.json"
    service = MultiCardRecognitionService(_FakePrototype(), history_path=history_path)
    service._temporal_history[4] = {
        "card": {"name": "Sunflora", "canonical_name": "Sunflora", "set_id": "GEM_PACK_VOL_5", "collector_number": "040"},
        "descriptor": ([], np.zeros((1, 128), dtype=np.float32)),
        "fingerprint": "0123456789abcdef",
        "treatment_response": (120.0, 25.0, 80.0),
        "center": [.5, .5],
        "confirmations": 3,
        "updated_at": time.time(),
    }
    service._persist_temporal_history()

    restored = MultiCardRecognitionService(_FakePrototype(), history_path=history_path)

    assert restored._temporal_history[4]["card"]["collector_number"] == "040"
    assert restored._temporal_history[4]["confirmations"] == 3
    assert "descriptor" not in restored._temporal_history[4]
    assert restored._temporal_history[4]["treatment_response"] == [120.0, 25.0, 80.0]


def test_temporal_history_rejects_synthetic_identity_and_blank_fingerprint(tmp_path):
    history_path = tmp_path / "temporal.json"
    history_path.write_text(json.dumps({
        "version": 1,
        "slots": {
            "4": {
                "card": {"name": "Variant 4", "collector_number": "159"},
                "fingerprint": "0000000000000000",
                "confirmations": 4,
                "updated_at": time.time(),
            }
        },
    }), encoding="utf-8")

    restored = MultiCardRecognitionService(_FakePrototype(), history_path=history_path)

    assert restored._temporal_history == {}


def test_record_temporal_evidence_advances_persisted_entry_without_descriptor(tmp_path):
    history_path = tmp_path / "temporal.json"
    service = MultiCardRecognitionService(_FakePrototype(), history_path=history_path)
    reference = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_5" and item.get("collector_number") == "040"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    service._crop_cache[1] = crop
    service._state["slots"] = [{
        "slot": 1,
        "status": "verified",
        "verified": True,
        "card": dict(reference),
        "polygon": [[.1, .1], [.3, .1], [.3, .4], [.1, .4]],
    }]
    service._temporal_history[1] = {
        "card": dict(reference),
        "fingerprint": ArtworkIndexService.variant_marker_fingerprint(crop),
        "center": [.2, .25],
        "confirmations": 2,
        "updated_at": time.time(),
    }

    service._record_temporal_evidence()

    assert service._temporal_history[1]["confirmations"] == 3
    assert history_path.exists()


def test_exact_observation_keeps_streak_when_lighting_changes_fingerprint(tmp_path):
    service = MultiCardRecognitionService(_FakePrototype(), history_path=tmp_path / "temporal.json")
    reference = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_5" and item.get("collector_number") == "040"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    service._crop_cache[1] = crop
    service._state["slots"] = [{
        "slot": 1,
        "verified": True,
        "card": dict(reference),
        "polygon": [[.1, .1], [.3, .1], [.3, .4], [.1, .4]],
    }]
    service._temporal_history[1] = {
        "card": dict(reference),
        "fingerprint": "ffffffffffffffff",
        "center": [.2, .25],
        "confirmations": 4,
        "updated_at": time.time(),
    }

    service._record_temporal_evidence()

    assert service._temporal_history[1]["confirmations"] == 5


def test_variant_assignment_uses_matching_temporal_fingerprint_as_tiebreaker():
    service = MultiCardRecognitionService(_FakePrototype())
    references = [
        record for record in service._reference_cards
        if record.get("set_id") == "GEM_PACK_VOL_5"
        and str(record.get("collector_number")) in {"156", "157", "158", "159", "160", "161"}
    ]
    references.sort(key=lambda card: int(card["collector_number"]))
    crops = {}
    slots = []
    for index, reference in enumerate(references, start=1):
        crop = cv2.imread(str(reference["reference_image"]))
        crops[index] = crop
        slots.append({"slot": index, "card": dict(reference), "verified": True})
    service._crop_cache = crops
    service._state["slots"] = slots
    service._temporal_history[1] = {
        "card": dict(references[2]),
        "fingerprint": ArtworkIndexService.variant_marker_fingerprint(crops[1]),
        "confirmations": 3,
        "updated_at": time.time(),
    }
    reference_tuples = [(reference, crops[index], ([], None)) for index, reference in enumerate(references, start=1)]
    scores = [[50.0 for _ in references] for _ in references]

    service._apply_temporal_variant_priors(list(crops), reference_tuples, scores)

    assert scores[0][2] == 400.0
    assert sum(score for row in scores for score in row) == 50.0 * 36 + 350.0


def test_single_temporal_observation_requires_near_identical_variant_fingerprint():
    service = MultiCardRecognitionService(_FakePrototype())
    reference = next(
        card for card in service._reference_cards
        if card.get("set_id") == "GEM_PACK_VOL_5" and card.get("collector_number") == "160"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    fingerprint = ArtworkIndexService.variant_marker_fingerprint(crop)
    service._crop_cache[1] = crop
    references = [(reference, crop, ([], None))]
    scores = [[20.0]]
    service._temporal_history[1] = {
        "card": dict(reference),
        "fingerprint": fingerprint,
        "confirmations": 1,
    }

    service._apply_temporal_variant_priors([1], references, scores)
    assert scores == [[370.0]]

    service._temporal_history[1]["fingerprint"] = "0" * 16
    scores = [[20.0]]
    service._apply_temporal_variant_priors([1], references, scores)
    assert scores == [[20.0]]


def test_selected_output_slots_persist_across_service_restart(tmp_path):
    presentation_path = tmp_path / "multi-card-presentation.json"
    service = MultiCardRecognitionService(
        _FakePrototype(), presentation_path=presentation_path
    )
    service._state["slots"] = [
        {"slot": slot, "status": "verified", "verified": True, "card": {"name": f"Card {slot}"}}
        for slot in (2, 5, 12)
    ]
    assert service.select_slots([2, 5, 12])["ok"] is True

    restored = MultiCardRecognitionService(
        _FakePrototype(), presentation_path=presentation_path
    )

    assert restored.status()["selected_slots"] == [2, 5, 12]


def test_completed_grid_results_persist_without_heavy_worker_payloads(tmp_path):
    presentation_path = tmp_path / "multi-card-presentation.json"
    service = MultiCardRecognitionService(
        _FakePrototype(), presentation_path=presentation_path
    )
    service._state = {
        **service._empty_state(),
        "status": "complete",
        "detected_count": 1,
        "completed_count": 1,
        "max_cards": 2,
        "slots": [{
            "slot": 1,
            "status": "verified",
            "verified": True,
            "card": {"english_name": "Crocalor", "collector_number": "157"},
            "confidence": .91,
            "polygon": [[.1, .1], [.2, .1], [.2, .3], [.1, .3]],
            "raw_text": [{"text": "large transient OCR"}],
            "candidate_preview": [{"id": "transient"}],
        }],
    }
    service._persist_presentation()

    restored = MultiCardRecognitionService(
        _FakePrototype(), presentation_path=presentation_path
    ).status()

    assert restored["restored"] is True
    assert restored["slots"][0]["card"]["collector_number"] == "157"
    assert "raw_text" not in restored["slots"][0]
    assert "candidate_preview" not in restored["slots"][0]


def test_public_exact_reference_resolver_reuses_strict_margin_gate(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    crop = np.zeros((700, 500, 3), dtype=np.uint8)
    monkeypatch.setattr(service, "_named_reference_matches_crop", lambda name, crop: [
        (36.0, {"canonical_name": name, "collector_number": "157"}),
        (27.0, {"canonical_name": name, "collector_number": "159"}),
    ])

    resolved = service.resolve_exact_reference(crop, "Crocalor")
    assert resolved["card"]["collector_number"] == "157"
    assert resolved["diagnostics"]["status"] == "resolved"
    assert resolved["diagnostics"]["score_gap"] == 9.0

    monkeypatch.setattr(service, "_named_reference_matches_crop", lambda name, crop: [
        (36.0, {"canonical_name": name, "collector_number": "157"}),
        (30.0, {"canonical_name": name, "collector_number": "159"}),
    ])
    ambiguous = service.resolve_exact_reference(crop, "Crocalor")
    assert ambiguous["card"] is None
    assert ambiguous["diagnostics"]["status"] == "ambiguous"
    assert ambiguous["diagnostics"]["score_gap"] == 6.0


def test_variant_marker_score_is_bounded_and_rewards_exact_treatment() -> None:
    exact = MultiCardRecognitionService._variant_marker_score(
        "0000000000000000", "0000000000000000"
    )
    close = MultiCardRecognitionService._variant_marker_score(
        "0000000000000000", "0000000000000007"
    )
    distant = MultiCardRecognitionService._variant_marker_score(
        "0000000000000000", "ffffffffffffffff"
    )

    assert exact == 14.4
    assert exact > close > distant
    assert distant == 0.0


def test_treatment_response_detects_lighting_change_but_not_duplicate() -> None:
    base = np.full((700, 500, 3), 90, dtype=np.uint8)
    lit = base.copy()
    lit[300:620, 40:460] = 125
    original = MultiCardRecognitionService.treatment_response(base)
    duplicate = MultiCardRecognitionService.treatment_response(base.copy())
    changed = MultiCardRecognitionService.treatment_response(lit)

    assert MultiCardRecognitionService.treatment_response_distance(original, duplicate) == 0.0
    assert MultiCardRecognitionService.treatment_response_distance(original, changed) >= 1.25


def test_reference_features_are_cached_and_invalidated_by_mtime(tmp_path, monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    path = tmp_path / "reference.png"
    assert cv2.imwrite(str(path), np.full((700, 500, 3), 80, dtype=np.uint8))
    record = {"image_path": str(path)}
    original_imread = cv2.imread
    reads = []

    def tracked_imread(value):
        reads.append(value)
        return original_imread(value)

    monkeypatch.setattr(cv2, "imread", tracked_imread)
    first = service._reference_features(record)
    second = service._reference_features(record)
    assert first is second
    assert len(reads) == 1

    current = path.stat().st_mtime_ns
    import os
    os.utime(path, ns=(current + 1_000_000, current + 1_000_000))
    third = service._reference_features(record)
    assert third is not second
    assert len(reads) == 2


def test_track_region_follows_polygon_when_slot_order_changes(monkeypatch):
    frame = np.zeros((800, 1200, 3), dtype=np.uint8)
    target = [[0.10, 0.10], [0.30, 0.10], [0.30, 0.45], [0.10, 0.45]]
    moved = [[0.11, 0.11], [0.31, 0.11], [0.31, 0.46], [0.11, 0.46]]
    other = [[0.60, 0.10], [0.80, 0.10], [0.80, 0.45], [0.60, 0.45]]
    monkeypatch.setattr(SixCardGridDetector, "detect", lambda frame, max_cards=12: [
        {"slot": 1, "polygon": other, "crop": np.ones((10, 10, 3), dtype=np.uint8)},
        {"slot": 2, "polygon": moved, "crop": np.full((10, 10, 3), 2, dtype=np.uint8)},
    ])

    tracked = MultiCardRecognitionService.track_region(frame, target)

    assert tracked["slot"] == 2
    assert tracked["tracking_iou"] > 0.8


def test_track_region_refuses_replacement_card(monkeypatch):
    frame = np.zeros((800, 1200, 3), dtype=np.uint8)
    target = [[0.10, 0.10], [0.30, 0.10], [0.30, 0.45], [0.10, 0.45]]
    replacement = [[0.55, 0.10], [0.75, 0.10], [0.75, 0.45], [0.55, 0.45]]
    monkeypatch.setattr(SixCardGridDetector, "detect", lambda frame, max_cards=12: [
        {"slot": 1, "polygon": replacement, "crop": np.ones((10, 10, 3), dtype=np.uint8)},
    ])

    assert MultiCardRecognitionService.track_region(frame, target) is None


def test_dense_twelve_card_centers_are_not_deduplicated(monkeypatch):
    frame = np.zeros((1000, 1600, 3), dtype=np.uint8)
    candidates = []
    slot = 0
    for y in (0.22, 0.50, 0.78):
        for x in (0.32, 0.43, 0.54, 0.65):
            slot += 1
            polygon = [[x-.035, y-.10], [x+.035, y-.10], [x+.035, y+.10], [x-.035, y+.10]]
            candidates.append({
                "row": -1, "column": -1, "confidence": 0.95,
                "polygon": polygon, "centroid": [x, y],
                "crop": np.full((20, 12, 3), slot, dtype=np.uint8),
                "ocr_crop": np.full((20, 12, 3), slot, dtype=np.uint8),
            })
    monkeypatch.setattr(SixCardGridDetector, "_contour_candidates", lambda frame: candidates)
    monkeypatch.setattr(VisionService, "detect", lambda cell: type("Detection", (), {
        "crop": None, "polygon": None,
    })())

    detected = SixCardGridDetector.detect(frame, max_cards=12)

    assert len(detected) == 12


def test_tilted_rows_keep_left_to_right_slot_order(monkeypatch):
    frame = np.zeros((1000, 1600, 3), dtype=np.uint8)
    candidates = []
    for value, x, y in ((1, .30, .31), (2, .50, .27), (3, .70, .23),
                        (4, .30, .66), (5, .50, .62), (6, .70, .58)):
        candidates.append({
            "row": -1, "column": -1, "confidence": .95,
            "polygon": [[x-.05,y-.13],[x+.05,y-.13],[x+.05,y+.13],[x-.05,y+.13]],
            "centroid": [x, y],
            "crop": np.full((20, 12, 3), value, dtype=np.uint8),
            "ocr_crop": np.full((20, 12, 3), value, dtype=np.uint8),
        })
    monkeypatch.setattr(SixCardGridDetector, "_contour_candidates", lambda frame: candidates)
    monkeypatch.setattr(VisionService, "detect", lambda cell: type("Detection", (), {
        "crop": None, "polygon": None,
    })())

    detected = SixCardGridDetector.detect(frame, max_cards=6)

    assert [int(item["crop"][0, 0, 0]) for item in detected] == [1, 2, 3, 4, 5, 6]


def test_playmat_sized_outlier_is_removed_from_card_grid(monkeypatch):
    frame = np.zeros((1000, 1600, 3), dtype=np.uint8)
    candidates = []
    for index, x in enumerate((0.25, 0.40, 0.55, 0.70), start=1):
        candidates.append({
            "row": -1, "column": -1, "confidence": 0.9,
            "polygon": [[x-.04,.15],[x+.04,.15],[x+.04,.38],[x-.04,.38]],
            "centroid": [x,.265], "crop": np.ones((20,12,3),dtype=np.uint8),
            "ocr_crop": np.ones((20,12,3),dtype=np.uint8),
        })
    candidates.append({
        "row": -1, "column": -1, "confidence": 0.99,
        "polygon": [[.70,.20],[.95,.20],[.95,.65],[.70,.65]],
        "centroid": [.825,.425], "crop": np.ones((20,12,3),dtype=np.uint8),
        "ocr_crop": np.ones((20,12,3),dtype=np.uint8),
    })
    monkeypatch.setattr(SixCardGridDetector, "_contour_candidates", lambda frame: candidates)
    monkeypatch.setattr(VisionService, "detect", lambda cell: type("Detection", (), {"crop":None,"polygon":None})())

    detected = SixCardGridDetector.detect(frame, max_cards=12)

    assert len(detected) == 4
    assert all(np.mean(item["polygon"], axis=0)[0] < .8 for item in detected)


def test_unresolved_reference_does_not_override_conflicting_ocr_family(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "verified": False,
        "name_candidate": "æ¶è·é¸­",
        "card": {"canonical_name": "Quaxwell"},
    }]
    service._candidate_cache[1] = [
        {"canonical_name": "Quaxwell", "score": .70},
        {"canonical_name": "Crocalor", "score": .66},
    ]
    crocalor = {
        "canonical_name": "Crocalor",
        "printed_name": "çç«é³",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "161",
    }
    monkeypatch.setattr(service, "_best_named_reference", lambda name, slot: crocalor)
    monkeypatch.setattr(service, "_named_reference_matches", lambda name, slot: [(40.0, crocalor)])

    service._reconcile_unresolved_references()

    item = service._state["slots"][0]
    assert item["verified"] is False
    assert item["ocr_family_conflict"] is True
    assert item["card"]["canonical_name"] == "Quaxwell"


def test_shared_family_does_not_overwrite_repeated_visual_candidate_family(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    crocalor = {
        "canonical_name": "Crocalor",
        "printed_name": "çç«é³",
        "set_id": "GEM_PACK_VOL_5",
    }
    service._state["slots"] = [
        {"slot": slot, "card": dict(crocalor), "name_candidate": "çç«é³", "verified": True}
        for slot in range(1, 5)
    ] + [{
        "slot": 5,
        "card": {"canonical_name": "Other", "set_id": "GEM_PACK_VOL_5"},
        "name_candidate": "çç«é³",
        "verified": False,
    }]
    service._candidate_cache[5] = [
        {"canonical_name": "Quaxwell", "collector_number": "165", "score": .70},
        {"canonical_name": "Quaxwell", "collector_number": "168", "score": .68},
        {"canonical_name": "Crocalor", "collector_number": "161", "score": .65},
    ]

    service._reconcile_ocr_identity()

    item = service._state["slots"][4]
    assert item["card"]["canonical_name"] == "Quaxwell"
    assert item["verified"] is False
    assert item["shared_family_override_blocked"] is True


def test_exact_reference_consensus_requires_distinct_matching_capture(monkeypatch):
    service = MultiCardRecognitionService(_FakePrototype())
    first = np.zeros((700, 500, 3), dtype=np.uint8)
    second = first.copy()
    second[300:340, 210:250] = 255
    matches = [
        (36.0, {"set_id": "GEM_PACK_VOL_5", "canonical_name": "Crocalor", "collector_number": "157"}),
        (31.0, {"set_id": "GEM_PACK_VOL_5", "canonical_name": "Crocalor", "collector_number": "160"}),
    ]
    monkeypatch.setattr(service, "_named_reference_matches_crop", lambda name, crop: matches)
    fingerprints = iter(["0000000000000000", "0000000000000000", "0000000000000003"])
    monkeypatch.setattr(
        ArtworkIndexService,
        "variant_marker_fingerprint",
        lambda crop: next(fingerprints),
    )

    initial = service.resolve_exact_reference(first, "Crocalor")
    duplicate = service.resolve_exact_reference(first, "Crocalor")
    confirmed = service.resolve_exact_reference(second, "Crocalor")

    assert initial["card"] is None
    assert initial["diagnostics"]["confirmation_progress"] == 1
    assert duplicate["card"] is None
    assert duplicate["diagnostics"]["confirmation_progress"] == 1
    assert confirmed["card"]["collector_number"] == "157"
    assert confirmed["diagnostics"]["multi_frame_confirmation"] is True


def test_temporal_history_invalidates_when_card_moves(tmp_path):
    service = MultiCardRecognitionService(_FakePrototype(), history_path=tmp_path / "temporal.json")
    reference = next(
        item for item in service._reference_cards
        if item.get("set_id") == "GEM_PACK_VOL_5" and item.get("collector_number") == "040"
    )
    crop = cv2.imread(str(reference["reference_image"]))
    service._crop_cache[1] = crop
    service._state["slots"] = [{
        "slot": 1,
        "status": "review-needed",
        "verified": False,
        "polygon": [[.7, .7], [.8, .7], [.8, .9], [.7, .9]],
        "card": {"name": "Sunflora", "canonical_name": "Sunflora"},
    }]
    service._temporal_history[1] = {
        "card": dict(reference),
        "fingerprint": ArtworkIndexService.variant_marker_fingerprint(crop),
        "center": [.2, .2],
        "confirmations": 3,
        "updated_at": time.time(),
    }

    service._apply_temporal_confirmation()

    assert service.status()["slots"][0]["verified"] is False
    assert 1 not in service._temporal_history


def test_overlapping_capture_cannot_replace_active_job(tmp_path):
    service = MultiCardRecognitionService(
        _FakePrototype(), presentation_path=tmp_path / "presentation.json"
    )
    service._capture_lock.acquire()
    try:
        result = service.capture(np.zeros((600, 900, 3), dtype=np.uint8))
    finally:
        service._capture_lock.release()

    assert result["ok"] is False
    assert result["reason"] == "capture_in_progress"
    assert result["job_id"] == 0
