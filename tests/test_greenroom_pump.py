"""Slow and failed peers cannot retain media permission or block healthy peers."""
import asyncio
from contextlib import suppress
from copy import deepcopy
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.greenroom_service import EMPTY_MEDIA, GreenroomService
from rareiq.web.greenroom import GreenroomHub, Peer


class Socket:
    headers = {"origin": "http://testserver"}
    url = "ws://testserver/socket"
    authorized = True

    def __init__(self, *, stall_send=False, stall_close=False, raise_send=False):
        self.stall_send, self.stall_close, self.raise_send = stall_send, stall_close, raise_send
        self.started, self.sent, self.closing = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.release = asyncio.Event()
        self.messages = []
        self.incoming = asyncio.Queue()

    async def accept(self):
        pass

    async def send_json(self, message):
        self.started.set()
        if self.raise_send:
            raise OSError("fixture disconnected")
        if self.stall_send:
            await self.release.wait()
        self.messages.append(message)
        self.sent.set()

    async def close(self, code):
        self.closing.set()
        if self.stall_close:
            await self.release.wait()

    async def receive(self):
        return await self.incoming.get()


def setup(tmp_path):
    service = GreenroomService(tmp_path / "room.sqlite3")
    state = {"program_slot": 1, "preview_slot": 2, "generation": 0,
             "program_sources": ["camera:1"], "preview_sources": ["camera:2"]}
    removed = []
    def remove(participant):
        removed.append(participant)
        for key in ("program_sources", "preview_sources"):
            state[key] = [s for s in state[key] if not s.startswith(f"guest:{participant}:")]
    hub = GreenroomHub(service, authorize_operator=lambda socket: socket.authorized,
                       switcher=lambda: deepcopy(state), removed=remove, static_dir=Path("."))
    hub.SEND_TIMEOUT, hub.CLOSE_TIMEOUT = .2, .03
    return service, hub, state, removed


def guest(service):
    token = "a" * 64
    participant = service.join(service.create_invite()["token"], "Fixture guest", token)
    service.moderate(participant["id"], "admit")
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
    return participant, token


def test_multiple_slow_recipients_do_not_delay_healthy_delivery(tmp_path):
    async def check():
        _, hub, _, _ = setup(tmp_path)
        blocked = [Socket(stall_send=True, stall_close=True) for _ in range(3)]
        healthy = Socket()
        hub.peers = {str(i): Peer(s, "producer") for i, s in enumerate([*blocked, healthy])}
        task = asyncio.create_task(hub._pump_once())
        await asyncio.wait_for(healthy.sent.wait(), .5)
        # Serial sends would close stalled peers before delivering to this one.
        assert all(s.started.is_set() and not s.closing.is_set() for s in blocked)
        await asyncio.wait_for(task, 1)
        assert list(hub.peers) == ["3"]
        await hub._pump_once()
        assert len(healthy.messages) == 2
    asyncio.run(check())


def test_send_lock_wait_and_close_handshake_are_bounded(tmp_path):
    async def check():
        _, hub, _, _ = setup(tmp_path)
        slow = Socket(stall_close=True)
        peer = Peer(slow, "output")
        hub.peers["slow"] = peer
        await peer.send_lock.acquire()
        try:
            await asyncio.wait_for(hub._pump_once(), 1)
            assert not slow.started.is_set() and slow.closing.is_set()
            assert "slow" not in hub.peers
        finally:
            peer.send_lock.release()
    asyncio.run(check())


def test_failed_guest_loses_readiness_and_program_before_close_finishes(tmp_path):
    async def check():
        service, hub, state, removed = setup(tmp_path)
        participant, token = guest(service)
        source = participant["sources"]["camera"]
        state["program_sources"] = state["preview_sources"] = [source]
        broken = Socket(raise_send=True, stall_close=True)
        hub.peers["guest"] = Peer(broken, "guest", participant_id=participant["id"], token=token)
        task = asyncio.create_task(hub._pump_once())
        await asyncio.wait_for(broken.closing.wait(), .5)
        assert not service.source_available(source)
        assert not hub.peers and participant["id"] in removed
        assert state["program_sources"] == state["preview_sources"] == []
        await asyncio.wait_for(task, .5)
        service.set_connected(participant["id"], True)
        service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
        assert state["program_sources"] == []  # Reconnect requires another take.
    asyncio.run(check())


def test_revoked_operator_gets_no_state_or_return_audio_subscription(tmp_path):
    async def check():
        service, hub, _, _ = setup(tmp_path)
        participant, token = guest(service)
        revoked, guest_socket = Socket(), Socket()
        revoked.authorized = False
        hub.peers = {"producer": Peer(revoked, "producer"),
                     "guest": Peer(guest_socket, "guest", participant_id=participant["id"], token=token)}
        await hub._pump_once()
        assert revoked.messages == [] and "producer" not in hub.peers
        assert guest_socket.messages[-1]["subscriptions"] == []
    asyncio.run(check())


def test_snapshot_failure_closes_peers_and_clears_media_permissions(tmp_path):
    async def check():
        service, hub, state, _ = setup(tmp_path)
        participant, token = guest(service)
        source = participant["sources"]["camera"]
        state["program_sources"] = [source]
        socket = Socket(stall_close=True)
        hub.peers["guest"] = Peer(socket, "guest", participant_id=participant["id"], token=token)
        hub._snapshot = lambda: (_ for _ in ()).throw(RuntimeError("fixture snapshot failure"))
        await asyncio.wait_for(hub._pump_once(), .5)
        assert not hub.peers and not service.source_available(source)
        assert state["program_sources"] == []
    asyncio.run(check())


def test_room_close_clears_selected_guests_missing_from_peer_map_and_history(tmp_path):
    _, hub, state, removed = setup(tmp_path)
    old_guest, other_guest = "b" * 32, "c" * 32
    state["program_sources"] = [f"guest:{old_guest}:camera", "camera:1"]
    state["preview_sources"] = [f"guest:{other_guest}:screen"]
    hub.authorize_operator = lambda request: True
    app = FastAPI()
    app.include_router(hub.router)
    with TestClient(app) as client:
        response = client.post("/api/production/greenroom/room/close", headers={"origin": "http://testserver"},
                               json={"expected_revision": 0, "request_id": "close"})
    assert response.status_code == 200
    assert set(removed) == {old_guest, other_guest}
    assert state["program_sources"] == ["camera:1"] and state["preview_sources"] == []


def test_signal_recipient_failure_does_not_disconnect_healthy_sender(tmp_path):
    async def check():
        service, hub, _, _ = setup(tmp_path)
        participant, token = guest(service)
        guest_id, producer_id = "a" * 32, "b" * 32
        sender, recipient = Socket(), Socket(raise_send=True)
        hub.peers = {guest_id: Peer(sender, "guest", participant_id=participant["id"], token=token),
                     producer_id: Peer(recipient, "producer")}
        await hub._message(guest_id, hub.peers[guest_id], {"type": "signal", "to": producer_id, "kind": "ice", "data": {"candidate": ""}})
        assert producer_id not in hub.peers and guest_id in hub.peers
        assert not sender.closing.is_set() and service.authenticate(token)["connected"]
    asyncio.run(check())


def test_late_media_packet_from_closed_socket_cannot_restore_permission(tmp_path):
    async def check():
        service, hub, state, _ = setup(tmp_path)
        participant, token = guest(service)
        state["program_sources"] = [participant["sources"]["camera"]]
        socket = Socket(stall_close=True)
        await socket.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "authenticate", "token": token})})
        serving = asyncio.create_task(hub._serve(socket, "guest"))
        try:
            await asyncio.wait_for(socket.sent.wait(), .5)
            key, peer = next(iter(hub.peers.items()))
            await hub._close_peer(key, peer)
            await socket.incoming.put({"type": "websocket.receive", "text": json.dumps({"type": "media", "media": EMPTY_MEDIA | {"camera": True}})})
            await asyncio.wait_for(serving, .5)
            assert not service.authenticate(token)["connected"]
            assert not service.source_available(participant["sources"]["camera"])
            assert state["program_sources"] == []
        finally:
            if not serving.done():
                serving.cancel()
                with suppress(asyncio.CancelledError):
                    await serving
            if hub._pump_task:
                hub._pump_task.cancel()
                with suppress(asyncio.CancelledError):
                    await hub._pump_task
    asyncio.run(check())


def test_old_socket_cleanup_does_not_disconnect_a_current_replacement(tmp_path):
    async def check():
        service, hub, state, removed = setup(tmp_path)
        participant, token = guest(service)
        source = participant["sources"]["camera"]
        state["program_sources"] = [source]
        old = Peer(Socket(), "guest", participant_id=participant["id"], token=token)
        current = Peer(Socket(), "guest", participant_id=participant["id"], token=token)
        hub.peers = {"old": old, "current": current}
        await hub._close_peer("old", old)
        hub._forget_peer("old", old)  # Old handler's later finally block.
        assert service.source_available(source) and not removed
        assert state["program_sources"] == [source]
    asyncio.run(check())
