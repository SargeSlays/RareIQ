"""Studio/Card startup regression tests; all hardware/output services are fakes."""
import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from rareiq.web import server


@pytest.fixture
def production(monkeypatch):
    slots = [{"slot_id": n, "source_id": f"cam-{n}", "connected": True,
              "last_frame_at": time.time(), "display_name": f"Camera {n}"} for n in range(1, 5)]
    recognition = Mock(return_value={"state": "error"})
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        camera_manager=SimpleNamespace(session_statuses=lambda: [], camera_slots=lambda: slots),
        recognition_state=SimpleNamespace(snapshot=recognition)))
    monkeypatch.setattr(server, "instant_replay", SimpleNamespace(snapshot=lambda: {"buffered_frames": 30, "fps": 5}))
    monkeypatch.setattr(server, "recording", SimpleNamespace(settings=lambda: {}, status=lambda: {}, capabilities=lambda: {}))
    command = Mock()
    monkeypatch.setattr(server, "obs", SimpleNamespace(status=lambda: {"enabled": False}, cached_stream_route_probe=lambda: {}, command=command))
    monkeypatch.setattr(server, "broadcast_destinations", SimpleNamespace(refresh_connectors=lambda **kw: None, snapshot=lambda **kw: {}))
    readiness = {"ready": False, "platform_live_verified": False, "detail": "Not verified", "action": "Configure OBS"}
    monkeypatch.setattr(server, "_broadcast_go_live_readiness", lambda *args: readiness)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [{"id": "host", "program_slot": 3}])
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", {"program_slot": 3, "preview_slot": 2, "active_scene_id": "host"})
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": False})
    monkeypatch.setattr(server, "PRODUCTION_SHOW_START_LOCK", asyncio.Lock())
    monkeypatch.setattr(server, "_save_production_session", lambda: None)
    monkeypatch.setattr(server, "_production_event", lambda *args: None)
    monkeypatch.setattr(server, "_invalidate_broadcast_runtime_health", lambda: None)
    reset = Mock()
    async def safe():
        reset()
        return {"program_slot": 1}
    async def session(request):
        server.PRODUCTION_SESSION.update(active=True, metadata=request.model_dump(), recording={})
        return {"session": dict(server.PRODUCTION_SESSION)}
    monkeypatch.setattr(server, "production_safe_recovery", safe)
    monkeypatch.setattr(server, "start_production_session", session)
    return SimpleNamespace(slots=slots, recognition=recognition, command=command, reset=reset, readiness=readiness)


def run(coroutine):
    return asyncio.run(coroutine)


def test_general_preflight_never_reads_or_depends_on_card_engine(production):
    production.recognition.side_effect = RuntimeError("Card engine not installed")
    preflight = run(server.production_preflight())["preflight"]
    assert preflight["workflow"] == "studio"
    assert preflight["ready"] is True
    assert preflight["broadcast_ready"] is False
    assert next(c for c in preflight["checks"] if c["id"] == "recognition")["state"] == "skip"
    production.recognition.assert_not_called()


def test_card_preflight_preserves_recognition_blocker_and_checks_startup_slot(production):
    preflight = run(server.production_preflight("cards"))["preflight"]
    assert preflight["ready"] is False
    assert [c["id"] for c in preflight["blockers"]] == ["recognition"]
    assert preflight["program_camera"]["slot_id"] == 1
    production.recognition.assert_called_once()


def test_general_preflight_still_requires_selected_program_camera(production):
    production.slots[2]["connected"] = False
    preflight = run(server.production_preflight("studio"))["preflight"]
    assert preflight["ready"] is False
    assert [c["id"] for c in preflight["blockers"]] == ["camera"]
    assert preflight["program_camera"]["slot_id"] == 3


def test_unassigned_program_cannot_be_mistaken_for_ready_video(production):
    production.slots[2].update(source_id=None, connected=False, last_frame_at=None)
    preflight = run(server.production_preflight("studio"))["preflight"]
    assert preflight["ready"] is False
    assert "camera" in [check["id"] for check in preflight["blockers"]]


def test_camera_freshness_is_sampled_after_potentially_slow_encoder_probe(production):
    order = []
    def slots():
        order.append("camera")
        return production.slots
    def obs_status():
        order.append("obs")
        return {"enabled": False}
    server.orchestrator.camera_manager.camera_slots = slots
    server.obs.status = obs_status
    run(server.production_preflight())
    assert order == ["obs", "camera"]


def test_card_preflight_checks_camera_one_before_resetting_to_it(production):
    production.recognition.return_value = {"state": "ready"}
    production.slots[0]["connected"] = False
    result = run(server.start_production_show(server.StartShowRequest(workflow="cards")))
    assert result.status_code == 409
    production.reset.assert_not_called()


def test_general_start_keeps_program_and_does_not_call_card_reset_or_obs(production):
    result = run(server.start_production_show(server.StartShowRequest(name="Gaming night")))
    assert result["started"] is True
    assert result["safe"] == {"ok": True, "preserved": True, "program_slot": 3, "preview_slot": 2, "active_scene_id": "host"}
    assert result["session"]["output_intent"]["workflow"] == "studio"
    production.reset.assert_not_called()
    production.recognition.assert_not_called()
    production.command.assert_not_called()


def test_card_start_keeps_legacy_reset_when_explicitly_requested(production):
    production.recognition.return_value = {"state": "ready"}
    result = run(server.start_production_show(server.StartShowRequest(workflow="cards")))
    assert result["started"] is True
    assert result["safe"]["program_slot"] == 1
    assert result["session"]["output_intent"]["workflow"] == "cards"
    production.reset.assert_called_once()


def test_unverified_stream_cannot_start_in_either_workflow(production):
    production.recognition.return_value = {"state": "ready"}
    for workflow in ("studio", "cards"):
        result = run(server.start_production_show(server.StartShowRequest(workflow=workflow, start_obs_stream=True)))
        assert result.status_code == 409
        assert json.loads(result.body)["reason"] == "broadcast_destination_unverified"
    production.reset.assert_not_called()
    production.command.assert_not_called()


def test_duplicate_and_concurrent_start_cannot_reset_running_show(production):
    async def both():
        return await asyncio.gather(*(server.start_production_show(server.StartShowRequest()) for _ in range(2)))
    results = run(both())
    assert sum(isinstance(result, dict) and result.get("started") for result in results) == 1
    assert next(result for result in results if not isinstance(result, dict)).status_code == 409
    production.reset.assert_not_called()


def test_workflow_is_validated():
    assert server.StartShowRequest().workflow == "studio"
    with pytest.raises(ValidationError):
        server.StartShowRequest(workflow="anything")


def test_general_operator_health_does_not_touch_optional_recognition(production):
    server.orchestrator.camera_manager.status = lambda: {}
    server.orchestrator.overlay_state = SimpleNamespace(get=lambda: {})
    production.recognition.side_effect = RuntimeError("No card engine")
    payload = run(server.production_operator_health())
    assert payload["recognition_required"] is False
    production.recognition.assert_not_called()


@pytest.mark.parametrize("workflow,reset", [("studio", False), ("cards", True)])
def test_stop_uses_the_active_show_workflow_not_a_ui_preference(production, monkeypatch, workflow, reset):
    server.PRODUCTION_SESSION.update(active=True, output_intent={"workflow": workflow})
    async def stop_session():
        server.PRODUCTION_SESSION["active"] = False
        return {"session": dict(server.PRODUCTION_SESSION)}
    monkeypatch.setattr(server, "stop_production_session", stop_session)
    payload = run(server.stop_production_show())
    assert payload["stopped"] is True
    assert production.reset.called is reset
    assert payload["safe"]["program_slot"] == (1 if reset else 3)
