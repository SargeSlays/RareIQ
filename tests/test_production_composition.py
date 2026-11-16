"""Composition launch and automation guard tests, with no hardware or live writes."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rareiq.services.greenroom_service import GreenroomService
from rareiq.services.production_composition import composition_state, validate_sources, LAYOUTS
from rareiq.services.production_scene_store import ProductionSceneStore
from rareiq.web import server


GUEST = "guest:" + "a" * 32 + ":camera"


@pytest.fixture
def rig(monkeypatch, tmp_path):
    state = dict(program_slot=1, preview_slot=2, generation=0, transition="fade", duration_ms=500)
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    service = GreenroomService(tmp_path / "room.sqlite3")
    monkeypatch.setattr(server, "greenroom_service", service)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server, "_production_slot_is_ready", lambda slot, slots: True)
    monkeypatch.setattr(server.obs, "sync_scene", lambda scene: {"ok": True})
    controls = SimpleNamespace(origin="operator", authorized=False, output=False, available=False, overrides=0)
    def override():
        controls.overrides += 1
    monkeypatch.setattr(server.vision_controller, "manual_override", override)
    monkeypatch.setattr(server.vision_controller, "action_authorized", lambda request: controls.authorized)
    monkeypatch.setattr(server.production_actions, "current_origin", lambda: controls.origin)
    monkeypatch.setattr(server.production_actions, "current_request_id", lambda: "fixture")
    monkeypatch.setattr(service, "source_available", lambda source: controls.available)
    monkeypatch.setattr(server.greenroom_hub, "source_ready", lambda source: controls.output)
    monkeypatch.setattr(server.greenroom_hub, "composition_ready", lambda sources: not any(s.startswith("guest:") for s in sources) or controls.output)
    monkeypatch.setattr(server.greenroom_hub, "output_status", lambda: {"rendered_generation": state["generation"] if controls.output else -1})
    return state, controls, service


def test_legacy_composition_and_intentional_blank_are_distinct():
    state = {"program_slot": 1, "preview_slot": 2}
    assert composition_state(state)["program_sources"] == ["camera:1"]
    assert composition_state({**state, "program_sources": []})["program_sources"] == []


@pytest.mark.parametrize("sources", [None, "camera:1", ["camera:5"], [GUEST, GUEST], ["camera:1"] * 7, [False], ["guest:" + "a" * 32 + ":unknown"]])
def test_invalid_sources_are_rejected(sources):
    with pytest.raises(ValueError):
        validate_sources(sources)


def test_waiting_or_unreceived_guest_cannot_take(rig):
    state, controls, _ = rig
    initial = deepcopy(state)
    assert server._take_program_action({"preview_sources": [GUEST]})["reason"] == "guest_source_unavailable"
    controls.available = True
    assert server._take_program_action({"preview_sources": [GUEST]})["reason"] == "guest_output_not_ready"
    assert state == initial
    assert server._production_source_problem([GUEST]) is None


def test_mix_swap_then_voice_camera_and_audit(rig):
    state, controls, service = rig
    controls.available = controls.output = True
    result = server._take_program_action({"preview_sources": ["camera:1", GUEST], "layout": "grid", "transition": "slide", "duration_ms": 500})
    assert result["ok"] and state["program_sources"] == ["camera:1", GUEST]
    assert state["preview_sources"] == ["camera:1"]
    assert state["program_layout"] == "grid" and state["generation"] == 1
    controls.origin = "host_voice"
    assert server._take_program_action({"preview_slot": 3, "transition": "cut"})["ok"]
    assert state["program_sources"] == ["camera:3"] and state["duration_ms"] == 0
    assert any(item["actor_kind"] == "host_voice" for item in service.history()["events"])


def test_expired_gesture_cannot_change_program(rig):
    state, controls, _ = rig
    controls.origin = "host_gesture"
    assert server._take_program_action({"preview_slot": 3})["reason"] == "gesture_action_expired"
    assert state["generation"] == 0
    controls.authorized = True
    assert server._take_program_action({"preview_slot": 3})["ok"]


def test_saved_scene_is_read_from_authoritative_store_without_prior_list(rig, monkeypatch, tmp_path):
    state, controls, _ = rig
    store = ProductionSceneStore(tmp_path / "scenes.sqlite3", tmp_path / "missing.json", [])
    store.edit(action="save", target="fresh", scene={"name": "Fresh", "program_slot": 3, "program_sources": ["camera:3"]},
               expected_revision=0, request_id="save", actor_kind="local_operator")
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [])
    assert server._take_scene_action({"scene_id": "fresh"})["ok"]
    assert state["program_sources"] == ["camera:3"]
    store.edit(action="save", target="fresh", scene={"name": "Audio", "program_slot": 2, "spotify_action": "play"},
               expected_revision=1, request_id="save2", actor_kind="local_operator")
    controls.origin = "host_voice"
    assert server._take_scene_action({"scene_id": "fresh"})["reason"] == "scene_requires_audio_controls"
    assert state["program_sources"] == ["camera:3"]


def test_guest_mix_readiness_requires_output_and_replay_is_truthful(rig):
    state, controls, _ = rig
    state["program_sources"] = [GUEST]
    controls.available = True
    assert not server._program_composition_readiness([], 1)["ready"]
    controls.output = True
    assert server._program_composition_readiness([], 1)["ready"]
    assert server._save_clip_action({})["reason"] == "composition_replay_unavailable"
    state["program_sources"] = []
    assert not server._program_composition_readiness([], 1)["ready"]


def test_safe_revokes_vision_and_clears_guest_mix(rig, monkeypatch):
    state, controls, _ = rig
    state["program_sources"] = [GUEST]
    overlay = SimpleNamespace(get=lambda: {}, update=lambda value: None)
    monkeypatch.setattr(server.orchestrator, "overlay_state", overlay)
    monkeypatch.setattr(server.orchestrator.multi_card_recognition, "select_slots", lambda values: {})
    monkeypatch.setattr(server.orchestrator.reveal_sequence, "cancel_animation", lambda: {})
    monkeypatch.setattr(server.instant_replay, "stop_playback", lambda: None)
    assert asyncio.run(server.production_safe_recovery())["safe"]
    assert controls.overrides == 1 and state["program_sources"] == ["camera:1"]


def test_picture_in_picture_preview_take_and_saved_scene(rig, monkeypatch, tmp_path):
    state, controls, _ = rig
    assert "pip" in LAYOUTS
    controls.available = controls.output = True
    sources = ["camera:1", GUEST]
    request = server.ProductionSwitcherRequest(preview_sources=sources, layout="pip")
    result = asyncio.run(server.production_switcher_preview(request))
    assert result["ok"] and state["preview_layout"] == "pip"
    assert composition_state(state)["program_sources"] == ["camera:1"]
    assert server._take_program_action({})["ok"]
    assert state["program_layout"] == "pip" and state["program_sources"] == sources
    scene = server.ProductionSceneRequest(name="Picture in picture", id="pip", expected_revision=0,
        request_id="save-pip", program_sources=sources, layout="pip")
    store = ProductionSceneStore(tmp_path / "scenes.sqlite3", tmp_path / "missing.json", [])
    store.edit(action="save", target="pip", scene=scene.model_dump(exclude={"expected_revision", "request_id"}),
        expected_revision=0, request_id="save-pip", actor_kind="local_operator")
    monkeypatch.setattr(server, "production_scene_store", ProductionSceneStore(store.path, store.legacy_path, []))
    assert server._take_scene_action({"scene_id": "pip"})["ok"]
    assert state["program_layout"] == "pip" and state["program_sources"] == sources


@pytest.mark.parametrize("layout", ["unknown", "PIP", "", 1])
def test_invalid_layout_cannot_enter_preview_take_or_saved_scene(rig, layout):
    state, _, _ = rig
    before = deepcopy(state)
    with pytest.raises(ValidationError):
        server.ProductionSwitcherRequest(layout=layout)
    with pytest.raises(ValidationError):
        server._take_program_action({"layout": layout})
    with pytest.raises(ValidationError):
        server.ProductionSceneRequest(name="Invalid", expected_revision=0, request_id="invalid", layout=layout)
    assert state == before
