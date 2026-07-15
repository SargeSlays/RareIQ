from __future__ import annotations

import numpy as np

from rareiq.services.pipeline_state_service import (
    PipelineStateService,
)
from rareiq.services.trigger_manager_service import (
    TriggerManagerService,
)
from rareiq.services.vision_service import VisionService


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

    crop = np.full(
        (700, 500, 3),
        160,
        dtype=np.uint8,
    )

    vision._best_lock_crop = crop.copy()
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
        source="auto"
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

    assert submitted is True
    assert len(recognition.frames) == 1
    assert np.array_equal(
        recognition.frames[0],
        crop,
    )

    trigger_status = trigger.status()

    assert trigger_status["submitted"] == 1
    assert (
        trigger_status["last_capture_path"]
        == capture_path
    )

    stages = {
        stage["key"]: stage
        for stage in pipeline.snapshot()["stages"]
    }

    assert stages["camera"]["state"] == "done"
    assert stages["detect"]["state"] == "done"
    assert stages["crop"]["state"] == "done"
    assert stages["ocr"]["state"] == "running"
    assert stages["artwork"]["state"] == "waiting"
    assert stages["verify"]["state"] == "waiting"


def test_same_capture_is_not_submitted_twice(
    tmp_path,
):
    vision = VisionService(
        lambda event: None,
        tmp_path,
    )

    crop = np.full(
        (700, 500, 3),
        160,
        dtype=np.uint8,
    )

    vision._best_lock_crop = crop.copy()

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

    assert vision.save_latest_crop("auto")

    recognition = FakeRecognition()
    pipeline = PipelineStateService()

    trigger = TriggerManagerService(
        vision,
        recognition,
        pipeline,
    )

    assert trigger.tick() is True

    recognition.payload["busy"] = False

    assert trigger.tick() is False
    assert len(recognition.frames) == 1
