"""Invitation-only guest routes and bounded WebRTC signaling; media stays peer-to-peer."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Any
from urllib.parse import urlsplit
import uuid

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict, model_validator

from rareiq.services.greenroom_service import GreenroomService, GreenroomError


PUBLIC_GUEST_PATHS = frozenset({"/guest", "/guest/join", "/guest/leave", "/guest/chat",
                              "/guest/assets/guest.css", "/guest/assets/guest.js",
                              "/guest/assets/greenroom_chat.js", "/guest/assets/greenroom_chat.css",
                              "/guest/assets/guest_room.js", "/guest/assets/guest_room.css",
                              "/guest/assets/rehearsal_room.js", "/guest/assets/rehearsal_room.css", "/api/guest/rehearsal",
                              "/guest/assets/guest_microphone.js", "/guest/assets/guest_audio_dsp.js", "/guest/assets/studio_noise_gate.js",
                              "/guest/assets/studio_noise_gate.worklet.js", "/guest/assets/greenroom_media.js", "/guest/assets/theme.css", "/guest/assets/mark.svg"})


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invite_token: str = Field(min_length=32, max_length=128)
    name: str = Field(min_length=1, max_length=60)
    session_token: str = Field(pattern=r"^[a-f0-9]{64}$")


class MutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class InviteRequest(MutationRequest):
    label: str = Field(default="Guest", max_length=60)
    ttl_minutes: int = Field(default=60, ge=1, le=1440, strict=True)


class GuestChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    room_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    channel: str = Field(pattern=r"^(room|private)$")
    text: str = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class ProducerChatRequest(GuestChatRequest):
    participant_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ModerateRequest(MutationRequest):
    action: str = Field(pattern=r"^(admit|wait|remove|program_audio)$")
    microphone_muted: bool | None = Field(default=None, strict=True)
    screen_muted: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_program_audio(self):
        if self.action == "program_audio":
            if self.microphone_muted is None or self.screen_muted is None:
                raise ValueError("program_audio_requires_both_mute_flags")
        elif {"microphone_muted", "screen_muted"} & self.model_fields_set:
            raise ValueError("mute_flags_require_program_audio_action")
        return self


@dataclass
class Peer:
    socket: WebSocket
    role: str
    participant_id: str | None = None
    token: str | None = field(default=None, repr=False)
    subscriptions: tuple[str, ...] = ()
    ready: dict[str, float] = field(default_factory=dict)
    rendered_generation: int = -1
    playback_generation: int = -1
    playback_reported_at: float = 0
    audio_blocked: bool = False
    playback_rendered: bool = False
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class GreenroomHub:
    SEND_TIMEOUT = 3
    CLOSE_TIMEOUT = .5

    def __init__(self, service: GreenroomService, *, authorize_operator: Callable,
                 switcher: Callable[[], dict], static_dir: Path,
                 ice_servers: Callable[[], list] = lambda: [],
                 public_origin: Callable[[], str] = lambda: "",
                 actor_kind: Callable = lambda request: "local_operator",
                 removed: Callable[[str], None] = lambda participant: None,
                 image_source_available: Callable[[str], bool] = lambda source: False,
                 source_available: Callable[[str], bool] | None = None):
        self.service, self.authorize_operator, self.switcher = service, authorize_operator, switcher
        self.static_dir, self.ice_servers, self.public_origin = static_dir, ice_servers, public_origin
        self.actor_kind, self.removed = actor_kind, removed
        self.image_source_available = image_source_available
        self.source_available = source_available or image_source_available
        self.peers: dict[str, Peer] = {}
        self._pump_task: asyncio.Task | None = None
        self._join_attempts: dict[str, deque] = {}
        self._pending_guests = 0
        self.ingress_status = lambda: {"configured": False, "state": "disabled", "available": False, "public_verified": False}
        self.router = self._router()

    def _same_origin(self, connection, *, required=False):
        origin = connection.headers.get("origin")
        if not origin:
            return not required
        parsed = urlsplit(str(connection.url))
        scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme)
        candidates = {scheme + "://" + parsed.netloc}
        if self.public_origin():
            candidates.add(self.public_origin().rstrip("/"))
        return origin.rstrip("/") in candidates

    def _operator(self, connection):
        return self.authorize_operator(connection) and self._same_origin(connection)

    def _actor(self, request):
        return {"actor_kind": self.actor_kind(request), "principal": request.scope.get("studio_principal")}

    @staticmethod
    def _error(reason, status=400):
        return JSONResponse({"ok": False, "reason": reason}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    def _bearer_token(self, request):
        values = request.headers.getlist("authorization")
        if len(values) != 1 or not values[0].startswith("Bearer "):
            raise GreenroomError("guest_session_required", 401)
        return values[0][7:]

    def _bearer(self, request):
        return self.service.authenticate(self._bearer_token(request))

    def output_status(self):
        # Action workers read this while the event loop may remove a socket.
        outputs = [p for p in list(self.peers.values()) if p.role == "output"]
        now = time.monotonic()
        groups = [sorted(s for s, stamp in dict(p.ready).items() if now - stamp < 6) for p in outputs]
        generation = self.switcher()["generation"]
        fresh = [p for p in outputs if p.playback_generation == generation and now - p.playback_reported_at < 6]
        confirmed = [p.rendered_generation for p in fresh if not p.audio_blocked and p.playback_rendered and p.rendered_generation == generation]
        return {"connected": len(outputs), "ready_sources": sorted({s for group in groups for s in group}), "ready_groups": groups,
                "rendered_generation": max(confirmed, default=-1),
                "audio_blocked": any(p.audio_blocked for p in fresh)}

    def source_ready(self, source):
        available = self.source_available(source) if source.startswith(("image:", "video:", "text:", "browser:")) else self.service.source_available(source)
        status = self.output_status()
        if source.startswith("browser:"):
            return bool(available and status["ready_groups"] and all(source in group for group in status["ready_groups"]))
        return available and source in status["ready_sources"]

    def composition_ready(self, sources):
        received = {source for source in sources if source.startswith(("guest:", "image:", "video:", "text:", "browser:"))}
        groups = self.output_status()["ready_groups"]
        browsers = {source for source in received if source.startswith("browser:")}
        if browsers and (not groups or any(not browsers.issubset(group) for group in groups)):
            return False
        return not received or any(received.issubset(group) for group in groups)

    def _snapshot(self):
        return {**self.service.snapshot(), "switcher": self.switcher(), "output": self.output_status(),
                "connection": {"public_origin_configured": bool(self.public_origin()),
                               "guest_ingress": self.ingress_status(),
                               "relay_configured": any(any(str(u).startswith(("turn:", "turns:")) for u in ([s.get("urls")] if isinstance(s.get("urls"), str) else s.get("urls", []))) for s in self.ice_servers()),
                               "account_identity": "invitation_session"}}

    def _router(self):
        router = APIRouter()

        @router.get("/guest", include_in_schema=False)
        async def guest_page():
            return FileResponse(self.static_dir / "guest.html", headers={
                "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})

        @router.get("/guest/assets/{name}", include_in_schema=False)
        async def guest_asset(name: str):
            aliases = {"theme.css": "brand/producer-please-v2/producer-please.tokens.css",
                       "mark.svg": "brand/producer-please-v2/favicon.svg"}
            if name in aliases:
                return FileResponse(self.static_dir / aliases[name], headers={"Cache-Control": "no-cache"})
            if name not in {"guest.css", "guest.js", "guest_room.js", "guest_room.css", "rehearsal_room.js", "rehearsal_room.css", "greenroom_chat.js", "greenroom_chat.css", "greenroom_media.js", "guest_microphone.js", "guest_audio_dsp.js", "studio_noise_gate.js", "studio_noise_gate.worklet.js"}:
                return self._error("asset_not_found", 404)
            return FileResponse(self.static_dir / name, headers={"Cache-Control": "no-cache", "Referrer-Policy": "no-referrer"})

        @router.post("/guest/join")
        async def join(request: Request, body: JoinRequest):
            if not self._same_origin(request):
                return self._error("guest_origin_rejected", 403)
            host = request.client.host if request.client else "unknown"
            now = time.monotonic()
            if len(self._join_attempts) > 1024:
                self._join_attempts = {k: v for k, v in self._join_attempts.items() if v and now - v[-1] < 60}
                if len(self._join_attempts) > 1024:
                    return self._error("guest_join_busy", 429)
            attempts = self._join_attempts.setdefault(host, deque())
            while attempts and now - attempts[0] > 60:
                attempts.popleft()
            if len(attempts) >= 20:
                return self._error("guest_join_rate_limited", 429)
            attempts.append(now)
            try:
                return JSONResponse(self.service.join(body.invite_token, body.name, body.session_token), headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.post("/guest/leave")
        async def leave(request: Request):
            try:
                participant = self._bearer(request)
                result = self.service.leave(participant["id"])
                self.removed(participant["id"])
                await self._disconnect_participant(participant["id"])
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.get("/api/production/greenroom")
        async def status(request: Request):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            return JSONResponse(self._snapshot(), headers={"Cache-Control": "no-store"})

        @router.get("/guest/chat")
        async def guest_chat(request: Request, channel: str = "room", room_id: str | None = None):
            if not self._same_origin(request):
                return self._error("guest_origin_rejected", 403)
            if set(request.query_params) - {"channel", "room_id"}:
                return self._error("invalid_chat_query")
            try:
                result = self.service.guest_chat(self._bearer_token(request), channel, room_id=room_id)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)
            except (sqlite3.Error, OSError):
                return self._error("chat_unavailable", 503)

        @router.post("/guest/chat")
        async def guest_chat_send(request: Request, body: GuestChatRequest):
            if not self._same_origin(request):
                return self._error("guest_origin_rejected", 403)
            try:
                result = self.service.send_guest_chat(self._bearer_token(request), **body.model_dump())
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)
            except (sqlite3.Error, OSError):
                return self._error("chat_unavailable", 503)

        @router.get("/api/production/greenroom/chat")
        async def producer_chat(request: Request, channel: str = "room", participant_id: str | None = None,
                                room_id: str | None = None):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            if set(request.query_params) - {"channel", "room_id", "participant_id"}:
                return self._error("invalid_chat_query")
            try:
                result = self.service.producer_chat(channel, participant_id=participant_id, room_id=room_id, **self._actor(request))
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)
            except (sqlite3.Error, OSError):
                return self._error("chat_unavailable", 503)

        @router.post("/api/production/greenroom/chat")
        async def producer_chat_send(request: Request, body: ProducerChatRequest):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            try:
                result = self.service.send_producer_chat(**body.model_dump(), **self._actor(request))
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)
            except (sqlite3.Error, OSError):
                return self._error("chat_unavailable", 503)

        @router.get("/api/production/greenroom/activity")
        async def activity(request: Request):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            return JSONResponse(self.service.history(), headers={"Cache-Control": "no-store"})

        @router.post("/api/production/greenroom/invites")
        async def invite(request: Request, body: InviteRequest):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            try:
                result = self.service.create_invite(**body.model_dump(), **self._actor(request))
                origin = self.public_origin().rstrip("/") or str(request.base_url).rstrip("/")
                if result.get("token"):
                    result["join_url"] = origin + "/guest#invite=" + result.pop("token")
                return JSONResponse(result, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.post("/api/production/greenroom/participants/{participant_id}")
        async def moderate(participant_id: str, request: Request, body: ModerateRequest):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            try:
                result = self.service.moderate(participant_id, **body.model_dump(exclude_unset=True), **self._actor(request))
                if body.action == "remove" or body.action == "wait" and any(
                        p["id"] == participant_id and p["state"] == "waiting"
                        for p in self.service.snapshot()["participants"]):
                    self.removed(participant_id)
                if body.action == "remove":
                    await self._disconnect_participant(participant_id, code=1008)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.post("/api/production/greenroom/invites/{invite_id}/revoke")
        async def revoke(invite_id: str, request: Request, body: MutationRequest):
            if not self._operator(request):
                return self._error("producer_access_required", 403)
            try:
                result = self.service.revoke_invite(invite_id, **body.model_dump(), **self._actor(request))
                if result.get("removed_participant_id"):
                    self.removed(result["removed_participant_id"])
                    await self._disconnect_participant(result["removed_participant_id"], code=1008)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.post("/api/production/greenroom/room/{action}")
        async def room_action(action: str, request: Request, body: MutationRequest):
            if not self._operator(request) or action not in {"open", "close"}:
                return self._error("producer_access_required", 403)
            try:
                method = self.service.open_room if action == "open" else self.service.close_room
                result = method(**body.model_dump(), **self._actor(request))
                if action == "close":
                    # Selected sources can outlive their socket or the bounded
                    # history snapshot. Clear the actual buses, not just peers.
                    selected = self.switcher()
                    participants = {source.split(":")[1]
                                    for bus in ("program_sources", "preview_sources")
                                    for source in selected.get(bus, [])
                                    if isinstance(source, str) and source.startswith("guest:") and len(source.split(":")) == 3}
                    for participant in participants:
                        self.removed(participant)
                    await asyncio.gather(*(self._close_peer(key, peer, code=1008)
                                           for key, peer in list(self.peers.items()) if peer.role in {"guest", "guest-view"}))
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
            except GreenroomError as exc:
                return self._error(exc.reason, exc.status)

        @router.websocket("/guest/ws")
        async def guest_socket(socket: WebSocket):
            await self._serve(socket, "guest")

        @router.websocket("/guest/view/ws")
        async def guest_view_socket(socket: WebSocket):
            await self._serve(socket, "guest-view")

        @router.websocket("/api/production/greenroom/producer-socket")
        async def producer_socket(socket: WebSocket):
            await self._serve(socket, "producer")

        @router.websocket("/api/production/greenroom/output-socket")
        async def output_socket(socket: WebSocket):
            await self._serve(socket, "output")

        return router

    async def _send(self, peer, payload):
        # Bound the lock wait as well as the socket write. A slow signaling write
        # must not leave a state update waiting indefinitely for the same peer.
        async with asyncio.timeout(self.SEND_TIMEOUT):
            async with peer.send_lock:
                await peer.socket.send_json(payload)

    def _forget_peer(self, key, peer):
        if self.peers.get(key) is peer:
            self.peers.pop(key)
        peer.subscriptions = ()
        peer.ready.clear()
        if peer.role == "guest" and peer.participant_id and not any(p.role == "guest" and p.participant_id == peer.participant_id for p in self.peers.values()):
            try:
                self.service.set_connected(peer.participant_id, False)
            except (GreenroomError, sqlite3.Error, OSError):
                pass
            # Rejoining may resume backstage, but must never silently put the
            # guest back on Program after losing their media connection.
            self.removed(peer.participant_id)

    async def _close_peer(self, key, peer, *, code=1008):
        # Revoke registry access and media readiness before attempting transport
        # cleanup; a broken close handshake cannot keep a guest source available.
        self._forget_peer(key, peer)
        try:
            async with asyncio.timeout(self.CLOSE_TIMEOUT):
                await peer.socket.close(code=code)
        except (RuntimeError, WebSocketDisconnect, OSError, asyncio.TimeoutError):
            pass

    async def _disconnect_participant(self, participant, *, code=1000):
        await asyncio.gather(*(self._close_peer(key, peer, code=code)
                               for key, peer in list(self.peers.items()) if peer.participant_id == participant))

    async def _read(self, socket):
        packet = await asyncio.wait_for(socket.receive(), 25)
        if packet.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(packet.get("code", 1000))
        raw = packet.get("text")
        if not isinstance(raw, str):
            raise ValueError("text_signaling_required")
        if len(raw.encode()) > 65536:
            raise ValueError("signaling_too_large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid_signaling")
        return value

    async def _serve(self, socket, role):
        guest_role = role in {"guest", "guest-view"}
        if not self._same_origin(socket) or (not guest_role and not self._operator(socket)):
            await socket.close(code=1008)
            return
        if not guest_role and sum(p.role == role for p in self.peers.values()) >= (3 if role == "producer" else 2):
            await socket.close(code=1013)
            return
        if guest_role and self._pending_guests >= 24:
            await socket.close(code=1013)
            return
        pending_guest = guest_role
        if pending_guest:
            self._pending_guests += 1
        key, peer = uuid.uuid4().hex, Peer(socket, role)
        try:
            await socket.accept()
            if guest_role:
                first = await asyncio.wait_for(self._read(socket), 5)
                if first.get("type") != "authenticate":
                    raise ValueError("authentication_required")
                participant = self.service.authenticate(first.get("token", ""))
                peer.participant_id, peer.token = participant["id"], first["token"]
                previous = [(old_key, old) for old_key, old in self.peers.items()
                            if old.role == role and old.participant_id == participant["id"]]
                if role == "guest":
                    if previous:
                        self.service.set_connected(participant["id"], False)
                        self.removed(participant["id"])
                    self.service.set_connected(participant["id"], True)
                self._pending_guests -= 1
                pending_guest = False
                # Reserve the newest role/session before a potentially slow close.
                # A second reconnect must see and replace this reservation, rather
                # than let both continuations register after the old close settles.
                self.peers[key] = peer
                for old_key, old in previous:
                    await self._close_peer(old_key, old, code=1000)
                if self.peers.get(key) is not peer:
                    return
            else:
                self.peers[key] = peer
            await self._send(peer, {"type": "hello", "peer_id": key, "role": role,
                                    "participant_id": peer.participant_id, "ice_servers": self.ice_servers()})
            if self._pump_task is None or self._pump_task.done():
                self._pump_task = asyncio.create_task(self._pump())
            rate = deque()
            while True:
                message = await self._read(socket)
                if self.peers.get(key) is not peer:
                    break  # A revoked/replaced socket cannot publish late media.
                now = time.monotonic()
                while rate and now - rate[0] > 10:
                    rate.popleft()
                if len(rate) >= 180:
                    raise ValueError("signaling_rate_limited")
                rate.append(now)
                if guest_role:
                    self.service.authenticate(peer.token)
                elif not self._operator(socket):
                    raise ValueError("access_revoked")
                await self._message(key, peer, message)
        except (WebSocketDisconnect, asyncio.TimeoutError, GreenroomError, ValueError, RuntimeError, OSError, sqlite3.Error):
            await self._close_peer(key, peer)
        finally:
            if pending_guest:
                self._pending_guests -= 1
            self._forget_peer(key, peer)

    def _view_sources(self, peer, snapshot):
        viewer = self.service.authenticate(peer.token)
        if viewer["state"] != "admitted" or not viewer["connected"]:
            return ()
        return tuple(sorted(p["sources"]["camera"] for p in snapshot["participants"]
                            if p["id"] != viewer["id"] and p["state"] == "admitted"
                            and p["connected"] and not p.get("expired") and p["media"]["camera"]))

    @staticmethod
    def _guest_room(snapshot):
        # A guest roster is not an operator snapshot: no invitations, activity,
        # output state, private messages, account data or network configuration.
        fields = ("id", "name", "state", "connected", "expired", "media", "sources")
        return {"room_id": snapshot["room_id"], "active": snapshot["active"],
                "participants": [{key: p[key] for key in fields if key in p}
                                 for p in snapshot["participants"]
                                 if p["state"] != "removed" and not p.get("expired")]}

    def _allowed_sources(self, peer, snapshot):
        if peer.role == "guest-view":
            return self._view_sources(peer, snapshot)
        participants = snapshot["participants"]
        if peer.role == "producer":
            return tuple(sorted(source for p in participants if p["connected"] and p["state"] != "removed" for source in p["sources"].values()))
        state = snapshot["switcher"]
        sources = state.get("program_sources", [f"camera:{state.get('program_slot', 1)}"]) + state.get("preview_sources", [f"camera:{state.get('preview_slot', 2)}"])
        return tuple(sorted({s for s in sources if (s.startswith("guest:") and self.service.source_available(s))
                             or (s.startswith(("image:", "video:", "text:", "browser:")) and self.source_available(s))}))

    async def _pump(self):
        while self.peers:
            await self._pump_once()
            await asyncio.sleep(.5)

    async def _pump_once(self):
        try:
            snapshot = self._snapshot()
        except (RuntimeError, ValueError, OSError, sqlite3.Error):
            # An unavailable authoritative snapshot must not leave old media
            # permissions active while the background task silently disappears.
            await asyncio.gather(*(self._close_peer(key, peer) for key, peer in list(self.peers.items())))
            return
        producer_ids = [k for k, p in self.peers.items() if p.role == "producer" and self._operator(p.socket)]
        # Each recipient has its own deadline. Even several blocked writes cost
        # at most one send/close deadline, below the client's 7-second watchdog.
        await asyncio.gather(*(self._pump_peer(key, peer, snapshot, producer_ids)
                               for key, peer in list(self.peers.items())))

    async def _pump_peer(self, key, peer, snapshot, producer_ids):
        try:
            if self.peers.get(key) is not peer:
                return
            if peer.role == "guest":
                participant = self.service.authenticate(peer.token)
                subscriptions = []
                for receiver_id, receiver in self.peers.items():
                    if receiver.role == "guest":
                        continue
                    if receiver.role == "guest-view":
                        try:
                            self.service.authenticate(receiver.token)
                        except GreenroomError:
                            continue
                    elif not self._operator(receiver.socket):
                        continue
                    sources = self._allowed_sources(receiver, snapshot)
                    kinds = [kind for kind, source in participant["sources"].items() if source in sources]
                    if kinds:
                        subscriptions.append({"peer_id": receiver_id, "role": receiver.role, "sources": kinds,
                            "return_audio": receiver_id == (producer_ids[0] if producer_ids else None) and participant["state"] == "admitted"})
                await self._send(peer, {"type": "state", "participant": participant, "subscriptions": subscriptions,
                                        "on_air_sources": snapshot["switcher"].get("program_sources", [])})
            elif peer.role == "guest-view":
                self.service.authenticate(peer.token)
                peer.subscriptions = self._view_sources(peer, snapshot)
                await self._send(peer, {"type": "state", "room": self._guest_room(snapshot),
                                        "subscriptions": peer.subscriptions})
            else:
                if not self._operator(peer.socket):
                    raise ValueError("access_revoked")
                peer.subscriptions = self._allowed_sources(peer, snapshot)
                peer.ready = {s: stamp for s, stamp in peer.ready.items() if s in peer.subscriptions}
                await self._send(peer, {"type": "state", "room": snapshot, "subscriptions": peer.subscriptions,
                                        "return_audio_owner": key == (producer_ids[0] if producer_ids else None)})
        except (RuntimeError, WebSocketDisconnect, GreenroomError, ValueError, OSError, sqlite3.Error, asyncio.TimeoutError):
            await self._close_peer(key, peer)

    @staticmethod
    def _signal(data, kind):
        if not isinstance(kind, str) or kind not in {"offer", "answer", "ice"}:
            raise ValueError("invalid_signal_kind")
        if not isinstance(data, dict):
            raise ValueError("invalid_signal")
        if kind in {"offer", "answer"}:
            if set(data) != {"type", "sdp"} or data["type"] != kind or not isinstance(data["sdp"], str) or len(data["sdp"]) > 50000:
                raise ValueError("invalid_description")
            lines = data["sdp"].splitlines()
            media = [line for line in lines if line.startswith("m=")]
            if (not lines or lines[0] != "v=0" or "\x00" in data["sdp"]
                    or any(len(line) > 4096 for line in lines) or not 1 <= len(media) <= 4
                    or any(not line.startswith(("m=audio ", "m=video ")) for line in media)
                    or any(not any(line.startswith(prefix) for line in lines) for prefix in ("o=", "s=", "t="))):
                raise ValueError("invalid_description")
        elif kind == "ice":
            if set(data) - {"candidate", "sdpMid", "sdpMLineIndex", "usernameFragment"} or not isinstance(data.get("candidate"), str) or len(data["candidate"]) > 2048:
                raise ValueError("invalid_candidate")
            if data.get("sdpMid") is not None and (not isinstance(data["sdpMid"], str) or len(data["sdpMid"]) > 16):
                raise ValueError("invalid_candidate")
            if data.get("sdpMLineIndex") is not None and (type(data["sdpMLineIndex"]) is not int or not 0 <= data["sdpMLineIndex"] <= 4):
                raise ValueError("invalid_candidate")
            if data.get("usernameFragment") is not None and (not isinstance(data["usernameFragment"], str) or len(data["usernameFragment"]) > 256):
                raise ValueError("invalid_candidate")
        else:
            raise ValueError("invalid_signal_kind")
        return data

    async def _message(self, key, peer, message):
        kind = message.get("type")
        if kind == "heartbeat":
            return
        if kind == "media" and peer.role == "guest":
            self.service.update_media(peer.participant_id, message.get("media"))
            return
        if kind == "ready" and peer.role == "output":
            sources = message.get("sources")
            if not isinstance(sources, list) or len(sources) > 12 or any(not isinstance(s, str) for s in sources):
                raise ValueError("invalid_ready_sources")
            if "playback" in message:
                playback = message["playback"]
                if (not isinstance(playback, dict) or set(playback) != {"generation", "audio_blocked", "rendered"}
                        or type(playback["generation"]) is not int or not 0 <= playback["generation"] <= 2**53 - 1
                        or type(playback["audio_blocked"]) is not bool or type(playback["rendered"]) is not bool
                        or playback["audio_blocked"] and playback["rendered"]):
                    raise ValueError("invalid_playback_state")
                if playback["generation"] == self.switcher()["generation"]:
                    peer.playback_generation = playback["generation"]
                    peer.playback_reported_at = time.monotonic()
                    peer.audio_blocked = playback["audio_blocked"]
                    peer.playback_rendered = playback["rendered"]
            peer.ready = {s: time.monotonic() for s in sources if s in peer.subscriptions and
                          (self.source_available(s) if s.startswith(("image:", "video:", "text:", "browser:")) else self.service.source_available(s))}
            return
        if kind == "rendered" and peer.role == "output":
            generation = message.get("generation")
            state = self.switcher()
            if (type(generation) is not int or generation != state["generation"]
                    or peer.playback_generation != generation or time.monotonic() - peer.playback_reported_at >= 6
                    or peer.audio_blocked or not peer.playback_rendered):
                return
            if generation != peer.rendered_generation:
                peer.rendered_generation = generation
                self.service.record_production_event("program.rendered", str(generation), "confirmed",
                                                     actor_kind="program_renderer", details={"generation": generation})
            return
        if kind != "signal":
            raise ValueError("message_not_allowed")
        target_id = message.get("to")
        if not isinstance(target_id, str) or len(target_id) != 32 or any(c not in "0123456789abcdef" for c in target_id):
            raise ValueError("invalid_signal_target")
        target = self.peers.get(target_id)
        if target is None:
            return
        guest, receiver = (peer, target) if peer.role == "guest" else (target, peer)
        if guest.role != "guest" or receiver.role not in {"producer", "output", "guest-view"}:
            raise ValueError("peer_pair_not_allowed")
        if receiver.role != "guest-view" and not self._operator(receiver.socket):
            raise ValueError("access_revoked")
        participant = self.service.authenticate(guest.token)
        allowed = self._allowed_sources(receiver, self._snapshot())
        if not any(source in allowed for source in participant["sources"].values()):
            raise ValueError("subscription_not_allowed")
        signal_kind = message.get("kind")
        if (signal_kind == "offer" and peer.role != "guest") or (signal_kind == "answer" and peer.role == "guest"):
            raise ValueError("signal_direction_not_allowed")
        data = self._signal(message.get("data"), signal_kind)
        try:
            await self._send(target, {"type": "signal", "from": key, "participant_id": guest.participant_id,
                                      "role": peer.role, "kind": signal_kind, "data": data})
        except (RuntimeError, WebSocketDisconnect, OSError, asyncio.TimeoutError):
            # A dead recipient is not a protocol violation by the healthy sender.
            await self._close_peer(target_id, target)
