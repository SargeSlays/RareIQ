import asyncio
import json
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rareiq.services import auto_clip_service as module
from rareiq.services.auto_clip_service import AutoClipService
from rareiq.services.instant_replay_service import InstantReplayService


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(module.time, "time", lambda: clock[0])
    jpeg = cv2.imencode(".jpg", np.full((64, 96, 3), (60, 150, 220), dtype=np.uint8))[1].tobytes()
    replay = InstantReplayService(tmp_path / "replays", lambda _slot: jpeg, lambda: 1)
    replay._frames.extend((1000 - index / 5, 1, jpeg) for index in reversed(range(51)))
    clip = AutoClipService(replay, tmp_path / "config.json")
    snapshot = {"generation": 1, "updated_at": 1000, "verification_state": "VERIFIED", "has_reference_evidence": True, "identity_consistent": True, "recognition_locked": True, "result_current": True, "card_present": True, "primary_candidate": {"id": "test-1", "english_name": "Test pull", "rarity": "Illustration Rare"}}
    def advance(seconds=3):
        for _ in range(round(seconds * 5)):
            clock[0] = round(clock[0] + .2, 1)
            replay._capture_once()
            clip.process_pending()
    return SimpleNamespace(clip=clip, replay=replay, clock=clock, snapshot=snapshot, advance=advance)


def test_disarmed_by_default_and_restart_never_restores_armed_state(rig):
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == 0
    assert rig.clip.configure({"minimum_tier": "low", "pre_seconds": 4, "post_seconds": 2})["updated"]
    rig.clip.arm(True)
    restored = AutoClipService(rig.replay, rig.clip.config_path)
    assert restored.snapshot()["enabled"] is False
    assert restored.snapshot()["config"]["pre_seconds"] == 4
    assert "enabled" not in json.loads(rig.clip.config_path.read_text())


def test_complete_clip_is_decodable_downloadable_retained_and_not_taken_on_air(rig):
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == 1
    assert not rig.replay.snapshot()["highlights"]
    rig.advance()
    state = rig.clip.snapshot()
    assert state["last_result"]["created"] is True
    assert state["saved_count"] == 1
    item = rig.replay.snapshot()["highlights"][0]
    assert item["frames"] == 41  # 5s before + 3s after, including the trigger frame.
    assert item["auto_clip"]["tier"] == "medium"
    assert rig.replay.snapshot()["playback"]["active"] is False
    path = rig.replay.video(item["id"])
    video = cv2.VideoCapture(str(path))
    try:
        assert video.get(cv2.CAP_PROP_FPS) == 5
        assert video.get(cv2.CAP_PROP_FRAME_COUNT) == 41
        ok, frame = video.read()
        assert ok and frame.shape[:2] == (64, 96)
    finally:
        video.release()
    restored = InstantReplayService(rig.replay.root, lambda _: None, lambda: 1)
    assert restored.video(item["id"]) == path
    assert restored.snapshot()["highlights"][0]["auto_clip"] == item["auto_clip"]


@pytest.mark.parametrize("key,value", [
    ("verification_state", "CANDIDATE"), ("has_reference_evidence", False),
    ("identity_consistent", False), ("recognition_locked", False), ("result_current", False),
    ("card_present", False), ("identity_conflicts", [{"language": "conflict"}]),
    ("primary_candidate", None), ("primary_candidate", {"provisional": True}),
    ("updated_at", 999), ("updated_at", float("nan")), ("generation", -1),
])
def test_unverified_stale_or_conflicted_identity_cannot_trigger(rig, key, value):
    rig.clip.arm(True)
    rig.clip.observe({**rig.snapshot, key: value})
    assert rig.clip.snapshot()["pending_count"] == 0


def test_duplicate_and_out_of_order_generations_do_not_schedule_more_clips(rig):
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    rig.clip.observe(rig.snapshot)
    rig.clip.observe({**rig.snapshot, "generation": 0})
    assert rig.clip.snapshot()["pending_count"] == 1
    rig.advance()
    rig.clip.observe({**rig.snapshot, "updated_at": rig.clock[0]})
    assert rig.clip.snapshot()["saved_count"] == 1
    assert rig.clip.snapshot()["pending_count"] == 0


def test_arm_baseline_does_not_retroactively_clip_current_card(rig):
    rig.clip.arm(True, baseline_generation=1)
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == 0
    rig.clip.observe({**rig.snapshot, "generation": 2})
    assert rig.clip.snapshot()["pending_count"] == 1


@pytest.mark.parametrize("tier,expected", [("standard", 0), ("low", 0), ("medium", 1), ("grail", 1)])
def test_threshold_uses_existing_hit_classification(rig, tier, expected):
    rig.clip.arm(True)
    rig.snapshot["primary_candidate"]["hit_tier"] = tier
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == expected


def test_cold_buffer_is_reported_without_retry_spam(rig):
    rig.replay._frames.clear()
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["last_result"]["reason"] == "auto_clip_buffer_warming"
    rig.advance(6)
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == 0


@pytest.mark.parametrize("failure", ["disconnect", "slot_change", "long_gap"])
def test_interrupted_program_buffer_cannot_save_a_misleading_clip(rig, failure):
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    if failure == "disconnect":
        rig.replay.frame_provider = lambda _: None
    elif failure == "slot_change":
        rig.replay.program_slot_provider = lambda: 2
    else:
        rig.clock[0] += 2
    rig.advance()
    assert rig.clip.snapshot()["last_result"]["reason"] == "auto_clip_buffer_interrupted"
    assert not rig.replay.snapshot()["highlights"]


def test_queue_is_bounded_and_disarm_cancels_pending_clips(rig):
    rig.clip.arm(True)
    for generation in range(1, 6):
        rig.clip.observe({**rig.snapshot, "generation": generation})
    assert rig.clip.snapshot()["pending_count"] == 3
    assert rig.clip.snapshot()["last_result"]["reason"] == "auto_clip_queue_full"
    rig.clip.arm(False)
    rig.advance()
    assert not rig.replay.snapshot()["highlights"]
    assert rig.clip.snapshot()["pending_count"] == 0


def test_disarm_during_encoding_cleans_up_and_blocks_rearm_until_finished(rig, monkeypatch):
    entered, finish = threading.Event(), threading.Event()
    def encode(_path, _count, _cancelled):
        entered.set()
        assert finish.wait(3)
    monkeypatch.setattr(rig.replay, "_encode_video", encode)
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    rig.advance(2.8)
    rig.clock[0] = 1003
    rig.replay._capture_once()
    worker = threading.Thread(target=rig.clip.process_pending)
    worker.start()
    try:
        assert entered.wait(3)
        rig.clip.arm(False)
        assert rig.clip.arm(True)["updated"] is False
    finally:
        finish.set()
        worker.join(3)
    assert not worker.is_alive()
    assert not rig.replay.snapshot()["highlights"]
    assert not list(rig.replay.root.iterdir())
    assert rig.clip.snapshot()["last_result"]["reason"] == "auto_clip_cancelled"


@pytest.mark.parametrize("failure", ["encoder", "storage", "unexpected"])
def test_failed_save_cleans_up_without_losing_previous_manual_clip(rig, monkeypatch, failure):
    old = rig.replay.mark()["highlight"]
    def fail(*_):
        raise {"encoder": ValueError, "storage": OSError, "unexpected": RuntimeError}[failure]("failure")
    monkeypatch.setattr(rig.replay, "_encode_video", fail)
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    rig.advance()
    assert rig.clip.snapshot()["saved_count"] == 0
    assert rig.clip.snapshot()["last_result"]["created"] is False
    assert rig.replay.snapshot()["highlights"] == [old]
    assert len([p for p in rig.replay.root.iterdir() if p.is_dir()]) == 1


@pytest.mark.parametrize("payload", [None, {}, {"minimum_tier": "fake", "pre_seconds": 5, "post_seconds": 3}, {"minimum_tier": "medium", "pre_seconds": True, "post_seconds": 3}, {"minimum_tier": "medium", "pre_seconds": 11, "post_seconds": 3}])
def test_bad_settings_preserve_defaults_and_do_not_arm(rig, payload):
    assert rig.clip.configure(payload)["updated"] is False
    assert rig.clip.snapshot()["config"] == AutoClipService.DEFAULTS
    assert rig.clip.snapshot()["enabled"] is False


def test_settings_storage_failure_and_armed_edit_leave_configuration_unchanged(rig, monkeypatch):
    monkeypatch.setattr(module, "atomic_json", lambda *_: (_ for _ in ()).throw(OSError()))
    assert rig.clip.configure({**AutoClipService.DEFAULTS, "pre_seconds": 7})["reason"] == "auto_clip_settings_unavailable"
    rig.clip.arm(True)
    assert rig.clip.configure(AutoClipService.DEFAULTS)["reason"] == "disarm_auto_clip_before_editing"
    assert rig.clip.snapshot()["config"] == AutoClipService.DEFAULTS


def test_event_api_rejects_old_generation_and_download_is_guarded(rig, monkeypatch):
    from rareiq.web import server
    monkeypatch.setattr(server, "auto_clip", rig.clip)
    monkeypatch.setattr(server, "instant_replay", rig.replay)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(recognition_state=SimpleNamespace(snapshot=lambda: rig.snapshot)))
    rig.clip.arm(True)
    asyncio.run(server._evaluate_auto_clip_event({"type": "recognition_update", "payload": {"generation": 0}}))
    asyncio.run(server._evaluate_auto_clip_event({"type": "vision_update", "payload": {"generation": 1}}))
    assert rig.clip.snapshot()["pending_count"] == 0
    asyncio.run(server._evaluate_auto_clip_event({"type": "recognition_update", "payload": {"generation": 1}}))
    rig.advance()
    payload = asyncio.run(server.production_replay_status())
    assert payload["auto_clip"]["saved_count"] == 1
    item = payload["highlights"][0]
    response = asyncio.run(server.download_replay_clip(item["id"]))
    assert response.media_type == "video/mp4"
    assert response.filename.endswith(".mp4")
    assert asyncio.run(server.download_replay_clip("../../private" )).status_code == 404
    rig.replay.video(item["id"]).unlink()
    assert asyncio.run(server.download_replay_clip(item["id"])).status_code == 404


def test_stop_disarms_and_invalid_saved_settings_fall_back(rig):
    rig.clip.start()
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    rig.clip.stop()
    assert not rig.clip._thread.is_alive()
    assert not rig.clip.snapshot()["enabled"]
    assert rig.clip.snapshot()["pending_count"] == 0
    rig.clip.config_path.write_text('[]')
    assert AutoClipService(rig.replay, rig.clip.config_path).snapshot()["config"] == AutoClipService.DEFAULTS


@pytest.mark.parametrize("context", [
    {"connected": False, "frame_age_seconds": .1, "source_id": "camera"},
    {"connected": True, "frame_age_seconds": 3, "source_id": "camera"},
    {"connected": True, "frame_age_seconds": None, "source_id": "camera"},
    {"connected": True, "frame_age_seconds": float("nan"), "source_id": "camera"},
])
def test_old_jpeg_from_disconnected_or_stalled_camera_is_not_buffered(rig, context):
    rig.replay.frame_context_provider = lambda _: context
    rig.replay._capture_once()
    assert rig.replay.snapshot()["buffered_frames"] == 0
    assert rig.replay.snapshot()["last_error"]


def test_source_replacement_in_the_same_slot_invalidates_pending_auto_clip(rig):
    context = {"connected": True, "frame_age_seconds": .1, "source_id": "camera", "stream_session_id": 1}
    rig.replay.frame_context_provider = lambda _: context
    rig.advance(.2)
    rig.clip.arm(True)
    rig.clip.observe({**rig.snapshot, "updated_at": rig.clock[0]})
    context["stream_session_id"] = 2
    rig.advance()
    assert rig.clip.snapshot()["last_result"]["reason"] == "auto_clip_buffer_interrupted"


def test_source_swap_during_frame_read_is_rejected(rig):
    contexts = iter([{"connected": True, "frame_age_seconds": .1, "source_id": "a"}, {"connected": True, "frame_age_seconds": .1, "source_id": "b"}])
    rig.replay.frame_context_provider = lambda _: next(contexts)
    rig.replay._capture_once()
    assert rig.replay.snapshot()["buffered_frames"] == 0


def test_automatic_clips_share_retention_with_manual_highlights(rig):
    rig.replay.MAX_HIGHLIGHTS = 2
    manual = rig.replay.mark()["highlight"]
    rig.clip.arm(True)
    rig.clip.observe(rig.snapshot)
    rig.advance()
    automatic = rig.replay.snapshot()["highlights"][0]
    rig.replay.mark(name="New manual clip")
    assert rig.replay.frame(manual["id"], 0) is None
    assert rig.replay.video(automatic["id"]).is_file()
    rig.replay.mark(name="Newest manual clip")
    assert rig.replay.video(automatic["id"]) is None
    assert not (rig.replay.root / automatic["id"]).exists()


def test_settings_and_arm_routes_keep_restart_safety_and_validate_types(rig, monkeypatch):
    from pydantic import ValidationError
    from rareiq.web import server
    monkeypatch.setattr(server, "auto_clip", rig.clip)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(recognition_state=SimpleNamespace(snapshot=lambda: rig.snapshot)))
    with pytest.raises(ValidationError):
        server.AutoClipArmRequest(enabled="true")
    with pytest.raises(ValidationError):
        server.AutoClipSettingsRequest(pre_seconds=2.7)
    result = asyncio.run(server.configure_auto_clip(server.AutoClipSettingsRequest(pre_seconds=4)))
    assert result["updated"] and result["enabled"] is False
    result = asyncio.run(server.arm_auto_clip(server.AutoClipArmRequest(enabled=True)))
    assert result["enabled"] is True
    rig.clip.observe(rig.snapshot)
    assert rig.clip.snapshot()["pending_count"] == 0
    blocked = asyncio.run(server.configure_auto_clip(server.AutoClipSettingsRequest()))
    assert blocked.status_code == 409
