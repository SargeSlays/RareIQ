from __future__ import annotations

import cv2
import numpy as np

from rareiq.services.vision_service import (
    ConfidenceLockTracker,
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


def test_imperfect_card_border_is_detected():
    frame = synthetic_card(
        angle=4.0,
        noise=2.0,
        broken_border=True,
    )

    result = VisionService.detect(frame)

    assert result.polygon is not None
    assert result.crop is not None
    assert result.crop.shape == (700, 500, 3)
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

    best = np.full(
        (700, 500, 3),
        180,
        dtype=np.uint8,
    )

    service._best_lock_crop = best.copy()
    service._best_lock_quality = 500.0

    with service._lock:
        service._status["frame_id"] = 77
        service._status["camera_name"] = "Test Camera"

    saved_path = service.save_latest_crop(
        source="auto"
    )

    assert saved_path is not None
    assert service.latest_crop() is not None
    assert np.array_equal(
        service.latest_crop(),
        best,
    )
    assert service.status()["last_capture_path"] == saved_path
    assert events[-1]["type"] == "card_captured"
