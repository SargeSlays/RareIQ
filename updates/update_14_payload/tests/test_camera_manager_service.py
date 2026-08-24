from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from rareiq.services.camera_manager_service import CameraManagerService


class VisionDouble:
    def __init__(self) -> None:
        self.frame_id = 10
        self.frame_timestamp = 100.0
        self.running = True
        self.alive = True
        self.error = None
        self.start_calls = 0
        self.stop_calls = 0
        self.latest_jpeg_calls = 0
        self.stream_session_id = 3
        self.device_sequence_id = 20
        self.content_fingerprint = "0123456789abcdef"

    def status(self):
        return {
            "running": self.running,
            "visible": False,
            "camera_index": 0,
            "camera_backend": 700,
            "camera_name": "Test Camera",
            "frame_id": self.frame_id,
            "frame_timestamp": self.frame_timestamp,
            "error": self.error,
            "camera_provenance": {
                "stream_session_id": self.stream_session_id,
                "device_sequence_id": self.device_sequence_id,
                "content_fingerprint": self.content_fingerprint,
                "repeated_content_count": 4,
                "last_genuinely_changed_frame_timestamp": 99.0,
                "last_duplicate_content_frame_id": 9,
            },
        }

    def worker_alive(self):
        return self.alive

    def latest_jpeg(self):
        self.latest_jpeg_calls += 1
        return b"cached-jpeg"

    def list_cameras(self):
        return [{"index": 0, "backend": 700, "name": "Test Camera"}]

    def start(self, camera_index, camera_backend):
        self.start_calls += 1
        self.running = True
        self.alive = True
        self.frame_id += 1
        self.frame_timestamp += 1.0
        return self.status()

    def stop(self):
        self.stop_calls += 1
        self.running = False
        self.alive = False
        return self.status()


def manager(tmp_path: Path) -> tuple[CameraManagerService, VisionDouble]:
    state = tmp_path / "camera.json"
    state.write_text(json.dumps({"selected_camera": {
        "index": 0, "backend": 700, "name": "Test Camera"
    }}), encoding="utf-8")
    vision = VisionDouble()
    service = CameraManagerService(vision, state)
    service._state = "running"
    service.status()
    return service, vision


def test_cached_jpeg_does_not_refresh_last_frame_at(tmp_path):
    service, vision = manager(tmp_path)
    first = service.status()["manager"]["last_frame_at"]
    time.sleep(0.01)
    second = service.status()["manager"]["last_frame_at"]
    assert first == second
    assert vision.latest_jpeg_calls == 0


def test_application_frame_id_without_device_progress_is_not_freshness(tmp_path):
    service, vision = manager(tmp_path)
    first = service.status()["manager"]["last_frame_at"]
    vision.frame_id += 1
    vision.frame_timestamp += 1.0
    time.sleep(0.01)
    status = service.status()["manager"]
    assert status["last_frame_at"] == first
    assert status["device_sequence_id"] == 20
    assert status["stream_session_id"] == 3
    assert status["content_fingerprint"] == "0123456789abcdef"


def test_new_device_sequence_is_authoritative_progress(tmp_path):
    service, vision = manager(tmp_path)
    first = service.status()["manager"]["last_frame_at"]
    time.sleep(0.01)
    vision.device_sequence_id += 1
    status = service.status()["manager"]
    assert status["last_frame_at"] > first


def test_frozen_frame_id_marks_stream_stalled(tmp_path):
    service, _ = manager(tmp_path)
    service.FRAME_STALL_TIMEOUT_SECONDS = 0.001
    time.sleep(0.005)
    status = service.status()
    assert status["manager"]["state"] == "stalled"
    assert status["manager"]["frame_fresh"] is False
    assert status["manager"]["health_reason"] == "frame_progress_stalled"


def test_dead_worker_is_unhealthy_even_with_cached_jpeg(tmp_path):
    service, vision = manager(tmp_path)
    vision.alive = False
    vision.running = False
    status = service.status()
    assert status["manager"]["state"] == "error"
    assert status["manager"]["health_reason"] == "dead_worker"
    assert service.health()["healthy"] is False


def test_same_healthy_camera_returns_already_running_without_reopen(tmp_path):
    service, vision = manager(tmp_path)
    result = service.start(0, 700)
    assert result["already_running"] is True
    assert result["manager"]["start_result"] == "already_running"
    assert vision.start_calls == 0
    assert vision.stop_calls == 0


def test_empty_scan_zone_does_not_reopen_healthy_camera(tmp_path):
    service, vision = manager(tmp_path)
    assert vision.status()["visible"] is False
    service.start(0, 700)
    assert vision.start_calls == vision.stop_calls == 0


def test_concurrent_starts_are_serialized_and_create_no_duplicate_worker(tmp_path):
    service, vision = manager(tmp_path)
    results = []
    threads = [threading.Thread(target=lambda: results.append(service.start(0, 700)))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 4
    assert all(result.get("already_running") for result in results)
    assert vision.start_calls == vision.stop_calls == 0
