from __future__ import annotations

import time
import numpy as np

from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.services.pipeline_state_service import PipelineStateService
from rareiq.core.recognition_state import RecognitionStateStore


class FakeVision:
    def __init__(self, crop):
        self.crop = crop

    def latest_crop(self):
        return self.crop.copy()

    def status(self):
        return {"frame_id": 77}

    def capture_fresh(self, source="manual"):
        self.capture_source = source
        return {"ok": True, "frame_id": 78}


class FakeRecognition:
    def __init__(self):
        self.submitted = []
        self.payload = {
            "enabled": True,
            "busy": False,
            "candidates": [],
            "candidate_count": 0,
        }

    def submit_frame(self, frame, **metadata):
        self.submitted.append(frame.copy())
        return "accepted"

    def invalidate_before(self, generation):
        self.generation = generation

    def status(self):
        return dict(self.payload)


class FakeCatalog:
    def __init__(self):
        self.submitted = []

    def submit(self, payload):
        self.submitted.append(dict(payload))


def make_orchestrator():
    obj = object.__new__(RareIQOrchestrator)
    obj.vision = FakeVision(np.zeros((120, 80, 3), dtype=np.uint8))
    obj.recognition = FakeRecognition()
    obj.catalog = FakeCatalog()
    obj.pipeline_state = PipelineStateService()
    obj._last_submitted_crop_hash = None
    obj._last_recognition_submit_at = 0.0
    obj._recognition_submit_count = 0
    obj._recognition_duplicate_count = 0
    obj._last_trigger_result = "waiting"
    obj._continuous_state = "EMPTY"
    obj._recognition_generation = 0
    obj._active_job_generation = None
    obj._pending_recognition = None
    obj._current_acquisition_epoch = 0
    obj._minimum_capture_frame_id = 0
    obj._continuous_state_at = 0.0
    obj._shutting_down = False
    obj._collector_retry_attempted_epoch = None
    obj._active_capture_attribution = None
    obj._diagnostic_journal = []
    obj.recognition_state = RecognitionStateStore()
    return obj


def capture_event(obj, source="auto"):
    return {
        "source": source,
        "frame_id": 77,
        "acquisition_epoch": 0,
        "crop": obj.vision.crop.copy(),
        "validation": {"accepted": True},
    }


def test_card_capture_submits_corrected_crop_once():
    obj = make_orchestrator()
    obj._submit_captured_card(capture_event(obj))

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


def test_manual_capture_is_not_suppressed_as_duplicate():
    obj = make_orchestrator()
    obj._submit_captured_card(capture_event(obj, "manual"))
    obj._submit_captured_card(capture_event(obj, "manual"))

    assert len(obj.recognition.submitted) == 2
    assert obj._recognition_generation == 2


def test_recognition_update_advances_pipeline():
    obj = make_orchestrator()
    obj._current_recognition_card = lambda: {
        "card_name": "Suicune ex"
    }
    obj._recognition_generation = 1

    obj._apply_recognition_pipeline_update({
        "name_candidate": "Suicune ex",
        "collector_number": "142/204",
        "candidates": [{"id": "proof"}],
        "verification_state": "VERIFIED",
        "generation": 1,
    })

    stages = {
        item["key"]: item
        for item in obj.pipeline_state.snapshot()["stages"]
    }
    assert stages["ocr"]["state"] == "done"
    assert stages["artwork"]["state"] == "done"
    assert stages["verify"]["state"] == "done"
    assert stages["current_card"]["state"] == "done"


def test_collector_retry_uses_one_newer_frame_without_new_generation():
    obj = make_orchestrator()
    obj._continuous_state = "IDENTIFIED"
    obj._recognition_generation = 4
    obj._active_capture_attribution = {
        "provenance": {"content_fingerprint": "old"},
    }
    obj.vision.status = lambda: {
        "frame_id": 78,
        "camera_provenance": {"content_fingerprint": "new"},
    }

    assert obj._schedule_collector_ocr_retry({
        "collector_retry_recommended": True,
        "generation": 4,
        "frame_id": 77,
    }) is True
    deadline = time.monotonic() + 1.0
    while not hasattr(obj.vision, "capture_source") and time.monotonic() < deadline:
        time.sleep(0.01)

    assert obj.vision.capture_source == "collector-ocr-retry"
    assert obj._recognition_generation == 4
    assert obj._schedule_collector_ocr_retry({
        "collector_retry_recommended": True,
        "generation": 4,
        "frame_id": 78,
    }) is False


def test_collector_retry_does_not_reprocess_identical_camera_content():
    obj = make_orchestrator()
    obj._continuous_state = "IDENTIFIED"
    obj._recognition_generation = 5
    obj.COLLECTOR_OCR_RETRY_TIMEOUT_SECONDS = 0.15
    obj._active_capture_attribution = {
        "provenance": {"content_fingerprint": "same"},
    }
    obj.vision.status = lambda: {
        "frame_id": 999,
        "camera_provenance": {"content_fingerprint": "same"},
    }

    assert obj._schedule_collector_ocr_retry({
        "collector_retry_recommended": True,
        "generation": 5,
        "frame_id": 77,
    }) is True
    time.sleep(0.3)

    assert not hasattr(obj.vision, "capture_source")
    assert any(
        item.get("event") == "collector_ocr_retry_timeout"
        and item.get("reason") == "no_changed_content"
        for item in obj._diagnostic_journal
    )
