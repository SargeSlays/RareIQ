"""Local image sources use the same guarded composition and output receipts."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from rareiq.services.production_composition import validate_sources
from rareiq.services.production_scene_store import ProductionSceneStore
from rareiq.services.reaction_asset_service import ReactionAssetService
from rareiq.web import server
from rareiq.web.greenroom import GreenroomHub, Peer


@pytest.fixture
def images(tmp_path, monkeypatch):
    assets = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    asset = assets.add("Title.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"x" * 32)["asset"]
    source = "image:" + asset["id"]
    state = dict(program_slot=1, preview_slot=2, generation=0, transition="fade", duration_ms=500,
                 program_sources=[], preview_sources=[source])
    monkeypatch.setattr(server.orchestrator, "reaction_assets", assets)
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server.vision_controller, "manual_override", lambda: None)
    service = SimpleNamespace(source_available=lambda value: value.startswith("guest:"), record_production_event=lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "greenroom_service", service)
    hub = GreenroomHub(service, authorize_operator=lambda request: True, switcher=lambda: deepcopy(state),
                       static_dir=Path("."), image_source_available=server._production_image_available)
    monkeypatch.setattr(server, "greenroom_hub", hub)
    return source, asset, assets, state, hub


def test_image_identifier_catalog_and_restart_persistence(images, tmp_path):
    source, asset, assets, _, _ = images
    assert validate_sources([source]) == [source]
    for value in ["image:../../secret", "image:https://example.test/image.png", "image:" + asset["id"].upper()]:
        with pytest.raises(ValueError):
            validate_sources([value])
    assert server._production_image_sources() == [{"id": source, "name": "Title", "url": asset["url"]}]
    reopened = ReactionAssetService(assets.root, assets.state_path)
    assert reopened.get_path(asset["id"])
    store = ProductionSceneStore(tmp_path / "scene.sqlite3", tmp_path / "missing.json", [])
    store.edit(action="save", target="title", scene={"name": "Title", "program_sources": [source]},
               expected_revision=0, request_id="save-image", actor_kind="local_operator")
    assert ProductionSceneStore(store.path, store.legacy_path, []).snapshot()["scenes"][0]["program_sources"] == [source]


def test_image_preview_take_needs_decoded_output_and_is_camera_free(images):
    source, _, _, state, hub = images
    initial = deepcopy(state)
    assert server._production_source_problem([source]) is None
    assert server._take_program_action({})["reason"] == "image_output_not_ready"
    assert state == initial
    peer = Peer(None, "output", subscriptions=(source,))
    hub.peers["output"] = peer
    asyncio.run(hub._message("output", peer, {"type": "ready", "sources": [source]}))
    assert server._take_program_action({"transition": "slide"})["ok"]
    assert state["program_sources"] == [source] and state["generation"] == 1
    assert not server._program_composition_readiness([], 1)["ready"]
    asyncio.run(hub._message("output", peer, {"type": "ready", "sources": [source],
                "playback": {"generation": 1, "audio_blocked": False, "rendered": True}}))
    asyncio.run(hub._message("output", peer, {"type": "rendered", "generation": 1}))
    assert server._program_composition_readiness([], 1)["ready"]
    peer.ready[source] = time.monotonic() - 7
    assert server._production_source_problem([source], require_output=True)["reason"] == "image_output_not_ready"


def test_image_and_guest_must_reach_the_same_output(images):
    source, _, _, _, hub = images
    guest = "guest:" + "a" * 32 + ":camera"
    hub.peers = {"one": Peer(None, "output", ready={source: time.monotonic()}),
                 "two": Peer(None, "output", ready={guest: time.monotonic()})}
    assert not hub.composition_ready([source, guest])
    hub.peers["one"].ready[guest] = time.monotonic()
    assert hub.composition_ready([source, guest])


def test_missing_wrong_kind_and_unsubscribed_images_fail_closed(images):
    source, asset, assets, state, hub = images
    audio = assets.add("voice.mp3", "audio/mpeg", b"ID3" + b"x" * 32)["asset"]
    assert server._production_source_problem(["image:" + audio["id"]])["reason"] == "image_source_unavailable"
    peer = Peer(None, "output")
    asyncio.run(hub._message("output", peer, {"type": "ready", "sources": [source]}))
    assert not peer.ready
    assert hub._allowed_sources(peer, {"participants": [], "switcher": state}) == (source,)
    assets.get_path(asset["id"])[0].unlink()
    assert server._production_source_problem([source])["reason"] == "image_source_unavailable"
    assert hub._allowed_sources(peer, {"participants": [], "switcher": state}) == ()
