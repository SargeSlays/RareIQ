from __future__ import annotations

import numpy as np

from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.services.pipeline_state_service import PipelineStateService


class FakeVision:
    def __init__(self, crop):
        self.crop = crop

    def latest_crop(self):
        return self.crop.copy()

    def status(self):
        return {"frame_id": 77}


class FakeRecognition:
    def __init__(self):
        self.submitted = []
        self.payload = {
            "enabled": True,
            "busy": False,
            "candidates": [],
            "candidate_count": 0,
        }

    def submit_frame(self, frame):
        self.submitted.append(frame.copy())

    def status(self):
        return dict(self.payload)


def make_orchestrator():
    obj = object.__new__(RareIQOrchestrator)
    obj.vision = FakeVision(np.zeros((120, 80, 3), dtype=np.uint8))
    obj.recognition = FakeRecognition()
    obj.pipeline_state = PipelineStateService()
    obj._last_submitted_crop_hash = None
    obj._last_recognition_submit_at = 0.0
    obj._recognition_submit_count = 0
    obj._recognition_duplicate_count = 0
    obj._last_trigger_result = "waiting"
    return obj


def test_card_capture_submits_corrected_crop_once():
    obj = make_orchestrator()
    obj._submit_captured_card({"source": "auto"})

    assert len(obj.recognition.submitted) == 1
    assert obj._recognition_submit_count == 1
    assert obj._last_trigger_result == "submitted"

    stages = {
        item["key"]: item
        for item in obj.pipeline_state.snapshot()["stages"]
    }
    assert stages["detect"]["state"] == "done"
    assert stages["crop"]["state"] == "done"
    assert stages["ocr"]["state"] == "running"


def test_duplicate_crop_is_suppressed():
    obj = make_orchestrator()
    obj._submit_captured_card({"source": "auto"})
    obj._submit_captured_card({"source": "auto"})

    assert len(obj.recognition.submitted) == 1
    assert obj._recognition_duplicate_count == 1
    assert obj._last_trigger_result == "duplicate_suppressed"


def test_recognition_update_advances_pipeline():
    obj = make_orchestrator()
    obj._current_recognition_card = lambda: {
        "card_name": "Suicune ex"
    }

    obj._apply_recognition_pipeline_update({
        "name_candidate": "Suicune ex",
        "collector_number": "142/204",
        "candidates": [{"id": "proof"}],
        "verification_state": "VERIFIED",
    })

    stages = {
        item["key"]: item
        for item in obj.pipeline_state.snapshot()["stages"]
    }
    assert stages["ocr"]["state"] == "done"
    assert stages["artwork"]["state"] == "done"
    assert stages["verify"]["state"] == "done"
    assert stages["current_card"]["state"] == "done"
