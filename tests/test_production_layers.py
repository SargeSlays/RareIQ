"""Layer geometry, Preview CAS and exact staged/rendered receipts; no media or user state."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from rareiq.services.production_composition import composition_id, composition_state, normalize_layers
from rareiq.services.production_scene_store import ProductionSceneStore
from rareiq.web import server
from rareiq.web.desktop_lifecycle import native_output_readiness
from rareiq.web.greenroom import GreenroomHub, Peer


IMAGE = "image:12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize("change", [
    {"x": -.1}, {"y": 1.1}, {"width": 0}, {"height": 2}, {"opacity": float("nan")},
    {"opacity": float("inf")}, {"x": True}, {"hidden": 1}, {"locked": "false"},
    {"z": 1.5}, {"z": 101}, {"crop": {"left": .6, "right": .4}},
    {"crop": {"bottom": .96}}, {"crop": {"top": False}}, {"rotate": 45},
    {"rotation": 180.01}, {"rotation": -180.01}, {"rotation": True},
    {"rotation": float("nan")}, {"rotation": "45"}, {"group": 12},
    {"group": None}, {"group": "x" * 41}, {"group": "\tGuest"},
    {"group": "Guest\x85"}, {"group": " "},
])
def test_invalid_geometry_cannot_enter_state(change):
    with pytest.raises(ValueError, match="invalid_production_layers"):
        normalize_layers(["camera:1"], {"camera:1": change})


def test_canonical_geometry_defaults_pruning_and_opaque_receipt():
    layers = normalize_layers(["camera:1"], {"camera:1": {"width": .5}, "camera:2": {"x": .2}})
    assert set(layers) == {"camera:1"}
    assert layers["camera:1"] == dict(x=0, y=0, width=.5, height=1,
        crop=dict(top=0, right=0, bottom=0, left=0), opacity=1, z=0, locked=False, hidden=False,
        rotation=0, group="")
    original = composition_id(["camera:1"], "custom", layers)
    assert len(original) == 64
    for field, value in [("x", .1), ("opacity", .4), ("z", 2), ("locked", True), ("hidden", True),
                         ("rotation", 90), ("group", "Guests")]:
        changed = deepcopy(layers)
        changed["camera:1"][field] = value
        assert composition_id(["camera:1"], "custom", changed) != original
    with pytest.raises(ValueError, match="layers_require_custom_layout"):
        normalize_layers(["camera:1"], layers, layout="grid")


def test_rotation_group_defaults_preserve_old_composition_identity_and_literal_names():
    sources = ["camera:1"]
    layers = normalize_layers(sources, {"camera:1": {"width": .5}})
    legacy = {source: {key: value for key, value in layer.items()
                       if key not in {"rotation", "group"}} for source, layer in layers.items()}
    legacy_id = hashlib.sha256(json.dumps(dict(sources=sources, layout="custom", layers=legacy),
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert composition_id(sources, "custom", layers) == legacy_id
    assert normalize_layers(sources, legacy) == layers
    rotated = normalize_layers(sources, {"camera:1": {"rotation": -12.3456789, "group": "Guests <3 🎥"}})
    assert rotated["camera:1"]["rotation"] == -12.345679
    assert rotated["camera:1"]["group"] == "Guests <3 🎥"
    assert normalize_layers(sources, rotated) == rotated


@pytest.fixture
def rig(monkeypatch):
    state = dict(program_slot=1, preview_slot=2, generation=0, transition="cut", duration_ms=0,
                 program_sources=["camera:1"], preview_sources=["camera:2"])
    events, available = [], {"camera:1", "camera:2", IMAGE}
    service = SimpleNamespace(source_available=lambda source: source in available,
        record_production_event=lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server, "greenroom_service", service)
    monkeypatch.setattr(server, "_production_source_available", lambda source: source in available)
    monkeypatch.setattr(server, "_production_slot_is_ready", lambda slot, slots: "camera:" + str(slot) in available)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server.vision_controller, "manual_override", lambda: None)
    hub = GreenroomHub(service, authorize_operator=lambda request: True, switcher=lambda: composition_state(state),
        static_dir=Path("."), source_available=lambda source: source in available)
    output = Peer(None, "output", subscriptions=("camera:1", "camera:2", IMAGE))
    hub.peers = {"captured": output}
    monkeypatch.setattr(server, "greenroom_hub", hub)
    return state, hub, output, available


def stage(rig, *, sources=None, layers=None, **extra):
    state = composition_state(rig[0])
    result = asyncio.run(server.production_switcher_preview(server.ProductionSwitcherRequest(
        preview_sources=sources or ["camera:2"], layout="custom", layers=layers or {"camera:2": {"width": .5}},
        expected_generation=state["generation"], expected_preview_revision=state["preview_revision"], **extra)))
    return json.loads(result.body) if hasattr(result, "body") else result


def receipt(rig, *, sources=None, preview_id=None, program_id=None):
    state, hub, output, _ = rig
    snapshot = composition_state(state)
    message = {"type": "ready", "sources": sources or snapshot["preview_sources"],
               "preview_composition_id": preview_id or snapshot["preview_composition_id"]}
    if program_id:
        message["playback"] = dict(generation=state["generation"], audio_blocked=False, rendered=True, composition_id=program_id)
    asyncio.run(hub._message("captured", output, message))


def take(rig, **extra):
    state = composition_state(rig[0])
    return server._take_program_action(dict(expected_generation=state["generation"],
        expected_preview_revision=state["preview_revision"], **extra))


def test_preview_edit_cas_never_changes_program_or_reuses_old_geometry_receipt(rig):
    state, hub, _, _ = rig
    before = composition_state(state)
    first = stage(rig)
    assert first["ok"] and first["preview_revision"] == 1 and first["generation"] == 0
    assert first["program_composition_id"] == before["program_composition_id"]
    assert take(rig)["reason"] == "composition_output_not_ready"
    receipt(rig)
    old = first["preview_composition_id"]
    assert hub.composition_ready(["camera:2"], composition_id=old)
    assert hub.output_status()["preview_composition_ready"]
    second = stage(rig, layers={"camera:2": {"width": .5, "hidden": True}})
    assert second["preview_composition_id"] != old
    assert not hub.composition_ready(["camera:2"], composition_id=second["preview_composition_id"])
    assert not hub.output_status()["preview_composition_ready"]
    assert take(rig)["reason"] == "composition_output_not_ready"
    conflict = asyncio.run(server.production_switcher_preview(server.ProductionSwitcherRequest(
        layout="custom", layers={"camera:2": {"x": .1}}, expected_generation=0, expected_preview_revision=1)))
    assert conflict.status_code == 409 and json.loads(conflict.body)["reason"] == "preview_revision_conflict"
    assert state["generation"] == 0 and composition_state(state)["preview_composition_id"] == second["preview_composition_id"]


def test_take_swaps_exact_maps_and_hidden_cannot_bypass_decode_or_review(rig):
    state, _, _, available = rig
    sources = ["camera:2", IMAGE]
    current = stage(rig, sources=sources, layers={"camera:2": {"z": 2}, IMAGE: {"hidden": True, "crop": {"left": .1}}})
    receipt(rig, sources=["camera:2"])
    assert take(rig)["reason"] == "image_output_not_ready"
    receipt(rig, sources=sources)
    available.remove(IMAGE)
    assert take(rig)["reason"] == "image_source_unavailable"
    available.add(IMAGE)
    result = take(rig)
    assert result["ok"] and state["program_layers"] == current["preview_layers"]
    assert result["program_composition_id"] == current["preview_composition_id"]
    assert state["preview_layers"] == {} and state["preview_layout"] == "auto"
    assert state["preview_sources"] == ["camera:1"] and state["generation"] == 1
    # Program changes remain deliberate; an old UI must never silently bypass custom staging.
    assert server._take_program_action({"layout": "custom"})["reason"] == "preview_revision_required"


def test_program_receipt_and_native_readiness_require_exact_geometry_id(rig):
    state, hub, output, _ = rig
    stage(rig)
    receipt(rig)
    assert take(rig)["ok"]
    current = composition_state(state)
    receipt(rig, sources=current["program_sources"], program_id="b" * 64)
    asyncio.run(hub._message("captured", output, {"type": "rendered", "generation": state["generation"]}))
    assert hub.output_status()["rendered_generation"] == -1
    assert not native_output_readiness(hub.peers, output_peer_id="captured", generation=state["generation"],
        sources=current["program_sources"], now=time.monotonic(), composition_id=current["program_composition_id"])["ready"]
    receipt(rig, sources=current["program_sources"], program_id=current["program_composition_id"])
    asyncio.run(hub._message("captured", output, {"type": "rendered", "generation": state["generation"]}))
    assert hub.output_status()["rendered_generation"] == state["generation"]
    assert native_output_readiness(hub.peers, output_peer_id="captured", generation=state["generation"],
        sources=current["program_sources"], now=time.monotonic(), composition_id=current["program_composition_id"])["ready"]


def test_custom_receipt_cannot_combine_partial_sources_from_different_outputs(rig):
    state, hub, _, _ = rig
    sources = ["camera:2", IMAGE]
    stage(rig, sources=sources)
    receipt(rig, sources=["camera:2"])
    second = Peer(None, "output", subscriptions=tuple(sources))
    hub.peers["second"] = second
    asyncio.run(hub._message("second", second, {"type": "ready", "sources": [IMAGE],
        "preview_composition_id": composition_state(state)["preview_composition_id"]}))
    assert not hub.output_status()["preview_composition_ready"]
    assert take(rig)["reason"] == "composition_output_not_ready"
    receipt(rig, sources=sources)
    assert hub.output_status()["preview_composition_ready"]
    rig[2].ready_composition_at -= 7
    assert not hub.output_status()["preview_composition_ready"]
    receipt(rig, sources=sources)
    assert take(rig)["ok"]


def test_removing_preview_source_prunes_metadata_without_interrupting_program(rig):
    state, _, _, _ = rig
    guest = "guest:" + "a" * 32 + ":camera"
    state.update(preview_sources=["camera:2", guest], preview_layout="custom",
        preview_layers=normalize_layers(["camera:2", guest]))
    before = composition_state(state)
    server._greenroom_removed("a" * 32)
    current = composition_state(state)
    assert guest not in state["preview_layers"] and current["preview_revision"] == before["preview_revision"] + 1
    assert current["generation"] == before["generation"] and current["program_composition_id"] == before["program_composition_id"]


def test_scene_persistence_roundtrips_both_buses_and_redacts_geometry_history(tmp_path):
    store = ProductionSceneStore(tmp_path / "scenes.sqlite3", tmp_path / "missing.json", [])
    scene = dict(name="Custom scene", program_sources=["camera:1", IMAGE], preview_sources=["camera:2"],
        layout="custom", layers=normalize_layers(["camera:1", IMAGE], {
            "camera:1": {"group": "Interview"}, IMAGE: {"x": .6, "width": .4, "locked": True, "rotation": 45, "group": "Interview"}}),
        preview_layout="custom", preview_layers=normalize_layers(["camera:2"], {"camera:2": {"opacity": .5, "rotation": -90, "group": "Guest"}}))
    result = store.edit(action="save", target="custom", scene=scene, expected_revision=0, request_id="save", actor_kind="local_operator")
    assert result["ok"]
    restored = ProductionSceneStore(store.path, store.legacy_path, []).snapshot()["scenes"][0]
    assert restored == {**scene, "id": "custom"}
    assert store.edit(action="save", target="custom", scene=scene, expected_revision=0, request_id="save", actor_kind="local_operator") == result
    changes = store.history()["events"][0]["changes"]
    assert changes["layers"] == {"changed": True} and changes["preview_layers"] == {"changed": True}
    with pytest.raises(ValueError):
        store.edit(action="save", target="bad", scene={**scene, "layers": {IMAGE: {"x": -1}}}, expected_revision=1, request_id="bad", actor_kind="local_operator")


def test_custom_scene_take_requires_staged_exact_scene_and_preserves_swap(rig, monkeypatch, tmp_path):
    state = rig[0]
    store = ProductionSceneStore(tmp_path / "scenes.sqlite3", tmp_path / "missing.json", [])
    layers = normalize_layers(["camera:2"], {"camera:2": {"x": .2, "width": .7, "opacity": .8, "rotation": 30, "group": "Guest"}})
    store.edit(action="save", target="custom", scene=dict(name="Scene", program_sources=["camera:2"],
        layout="custom", layers=layers), expected_revision=0, request_id="scene", actor_kind="local_operator")
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server.obs, "sync_scene", lambda scene_id: {"ok": True})
    monkeypatch.setattr(server.orchestrator, "overlay_state", SimpleNamespace(get=lambda: {}, update=lambda value: None))
    before = deepcopy(state)
    assert server._take_scene_action({"scene_id": "custom"})["reason"] == "composition_output_not_ready"
    assert state == before
    stage(rig, layers=layers)
    assert server._take_scene_action({"scene_id": "custom"})["reason"] == "composition_output_not_ready"
    receipt(rig)
    assert server._take_scene_action({"scene_id": "custom"})["ok"]
    assert state["program_layers"] == layers and state["preview_layout"] == "auto"
    assert state["preview_sources"] == ["camera:1"] and state["preview_layers"] == {}


def test_safe_recovery_clears_custom_metadata_and_retires_preview_revision(rig, monkeypatch):
    state = rig[0]
    state.update(program_layout="custom", program_layers=normalize_layers(["camera:1"]),
        preview_layout="custom", preview_layers=normalize_layers(["camera:2"]), preview_revision=7)
    monkeypatch.setattr(server.orchestrator, "overlay_state", SimpleNamespace(get=lambda: {}, update=lambda value: None))
    monkeypatch.setattr(server.orchestrator.multi_card_recognition, "select_slots", lambda values: {})
    monkeypatch.setattr(server.orchestrator.reveal_sequence, "cancel_animation", lambda: {})
    monkeypatch.setattr(server.instant_replay, "stop_playback", lambda: None)
    monkeypatch.setattr(server.obs, "sync_scene", lambda scene_id: {"ok": True})
    assert asyncio.run(server.production_safe_recovery())["safe"]
    assert composition_state(state)["program_layers"] == state["preview_layers"] == {}
    assert state["program_layout"] == state["preview_layout"] == "auto" and state["preview_revision"] == 8
