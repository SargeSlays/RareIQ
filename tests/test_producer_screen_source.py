"""Synthetic local-only producer screen authorization, ownership and output guards."""
import asyncio
from copy import deepcopy
from pathlib import Path
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from rareiq.services.greenroom_service import GreenroomService
from rareiq.services.production_composition import validate_sources
from rareiq.web.greenroom import GreenroomHub, Peer


SOURCE = "producer:screen:" + "a" * 32
SDP = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n" + "".join(
    f"m={kind} 9 UDP/TLS/RTP/SAVPF 96\r\na=mid:{index}\r\na={'sendonly' if index == 2 else 'inactive'}\r\n"
    for index, kind in enumerate(("audio", "video", "video", "audio")))


class Socket:
    def __init__(self, host="127.0.0.1"):
        self.client = SimpleNamespace(host=host)
        self.headers = {}
        self.sent = []

    async def send_json(self, value):
        self.sent.append(value)

    async def close(self, **kwargs):
        pass


@pytest.fixture
def setup(tmp_path):
    state = dict(program_slot=1, preview_slot=2, program_sources=[], preview_sources=[], generation=0, transition="cut", duration_ms=0)
    removed = []
    service = GreenroomService(tmp_path / "room.sqlite3")
    hub = GreenroomHub(service, authorize_operator=lambda connection: True,
        authorize_publisher=lambda connection: connection.client.host == "127.0.0.1",
        switcher=lambda: deepcopy(state), static_dir=Path("."), producer_removed=removed.append)
    publisher = Peer(Socket(), "producer-screen")
    hub.peers["a" * 32] = publisher
    return hub, publisher, state, removed


def publish(hub, peer, active=True):
    asyncio.run(hub._message("a" * 32, peer, {"type": "media", "media": {"screen": active}}))


def test_source_is_explicit_epoch_bound_video_only_and_never_a_guest(setup):
    hub, publisher, state, _ = setup
    assert validate_sources([SOURCE]) == [SOURCE]
    assert not hub.producer_source_available(SOURCE)
    publish(hub, publisher)
    assert hub.producer_source_available(SOURCE)
    assert hub.producer_sources() == [{"id": SOURCE, "kind": "producer_screen", "name": "My screen / window", "available": True, "video_only": True}]
    assert hub.service.snapshot()["participants"] == []
    assert state["program_sources"] == state["preview_sources"] == []
    for invalid in ["producer:screen", "producer:screen:../../private", "producer:camera:" + "a" * 32]:
        with pytest.raises(ValueError):
            validate_sources([invalid])
        assert not hub.producer_source_available(invalid)
    for media in [{"screen": 1}, {"screen": True, "microphone": True}, {"screen": True, "screen_audio": True}]:
        with pytest.raises(ValueError, match="invalid_producer_media"):
            asyncio.run(hub._message("a" * 32, publisher, {"type": "media", "media": media}))


def test_only_selected_output_receives_screen_and_guest_view_never_subscribes(setup):
    hub, publisher, state, _ = setup
    publish(hub, publisher)
    output, producer = Peer(Socket(), "output"), Peer(Socket(), "producer")
    hub.peers.update({"b" * 32: output, "c" * 32: producer})
    snapshot = hub._snapshot()
    assert SOURCE in hub._allowed_sources(producer, snapshot)
    assert SOURCE not in hub._allowed_sources(output, snapshot)
    asyncio.run(hub._pump_once())
    assert [row["role"] for row in publisher.socket.sent[-1]["subscriptions"]] == ["producer"]
    state["preview_sources"] = [SOURCE]
    asyncio.run(hub._pump_once())
    subscriptions = publisher.socket.sent[-1]["subscriptions"]
    assert {row["role"] for row in subscriptions} == {"producer", "output"}
    assert all(row["sources"] == ["screen"] and row["return_audio"] is False for row in subscriptions)
    assert SOURCE in output.subscriptions
    # The guest gallery uses only invited participant cameras, never producer sources.
    hub.service.authenticate = lambda token: {"id": "guest", "state": "admitted", "connected": True}
    viewer = Peer(Socket(), "guest-view", token="fixture")
    assert hub._allowed_sources(viewer, hub._snapshot()) == ()
    hub.peers["d" * 32] = viewer
    with pytest.raises(ValueError, match="producer_subscription_not_allowed"):
        asyncio.run(hub._message("a" * 32, publisher, {"type": "signal", "to": "d" * 32, "kind": "offer", "data": {"type": "offer", "sdp": SDP}}))


def test_stop_disconnect_stall_and_revoked_local_access_invalidate_epoch(setup):
    hub, publisher, _, removed = setup
    output = Peer(Socket(), "output", subscriptions=(SOURCE,), ready={SOURCE: time.monotonic()})
    hub.peers["b" * 32] = output
    publish(hub, publisher)
    assert hub.source_ready(SOURCE)
    publish(hub, publisher, False)
    assert not hub.source_ready(SOURCE) and SOURCE not in output.ready and removed == [SOURCE]
    publish(hub, publisher)
    publisher.last_seen -= 8
    assert not hub.producer_source_available(SOURCE)
    publisher.last_seen = time.monotonic()
    publisher.socket.client.host = "192.0.2.10"
    assert not hub.producer_source_available(SOURCE)
    publisher.socket.client.host = "127.0.0.1"
    hub._forget_peer("a" * 32, publisher)
    assert not hub.producer_source_available(SOURCE) and removed[-1] == SOURCE
    replacement = Peer(Socket(), "producer-screen", screen_active=True)
    hub.peers["c" * 32] = replacement
    assert hub.producer_source_available("producer:screen:" + "c" * 32)
    assert not hub.producer_source_available(SOURCE)


def test_producer_signals_are_video_publisher_offers_and_selected_receiver_answers(setup):
    hub, publisher, state, _ = setup
    publish(hub, publisher)
    output = Peer(Socket(), "output")
    hub.peers["b" * 32] = output
    offer = {"type": "signal", "to": "b" * 32, "kind": "offer", "data": {"type": "offer", "sdp": SDP}}
    with pytest.raises(ValueError, match="producer_subscription_not_allowed"):
        asyncio.run(hub._message("a" * 32, publisher, offer))
    state["preview_sources"] = [SOURCE]
    asyncio.run(hub._message("a" * 32, publisher, offer))
    assert output.socket.sent[-1]["source_id"] == SOURCE
    assert output.socket.sent[-1]["role"] == "producer-screen"
    assert "participant_id" not in output.socket.sent[-1]
    with pytest.raises(ValueError, match="producer_screen_video_only"):
        asyncio.run(hub._message("a" * 32, publisher, {**offer, "data": {"type": "offer", "sdp": SDP.replace("a=inactive", "a=sendonly", 1)}}))
    with pytest.raises(ValueError, match="signal_direction_not_allowed"):
        asyncio.run(hub._message("b" * 32, output, {**offer, "to": "a" * 32}))


def test_http_and_websocket_publisher_reject_nonlocal_operators(tmp_path):
    hub = GreenroomHub(GreenroomService(tmp_path / "room.sqlite3"), authorize_operator=lambda connection: True,
        authorize_publisher=lambda connection: connection.client.host == "127.0.0.1",
        switcher=lambda: {"generation": 0}, static_dir=Path("."))
    app = FastAPI()
    app.include_router(hub.router)
    with TestClient(app, client=("192.0.2.10", 50000)) as client:
        assert client.get("/api/production/greenroom/producer-screen").json()["capture_allowed"] is False
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/api/production/greenroom/producer-screen-socket", headers={"origin": "http://testserver"}):
                pass
        assert error.value.code == 1008
    assert hub.peers == {}


def test_server_take_requires_same_output_and_disconnect_removes_buses(setup, monkeypatch):
    from rareiq.web import server
    hub, publisher, state, _ = setup
    publish(hub, publisher)
    state["preview_sources"] = [SOURCE]
    monkeypatch.setattr(server, "greenroom_hub", hub)
    monkeypatch.setattr(server, "greenroom_service", hub.service)
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server.vision_controller, "manual_override", lambda: None)
    assert server._production_source_problem([SOURCE]) is None
    assert server._take_program_action({})["reason"] == "producer_screen_output_not_ready"
    output = Peer(Socket(), "output", subscriptions=(SOURCE,))
    hub.peers["b" * 32] = output
    asyncio.run(hub._message("b" * 32, output, {"type": "ready", "sources": [SOURCE]}))
    assert server._take_program_action({})["ok"]
    assert state["program_sources"] == [SOURCE]
    hub.producer_removed = server._producer_screen_removed
    before = state["generation"]
    hub._forget_peer("a" * 32, publisher)
    assert SOURCE not in state["program_sources"] + state["preview_sources"]
    assert state["generation"] == before + 1
    assert server._production_source_problem([SOURCE])["reason"] == "producer_screen_source_unavailable"
