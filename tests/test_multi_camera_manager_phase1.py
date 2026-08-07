from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from rareiq.services.camera_manager_service import CameraManagerService
from rareiq.services.camera_source_session import (
    CameraSourceSession,
    camera_source_id,
    camera_device_key,
    enrich_camera_source,
)


CAMERAS = [
    {"index": 0, "backend": 700, "name": "Physical A", "path": "device-a"},
    {"index": 1, "backend": 700, "name": "Physical B", "path": "device-b"},
    {"index": 2, "backend": 700, "name": "OBS Virtual Camera", "path": "virtual-c"},
]


class VisionDouble:
    def __init__(self) -> None:
        self.selected = dict(CAMERAS[0])
        self.running = True
        self.frame_id = 1
        self.start_calls: list[tuple[int, int]] = []
        self.stop_calls = 0

    def list_cameras(self):
        return [dict(item) for item in CAMERAS]

    def status(self):
        return {
            "running": self.running,
            "visible": False,
            "camera_index": self.selected["index"],
            "camera_backend": self.selected["backend"],
            "camera_name": self.selected["name"],
            "frame_id": self.frame_id,
            "frame_timestamp": float(self.frame_id),
            "error": None,
            "camera_provenance": {
                "stream_session_id": 1,
                "device_sequence_id": self.frame_id,
            },
        }

    def worker_alive(self):
        return self.running

    def start(self, index, backend):
        self.start_calls.append((index, backend))
        self.selected = next(item for item in CAMERAS if item["index"] == index)
        self.running = True
        self.frame_id += 1
        return self.status()

    def stop(self):
        self.stop_calls += 1
        self.running = False
        return self.status()

    def latest_jpeg(self):
        return f"active-{self.selected['index']}".encode()

    def latest_frame(self):
        return np.full((2, 2, 3), self.selected["index"], dtype=np.uint8)

    def latest_crop(self):
        return None


class SessionDouble:
    def __init__(self, source):
        self.source = source
        self.source_id = source["source_id"]
        self.starts = 0
        self.stops = 0
        self.reconnects = 0
        self.subscribers = 0

    def start(self):
        self.starts += 1
        return self.status()

    def stop(self):
        self.stops += 1
        return self.status()

    def reconnect(self):
        self.reconnects += 1
        return self.status()

    def latest_jpeg(self):
        return f"preview-{self.source['index']}".encode()

    def subscribe(self):
        self.subscribers += 1

    def unsubscribe(self):
        self.subscribers = max(0, self.subscribers - 1)

    def status(self):
        return {
            "source_id": self.source_id,
            "display_name": self.source["display_name"],
            "connected": True,
            "state": "connected",
            "last_frame_at": 1.0,
            "error": None,
            "subscribers": self.subscribers,
        }


def build_manager(tmp_path: Path):
    state = tmp_path / "camera.json"
    state.write_text(json.dumps({"selected_camera": CAMERAS[0]}), encoding="utf-8")
    vision = VisionDouble()
    sessions: dict[str, SessionDouble] = {}

    def factory(source):
        session = SessionDouble(source)
        sessions[source["source_id"]] = session
        return session

    manager = CameraManagerService(vision, state, session_factory=factory)
    manager._state = "running"
    devices = manager.discover(force=True)
    return manager, vision, sessions, devices


def test_discovery_exposes_stable_identity_and_classification(tmp_path):
    manager, _, _, devices = build_manager(tmp_path)
    assert devices[0]["source_id"] == camera_source_id(CAMERAS[0])
    assert enrich_camera_source(CAMERAS[0])["physical"] is True
    assert devices[2]["virtual"] is True
    assert devices[2]["classification"] == "virtual"
    assert manager.active_slot_id() == 1


def test_refresh_marks_missing_assigned_source_without_replacing_it(tmp_path):
    manager, vision, _, devices = build_manager(tmp_path)
    source_b = devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    vision.list_cameras = lambda: [dict(CAMERAS[0]), dict(CAMERAS[2])]
    refreshed = manager.discover(force=True)
    assert all(item["source_id"] != source_b for item in refreshed)
    slot = manager.camera_slots()[1]
    assert slot["source_id"] == source_b
    assert slot["source"]["available"] is False
    assert slot["source"]["availability"] == "missing"


def test_staging_assignment_does_not_switch_recognition(tmp_path):
    manager, vision, sessions, devices = build_manager(tmp_path)
    slot = manager.assign_slot(2, devices[1]["source_id"], "player-2")
    assert slot["role"] == "staging"
    assert slot["side"] == "player-2"
    assert manager.active_slot_id() == 1
    assert vision.start_calls == []
    assert sessions[devices[1]["source_id"]].starts == 1
    assert manager.slot_jpeg(2) == b"preview-1"


def test_unassign_preserves_side_metadata_and_stops_only_that_preview(tmp_path):
    manager, vision, sessions, devices = build_manager(tmp_path)
    source_b = devices[1]["source_id"]
    manager.assign_slot(2, source_b, "player-2")
    slot = manager.assign_slot(2, None)
    assert slot["source_id"] is None
    assert slot["side"] == "player-2"
    assert sessions[source_b].stops == 1
    assert vision.running is True


def test_duplicate_assignment_is_rejected(tmp_path):
    manager, _, _, devices = build_manager(tmp_path)
    manager.assign_slot(2, devices[1]["source_id"])
    try:
        manager.assign_slot(3, devices[1]["source_id"])
    except ValueError as exc:
        assert "already assigned" in str(exc)
    else:
        raise AssertionError("duplicate camera assignment was accepted")


def test_same_physical_device_through_another_backend_is_rejected(tmp_path):
    manager, _, _, devices = build_manager(tmp_path)
    alias = enrich_camera_source({
        "index": 9,
        "backend": 1400,
        "name": "Physical B (MSMF)",
        "path": "device-b",
    })
    assert alias["source_id"] != devices[1]["source_id"]
    assert camera_device_key(alias) == camera_device_key(devices[1])
    manager._sources[alias["source_id"]] = alias
    manager.assign_slot(2, devices[1]["source_id"])
    try:
        manager.assign_slot(3, alias["source_id"])
    except ValueError as exc:
        assert "device is already assigned" in str(exc)
    else:
        raise AssertionError("one physical camera was opened through two backends")


def test_explicit_promotion_is_atomic_and_clears_once(tmp_path):
    manager, vision, sessions, devices = build_manager(tmp_path)
    source_a, source_b = devices[0]["source_id"], devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    events = []
    manager.set_active_change_hook(events.append)
    result = manager.activate_slot(2)
    assert result["active_slot"] == 2
    assert manager.active_slot_id() == 2
    assert manager.camera_slots()[0]["role"] == "staging"
    assert vision.start_calls[-1] == (1, 700)
    assert sessions[source_b].stops == 1
    assert sessions[source_a].starts == 1
    assert events == [{"old_active_slot": 1, "active_slot": 2, "source_id": source_b}]
    assert manager.slot_jpeg(1) == b"preview-0"
    assert manager.slot_jpeg(2) == b"active-1"


def test_failed_promotion_restores_previous_active_role_and_camera(tmp_path):
    manager, vision, _, devices = build_manager(tmp_path)
    source_b = devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    original_start = vision.start

    def fail_new_camera(index, backend):
        if index == 1:
            vision.running = False
            return {**vision.status(), "error": "open failed"}
        return original_start(index, backend)

    vision.start = fail_new_camera
    try:
        manager.activate_slot(2)
    except RuntimeError as exc:
        assert "activation failed" in str(exc).lower()
    else:
        raise AssertionError("failed promotion was accepted")
    assert manager.active_slot_id() == 1
    assert vision.selected["index"] == 0
    assert vision.running is True


def test_reconnect_and_disconnect_are_isolated(tmp_path):
    manager, vision, sessions, devices = build_manager(tmp_path)
    source_b = devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    active_before = vision.start_calls[:]
    manager.reconnect_source(source_b)
    assert sessions[source_b].reconnects == 1
    assert vision.start_calls == active_before
    assert manager.active_slot_id() == 1


def test_active_reconnect_does_not_stop_staging_sessions(tmp_path):
    manager, _, sessions, devices = build_manager(tmp_path)
    source_a, source_b = devices[0]["source_id"], devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    manager.reconnect_source(source_a)
    assert sessions[source_b].stops == 0
    assert manager.camera_slots()[1]["source_id"] == source_b


def test_multiple_preview_consumers_reuse_one_session(tmp_path):
    manager, _, sessions, devices = build_manager(tmp_path)
    source_b = devices[1]["source_id"]
    manager.assign_slot(2, source_b)
    manager.subscribe_slot(2)
    manager.subscribe_slot(2)
    assert sessions[source_b].starts == 1
    assert sessions[source_b].subscribers == 2
    manager.unsubscribe_slot(2)
    assert sessions[source_b].subscribers == 1


def test_shutdown_stops_every_session_and_active_vision(tmp_path):
    manager, vision, sessions, devices = build_manager(tmp_path)
    manager.assign_slot(2, devices[1]["source_id"])
    manager.assign_slot(3, devices[2]["source_id"])
    manager.shutdown()
    assert vision.stop_calls == 1
    assert all(session.stops == 1 for session in sessions.values())
    assert manager.session_statuses() == {}


class CaptureDouble:
    def __init__(self):
        self.releases = 0
        self.reads = 0

    def isOpened(self):
        return True

    def set(self, *_args):
        return True

    def read(self):
        self.reads += 1
        time.sleep(0.002)
        return True, np.full((8, 8, 3), self.reads % 255, dtype=np.uint8)

    def release(self):
        self.releases += 1


def test_real_session_pump_is_bounded_and_releases_exactly_once():
    capture = CaptureDouble()
    source = enrich_camera_source(CAMERAS[1])
    session = CameraSourceSession(source, capture_factory=lambda *_: capture)
    session.start()
    deadline = time.time() + 1.0
    while session.latest_jpeg() is None and time.time() < deadline:
        time.sleep(0.005)
    first = session.latest_frame()
    assert first is not None
    session.stop()
    assert capture.releases == 1
    assert session.status()["worker_alive"] is False


def test_rapid_promotion_a_b_a_keeps_one_active_role(tmp_path):
    manager, _, _, devices = build_manager(tmp_path)
    manager.assign_slot(2, devices[1]["source_id"])
    manager.activate_slot(2)
    manager.activate_slot(1)
    roles = [slot["role"] for slot in manager.camera_slots()]
    assert roles.count("active") == 1
    assert manager.active_slot_id() == 1
