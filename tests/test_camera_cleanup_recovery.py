"""Real session lifecycle with synthetic captures; never opens camera hardware."""
import asyncio
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from rareiq.services.camera_source_session import CameraSourceSession
from rareiq.services.camera_manager_service import CameraManagerService
from rareiq.web import server


class Capture:
    def __init__(self, fail_release=False):
        self.reading = threading.Event()
        self.allow_read = threading.Event()
        self.owner = None
        self.release_owner = None
        self.releases = 0
        self.fail_release = fail_release

    def isOpened(self):
        return True

    def set(self, *_):
        pass

    def read(self):
        self.owner = threading.get_ident()
        self.reading.set()
        self.allow_read.wait(5)
        self.reading.clear()
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

    def release(self):
        assert not self.reading.is_set(), "release raced the driver's read"
        self.release_owner = threading.get_ident()
        self.releases += 1
        if self.fail_release:
            raise RuntimeError("driver cleanup failure")


def session(capture):
    return CameraSourceSession(
        {"index": 0, "backend": 700, "name": "Synthetic"},
        capture_factory=lambda *_: capture,
    )


def test_stop_waits_for_read_and_releases_on_the_capture_worker():
    capture = Capture()
    source = session(capture)
    source.start()
    assert capture.reading.wait(1)
    stopped = threading.Event()
    thread = threading.Thread(target=lambda: (source.stop(), stopped.set()))
    thread.start()
    try:
        assert source._stop_event.wait(1)
        assert capture.releases == 0
        capture.allow_read.set()
        assert stopped.wait(2)
        assert capture.releases == 1
        assert capture.release_owner == capture.owner
        assert source.latest_jpeg() is None
        assert not source.status()["worker_alive"]
    finally:
        capture.allow_read.set()
        thread.join(3)
        source.stop()


def test_slow_stop_retains_owner_and_blocks_reopen_until_cleanup_finishes():
    capture = Capture()
    source = session(capture)
    source.start()
    assert capture.reading.wait(1)
    try:
        status = source.stop()
        assert status["worker_alive"] and status["release_pending"]
        assert capture.releases == 0
        with pytest.raises(RuntimeError, match="still stopping"):
            source.start()
        assert source.status()["open_count"] == 1
    finally:
        capture.allow_read.set()
        source.stop()
    assert capture.releases == 1
    assert not source.status()["release_pending"]
    source.start()
    source.stop()
    assert source.status()["open_count"] == 2


def test_release_failure_keeps_ownership_and_reconnect_fails_truthfully():
    capture = Capture(fail_release=True)
    source = session(capture)
    source.start()
    assert capture.reading.wait(1)
    source._stop_event.set()
    capture.allow_read.set()
    source.stop()
    assert source.status()["release_pending"]
    assert not source.status()["worker_alive"]
    with pytest.raises(RuntimeError, match="cleanup failed"):
        source.reconnect()
    assert source.status()["open_count"] == 1


def test_manager_does_not_forget_a_capture_that_failed_to_stop():
    manager = CameraManagerService.__new__(CameraManagerService)
    pending = [True]
    source = SimpleNamespace(stop=lambda: None, status=lambda: {"worker_alive": pending[0]})
    manager._sessions = {"old": source}
    with pytest.raises(RuntimeError, match="cleanup"):
        manager._stop_preview_session("old")
    assert manager._sessions["old"] is source
    pending[0] = False
    manager._stop_preview_session("old")
    assert "old" not in manager._sessions


@pytest.mark.parametrize("operation", ["assign", "reconnect", "restart"])
def test_routes_report_cleanup_failure_without_unhandled_500(monkeypatch, operation):
    def fail(*_):
        raise RuntimeError("private driver diagnostics")
    manager = SimpleNamespace(assign_slot=fail, reconnect_source=fail, restart_source=fail)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(camera_manager=manager))
    if operation == "assign":
        response = asyncio.run(server.assign_camera_slot(2, server.CameraSlotSourceRequest(source_id="new")))
    elif operation == "reconnect":
        response = asyncio.run(server.reconnect_camera_source("old"))
    else:
        response = asyncio.run(server.restart_camera_source("old"))
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["ok"] is False
    assert body["error"] == "camera_cleanup_pending"
    assert "private" not in body["message"]
