"""Isolated backstage/private chat contracts; no devices, ingress or live rooms."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.greenroom_service import GreenroomError, GreenroomService
from rareiq.web.greenroom import GreenroomHub, PUBLIC_GUEST_PATHS
from rareiq.web.shared_scene_access import VerifiedPrincipal


ORIGIN = {"origin": "http://testserver"}
OPERATOR = ORIGIN | {"x-test-producer": "yes"}


@pytest.fixture
def room(tmp_path):
    now = [10000.0]
    service = GreenroomService(tmp_path / "room.sqlite3", clock=lambda: now[0])
    return service, now


def join(service, number=1):
    invite = service.create_invite()
    token = f"{number:064x}"
    person = service.join(invite["token"], f"Guest {number}", token)
    return invite, person, token


def guest_send(service, token, *, channel="room", text="Hello", request_id="message", room_id=None):
    return service.send_guest_chat(token, channel, text, request_id, room_id or service.snapshot()["room_id"])


def producer_send(service, *, channel="room", participant_id=None, text="Producer hello", request_id="producer-message", **kwargs):
    return service.send_producer_chat(channel, text, request_id, service.snapshot()["room_id"], participant_id=participant_id, **kwargs)


def test_room_shared_private_isolated_and_no_revision_or_activity_leak(room):
    service, _ = room
    _, a, token_a = join(service)
    _, b, token_b = join(service, 2)
    before, history = service.snapshot(), service.history()
    shared = guest_send(service, token_a, text="Everyone backstage")
    private = guest_send(service, token_a, channel="private", request_id="private", text="Only production A")
    producer = producer_send(service, channel="private", participant_id=b["id"], text="Only guest B")
    assert service.guest_chat(token_b)["messages"] == [shared["message"]]
    assert service.guest_chat(token_a, "private")["messages"] == [private["message"]]
    assert service.guest_chat(token_b, "private")["messages"] == [producer["message"]]
    assert service.producer_chat("private", participant_id=a["id"])["messages"] == [private["message"]]
    assert shared["message"]["author_name"] == "Guest 1"
    assert shared["message"]["participant_id"] is None
    assert not shared["message"]["identity_verified"]
    assert producer["message"]["author_name"] == "Production team"
    assert not producer["message"]["identity_verified"]
    assert service.snapshot() == before and service.history() == history
    assert "Only production A" not in json.dumps(service.history())
    assert token_a not in json.dumps(shared)


@pytest.mark.parametrize("remove", ["leave", "remove", "revoke", "expire"])
def test_guest_permission_is_rechecked_even_for_idempotent_retries(room, remove):
    service, now = room
    invite, person, token = join(service)
    message = guest_send(service, token, channel="private")
    if remove == "leave":
        service.leave(person["id"])
    elif remove == "remove":
        service.moderate(person["id"], "remove")
    elif remove == "revoke":
        service.revoke_invite(invite["invite_id"])
    else:
        now[0] += 12 * 3600
    for action in (lambda: service.guest_chat(token, "private"), lambda: guest_send(service, token, channel="private")):
        with pytest.raises(GreenroomError) as error:
            action()
        assert error.value.status == 401
    assert service.producer_chat("private", participant_id=person["id"])["messages"] == [message["message"]]
    with pytest.raises(GreenroomError) as error:
        producer_send(service, channel="private", participant_id=person["id"])
    assert error.value.status == 404


def test_closed_and_reopened_room_reject_stale_access_keep_local_history(room):
    service, _ = room
    _, person, token = join(service)
    old = service.snapshot()["room_id"]
    guest_send(service, token, text="Historic local message")
    service.close_room()
    with pytest.raises(GreenroomError, match="room_closed"):
        service.producer_chat()
    service.open_room()
    assert service.producer_chat()["messages"] == []
    with pytest.raises(GreenroomError, match="chat_room_conflict"):
        guest_send(service, token, room_id=old)
    with pytest.raises(GreenroomError, match="invalid_guest_session"):
        service.guest_chat(token)
    with pytest.raises(GreenroomError, match="guest_unavailable"):
        service.producer_chat("private", participant_id=person["id"])
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT text FROM greenroom_chat WHERE room_id=?", (old,)).fetchone()[0] == "Historic local message"


def test_idempotency_concurrency_fingerprints_and_restart(room):
    service, now = room
    _, _, token = join(service)
    # Separate service objects exercise the SQLite transaction, not just one lock.
    other = GreenroomService(service.path, clock=lambda: now[0], reset_runtime=False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda index: guest_send(service if index % 2 else other, token), range(16)))
    assert all(result == results[0] for result in results)
    assert len(other.guest_chat(token)["messages"]) == 1
    with pytest.raises(GreenroomError, match="chat_request_conflict"):
        guest_send(service, token, text="Different payload")
    with pytest.raises(GreenroomError, match="chat_request_conflict"):
        guest_send(service, token, channel="private")
    assert other.snapshot()["revision"] == service.snapshot()["revision"]


def test_rate_limit_shared_across_channels_retries_do_not_count_and_reads_bounded(room):
    service, now = room
    _, _, token = join(service)
    for index in range(20):
        guest_send(service, token, channel="private" if index % 2 else "room", request_id=f"message-{index}")
    guest_send(service, token, request_id="message-0")
    with pytest.raises(GreenroomError) as error:
        guest_send(service, token, request_id="over-limit")
    assert error.value.status == 429 and error.value.reason == "chat_rate_limited"
    for index in range(105):
        now[0] += 61
        guest_send(service, token, request_id=f"history-{index}")
    result = service.guest_chat(token)
    ids = [message["id"] for message in result["messages"]]
    assert len(ids) == 100 and ids == sorted(ids) and result["latest_id"] == ids[-1]
    with sqlite3.connect(service.path) as db:
        assert db.execute("SELECT COUNT(*) FROM greenroom_chat").fetchone()[0] == 125
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM greenroom_chat")


@pytest.mark.parametrize("text", ["", "  \n\t ", "x" * 1001, "a\x00b", "a\rb", "a\x7fb", "a\x85b", "a\ud800b", None, 12])
def test_invalid_text_rejected_without_mutation(room, text):
    service, _ = room
    _, _, token = join(service)
    with pytest.raises(GreenroomError, match="invalid_chat_text"):
        guest_send(service, token, text=text)
    assert service.guest_chat(token)["messages"] == []


def test_plain_text_markup_unicode_tabs_and_newlines_are_data(room):
    service, _ = room
    _, _, token = join(service)
    text = '<script>alert("test")</script>\n\tHello 👋'
    assert guest_send(service, token, text=text)["message"]["text"] == text
    assert len(guest_send(service, token, text="x" * 1000, request_id="maximum")["message"]["text"]) == 1000
    verified = producer_send(service, principal=VerifiedPrincipal("fixture", "studio", "private-subject"))["message"]
    assert verified["identity_verified"] and verified["author_name"] == "Production team"
    assert "private-subject" not in json.dumps(verified)
    for invalid in (None, "", "a", 123):
        with pytest.raises(GreenroomError):
            service.guest_chat(invalid)


@pytest.fixture
def client(room):
    service, _ = room
    hub = GreenroomHub(service, authorize_operator=lambda request: request.headers.get("x-test-producer") == "yes",
                       switcher=lambda: {"generation": 0}, static_dir=Path(__file__).parents[1] / "rareiq/web/static")
    app = FastAPI()
    app.include_router(hub.router)
    with TestClient(app) as connected:
        yield connected


def body(service, **changes):
    return {"room_id": service.snapshot()["room_id"], "channel": "room", "text": "HTTP chat", "request_id": "http-message"} | changes


def test_http_guest_auth_producer_authority_and_spoof_rejection(room, client):
    service, _ = room
    _, person, token = join(service)
    headers = ORIGIN | {"authorization": "Bearer " + token}
    for method in ("get", "post"):
        request = client.get if method == "get" else client.post
        kwargs = {} if method == "get" else {"json": body(service)}
        assert request("/guest/chat", **kwargs).status_code == 401
        assert request("/api/production/greenroom/chat", headers=headers, **kwargs).status_code == 403
        assert request("/guest/chat", headers=headers | {"origin": "https://untrusted.invalid"}, **kwargs).status_code == 403
        assert request("/api/production/greenroom/chat", headers=OPERATOR | {"origin": "https://untrusted.invalid"}, **kwargs).status_code == 403
    for extra in ({"participant_id": person["id"]}, {"author_name": "Producer"}, {"author_kind": "producer"}, {"identity_verified": True}):
        assert client.post("/guest/chat", headers=headers, json=body(service, **extra)).status_code == 422
    assert client.get("/guest/chat", headers=headers, params={"channel": "private", "participant_id": person["id"]}).status_code == 400
    response = client.post("/guest/chat", headers=headers, json=body(service, channel="private"))
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    result = client.get("/api/production/greenroom/chat", headers=OPERATOR, params={"channel": "private", "participant_id": person["id"]})
    assert result.status_code == 200 and result.json()["messages"] == [response.json()["message"]]
    assert result.headers["cache-control"] == "no-store"
    reply = client.post("/api/production/greenroom/chat", headers=OPERATOR, json=body(service, channel="private", participant_id=person["id"], text="Reply"))
    assert reply.status_code == 200
    assert client.get("/guest/chat", headers=headers, params={"channel": "private"}).json()["messages"][-1] == reply.json()["message"]
    assert client.get("/guest/chat", headers=headers).json()["messages"] == []
    assert "/guest/chat" in PUBLIC_GUEST_PATHS
    assert {"/guest/assets/greenroom_chat.js", "/guest/assets/greenroom_chat.css"} <= PUBLIC_GUEST_PATHS


@pytest.mark.parametrize("change", [{"room_id": None}, {"channel": "public"}, {"text": 1}, {"request_id": "bad id"}, {"text": "x" * 1001}])
def test_http_required_strict_schema(room, client, change):
    service, _ = room
    _, _, token = join(service)
    assert client.post("/guest/chat", headers=ORIGIN | {"authorization": "Bearer " + token}, json=body(service, **change)).status_code == 422


def test_chat_does_not_invalidate_prepared_producer_action(room):
    service, _ = room
    _, person, token = join(service)
    revision = service.snapshot()["revision"]
    guest_send(service, token)
    producer_send(service)
    assert service.moderate(person["id"], "admit", expected_revision=revision, request_id="prepared-admit")["ok"]
