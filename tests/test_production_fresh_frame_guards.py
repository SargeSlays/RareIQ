"""Launch guards use synthetic camera state and cannot touch OBS or hardware."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from rareiq.web import server


@pytest.fixture
def rig(monkeypatch):
    slot = {"slot_id": 2, "source_id": "synthetic", "connected": True,
            "last_frame_at": 99.5, "display_name": "Test camera"}
    state = {"program_slot": 1, "preview_slot": 2, "generation": 4,
             "transition": "fade", "duration_ms": 500}
    def forbidden(*args):
        pytest.fail("Rejected camera must not change graphics or OBS")
    monkeypatch.setattr(server.time, "time", lambda: 100.0)
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [{"id": "test", "program_slot": 2, "screen_action": "show"}])
    monkeypatch.setattr(server, "production_scene_store", SimpleNamespace(snapshot=lambda: {"scenes": server.PRODUCTION_SCENES}))
    monkeypatch.setattr(server.greenroom_service, "record_production_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        camera_manager=SimpleNamespace(camera_slots=lambda: [slot]),
        reaction_assets=SimpleNamespace(snapshot=lambda: {"assets": []}),
        overlay_state=SimpleNamespace(get=forbidden, update=forbidden)))
    monkeypatch.setattr(server, "obs", SimpleNamespace(sync_scene=forbidden))
    return slot, state


@pytest.mark.parametrize("timestamp", [None, 97.0, float("nan"), float("inf"), -float("inf"), 101.0, "invalid"])
@pytest.mark.parametrize("action", ["preview", "take", "scene"])
def test_stale_or_invalid_frames_cannot_change_production(rig, timestamp, action):
    slot, state = rig
    slot["last_frame_at"] = timestamp
    before = deepcopy(state)
    request = server.ProductionSwitcherRequest(preview_slot=2)
    if action == "preview":
        response = asyncio.run(server.production_switcher_preview(request))
    elif action == "take":
        response = server._take_program_action(request.model_dump())
    else:
        response = asyncio.run(server.take_production_scene("test"))
    if not isinstance(response, dict):
        assert response.status_code == 409
        response = json.loads(response.body)
    assert response["ok"] is False
    assert response["reason"] == "camera_slot_unavailable"
    assert state == before


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), -float("inf"), 101.0])
def test_preflight_never_treats_invalid_timestamps_as_fresh(rig, timestamp):
    slot, _ = rig
    slot["last_frame_at"] = timestamp
    readiness = server._program_camera_readiness([slot], 2, now=100.0)
    assert readiness["ready"] is False
    json.dumps(readiness, allow_nan=False)


def test_current_frames_allow_take_and_readiness_recovers(rig):
    slot, state = rig
    slot["last_frame_at"] = 97.0
    assert server._take_program_action({"preview_slot": 2})["ok"] is False
    slot["last_frame_at"] = 99.9
    result = server._take_program_action({"preview_slot": 2})
    assert result["ok"] is True
    assert state["program_slot"] == 2 and state["generation"] == 5


def test_switcher_reports_readiness_without_mutating_camera_status(rig):
    slot, _ = rig
    slot["last_frame_at"] = 97.0
    payload = asyncio.run(server.production_switcher_status())
    assert payload["image_sources"] == []
    assert payload["slots"][0]["production_readiness"]["ready"] is False
    assert "production_readiness" not in slot
