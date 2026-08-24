from __future__ import annotations

import numpy as np
import cv2

from rareiq.services.pipeline_state_service import (
    PipelineStateService,
)
from rareiq.services.trigger_manager_service import (
    TriggerManagerService,
)
from rareiq.services.vision_service import VisionService


POLYGON = np.array(
    [[0.2, 0.1], [0.8, 0.1], [0.8, 0.9], [0.2, 0.9]],
    dtype=np.float32,
)


def valid_crop():
    crop = np.full((1400, 1000, 3), 165, dtype=np.uint8)
    cv2.rectangle(crop, (20, 20), (980, 1380), (15, 15, 15), 18)
    cv2.rectangle(crop, (80, 150), (920, 760), (40, 130, 220), -1)
    cv2.putText(crop, "HORSEA", (120, 1120), cv2.FONT_HERSHEY_SIMPLEX,
                3.5, (20, 20, 20), 14, cv2.LINE_AA)
    return crop


def prepare_auto_capture(vision, frame_id):
    crop = valid_crop()
    sample = vision._acquisition.add(
        crop=crop,
        polygon=POLYGON,
        frame_id=frame_id,
        detection_confidence=.9,
        acquisition_epoch=vision._acquisition_epoch,
    )
    vision._best_lock_crop = crop.copy()
    vision._tracked_polygon = POLYGON.copy()
    return sample


def test_capture_event_carries_camera_provenance(tmp_path):
    events = []
    vision = VisionService(events.append, tmp_path)
    vision._stream_session_id = 6
    vision._device_sequence_id = 44
    vision._frame_id = 44
    vision._status["frame_id"] = 44
    vision._latest_provenance = {
        "stream_session_id": 6,
        "device_sequence_id": 44,
        "device_timestamp": 123.5,
        "application_frame_id": 44,
        "content_fingerprint": "1234567890abcdef",
        "source_camera_index": 1,
        "source_camera_backend": 700,
    }
    crop = valid_crop()
    sample = vision._acquisition.add(
        crop=crop, polygon=POLYGON, frame_id=44,
        detection_confidence=.9, acquisition_epoch=0,
        provenance=vision._latest_provenance,
    )
    vision._tracked_polygon = POLYGON.copy()
    assert vision.save_latest_crop(
        "auto", sample=sample, current_polygon=POLYGON
    )
    payload = events[-1]["payload"]
    assert payload["provenance"]["stream_session_id"] == 6
    assert payload["provenance"]["device_sequence_id"] == 44
    assert payload["provenance"]["content_fingerprint"] == (
        "1234567890abcdef"
    )


class FakeRecognition:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.payload = {
            "busy": False,
            "candidates": [],
            "candidate_count": 0,
            "verification_state": None,
        }

    def status(self):
        return dict(self.payload)

    def submit_frame(self, frame):
        self.frames.append(frame.copy())
        self.payload["busy"] = True


def test_saved_crop_triggers_submission_and_starts_ocr(
    tmp_path,
):
    events: list[dict] = []

    vision = VisionService(
        events.append,
        tmp_path,
    )

    sample = prepare_auto_capture(vision, 101)
    vision._best_lock_quality = 400.0

    with vision._lock:
        vision._status.update(
            {
                "frame_id": 101,
                "camera_name": "Synthetic Camera",
                "visible": True,
                "stable": True,
                "stable_frames": 8,
                "stable_target": 8,
            }
        )

    capture_path = vision.save_latest_crop(
        source="auto", sample=sample, current_polygon=POLYGON
    )

    assert capture_path is not None

    recognition = FakeRecognition()
    pipeline = PipelineStateService()

    trigger = TriggerManagerService(
        vision,
        recognition,
        pipeline,
    )

    submitted = trigger.tick()

    assert submitted is False
    assert len(recognition.frames) == 0

    trigger_status = trigger.status()

    assert trigger_status["submitted"] == 0
    assert trigger_status["state"] == "observed"
    assert (
        trigger_status["last_capture_path"]
        == capture_path
    )

    stages = {
        stage["key"]: stage
        for stage in pipeline.snapshot()["stages"]
    }

    assert stages["camera"]["state"] == "waiting"


def test_same_capture_is_not_submitted_twice(
    tmp_path,
):
    vision = VisionService(
        lambda event: None,
        tmp_path,
    )

    sample = prepare_auto_capture(vision, 102)

    with vision._lock:
        vision._status.update(
            {
                "frame_id": 102,
                "visible": True,
                "stable": True,
                "stable_frames": 8,
                "stable_target": 8,
            }
        )

    assert vision.save_latest_crop(
        "auto", sample=sample, current_polygon=POLYGON
    )

    recognition = FakeRecognition()
    pipeline = PipelineStateService()

    trigger = TriggerManagerService(
        vision,
        recognition,
        pipeline,
    )

    assert trigger.tick() is False

    recognition.payload["busy"] = False

    assert trigger.tick() is False
    assert len(recognition.frames) == 0


def test_invalid_auto_crop_retries_then_emits_only_valid_crop(tmp_path):
    events = []
    vision = VisionService(events.append, tmp_path)
    vision._auto_capture_armed = True
    invalid = np.full((1400, 1000, 3), 150, np.uint8)
    invalid_sample = vision._acquisition.add(
        crop=invalid, polygon=POLYGON, frame_id=10,
        detection_confidence=.9, acquisition_epoch=0,
    )
    vision._tracked_polygon = POLYGON.copy()
    vision._status["frame_id"] = 10

    assert vision.save_latest_crop(
        "auto", sample=invalid_sample, current_polygon=POLYGON
    ) is None
    assert vision._auto_capture_armed
    assert not events

    valid_sample = prepare_auto_capture(vision, 11)
    vision._status["frame_id"] = 11
    assert vision.save_latest_crop(
        "auto", sample=valid_sample, current_polygon=POLYGON
    )
    assert len(events) == 1
    assert events[0]["payload"]["validation"]["accepted"]
    assert np.array_equal(events[0]["payload"]["crop"], valid_sample.crop)
    assert not events[0]["payload"]["crop"].flags.writeable


def test_manual_capture_reports_quality_failure(tmp_path):
    vision = VisionService(lambda event: None, tmp_path)
    invalid = np.full((1400, 1000, 3), 150, np.uint8)
    vision._latest_frame = invalid.copy()
    vision.detect = lambda frame: type("Result", (), {
        "crop": invalid.copy(), "polygon": POLYGON.copy(), "confidence": .9
    })()
    vision._status["frame_id"] = 12

    result = vision.capture_fresh("manual")

    assert not result["ok"]
    assert "insufficient_sharpness" in result["reason"]
