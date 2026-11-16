"""Isolated guest HTTP/signaling acceptance: no main app, devices or external peers."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from rareiq.services.greenroom_service import EMPTY_MEDIA, GreenroomError, GreenroomService
from rareiq.web.greenroom import GreenroomHub, Peer


ORIGIN = {"origin": "http://testserver"}
OPERATOR = ORIGIN | {"x-test-producer": "yes"}
SDP = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=mid:0\r\na=sendonly\r\n"


@pytest.fixture
def fixture(tmp_path):
    service = GreenroomService(tmp_path / "room.sqlite3")
    state = {"program_slot": 1, "preview_slot": 2, "generation": 0,
             "program_sources": ["camera:1"], "preview_sources": ["camera:2"]}
    removed = []
    hub = GreenroomHub(service, authorize_operator=lambda request: request.headers.get("x-test-producer") == "yes",
                       switcher=lambda: deepcopy(state), static_dir=Path(__file__).parents[1] / "rareiq/web/static",
                       removed=removed.append)
    app = FastAPI()
    app.include_router(hub.router)
    with TestClient(app) as client:
        yield service, hub, state, removed, client


def join(fixture, number=1):
    service, _, _, _, client = fixture
    invitation = service.create_invite()
    token = f"{number:064x}"
    response = client.post("/guest/join", headers=ORIGIN,
                           json={"invite_token": invitation["token"], "name": "Fixture guest", "session_token": token})
    assert response.status_code == 200
    return invitation, response.json(), token


@contextmanager
def socket(client, role, token=None):
    path = "/guest/ws" if role == "guest" else f"/api/production/greenroom/{role}-socket"
    with client.websocket_connect(path, headers=ORIGIN if role == "guest" else OPERATOR) as connection:
        if role == "guest":
            connection.send_json({"type": "authenticate", "token": token})
        hello = connection.receive_json()
        assert hello["type"] == "hello" and hello["role"] == role
        yield connection, hello


def next_type(connection, kind):
    for _ in range(12):
        message = connection.receive_json()
        if message.get("type") == kind:
            return message
    pytest.fail("Expected bounded signaling message was not received")


def assert_closed(connection, expected=1008):
    with pytest.raises(WebSocketDisconnect) as failure:
        for _ in range(12):
            connection.receive_json()
    assert failure.value.code == expected


def test_guest_join_invite_secret_and_host_controls_are_separate(fixture):
    service, _, _, _, client = fixture
    invite_response = client.post("/api/production/greenroom/invites", headers=OPERATOR,
                                  json={"label": "Fixture", "expected_revision": 0, "request_id": "invite"})
    assert invite_response.status_code == 200
    body = invite_response.json()
    token = body["join_url"].split("#invite=")[1]
    assert "token" not in body and "?" not in body["join_url"]
    assert invite_response.headers["cache-control"] == "no-store"
    snapshot = client.get("/api/production/greenroom", headers=OPERATOR)
    assert token not in snapshot.text
    response = client.post("/guest/join", headers=ORIGIN, json={"invite_token": token, "name": "Fixture guest", "session_token": "a" * 64})
    assert response.status_code == 200
    guest_headers = ORIGIN | {"authorization": "Bearer " + "a" * 64}
    assert client.get("/api/production/greenroom", headers=guest_headers).status_code == 403
    assert client.get("/api/production/greenroom/activity", headers=guest_headers).status_code == 403
    assert client.post("/api/production/greenroom/invites", headers=guest_headers,
                       json={"expected_revision": service.snapshot()["revision"], "request_id": "forged"}).status_code == 403
    assert client.post("/guest/join", headers=ORIGIN,
                       json={"invite_token": token, "name": "Fixture guest", "session_token": "a" * 64, "role": "producer"}).status_code == 422


def test_http_foreign_origin_cannot_join_or_control(fixture):
    service, _, _, _, client = fixture
    invitation = service.create_invite()
    assert client.post("/guest/join", headers={"origin": "https://untrusted.invalid"},
                       json={"invite_token": invitation["token"], "name": "Fixture", "session_token": "a" * 64}).status_code == 403
    assert service.snapshot()["invites"][0]["status"] == "ready"
    assert client.get("/api/production/greenroom", headers=OPERATOR | {"origin": "https://untrusted.invalid"}).status_code == 403


def test_program_audio_is_same_origin_producer_only_and_in_snapshot(fixture):
    service, _, _, _, client = fixture
    _, joined, token = join(fixture)
    participant = service.authenticate(token)
    path = f"/api/production/greenroom/participants/{participant['id']}"
    body = {"action": "program_audio", "microphone_muted": True, "screen_muted": False,
            "expected_revision": service.snapshot()["revision"], "request_id": "mute"}
    for headers in (ORIGIN | {"authorization": "Bearer " + token}, OPERATOR | {"origin": "https://untrusted.invalid"}):
        assert client.post(path, headers=headers, json=body).status_code == 403
    response = client.post(path, headers=OPERATOR, json=body)
    assert response.status_code == 200
    assert client.post(path, headers=OPERATOR, json=body).json() == response.json()
    flags = {"microphone_muted": True, "screen_muted": False}
    assert response.json()["program_audio"] == flags
    current = client.get("/api/production/greenroom", headers=OPERATOR).json()["participants"][0]
    assert current["program_audio"] == flags and current["state"] == "waiting"
    assert current["media"] == EMPTY_MEDIA


@pytest.mark.parametrize("change", [
    {"microphone_muted": None}, {"screen_muted": 1}, {"screen_muted": "false"},
    {"extra": True}, {"program_audio": {"microphone_muted": True, "screen_muted": False}},
    {"action": "admit"}, {"action": "remove"},
])
def test_program_audio_http_schema_rejects_coercion_extra_or_wrong_action(fixture, change):
    service, _, _, _, client = fixture
    _, _, token = join(fixture)
    participant = service.authenticate(token)
    body = {"action": "program_audio", "microphone_muted": True, "screen_muted": False,
            "expected_revision": service.snapshot()["revision"], "request_id": "invalid"}
    response = client.post(f"/api/production/greenroom/participants/{participant['id']}", headers=OPERATOR, json=body | change)
    assert response.status_code == 422
    assert not any(service.authenticate(token)["program_audio"].values())


@pytest.mark.parametrize("missing", ["microphone_muted", "screen_muted", "expected_revision", "request_id"])
def test_program_audio_http_requires_both_flags_and_preconditions(fixture, missing):
    service, _, _, _, client = fixture
    _, _, token = join(fixture)
    participant = service.authenticate(token)
    body = {"action": "program_audio", "microphone_muted": True, "screen_muted": False,
            "expected_revision": service.snapshot()["revision"], "request_id": "invalid"}
    del body[missing]
    assert client.post(f"/api/production/greenroom/participants/{participant['id']}", headers=OPERATOR, json=body).status_code == 422


@pytest.mark.parametrize("message", [
    {"type": "program_audio", "microphone_muted": False, "screen_muted": False},
    {"type": "media", "media": EMPTY_MEDIA | {"program_audio": {"microphone_muted": False, "screen_muted": False}}},
])
def test_guest_socket_cannot_override_program_audio(fixture, message):
    service, _, _, _, client = fixture
    _, _, token = join(fixture)
    participant = service.authenticate(token)
    service.moderate(participant["id"], "program_audio", microphone_muted=True, screen_muted=True)
    with socket(client, "guest", token) as (guest, _):
        guest.send_json(message)
        assert_closed(guest)
    assert all(service.authenticate(token)["program_audio"].values())


@pytest.mark.parametrize("role", ["guest", "producer", "output"])
def test_websocket_foreign_origin_is_rejected_before_acceptance(fixture, role):
    *_, client = fixture
    path = "/guest/ws" if role == "guest" else f"/api/production/greenroom/{role}-socket"
    with pytest.raises(WebSocketDisconnect) as failure:
        with client.websocket_connect(path, headers=OPERATOR | {"origin": "https://untrusted.invalid"}):
            pytest.fail("Foreign-origin socket accepted")
    assert failure.value.code == 1008


def test_guest_cannot_authenticate_as_operator_or_send_control_commands(fixture):
    _, _, _, _, client = fixture
    _, _, token = join(fixture)
    for role in ("producer", "output"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/production/greenroom/{role}-socket",
                                          headers=ORIGIN | {"authorization": "Bearer " + token}):
                pytest.fail("Guest gained operator socket")
    with socket(client, "guest", token) as (guest, _):
        guest.send_json({"type": "take", "source": "camera:2"})
        assert_closed(guest)


def test_guest_to_guest_signaling_is_forbidden(fixture):
    *_, client = fixture
    _, _, first = join(fixture, 1)
    _, _, second = join(fixture, 2)
    with socket(client, "guest", first) as (guest_a, _), socket(client, "guest", second) as (guest_b, hello_b):
        guest_a.send_json({"type": "signal", "to": hello_b["peer_id"], "kind": "offer", "data": {"type": "offer", "sdp": SDP}})
        assert_closed(guest_a)
        guest_b.send_json({"type": "heartbeat"})
        assert next_type(guest_b, "state")["participant"]["state"] == "waiting"


def test_waiting_guest_cannot_signal_to_output_even_if_switcher_references_it(fixture):
    service, hub, state, _, client = fixture
    _, participant, token = join(fixture)
    state["preview_sources"] = [participant["sources"]["camera"]]
    with socket(client, "output") as (output, output_hello), socket(client, "guest", token) as (guest, _):
        guest.send_json({"type": "media", "media": EMPTY_MEDIA | {"camera": True}})
        assert next_type(output, "state")["subscriptions"] == []
        guest.send_json({"type": "signal", "to": output_hello["peer_id"], "kind": "offer", "data": {"type": "offer", "sdp": SDP}})
        assert_closed(guest)
        assert not hub.source_ready(participant["sources"]["camera"])
        assert service.snapshot()["participants"][0]["state"] == "waiting"


def test_admitted_guest_offer_reaches_only_authorized_output(fixture):
    service, _, state, _, client = fixture
    _, participant, token = join(fixture)
    service.moderate(participant["id"], "admit")
    state["preview_sources"] = [participant["sources"]["camera"]]
    with socket(client, "output") as (output, output_hello), socket(client, "guest", token) as (guest, _):
        guest.send_json({"type": "media", "media": EMPTY_MEDIA | {"camera": True}})
        guest.send_json({"type": "signal", "to": output_hello["peer_id"], "kind": "offer", "data": {"type": "offer", "sdp": SDP}})
        forwarded = next_type(output, "signal")
        assert forwarded["participant_id"] == participant["id"]
        assert forwarded["data"] == {"type": "offer", "sdp": SDP}
        assert "token" not in json.dumps(forwarded)


def test_output_ready_requires_admission_subscription_and_current_media(fixture):
    service, hub, state, _, _ = fixture
    _, participant, _ = join(fixture)
    source = participant["sources"]["camera"]
    service.set_connected(participant["id"], True)
    service.update_media(participant["id"], EMPTY_MEDIA | {"camera": True})
    output = Peer(None, "output")
    hub.peers["fixture-output"] = output
    try:
        state["preview_sources"] = [source]
        output.subscriptions = hub._allowed_sources(output, hub._snapshot())
        asyncio.run(hub._message("fixture-output", output, {"type": "ready", "sources": [source]}))
        assert not hub.source_ready(source)
        service.moderate(participant["id"], "admit")
        output.subscriptions = hub._allowed_sources(output, hub._snapshot())
        asyncio.run(hub._message("fixture-output", output, {"type": "ready", "sources": [source]}))
        assert hub.source_ready(source)
        output.ready[source] -= 7
        assert not hub.source_ready(source)
        service.set_connected(participant["id"], False)
        asyncio.run(hub._message("fixture-output", output, {"type": "ready", "sources": [source]}))
        assert not hub.source_ready(source)
    finally:
        hub.peers.pop("fixture-output")


def test_consumed_invite_revocation_closes_guest_and_clears_selected_sources(fixture):
    service, _, _, removed, client = fixture
    invite, participant, token = join(fixture)
    with socket(client, "guest", token) as (guest, _):
        revision = service.snapshot()["revision"]
        response = client.post(f"/api/production/greenroom/invites/{invite['invite_id']}/revoke", headers=OPERATOR,
                               json={"expected_revision": revision, "request_id": "revoke"})
        assert response.status_code == 200
        assert participant["id"] in removed
        assert_closed(guest, 1000)
        with pytest.raises(GreenroomError):
            service.authenticate(token)


def test_oversized_socket_message_is_closed(fixture):
    *_, client = fixture
    _, _, token = join(fixture)
    with socket(client, "guest", token) as (guest, _):
        guest.send_text(json.dumps({"type": "heartbeat", "padding": "x" * 65536}))
        assert_closed(guest)


def test_binary_socket_message_is_rejected_without_protocol_exception(fixture):
    *_, client = fixture
    _, _, token = join(fixture)
    with socket(client, "guest", token) as (guest, _):
        guest.send_bytes(b"not a signaling text frame")
        assert_closed(guest)


def test_pending_guest_handshakes_are_bounded_before_accept(fixture):
    _, hub, _, _, client = fixture
    hub._pending_guests = 24
    try:
        with pytest.raises(WebSocketDisconnect) as failure:
            with client.websocket_connect("/guest/ws", headers=ORIGIN):
                pytest.fail("Pending guest limit was exceeded")
        assert failure.value.code == 1013
    finally:
        hub._pending_guests = 0


def test_renderer_receipt_is_distinct_and_matches_current_generation(fixture):
    service, hub, state, _, _ = fixture
    state["generation"] = 3
    output = Peer(None, "output")
    asyncio.run(hub._message("fixture", output, {"type": "rendered", "generation": 2}))
    assert service.history()["events"] == []
    asyncio.run(hub._message("fixture", output, {"type": "rendered", "generation": 3}))
    assert service.history()["events"] == [], "a bare receipt has no fresh playback evidence"
    asyncio.run(hub._message("fixture", output, {"type": "ready", "sources": [], "playback": {
        "generation": 3, "audio_blocked": False, "rendered": True}}))
    asyncio.run(hub._message("fixture", output, {"type": "rendered", "generation": 3}))
    asyncio.run(hub._message("fixture", output, {"type": "rendered", "generation": 3}))
    events = service.history()["events"]
    assert len(events) == 1 and events[0]["outcome"] == "confirmed"
    assert events[0]["actor_kind"] == "program_renderer" and not events[0]["identity_verified"]
    assert output.rendered_generation == 3


@pytest.mark.parametrize("condition", ["expired", "other_generation", "blocked", "pending", "other_peer"])
def test_renderer_receipt_cannot_create_confirmed_history_without_current_peer_health(fixture, condition):
    service, hub, state, _, _ = fixture
    state["generation"] = 3
    output = Peer(None, "output")
    asyncio.run(hub._message("fixture", output, {"type": "ready", "sources": [], "playback": {
        "generation": 3, "audio_blocked": condition == "blocked", "rendered": condition not in {"blocked", "pending"}}}))
    if condition == "expired":
        output.playback_reported_at -= 7
    elif condition == "other_generation":
        output.playback_generation = 2
    elif condition == "other_peer":
        output = Peer(None, "output")
    asyncio.run(hub._message("fixture", output, {"type": "rendered", "generation": 3}))
    assert service.history()["events"] == []
    assert output.rendered_generation == -1


def test_output_confirmation_requires_fresh_same_peer_generation_playback(fixture):
    _, hub, state, _, _ = fixture
    state["generation"] = 3
    first, second = Peer(None, "output"), Peer(None, "output")
    hub.peers.update({"first": first, "second": second})
    def playback(peer, *, generation=3, blocked=False, rendered=True):
        asyncio.run(hub._message("fixture", peer, {"type": "ready", "sources": [], "playback": {
            "generation": generation, "audio_blocked": blocked, "rendered": rendered}}))
    def receipt(peer):
        asyncio.run(hub._message("fixture", peer, {"type": "rendered", "generation": 3}))
    try:
        playback(first, blocked=True, rendered=False)
        receipt(first)
        assert first.rendered_generation == -1
        assert hub.output_status()["audio_blocked"]
        playback(first)
        receipt(first)
        assert hub.output_status()["rendered_generation"] == 3
        playback(first, blocked=True, rendered=False)
        playback(second)
        assert hub.output_status()["rendered_generation"] == -1, "another peer cannot borrow the earlier receipt"
        receipt(second)
        assert hub.output_status()["rendered_generation"] == 3
        assert hub.output_status()["audio_blocked"], "one healthy renderer cannot conceal another blocked output"
        second.playback_reported_at -= 7
        assert hub.output_status()["rendered_generation"] == -1
        playback(first, generation=2)
        assert first.audio_blocked, "stale-generation health cannot clear the current blocker"
        state["generation"] = 4
        assert not hub.output_status()["audio_blocked"]
        assert hub.output_status()["rendered_generation"] == -1
    finally:
        hub.peers.clear()


@pytest.mark.parametrize("playback", [None, {}, {"generation": True, "audio_blocked": False, "rendered": True},
    {"generation": -1, "audio_blocked": False, "rendered": True},
    {"generation": 0, "audio_blocked": "false", "rendered": True},
    {"generation": 0, "audio_blocked": True, "rendered": True},
    {"generation": 0, "audio_blocked": False, "rendered": 1},
    {"generation": 0, "audio_blocked": False, "rendered": True, "extra": "untrusted"}])
def test_output_playback_reports_are_strict_and_bounded(fixture, playback):
    _, hub, _, _, _ = fixture
    with pytest.raises(ValueError, match="invalid_playback_state"):
        asyncio.run(hub._message("fixture", Peer(None, "output"), {"type": "ready", "sources": [], "playback": playback}))


@pytest.mark.parametrize("description", [None, {}, {"type": "offer", "sdp": ""}, {"type": "offer", "sdp": "not SDP"},
                                         {"type": "offer", "sdp": "v=0\r\n" + "x" * 50000},
                                         {"type": "answer", "sdp": SDP}, {"type": "offer", "sdp": SDP, "role": "owner"}])
def test_malformed_or_oversized_descriptions_are_rejected(description):
    with pytest.raises(ValueError):
        GreenroomHub._signal(description, "offer")


@pytest.mark.parametrize("candidate", [
    {"candidate": "x" * 2049}, {"candidate": "fixture", "sdpMid": "x" * 17},
    {"candidate": "fixture", "sdpMLineIndex": True}, {"candidate": "fixture", "sdpMLineIndex": 5},
    {"candidate": "fixture", "usernameFragment": "x" * 257}, {"candidate": "fixture", "unexpected": "value"},
])
def test_unbounded_or_coerced_ice_fields_are_rejected(candidate):
    with pytest.raises(ValueError):
        GreenroomHub._signal(candidate, "ice")


@pytest.mark.parametrize("kind", [None, [], {}, True, 7, "arbitrary"])
def test_signal_kind_must_be_known_string(kind):
    with pytest.raises(ValueError):
        GreenroomHub._signal({"candidate": ""}, kind)


@pytest.mark.parametrize("target", [[], {}, 7, True, "x" * 1000])
def test_signal_peer_ids_must_be_bounded_strings(fixture, target):
    _, hub, _, _, _ = fixture
    peer = Peer(None, "producer")
    with pytest.raises(ValueError):
        asyncio.run(hub._message("producer", peer, {"type": "signal", "to": target, "kind": "ice", "data": {"candidate": ""}}))


def test_one_output_must_receive_the_entire_guest_composition(fixture):
    import time
    _, hub, _, _, _ = fixture
    camera = 'guest:' + 'a' * 32 + ':camera'
    screen = 'guest:' + 'b' * 32 + ':screen'
    first = Peer(socket=None, role='output')
    second = Peer(socket=None, role='output')
    first.ready = {camera: time.monotonic()}
    second.ready = {screen: time.monotonic()}
    hub.peers = {'one': first, 'two': second}
    assert set(hub.output_status()['ready_sources']) == {camera, screen}
    assert not hub.composition_ready([camera, screen])
    first.ready[screen] = time.monotonic()
    assert hub.composition_ready([camera, screen])
    first.ready[screen] -= 7
    assert not hub.composition_ready([camera, screen])
    assert hub.composition_ready(['camera:1'])
    hub.peers.clear()


@pytest.mark.parametrize("name", ["guest_microphone.js", "guest_audio_dsp.js", "studio_noise_gate.js", "studio_noise_gate.worklet.js"])
def test_guest_noise_gate_assets_are_explicitly_served(fixture, name):
    _, _, _, _, client = fixture
    response = client.get("/guest/assets/" + name)
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert client.get("/guest/assets/server.py").status_code == 404
