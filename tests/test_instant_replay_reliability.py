import json
import os
from pathlib import Path

import pytest

from rareiq.services import instant_replay_service as module
from rareiq.services.instant_replay_service import InstantReplayService


@pytest.fixture
def replay(tmp_path, monkeypatch):
    monkeypatch.setattr(module.time, "time", lambda: 1000.0)
    service = InstantReplayService(tmp_path / "replays", lambda _slot: b"jpeg", lambda: 1)
    service._frames.append((1000, 1, b"jpeg"))
    return service


@pytest.mark.parametrize("failure", ["frame", "short_frame", "index"])
def test_failed_highlight_save_preserves_prior_index_and_files(replay, monkeypatch, failure):
    assert replay.mark()["created"] is True
    before = replay.snapshot()["highlights"]
    disk = (replay.root / "highlights.json").read_bytes()
    files = sorted(replay.root.rglob("*"))
    original_write = Path.write_bytes
    def write(path, data):
        if path.suffix == ".jpg":
            if failure == "frame":
                raise OSError("disk disconnected")
            if failure == "short_frame":
                original_write(path, data[:1])
                return 1
        return original_write(path, data)
    def fail(*_args):
        raise OSError("index unavailable")
    if failure == "index":
        monkeypatch.setattr(os, "replace", fail)
    else:
        monkeypatch.setattr(Path, "write_bytes", write)
    result = replay.mark()
    assert result == {"created": False, "reason": "replay_storage_unavailable"}
    assert replay.snapshot()["highlights"] == before
    assert (replay.root / "highlights.json").read_bytes() == disk
    assert sorted(replay.root.rglob("*")) == files


def test_capture_error_clears_stale_buffer_and_recovers(replay):
    def failed(_slot):
        raise OSError("camera unavailable")
    replay.frame_provider = failed
    replay._capture_once()
    assert replay.snapshot()["buffered_frames"] == 0
    assert replay.snapshot()["last_error"]
    replay.frame_provider = lambda _slot: b"fresh jpeg"
    replay._capture_once()
    assert replay.snapshot()["buffered_frames"] == 1
    assert replay.snapshot()["last_error"] == ""


def test_buffer_status_does_not_advertise_expired_frames(replay, monkeypatch):
    monkeypatch.setattr(module.time, "time", lambda: 1100.0)
    assert replay.snapshot()["buffered_frames"] == 0
    assert replay.mark()["reason"] == "replay_buffer_empty"


def test_missing_frame_cannot_be_taken_on_air(replay):
    item = replay.mark()["highlight"]
    replay.frame(item["id"], 0).unlink()
    result = replay.take(item["id"])
    assert result["updated"] is False
    assert result["reason"] == "highlight_frames_unavailable"
    assert replay.snapshot()["playback"]["active"] is False


def test_playback_expires_and_does_not_restart_from_persisted_history(replay, monkeypatch):
    item = replay.mark()["highlight"]
    assert replay.take(item["id"])["playback"]["active"] is True
    monkeypatch.setattr(module.time, "time", lambda: 1001.0)
    assert replay.snapshot()["playback"]["active"] is False
    restored = InstantReplayService(replay.root, lambda _: None, lambda: 1)
    assert restored.snapshot()["playback"]["active"] is False
    assert len(restored.snapshot()["highlights"]) == 1


def test_retention_does_not_delete_an_active_highlight(replay):
    replay.MAX_HIGHLIGHTS = 2
    active = replay.mark(name="on air")["highlight"]
    replay.take(active["id"])
    retired = replay.mark(name="second")["highlight"]
    replay.mark(name="third")
    assert replay.frame(active["id"], 0).is_file()
    assert replay.frame(retired["id"], 0) is None
    assert len(replay.snapshot()["highlights"]) == 2


@pytest.mark.parametrize("speed", [float("nan"), float("inf"), "invalid"])
def test_invalid_speed_cannot_change_playback(replay, speed):
    item = replay.mark()["highlight"]
    result = replay.take(item["id"], speed)
    assert result["updated"] is False
    assert replay.snapshot()["playback"]["active"] is False


def test_frame_index_must_be_within_the_saved_clip(replay):
    item = replay.mark()["highlight"]
    assert replay.frame(item["id"], -1) is None
    assert replay.frame(item["id"], 1) is None


@pytest.mark.parametrize("bad", [{"frames": "oops"}, {"fps": 0}, {"frames": 999999}, {"fps": []}])
def test_malformed_saved_metadata_cannot_become_a_playable_highlight(replay, bad):
    replay.mark()
    index = replay.root / "highlights.json"
    items = json.loads(index.read_text())
    items[0].update(bad)
    index.write_text(json.dumps(items), encoding="utf-8")
    restored = InstantReplayService(replay.root, lambda _: None, lambda: 1)
    assert restored.snapshot()["highlights"] == []
