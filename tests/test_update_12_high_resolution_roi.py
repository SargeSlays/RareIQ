from __future__ import annotations

import cv2
import numpy as np

from rareiq.services.vision_service import VisionService


def card_frame(
    *,
    width: int = 1920,
    height: int = 1080,
    left: int = 720,
    top: int = 160,
    card_width: int = 480,
    card_height: int = 760,
    details: bool = False,
) -> np.ndarray:
    frame = np.full((height, width, 3), 28, dtype=np.uint8)
    right = left + card_width
    bottom = top + card_height
    cv2.rectangle(frame, (left, top), (right, bottom), (232, 232, 232), -1)
    cv2.rectangle(frame, (left, top), (right, bottom), (8, 8, 8), 12)
    if details:
        cv2.circle(
            frame,
            (left + card_width // 2, top + card_height // 2),
            2,
            (0, 0, 255),
            -1,
        )
    return frame


def test_card_inside_scan_zone_is_detected() -> None:
    result = VisionService.detect(card_frame())

    assert result.polygon is not None
    assert result.crop is not None
    assert result.crop.shape == (1400, 1000, 3)


def test_contour_outside_scan_zone_is_ignored() -> None:
    frame = card_frame(
        left=5,
        top=170,
        card_width=150,
        card_height=740,
    )

    result = VisionService.detect(frame)

    assert result.polygon is None
    assert result.crop is None


def test_roi_coordinates_are_mapped_to_full_frame() -> None:
    result = VisionService.detect(card_frame())

    assert result.polygon is not None
    xs = result.polygon[:, 0]
    ys = result.polygon[:, 1]
    assert np.min(xs) == pytest_approx(720 / 1920, abs=0.025)
    assert np.max(xs) == pytest_approx(1200 / 1920, abs=0.025)
    assert np.min(ys) == pytest_approx(160 / 1080, abs=0.025)
    assert np.max(ys) == pytest_approx(920 / 1080, abs=0.025)


def test_crop_uses_original_full_resolution_frame() -> None:
    frame = card_frame(details=True)
    result = VisionService.detect(frame)

    assert result.crop is not None
    red_signal = (
        result.crop[:, :, 2].astype(np.int16)
        - result.crop[:, :, 1].astype(np.int16)
    )
    assert int(red_signal.max()) > 180


class FakeCapture:
    def __init__(self, frame: np.ndarray) -> None:
        self.frame = frame
        self.read_count = 0
        self.set_calls: list[tuple[int, float]] = []
        self.released = False

    def isOpened(self) -> bool:
        return True

    def set(self, property_id: int, value: float) -> bool:
        self.set_calls.append((property_id, value))
        return True

    def read(self):
        self.read_count += 1
        if self.read_count == 1:
            return True, self.frame.copy()
        return False, None

    def release(self) -> None:
        self.released = True


def run_one_camera_frame(monkeypatch, tmp_path, frame: np.ndarray):
    capture = FakeCapture(frame)
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_args: capture)
    service = VisionService(lambda _event: None, tmp_path)
    service._selected_camera = {
        "index": 0,
        "backend": cv2.CAP_DSHOW,
        "name": "Test Camera",
    }
    service._running = True
    service._worker()
    return service.status(), capture


def test_requested_resolution_success(monkeypatch, tmp_path) -> None:
    status, capture = run_one_camera_frame(
        monkeypatch,
        tmp_path,
        np.zeros((1080, 1920, 3), dtype=np.uint8),
    )

    assert (cv2.CAP_PROP_FRAME_WIDTH, 1920) in capture.set_calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 1080) in capture.set_calls
    assert status["requested_resolution"] == [1920, 1080]
    assert status["actual_resolution"] == [1920, 1080]
    assert status["resolution_fallback"] is False
    assert status["frame_shape"] == [1080, 1920, 3]


def test_resolution_fallback_and_scan_zone_telemetry(
    monkeypatch,
    tmp_path,
) -> None:
    status, _capture = run_one_camera_frame(
        monkeypatch,
        tmp_path,
        np.zeros((720, 1280, 3), dtype=np.uint8),
    )

    assert status["actual_resolution"] == [1280, 720]
    assert status["resolution_fallback"] is True
    assert status["scan_zone"] == {
        "left": 0.10,
        "top": 0.08,
        "right": 0.90,
        "bottom": 0.92,
    }
    assert status["scan_zone_pixels"] == {
        "left": 128,
        "top": 58,
        "right": 1152,
        "bottom": 662,
    }


def pytest_approx(value: float, *, abs: float):
    import pytest

    return pytest.approx(value, abs=abs)
