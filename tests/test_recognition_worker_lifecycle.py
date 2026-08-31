"""Worker ownership tests without camera, OCR models, catalog, or real threads."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from rareiq.services.recognition_service import RecognitionService
import rareiq.services.recognition_service as recognition


@pytest.fixture
def worker(monkeypatch):
    service = object.__new__(RecognitionService)
    service._lock = threading.Lock()
    service._status = {"enabled": True, "busy": False}
    service._busy = False
    service._active_job = None
    service._last_started_at = 0.0
    service._fast_interval = 0.0
    service._current_generation = 0
    service.emit = Mock()
    queued = []

    def thread(**kwargs):
        return SimpleNamespace(start=lambda: queued.append(kwargs))

    monkeypatch.setattr(recognition.threading, "Thread", thread)
    return SimpleNamespace(service=service, queued=queued, frame=np.zeros((14, 10, 3), dtype=np.uint8))


@pytest.mark.parametrize("failure", ["snapshot", "thread_start"])
def test_startup_exception_releases_busy_and_allows_retry(worker, monkeypatch, failure):
    service = worker.service
    with monkeypatch.context() as patch:
        if failure == "snapshot":
            patch.setattr(service, "_snapshot_frame_inputs", Mock(side_effect=RuntimeError("copy failed")))
        else:
            patch.setattr(recognition.threading, "Thread", lambda **kwargs: SimpleNamespace(
                start=Mock(side_effect=RuntimeError("thread startup failed"))))
        with pytest.raises(RuntimeError):
            service.submit_frame(worker.frame, generation=1, frame_id=2)
    assert service._busy is False
    assert service._status["busy"] is False
    assert service._status["recognition_locked"] is False
    assert service.submit_frame(worker.frame, generation=2, frame_id=3) == "accepted"


def test_unhandled_final_validation_error_releases_worker_and_publishes_failure(worker):
    service = worker.service
    service._recognize_worker = Mock(side_effect=RuntimeError("final validation failed"))
    assert service.submit_frame(worker.frame, generation=1, frame_id=2) == "accepted"
    job = worker.queued.pop()
    job["target"](*job["args"])
    assert service._busy is False
    payload = service.emit.call_args.args[0]["payload"]
    assert payload["recognition_path"] == "worker-error"
    assert payload["generation"] == 1 and payload["frame_id"] == 2
    assert payload["database_match"] is None and payload["recognition_locked"] is False
    assert service.submit_frame(worker.frame, generation=2, frame_id=3) == "accepted"


def test_stale_failure_releases_only_old_job_without_publishing_identity(worker):
    service = worker.service
    service._recognize_worker = Mock(side_effect=RuntimeError("late failure"))
    service.submit_frame(worker.frame, generation=1)
    service.invalidate_before(2)
    job = worker.queued.pop()
    job["target"](*job["args"])
    assert service._busy is False
    service.emit.assert_not_called()
    assert service.submit_frame(worker.frame, generation=2) == "accepted"


def test_failed_old_event_delivery_cannot_release_a_newer_worker(worker):
    service = worker.service

    def completed_then_callback_failed(*_args):
        # Normal completion releases the worker before notifying consumers.
        service._busy = False
        service.submit_frame(worker.frame, generation=2, frame_id=3)
        raise RuntimeError("old event delivery failed")

    service._recognize_worker = completed_then_callback_failed
    service.submit_frame(worker.frame, generation=1, frame_id=2)
    old_job = worker.queued.pop()
    old_job["target"](*old_job["args"])
    assert service._busy is True
    assert service._status["generation"] == 2
    service.emit.assert_not_called()
