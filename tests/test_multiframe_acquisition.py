
from __future__ import annotations

import numpy as np

from rareiq.services.vision_service import (
    MultiFrameAcquisitionBuffer,
)


def make_card(
    value: int,
    *,
    glare: bool = False,
    blur: bool = False,
) -> np.ndarray:
    image = np.full(
        (700, 500, 3),
        value,
        dtype=np.uint8,
    )

    image[80:260, 50:450] = (
        min(255, value + 40),
        max(0, value - 20),
        min(255, value + 15),
    )

    image[300:600, 70:430] = (
        max(0, value - 35),
        min(255, value + 30),
        max(0, value - 5),
    )

    if glare:
        image[420:690, 300:495] = 255

    if blur:
        image = (
            image.astype(np.float32) * 0.85
            + np.roll(image, 8, axis=1).astype(np.float32) * 0.15
        ).astype(np.uint8)

    return image


def polygon() -> np.ndarray:
    return np.array(
        [
            [0.2, 0.1],
            [0.8, 0.1],
            [0.8, 0.9],
            [0.2, 0.9],
        ],
        dtype=np.float32,
    )


def test_buffer_keeps_only_capacity() -> None:
    buffer = MultiFrameAcquisitionBuffer(
        max_samples=5,
        consensus_count=3,
    )

    for frame_id in range(12):
        buffer.add(
            crop=make_card(90 + frame_id),
            polygon=polygon(),
            frame_id=frame_id,
            detection_confidence=0.88,
        )

    assert len(buffer.samples) == 5


def test_glare_heavy_frame_loses_to_clean_frame() -> None:
    buffer = MultiFrameAcquisitionBuffer()

    clean = buffer.add(
        crop=make_card(125),
        polygon=polygon(),
        frame_id=1,
        detection_confidence=0.85,
    )

    glare = buffer.add(
        crop=make_card(125, glare=True),
        polygon=polygon(),
        frame_id=2,
        detection_confidence=0.95,
    )

    assert clean is not None
    assert glare is not None
    assert clean.glare_score > glare.glare_score

    best = buffer.best_consensus()

    assert best is not None
    assert best.frame_id == 1


def test_consensus_prefers_repeated_card_view() -> None:
    buffer = MultiFrameAcquisitionBuffer(
        max_samples=12,
        consensus_count=3,
    )

    for frame_id, value in enumerate(
        [120, 121, 119, 40],
        start=1,
    ):
        buffer.add(
            crop=make_card(value),
            polygon=polygon(),
            frame_id=frame_id,
            detection_confidence=0.87,
        )

    best = buffer.best_consensus()

    assert best is not None
    assert best.frame_id in {1, 2, 3}


def test_same_card_does_not_rearm() -> None:
    buffer = MultiFrameAcquisitionBuffer()

    captured = buffer.add(
        crop=make_card(120),
        polygon=polygon(),
        frame_id=1,
        detection_confidence=0.90,
    )

    buffer.mark_captured(captured)

    for _ in range(6):
        current = buffer.add(
            crop=make_card(121),
            polygon=polygon(),
            frame_id=2,
            detection_confidence=0.90,
        )

        assert current is not None
        assert not buffer.observe_replacement(
            current.fingerprint
        )


def test_different_card_rearms_after_confirmation() -> None:
    buffer = MultiFrameAcquisitionBuffer()

    captured = buffer.add(
        crop=make_card(80),
        polygon=polygon(),
        frame_id=1,
        detection_confidence=0.90,
    )

    buffer.mark_captured(captured)

    replacement_image = make_card(210)

    # Simulate a genuinely different card layout.
    replacement_image[60:310, 35:245] = (15, 15, 15)
    replacement_image[340:675, 255:490] = (245, 245, 245)
    replacement_image[120:580, 225:275] = (40, 180, 90)

    replacement = buffer.add(
        crop=replacement_image,
        polygon=polygon(),
        frame_id=2,
        detection_confidence=0.90,
    )

    assert replacement is not None

    results = [
        buffer.observe_replacement(
            replacement.fingerprint
        )
        for _ in range(4)
    ]

    assert results == [
        False,
        False,
        False,
        True,
    ]


def test_reset_clears_samples_not_capture_identity() -> None:
    buffer = MultiFrameAcquisitionBuffer()

    captured = buffer.add(
        crop=make_card(110),
        polygon=polygon(),
        frame_id=1,
        detection_confidence=0.90,
    )

    buffer.mark_captured(captured)
    fingerprint = (
        buffer.last_captured_fingerprint.copy()
    )

    buffer.reset()

    assert buffer.samples == []
    assert np.array_equal(
        buffer.last_captured_fingerprint,
        fingerprint,
    )
