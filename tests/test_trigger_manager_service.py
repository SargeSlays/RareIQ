from __future__ import annotations

import numpy as np

from rareiq.services.pipeline_state_service import PipelineStateService
from rareiq.services.trigger_manager_service import TriggerManagerService


class FakeVision:
    def __init__(self):
        self.capture = None
        self.frame_id = 42
        self.crop = np.zeros((80, 60, 3), dtype=np.uint8)

    def status(self):
        return {
            "last_capture_path": self.capture,
            "frame_id": self.frame_id,
            "visible": True,
            "stable": True,
            "stable_frames": 8,
            "stable_target": 8,
        }

    def latest_crop(self):
        return self.crop.copy()


class FakeRecognition:
    def __init__(self):
        self.frames = []
        self.payload = {"busy": False, "candidates": []}

    def status(self):
        return dict(self.payload)

    def submit_frame(self, frame):
        self.frames.append(frame.copy())
        self.payload["busy"] = True


def test_new_capture_is_observed_without_submission():
    vision = FakeVision()
    recognition = FakeRecognition()
    pipeline = PipelineStateService()
    manager = TriggerManagerService(vision, recognition, pipeline)

    vision.capture = "capture-1.jpg"
    assert manager.tick() is False
    assert manager.tick() is False
    assert len(recognition.frames) == 0
    assert manager.status()["submitted"] == 0
    assert manager.status()["state"] == "watching"

    stages = {item["key"]: item for item in pipeline.snapshot()["stages"]}
    assert stages["detect"]["state"] == "waiting"


def test_second_capture_is_also_telemetry_only():
    vision = FakeVision()
    recognition = FakeRecognition()
    pipeline = PipelineStateService()
    manager = TriggerManagerService(vision, recognition, pipeline)

    vision.capture = "capture-1.jpg"
    assert manager.tick() is False
    recognition.payload["busy"] = False
    vision.capture = "capture-2.jpg"
    assert manager.tick() is False
    assert len(recognition.frames) == 0


def test_recognition_candidates_advance_pipeline():
    vision = FakeVision()
    recognition = FakeRecognition()
    pipeline = PipelineStateService()
    manager = TriggerManagerService(vision, recognition, pipeline)

    vision.capture = "capture-1.jpg"
    manager.tick()
    recognition.payload.update({
        "busy": False,
        "name_candidate": "Suicune ex",
        "collector_number": "239/204",
        "candidates": [{"id": "candidate"}],
        "verification_state": "VERIFIED",
    })
    manager.sync_recognition()

    stages = {item["key"]: item for item in pipeline.snapshot()["stages"]}
    assert stages["ocr"]["state"] == "done"
    assert stages["artwork"]["state"] == "done"
    assert stages["verify"]["state"] == "done"
