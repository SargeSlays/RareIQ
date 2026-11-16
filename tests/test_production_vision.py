from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.production_vision_service import ProductionVisionController
from rareiq.services.vision_assets import VisionAssets
from rareiq.web.production_vision import create_production_vision_router


class Actions:
    def __init__(self):
        self.calls = []
        self.before_execute = lambda: None

    def dispatch(self, action, params, **kwargs):
        self.before_execute()
        if kwargs["cancelled"]():
            return {"ok": False, "reason": "cancelled"}
        self.calls.append((action, params, kwargs["origin"]))
        return {"ok": True}


def fixture(mode="hands"):
    now = [100.0]
    frames = [0]
    ready = [True]
    def frame(_):
        frames[0] += 1
        return b"\xff\xd8" + str(frames[0]).encode() + b"\xff\xd9"
    actions = Actions()
    controller = ProductionVisionController(actions, lambda _, p: p, lambda _: ready[0], frame,
        SimpleNamespace(ready=lambda: True), enabled=True, clock=lambda: now[0], wallclock=lambda: 1000 + now[0])
    labels = ["open_palm", "thumbs_up", "victory"] if mode == "hands" else ["look_camera_1", "look_camera_2"]
    bindings = {key: {"action_id": "program.take", "params": {"preview_slot": i + 1}} for i, key in enumerate(labels)}
    nonce = controller.start(mode=mode, tracking_camera=1, bindings=bindings)["nonce"]
    return controller, nonce, now, ready, bindings, actions


def sample(c, nonce, now, *, gesture="open_palm", confidence=.99, face=1, hand=1, yaw=0, pitch=0, delay=.15):
    now[0] += delay
    _, frame_id = c.frame(nonce, 1)
    return c.observe(nonce, {"frame_id": frame_id, "hand_count": hand, "gesture": gesture,
        "gesture_score": confidence, "face_count": face, "yaw": yaw, "pitch": pitch})


def hold(c, nonce, now, **kwargs):
    return [sample(c, nonce, now, **kwargs) for _ in range(8)]


def test_practice_default_dwell_then_explicit_arm_and_release():
    c, nonce, now, _, _, actions = fixture()
    assert any(r.get("state") == "practice_match" for r in hold(c, nonce, now))
    assert actions.calls == []
    c.arm(nonce, False)
    assert any(r.get("state") == "action_result" for r in hold(c, nonce, now))
    hold(c, nonce, now)
    assert len(actions.calls) == 1
    hold(c, nonce, now, hand=0)
    hold(c, nonce, now)
    assert len(actions.calls) == 2 and actions.calls[0][2] == "host_gesture"


def test_uncertain_multiple_hands_and_slow_samples_never_accumulate():
    c, nonce, now, _, _, actions = fixture()
    sample(c, nonce, now)
    c.arm(nonce, False)
    for args in ({"confidence": .5}, {"hand": 2}, {"delay": .5}):
        hold(c, nonce, now, **args)
    assert not actions.calls


def test_replayed_frozen_and_stale_frames_fail_closed():
    c, nonce, now, *_ = fixture()
    c.frame_provider = lambda _: b"\xff\xd8frame\xff\xd9"
    _, frame_id = c.frame(nonce, 1)
    data = {"frame_id": frame_id, "hand_count": 1, "gesture": "open_palm", "gesture_score": .99, "face_count": 0, "yaw": None, "pitch": None}
    c.observe(nonce, data)
    with pytest.raises(ValueError, match="stale_frame"):
        c.observe(nonce, data)
    with pytest.raises(ValueError, match="waiting_for_new_frame"):
        c.frame(nonce, 1)
    c.frame_provider = lambda _: b"\xff\xd8newframe\xff\xd9"
    _, data["frame_id"] = c.frame(nonce, 1)
    now[0] += 1.1
    with pytest.raises(ValueError, match="stale_frame"):
        c.observe(nonce, data)


def test_manual_override_invalidates_queued_work_and_old_nonce():
    c, nonce, now, _, bindings, actions = fixture()
    sample(c, nonce, now)
    c.arm(nonce, False)
    actions.before_execute = c.manual_override
    for _ in range(7):
        result = sample(c, nonce, now)
    assert result.get("outcome", {}).get("reason") == "cancelled"
    assert not actions.calls
    new = c.start(mode="hands", tracking_camera=1, bindings=bindings)["nonce"]
    c.stop(nonce)
    assert c.status()["active"]
    with pytest.raises(ValueError, match="session_expired"):
        c.arm(nonce, False)
    c.stop(new)


def test_no_frame_acquisition_and_readiness_loss_stops():
    c, nonce, now, ready, _, actions = fixture()
    sample(c, nonce, now)
    ready[0] = False
    with pytest.raises(ValueError, match="camera_unavailable"):
        c.frame(nonce, 1)
    assert not c.status()["active"] and not actions.calls


def test_observations_cannot_supply_identity_actions_or_verified_provenance():
    c, nonce, now, *_ = fixture()
    for key in ("verified", "origin", "action_id", "identity"):
        with pytest.raises(ValueError, match="invalid_observation"):
            c.observe(nonce, {key: True})
    with pytest.raises(ValueError, match="reference_camera_mismatch"):
        c.frame(nonce, 2)


def test_head_calibration_distinct_stable_session_only_and_tracking_loss():
    c, nonce, now, _, bindings, actions = fixture("head")
    hold(c, nonce, now, yaw=-20)
    with pytest.raises(ValueError, match="calibration_required"):
        c.arm(nonce, False)
    assert not c.calibrate(nonce, 1)["ready"]
    hold(c, nonce, now, yaw=-18)
    with pytest.raises(ValueError, match="directions_too_close"):
        c.calibrate(nonce, 2)
    c._session["samples"].clear()
    hold(c, nonce, now, yaw=20)
    assert c.calibrate(nonce, 2)["ready"]
    assert any(r.get("state") == "practice_match" for r in hold(c, nonce, now, yaw=20))
    assert not actions.calls
    assert sample(c, nonce, now, face=0)["stopped"]
    c.start(mode="head", tracking_camera=1, bindings=bindings)
    assert c.status()["calibrated"] == []


def test_expired_tracking_and_feature_gate():
    c, nonce, now, _, bindings, _ = fixture()
    now[0] += 3.1
    assert not c.status()["active"]
    c.enabled = False
    with pytest.raises(ValueError, match="assets_unavailable"):
        c.start(mode="hands", tracking_camera=1, bindings=bindings)


def test_head_ambiguity_and_pose_boundaries_cannot_arm():
    c, nonce, now, *_ = fixture("head")
    for args in ({"face": 2}, {"yaw": float("nan")}, {"pitch": 70}):
        sample(c, nonce, now, **args)
        with pytest.raises(ValueError, match="fresh_tracking_required"):
            c.arm(nonce, False)
        with pytest.raises(ValueError, match="hold_direction"):
            c.calibrate(nonce, 1)


def test_direction_between_calibrated_targets_does_not_fire():
    c, nonce, now, _, _, actions = fixture("head")
    hold(c, nonce, now, yaw=-8)
    c.calibrate(nonce, 1)
    hold(c, nonce, now, yaw=8)
    c.calibrate(nonce, 2)
    sample(c, nonce, now, yaw=8)
    c.arm(nonce, False)
    hold(c, nonce, now, yaw=0)
    assert not actions.calls


def test_action_authorization_expires_and_is_invalidated_by_new_session():
    c, nonce, now, _, bindings, actions = fixture()
    captured = []
    def dispatch(action, params, **kwargs):
        captured.append(kwargs["request_id"])
        assert c.action_authorized(kwargs["request_id"])
        return {"ok": True}
    actions.dispatch = dispatch
    sample(c, nonce, now)
    c.arm(nonce, False)
    hold(c, nonce, now)
    assert captured
    now[0] += .8
    assert not c.action_authorized(captured[0])
    c.start(mode="hands", tracking_camera=1, bindings=bindings)
    assert not c.action_authorized(captured[0])


def test_camera_actions_cannot_smuggle_guest_sources_or_arbitrary_origins():
    c, _, _, _, bindings, _ = fixture()
    bad = {"open_palm": {"action_id": "program.take", "params": {"preview_slot": 1, "preview_sources": ["guest-secret"]}}}
    with pytest.raises(ValueError, match="invalid_action"):
        c.start(mode="hands", tracking_camera=1, bindings=bad)
    bindings["open_palm"]["action_id"] = "clip.save"
    with pytest.raises(ValueError, match="invalid_action"):
        c.start(mode="hands", tracking_camera=1, bindings=bindings)


def test_invalid_observation_resets_dwell_and_prevents_stale_arm():
    c, nonce, now, *_ = fixture()
    for _ in range(4):
        sample(c, nonce, now)
    with pytest.raises(ValueError, match="invalid_observation"):
        c.observe(nonce, {"verified": True})
    with pytest.raises(ValueError, match="fresh_tracking_required"):
        c.arm(nonce, False)
    assert all(sample(c, nonce, now).get("state") == "candidate" for _ in range(4))


def test_loopback_same_origin_only_and_asset_allowlist(tmp_path):
    app = FastAPI()
    router, controller = create_production_vision_router(Actions(), lambda a, p: p, lambda _: True,
                                                       lambda _: None, cache_dir=tmp_path, enabled=True)
    app.include_router(router)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 8888)) as client:
        assert client.get("/api/production/vision").json()["assets_ready"] is False
        assert client.get("/api/production/vision", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/production/vision", headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/production/vision/session", json={"verified": True}).status_code == 409
        assert client.get("/api/production/vision/assets/unknown.task").status_code == 409
    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.4", 8888)) as client:
        assert client.get("/api/production/vision").status_code == 403
    assert not controller.status()["active"]
    with pytest.raises(ValueError):
        VisionAssets(tmp_path).resolve("../anything")
