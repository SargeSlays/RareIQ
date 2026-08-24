from __future__ import annotations

import cv2
import numpy as np
import time

from rareiq.services.vision_service import (
    ConfidenceLockTracker,
    MultiFrameAcquisitionBuffer,
    VisionService,
)


BASE_POLYGON = np.array(
    [
        [0.31, 0.12],
        [0.69, 0.12],
        [0.69, 0.88],
        [0.31, 0.88],
    ],
    dtype=np.float32,
)


def synthetic_card(
    *,
    angle: float = 0.0,
    noise: float = 0.0,
    broken_border: bool = False,
) -> np.ndarray:
    frame = np.full(
        (720, 1280, 3),
        38,
        dtype=np.uint8,
    )

    card = np.full(
        (500, 350, 3),
        225,
        dtype=np.uint8,
    )

    cv2.rectangle(
        card,
        (7, 7),
        (342, 492),
        (16, 16, 16),
        8,
    )

    cv2.rectangle(
        card,
        (35, 55),
        (315, 280),
        (80, 125, 210),
        -1,
    )

    cv2.putText(
        card,
        "RareIQ",
        (70, 410),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.4,
        (20, 20, 20),
        4,
        cv2.LINE_AA,
    )

    if broken_border:
        card[0:24, 115:235] = 225
        card[476:500, 60:165] = 225

    matrix = cv2.getRotationMatrix2D(
        (175, 250),
        angle,
        1.0,
    )

    rotated = cv2.warpAffine(
        card,
        matrix,
        (350, 500),
        borderValue=(38, 38, 38),
    )

    frame[110:610, 465:815] = rotated

    if noise:
        rng = np.random.default_rng(7)

        perturbation = rng.normal(
            0,
            noise,
            frame.shape,
        ).astype(np.int16)

        frame = np.clip(
            frame.astype(np.int16) + perturbation,
            0,
            255,
        ).astype(np.uint8)

    return frame


def replacement_card(value: int, *, variant: bool = False) -> np.ndarray:
    image = np.full((1400, 1000, 3), value, dtype=np.uint8)
    cv2.rectangle(image, (12, 12), (988, 1388), (20, 20, 20), 18)
    cv2.rectangle(image, (110, 180), (890, 760), (80, 145, 210), -1)
    for row in range(210, 750, 55):
        cv2.line(image, (130, row), (870, row + 25), (220, 235, 245), 5)
    cv2.putText(image, "CARD", (170, 1120), cv2.FONT_HERSHEY_SIMPLEX,
                4.0, (30, 30, 30), 14, cv2.LINE_AA)
    if variant:
        rng = np.random.default_rng(314)
        texture = rng.integers(
            0, 256, size=(590, 740, 3), dtype=np.uint8
        )
        for column in range(0, 740, 82):
            texture[:, column:column + 41] = 245
            texture[:, column + 41:column + 82] = 10
        image[150:740, 130:870] = texture
        cv2.circle(image, (500, 1050), 180, (230, 230, 230), -1)
        cv2.line(image, (100, 900), (900, 1250), (15, 15, 15), 30)
    return image


def acquisition_sample(buffer, image, frame_id, polygon=BASE_POLYGON):
    return buffer.add(
        crop=image,
        polygon=np.asarray(polygon, dtype=np.float32),
        frame_id=frame_id,
        detection_confidence=0.90,
    )


def capture_metrics(image, *, polygon=BASE_POLYGON, current_polygon=BASE_POLYGON,
                    frame_id=20, current_frame_id=20, epoch=2, current_epoch=2,
                    age=0.0):
    return VisionService._validate_capture_candidate(
        image,
        np.asarray(polygon, np.float32),
        np.asarray(current_polygon, np.float32),
        frame_id=frame_id,
        current_frame_id=current_frame_id,
        captured_at=time.time() - age,
        acquisition_epoch=epoch,
        current_epoch=current_epoch,
    )


def provenance(session, sequence, frame_id):
    return {
        "stream_session_id": session,
        "device_sequence_id": sequence,
        "device_timestamp": time.time(),
        "application_frame_id": frame_id,
        "content_fingerprint": f"{sequence:016x}",
        "source_camera_index": 1,
        "source_camera_backend": 700,
    }


def test_operator_next_clear_rearms_one_fresh_acquisition(tmp_path):
    service = VisionService(lambda event: None, tmp_path / "captures")
    service._auto_capture_armed = False
    service._acquisition_epoch = 4
    service._last_accepted_provenance = provenance(2, 3, 3)
    service._last_accepted_crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    service._last_accepted_full_hash = 1
    service._last_accepted_artwork_hash = 2
    status = service.prepare_next_card()
    assert service._acquisition_epoch == 5
    assert service._auto_capture_armed is True
    assert service._last_accepted_provenance is None
    assert service._last_accepted_crop is None
    assert service._empty_content_transition_seen is True
    assert status["auto_capture_armed"] is True


def test_new_card_epoch_bypasses_previous_card_capture_cooldown():
    service = object.__new__(VisionService)
    service._acquisition_epoch = 8
    service._last_auto_capture_epoch = 7
    service._last_auto_capture_at = 100.0

    assert service._auto_capture_cooldown_ready(100.05) is True


def test_same_card_epoch_keeps_duplicate_capture_cooldown():
    service = object.__new__(VisionService)
    service._acquisition_epoch = 8
    service._last_auto_capture_epoch = 8
    service._last_auto_capture_at = 100.0

    assert service._auto_capture_cooldown_ready(100.05) is False
    assert service._auto_capture_cooldown_ready(
        100.0 + service.CAPTURE_COOLDOWN_SECONDS
    ) is True


def test_pre_removal_duplicate_pixels_are_rejected_then_new_content_is_used(
    tmp_path,
):
    events = []
    service = VisionService(events.append, tmp_path)
    card_a = replacement_card(170)
    service._stream_session_id = 4
    service._device_sequence_id = 12
    service._frame_id = 12
    service._status["frame_id"] = 12
    service._tracked_polygon = BASE_POLYGON.copy()
    service._last_accepted_crop = card_a.copy()
    service._last_accepted_full_hash = service._acquisition._dhash(card_a)
    service._last_accepted_artwork_hash = service._acquisition._dhash(
        card_a, artwork=True
    )
    service._last_accepted_provenance = provenance(4, 5, 5)
    service._epoch_device_sequence_baseline = 5
    service._empty_content_transition_seen = False
    repeated = service._acquisition.add(
        crop=card_a,
        polygon=BASE_POLYGON,
        frame_id=11,
        detection_confidence=.9,
        acquisition_epoch=service._acquisition_epoch,
        provenance=provenance(4, 11, 11),
    )
    assert service.save_latest_crop(
        "auto", sample=repeated, current_polygon=BASE_POLYGON
    ) is None
    assert service._last_capture_validation["rejection_reason"] == (
        "duplicate_pre_removal_content"
    )
    changed = replacement_card(90, variant=True)
    newer = service._acquisition.add(
        crop=changed,
        polygon=BASE_POLYGON,
        frame_id=12,
        detection_confidence=.9,
        acquisition_epoch=service._acquisition_epoch,
        provenance=provenance(4, 12, 12),
    )
    assert service.save_latest_crop(
        "auto", sample=newer, current_polygon=BASE_POLYGON
    )
    assert events[-1]["payload"]["provenance"]["device_sequence_id"] == 12


def test_same_card_return_is_allowed_after_real_empty_scene(tmp_path):
    service = VisionService(lambda event: None, tmp_path)
    card = replacement_card(170)
    service._stream_session_id = 2
    service._frame_id = 9
    service._status["frame_id"] = 9
    service._tracked_polygon = BASE_POLYGON.copy()
    service._last_accepted_crop = card.copy()
    service._last_accepted_full_hash = service._acquisition._dhash(card)
    service._last_accepted_artwork_hash = service._acquisition._dhash(
        card, artwork=True
    )
    service._last_accepted_provenance = provenance(2, 3, 3)
    service._epoch_device_sequence_baseline = 7
    service._empty_content_transition_seen = True
    returned = service._acquisition.add(
        crop=card,
        polygon=BASE_POLYGON,
        frame_id=9,
        detection_confidence=.9,
        acquisition_epoch=service._acquisition_epoch,
        provenance=provenance(2, 9, 9),
    )
    assert service.save_latest_crop(
        "auto", sample=returned, current_polygon=BASE_POLYGON
    )


def test_wrong_stream_and_baseline_device_sequence_are_rejected(tmp_path):
    service = VisionService(lambda event: None, tmp_path)
    card = replacement_card(120, variant=True)
    service._stream_session_id = 8
    service._frame_id = 20
    service._status["frame_id"] = 20
    service._tracked_polygon = BASE_POLYGON.copy()
    service._epoch_device_sequence_baseline = 10
    wrong_stream = service._acquisition.add(
        crop=card, polygon=BASE_POLYGON, frame_id=19,
        detection_confidence=.9, acquisition_epoch=0,
        provenance=provenance(7, 19, 19),
    )
    assert service.save_latest_crop(
        "auto", sample=wrong_stream, current_polygon=BASE_POLYGON
    ) is None
    assert "wrong_stream_session" in service._last_capture_validation[
        "rejection_reason"
    ]
    stale_sequence = service._acquisition.add(
        crop=card, polygon=BASE_POLYGON, frame_id=20,
        detection_confidence=.9, acquisition_epoch=0,
        provenance=provenance(8, 10, 20),
    )
    assert service.save_latest_crop(
        "auto", sample=stale_sequence, current_polygon=BASE_POLYGON
    ) is None
    assert "stale_device_sequence" in service._last_capture_validation[
        "rejection_reason"
    ]


def test_background_only_capture_is_rejected_before_recognition():
    failed = np.full((1400, 1000, 3), (179, 159, 134), np.uint8)
    failed[:, 965:] = (245, 245, 245)
    failed = cv2.GaussianBlur(failed, (31, 31), 8.0)
    result = capture_metrics(failed)
    assert not result["accepted"]
    assert "insufficient_sharpness" in result["rejection_reason"]
    assert "smooth_background" in result["rejection_reason"]


def test_low_texture_capture_remains_rejected():
    failed = np.full((1400, 1000, 3), 150, np.uint8)
    result = capture_metrics(failed)
    assert not result["accepted"]
    assert result["sharpness"] < 1.0
    assert "insufficient_texture" in result["rejection_reason"]


def test_guarded_low_contrast_card_passes_only_with_strong_structure():
    assert VisionService._capture_texture_supported(
        pixel_stddev=26.3,
        sharpness=18.4,
        edge_density=0.027,
        supported_sides=4,
    ) is True
    assert VisionService._capture_texture_supported(
        pixel_stddev=26.3,
        sharpness=18.4,
        edge_density=0.027,
        supported_sides=2,
    ) is False
    assert VisionService._capture_texture_supported(
        pixel_stddev=26.3,
        sharpness=4.0,
        edge_density=0.027,
        supported_sides=4,
    ) is False


def test_valid_horsea_like_capture_passes_quality_gate():
    valid = replacement_card(150)
    valid = cv2.GaussianBlur(valid, (3, 3), 0.8)
    result = capture_metrics(valid)
    assert result["accepted"], result
    assert result["sharpness"] >= VisionService.CAPTURE_MIN_LAPLACIAN_SHARPNESS
    assert result["supported_sides"] >= 3


def test_capture_epoch_frame_age_and_polygon_are_enforced():
    valid = replacement_card(150)
    assert "wrong_acquisition_epoch" in capture_metrics(
        valid, epoch=1, current_epoch=2
    )["rejection_reason"]
    assert "stale_frame" in capture_metrics(valid, age=0.6)["rejection_reason"]
    shifted = BASE_POLYGON + np.array([0.25, 0.0], np.float32)
    assert "polygon_mismatch" in capture_metrics(
        valid, polygon=shifted
    )["rejection_reason"]


def test_same_card_exposure_autofocus_and_glare_retain_identity():
    buffer = MultiFrameAcquisitionBuffer()
    base = replacement_card(150)
    captured = acquisition_sample(buffer, base, 1)
    buffer.mark_captured(captured)
    frames = []
    for index in range(16):
        frame = cv2.convertScaleAbs(base, alpha=1.0 + ((index % 3) - 1) * .05,
                                    beta=((index % 5) - 2) * 4)
        if index % 4 == 0:
            frame = cv2.GaussianBlur(frame, (7, 7), 1.5)
        if index % 5 == 0:
            cv2.circle(frame, (720, 360), 45, (245, 245, 245), -1)
        frames.append(acquisition_sample(buffer, frame, index + 2))
    assert all(not buffer.observe_replacement(sample) for sample in frames)


def test_isolated_high_distance_frame_decays_without_replacement():
    buffer = MultiFrameAcquisitionBuffer()
    base = replacement_card(140)
    buffer.mark_captured(acquisition_sample(buffer, base, 1))
    different = acquisition_sample(buffer, replacement_card(30, variant=True), 2)
    assert not buffer.observe_replacement(different)
    for frame_id in range(3, 11):
        assert not buffer.observe_replacement(
            acquisition_sample(buffer, base, frame_id)
        )
    assert buffer.replacement_frames == 0


def test_direct_card_swap_confirms_within_rolling_window():
    buffer = MultiFrameAcquisitionBuffer()
    base = replacement_card(145)
    buffer.mark_captured(acquisition_sample(buffer, base, 1))
    changed = replacement_card(25, variant=True)
    results = []
    for frame_id in range(2, 10):
        sample = acquisition_sample(buffer, changed, frame_id)
        # The fixture represents a stable full-card A-to-B replacement.
        results.append(buffer.observe_replacement(sample))
    assert results[-1]
    assert sum(item["changed"] for item in buffer.replacement_window) >= 6
    assert buffer.last_replacement_evidence["decisive"]


def test_strong_artwork_branch_survives_two_near_identity_frames(monkeypatch):
    buffer = MultiFrameAcquisitionBuffer()
    reference = acquisition_sample(buffer, replacement_card(145), 1)
    buffer.mark_captured(reference)
    similarities = iter((0.50, 0.52, 0.95, 0.48, 0.51, 0.96, 0.49, 0.50))
    monkeypatch.setattr(
        MultiFrameAcquisitionBuffer,
        "_structural_similarity",
        staticmethod(lambda left, right: next(similarities)),
    )
    strong_positions = {0, 1, 3, 4, 6, 7}
    results = []
    for index in range(8):
        sample = acquisition_sample(
            buffer, replacement_card(80 + index), index + 2
        )
        if index in strong_positions:
            sample.full_card_hash = reference.full_card_hash ^ 0x7F
            sample.artwork_hash = reference.artwork_hash ^ 0xFFFF
        else:
            sample.full_card_hash = reference.full_card_hash ^ 0x03
            sample.artwork_hash = reference.artwork_hash ^ 0x07
        results.append(buffer.observe_replacement(sample))
    assert results[-1] is True
    assert len(buffer.replacement_window) == 8
    assert sum(item["changed"] for item in buffer.replacement_window) == 6
    assert sum(
        item["artwork_identity_changed"]
        and not item["primary_identity_changed"]
        for item in buffer.replacement_window
    ) == 6


def test_two_glare_spikes_do_not_confirm_artwork_branch(monkeypatch):
    buffer = MultiFrameAcquisitionBuffer()
    reference = acquisition_sample(buffer, replacement_card(145), 1)
    buffer.mark_captured(reference)
    similarities = iter((0.95, 0.50, 0.94, 0.96, 0.48, 0.95, 0.93, 0.97))
    monkeypatch.setattr(
        MultiFrameAcquisitionBuffer,
        "_structural_similarity",
        staticmethod(lambda left, right: next(similarities)),
    )
    results = []
    for index in range(8):
        sample = acquisition_sample(buffer, replacement_card(145), index + 2)
        if index in {1, 4}:
            sample.full_card_hash = reference.full_card_hash ^ 0xFFFF
            sample.artwork_hash = reference.artwork_hash ^ 0xFFFF
        results.append(buffer.observe_replacement(sample))
    assert not any(results)
    assert sum(item["changed"] for item in buffer.replacement_window) <= 2


def test_shifted_replacement_uses_proposed_b_geometry_not_card_a():
    buffer = MultiFrameAcquisitionBuffer()
    card_a = replacement_card(145)
    buffer.mark_captured(acquisition_sample(buffer, card_a, 1, BASE_POLYGON))
    card_b = replacement_card(25, variant=True)
    shifted_b = BASE_POLYGON + np.array([0.16, 0.045], np.float32)
    results = []
    for frame_id in range(2, 10):
        jitter = np.array([((frame_id % 2) - .5) * .002, 0], np.float32)
        sample = acquisition_sample(
            buffer, card_b, frame_id, shifted_b + jitter
        )
        results.append(buffer.observe_replacement(sample))
    assert results[-1] is True
    evidence = buffer.last_replacement_evidence
    assert evidence["polygon_iou"] >= buffer.POLYGON_IOU_MINIMUM
    assert evidence["corner_movement"] <= buffer.MAX_CORNER_MOVEMENT
    assert MultiFrameAcquisitionBuffer._polygon_iou(
        shifted_b, BASE_POLYGON
    ) < buffer.POLYGON_IOU_MINIMUM


def test_unstable_proposed_b_geometry_resets_confirmation():
    buffer = MultiFrameAcquisitionBuffer()
    buffer.mark_captured(acquisition_sample(
        buffer, replacement_card(145), 1, BASE_POLYGON
    ))
    card_b = replacement_card(25, variant=True)
    results = []
    for frame_id in range(2, 14):
        offset = np.array([0.12 if frame_id % 2 else -0.12, 0], np.float32)
        results.append(buffer.observe_replacement(acquisition_sample(
            buffer, card_b, frame_id, BASE_POLYGON + offset
        )))
    assert not any(results)
    assert len(buffer.replacement_window) < buffer.REPLACEMENT_WINDOW_SIZE


def test_replacement_journal_retains_decisive_frames():
    buffer = MultiFrameAcquisitionBuffer()
    buffer.mark_captured(acquisition_sample(
        buffer, replacement_card(145), 1
    ))
    for frame_id in range(2, 10):
        buffer.observe_replacement(acquisition_sample(
            buffer, replacement_card(25, variant=True), frame_id
        ))
    decisions = [item for item in buffer.replacement_journal
                 if item["event"] == "replacement_window_decision"]
    assert len(decisions) == 8
    assert decisions[-1]["reason"] == "replacement_confirmed"
    assert decisions[-1]["changed_frames"] >= 6


def test_capture_rebases_acquisition_and_reference_history():
    buffer = MultiFrameAcquisitionBuffer()
    old = acquisition_sample(buffer, replacement_card(80), 1)
    for frame_id in range(2, 8):
        acquisition_sample(buffer, replacement_card(90 + frame_id), frame_id)
    chosen = acquisition_sample(buffer, replacement_card(160), 8)
    buffer.replacement_window.append({"changed": True})

    buffer.mark_captured(chosen)

    assert buffer.samples == [chosen]
    assert buffer.reference_samples
    assert len(buffer.reference_samples) <= buffer.REFERENCE_SAMPLE_COUNT
    assert not buffer.replacement_window
    assert buffer.replacement_frames == 0


def test_imperfect_card_border_is_detected():
    frame = synthetic_card(
        angle=4.0,
        noise=2.0,
        broken_border=True,
    )

    result = VisionService.detect(frame)

    assert result.polygon is not None
    assert result.crop is not None
    assert result.crop.shape == (1400, 1000, 3)
    assert result.confidence >= VisionService.DETECT_THRESHOLD


def test_wide_non_card_rectangle_is_rejected():
    frame = np.full(
        (720, 1280, 3),
        40,
        dtype=np.uint8,
    )

    cv2.rectangle(
        frame,
        (150, 260),
        (1130, 460),
        (230, 230, 230),
        -1,
    )

    cv2.rectangle(
        frame,
        (150, 260),
        (1130, 460),
        (12, 12, 12),
        8,
    )

    result = VisionService.detect(frame)

    assert (
        result.polygon is None
        or result.confidence < VisionService.DETECT_THRESHOLD
    )


def test_contour_below_twelve_tenths_percent_is_rejected():
    frame = np.full((1080, 1920, 3), 32, dtype=np.uint8)
    cv2.rectangle(frame, (880, 450), (989, 604), (232, 232, 232), -1)
    cv2.rectangle(frame, (880, 450), (989, 604), (8, 8, 8), 4)

    result = VisionService.detect(frame)

    assert result.polygon is None
    assert result.crop is None


def test_small_non_card_aspect_rectangle_is_rejected():
    frame = np.full((1080, 1920, 3), 32, dtype=np.uint8)
    cv2.rectangle(frame, (790, 500), (1050, 602), (232, 232, 232), -1)
    cv2.rectangle(frame, (790, 500), (1050, 602), (8, 8, 8), 4)

    result = VisionService.detect(frame)

    assert result.polygon is None
    assert result.crop is None


def test_small_irregular_blob_is_rejected():
    frame = np.full((1080, 1920, 3), 32, dtype=np.uint8)
    points = np.array(
        [[820, 430], [985, 430], [985, 485], [900, 485],
         [900, 625], [820, 625]],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [points], (232, 232, 232))
    cv2.polylines(frame, [points], True, (8, 8, 8), 4)

    result = VisionService.detect(frame)

    assert result.polygon is None
    assert result.crop is None


def envelope_fixture():
    edges = np.zeros((568, 960), dtype=np.uint8)
    outer = np.array(
        [[[220, 60]], [[700, 60]], [[700, 520]], [[220, 520]],
         [[220, 350]], [[310, 290]], [[220, 230]]],
        dtype=np.int32,
    )
    inner = np.array(
        [[360, 270], [490, 270], [490, 355], [360, 355]],
        dtype=np.float32,
    )
    box = VisionService._order(cv2.boxPoints(cv2.minAreaRect(cv2.convexHull(outer))))
    return edges, outer, inner, box


def test_fragmented_envelope_without_side_edges_is_rejected():
    edges, outer, inner, _ = envelope_fixture()
    assert VisionService._fragmented_outer_envelope(
        outer, edges, float(edges.size), inner
    ) is None


def test_aggregate_edge_support_cannot_replace_three_supported_sides():
    edges, outer, inner, box = envelope_fixture()
    for index in (0, 1):
        cv2.line(
            edges,
            tuple(box[index].astype(int)),
            tuple(box[(index + 1) % 4].astype(int)),
            255,
            7,
        )
    assert VisionService._edge_support(edges, box) > 0.80
    assert VisionService._fragmented_outer_envelope(
        outer, edges, float(edges.size), inner
    ) is None


def test_envelope_not_containing_inner_candidate_is_rejected():
    edges, outer, _, box = envelope_fixture()
    cv2.polylines(edges, [box.astype(np.int32)], True, 255, 7)
    outside_inner = np.array(
        [[730, 270], [850, 270], [850, 350], [730, 350]],
        dtype=np.float32,
    )
    assert VisionService._fragmented_outer_envelope(
        outer, edges, float(edges.size), outside_inner
    ) is None


def test_envelope_outside_roi_tolerance_is_rejected():
    edges = np.zeros((568, 960), dtype=np.uint8)
    outer = np.array(
        [[[-12, 60]], [[480, 60]], [[480, 520]], [[-12, 520]],
         [[80, 300]]],
        dtype=np.int32,
    )
    inner = np.array(
        [[120, 250], [250, 250], [250, 340], [120, 340]],
        dtype=np.float32,
    )
    box = VisionService._order(cv2.boxPoints(cv2.minAreaRect(cv2.convexHull(outer))))
    cv2.polylines(edges, [np.clip(box, 0, [959, 567]).astype(np.int32)], True, 255, 7)
    assert VisionService._fragmented_outer_envelope(
        outer, edges, float(edges.size), inner
    ) is None


def test_stationary_card_reaches_lock():
    tracker = ConfidenceLockTracker(
        stable_target=8,
    )

    rng = np.random.default_rng(42)
    locked = False

    for _ in range(24):
        polygon = (
            BASE_POLYGON
            + rng.normal(
                0.0,
                0.0012,
                BASE_POLYGON.shape,
            )
        )

        _, locked, _ = tracker.update(
            polygon,
            0.88,
        )

    assert locked is True
    assert tracker.stable_frames == 8
    assert tracker.lock_confidence >= tracker.lock_threshold


def test_real_motion_does_not_lock():
    tracker = ConfidenceLockTracker(
        stable_target=8,
    )

    locked = False

    for step in range(24):
        polygon = (
            BASE_POLYGON
            + np.array(
                [step * 0.021, 0.0],
                dtype=np.float32,
            )
        )

        _, locked, _ = tracker.update(
            polygon,
            0.90,
        )

    assert locked is False


def test_brief_detection_loss_preserves_progress():
    tracker = ConfidenceLockTracker(
        stable_target=8,
        missing_tolerance=3,
    )

    for _ in range(12):
        tracker.update(
            BASE_POLYGON,
            0.88,
        )

    before = tracker.lock_confidence

    tracker.miss()
    tracker.miss()

    assert tracker.reference is not None
    assert tracker.lock_confidence > 0.0
    assert tracker.lock_confidence < before

    for _ in range(8):
        _, locked, _ = tracker.update(
            BASE_POLYGON,
            0.88,
        )

    assert locked is True


def test_long_detection_loss_resets_geometry():
    tracker = ConfidenceLockTracker(
        stable_target=8,
        missing_tolerance=2,
    )

    for _ in range(12):
        tracker.update(
            BASE_POLYGON,
            0.88,
        )

    tracker.miss()
    tracker.miss()
    tracker.miss()

    assert tracker.reference is None
    assert tracker.stable_frames == 0


def test_saved_auto_crop_becomes_latest_crop(tmp_path):
    events: list[dict] = []

    service = VisionService(
        events.append,
        tmp_path,
    )

    best = replacement_card(180)

    service._best_lock_crop = best.copy()
    service._best_lock_quality = 500.0
    sample = service._acquisition.add(
        crop=best,
        polygon=BASE_POLYGON,
        frame_id=77,
        detection_confidence=.9,
        acquisition_epoch=service._acquisition_epoch,
    )
    service._frame_id = 1
    service._tracked_polygon = BASE_POLYGON.copy()

    with service._lock:
        service._status["frame_id"] = 77
        service._status["camera_name"] = "Test Camera"

    saved_path = service.save_latest_crop(
        source="auto", sample=sample, current_polygon=BASE_POLYGON
    )

    assert saved_path is not None
    assert service.latest_crop() is not None
    assert np.array_equal(
        service.latest_crop(),
        best,
    )
    assert service.status()["last_capture_path"] == saved_path
    assert events[-1]["type"] == "card_captured"


def test_auto_capture_selects_consensus_before_save(tmp_path, monkeypatch):
    service = VisionService(lambda event: None, tmp_path)
    crop = replacement_card(170)
    sample = service._acquisition.add(
        crop=crop, polygon=BASE_POLYGON, frame_id=1,
        detection_confidence=.9, acquisition_epoch=service._acquisition_epoch,
    )
    service._frame_id = 1
    seen = []
    monkeypatch.setattr(service, "save_latest_crop", lambda **kwargs: seen.append(kwargs) or "ok.jpg")
    assert service._attempt_auto_capture(BASE_POLYGON) is True
    assert seen[0]["sample"] is sample
    assert service._auto_capture_armed is False


def test_auto_capture_without_consensus_retries_without_disarming(tmp_path, monkeypatch):
    service = VisionService(lambda event: None, tmp_path)
    monkeypatch.setattr(service, "save_latest_crop", lambda **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert service._attempt_auto_capture(BASE_POLYGON) is False
    assert service._auto_capture_armed is True
    assert service.status()["capture_validation"]["rejection_reason"] == "no_eligible_consensus_sample"


def test_recoverable_auto_capture_exception_keeps_worker_state(tmp_path, monkeypatch):
    service = VisionService(lambda event: None, tmp_path)
    crop = replacement_card(170)
    service._acquisition.add(
        crop=crop, polygon=BASE_POLYGON, frame_id=1,
        detection_confidence=.9, acquisition_epoch=service._acquisition_epoch,
    )
    service._running = True
    service._frame_id = 1
    monkeypatch.setattr(service, "save_latest_crop", lambda **kwargs: (_ for _ in ()).throw(OSError("disk busy")))
    assert service._attempt_auto_capture(BASE_POLYGON) is False
    assert service._running is True
    assert service._auto_capture_armed is True
    assert "OSError: disk busy" in service.status()["capture_error"]


def test_stale_high_quality_sample_is_skipped_for_recent_consensus():
    buffer = MultiFrameAcquisitionBuffer()
    now = time.time()
    stale = buffer.add(
        crop=replacement_card(170), polygon=BASE_POLYGON, frame_id=10,
        detection_confidence=.95, acquisition_epoch=4, captured_at=now - 1.0,
    )
    fresh = buffer.add(
        crop=cv2.GaussianBlur(replacement_card(150), (5, 5), 1.0),
        polygon=BASE_POLYGON, frame_id=11, detection_confidence=.85,
        acquisition_epoch=4, captured_at=now,
    )
    stale.quality_score = .99
    fresh.quality_score = .20
    chosen = buffer.best_recent_consensus(
        current_epoch=4, current_frame_id=11,
        current_polygon=BASE_POLYGON, now=now,
    )
    assert chosen is fresh


def test_polygon_mismatched_high_quality_sample_is_skipped():
    buffer = MultiFrameAcquisitionBuffer()
    now = time.time()
    mismatched = buffer.add(
        crop=replacement_card(170),
        polygon=BASE_POLYGON + np.array([.25, 0], np.float32),
        frame_id=20, detection_confidence=.95,
        acquisition_epoch=2, captured_at=now,
    )
    valid = buffer.add(
        crop=replacement_card(150), polygon=BASE_POLYGON, frame_id=21,
        detection_confidence=.85, acquisition_epoch=2, captured_at=now,
    )
    mismatched.quality_score = .99
    chosen = buffer.best_recent_consensus(
        current_epoch=2, current_frame_id=21,
        current_polygon=BASE_POLYGON, now=now,
    )
    assert chosen is valid


def test_rejected_fresh_sample_falls_back_to_older_sample_same_cycle(
    tmp_path, monkeypatch
):
    service = VisionService(lambda event: None, tmp_path)
    now = time.time()
    older = service._acquisition.add(
        crop=replacement_card(175), polygon=BASE_POLYGON, frame_id=30,
        detection_confidence=.95, acquisition_epoch=0, captured_at=now,
    )
    newer = service._acquisition.add(
        crop=replacement_card(145), polygon=BASE_POLYGON, frame_id=31,
        detection_confidence=.85, acquisition_epoch=0, captured_at=now,
    )
    older.quality_score = .99
    newer.quality_score = .10
    service._frame_id = 31
    calls = []

    def save(**kwargs):
        sample = kwargs["sample"]
        calls.append(sample.frame_id)
        if sample.frame_id == 31:
            service._last_capture_validation = {
                "accepted": False, "rejection_reason": "polygon_mismatch"
            }
            return None
        return "fresh.jpg"

    monkeypatch.setattr(service, "save_latest_crop", save)
    assert service._attempt_auto_capture(BASE_POLYGON, now=now) is True
    assert calls == [31, 30]
    assert service._capture_telemetry["last_accepted_frame_id"] == 30
    assert service._capture_telemetry["total_capture_rejections"] == 1
    assert not service._capture_quarantined_frame_ids


def test_quarantined_frame_is_not_retried_and_capture_stays_armed(
    tmp_path, monkeypatch
):
    service = VisionService(lambda event: None, tmp_path)
    now = time.time()
    service._acquisition.add(
        crop=replacement_card(170), polygon=BASE_POLYGON, frame_id=40,
        detection_confidence=.9, acquisition_epoch=0, captured_at=now,
    )
    service._frame_id = 40
    calls = []

    def reject(**kwargs):
        calls.append(kwargs["sample"].frame_id)
        service._last_capture_validation = {
            "accepted": False, "rejection_reason": "stale_frame"
        }
        return None

    monkeypatch.setattr(service, "save_latest_crop", reject)
    assert service._attempt_auto_capture(BASE_POLYGON, now=now) is False
    assert service._attempt_auto_capture(BASE_POLYGON, now=now) is False
    assert calls == [40]
    assert service._auto_capture_armed is True
    assert service._capture_telemetry["quarantined_sample_count"] == 1


def test_capture_counters_outlive_bounded_journal(tmp_path):
    service = VisionService(lambda event: None, tmp_path)
    for frame_id in range(100):
        service._record_capture_rejection(frame_id, "stale_frame")
        service._acquisition._record_replacement_decision({
            "event": "capture_rejected", "reason": "stale_frame",
            "frame_id": frame_id,
        })
    telemetry = service._capture_telemetry
    assert telemetry["total_capture_rejections"] == 100
    assert telemetry["rejections_by_reason"]["stale_frame"] == 100
    assert telemetry["last_rejected_frame_id"] == 99
    assert len(service._acquisition.replacement_journal) == 64


def test_capture_quality_thresholds_remain_unchanged():
    assert VisionService.CAPTURE_MIN_LAPLACIAN_SHARPNESS == 5.0
    assert VisionService.CAPTURE_MIN_PIXEL_STDDEV == 28.0
    assert VisionService.CAPTURE_MIN_EDGE_DENSITY == 0.008
    assert VisionService.CAPTURE_MIN_SIDE_EDGE_SUPPORT == 0.012
    assert VisionService.CAPTURE_MIN_SUPPORTED_SIDES == 3
    assert VisionService.CAPTURE_MIN_POLYGON_IOU == 0.80
    assert VisionService.CAPTURE_MAX_FRAME_AGE_SECONDS == 0.40
