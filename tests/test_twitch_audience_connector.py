"""All provider traffic is fake; importing/running this suite uses no credentials."""
import asyncio
from datetime import datetime, timezone
import json

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.audience_service import AudienceService
from rareiq.services.viewer_chat_service import ViewerChatService
from rareiq.services.twitch_audience_connector import TwitchAudienceConnector, _NoRedirectConnect, _ProviderError, _open_websocket
from rareiq.web.twitch_audience import create_twitch_audience_router
from rareiq.web.audience import create_audience_router


NOW = 1800000000.0
CREDENTIALS = {"client_id": "fixture-client", "channel_login": "fixture_channel", "user_access_token": "fixture-private-token"}


def frame(kind, payload, *, now=NOW, message_id="delivery-1", **metadata):
    return json.dumps({"metadata": {"message_id": message_id, "message_type": kind,
        "message_timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"), **metadata}, "payload": payload})


def welcome(session="session-1"):
    return frame("session_welcome", {"session": {"id": session, "status": "connected", "keepalive_timeout_seconds": 10}})


def notification(*, session="session-1", subscription="sub-1", event_id="chat-1", now=NOW):
    return frame("notification", {"subscription": {"id": subscription, "type": "channel.chat.message", "version": "1", "status": "enabled",
        "condition": {"broadcaster_user_id": "123", "user_id": "123"}, "transport": {"method": "websocket", "session_id": session}},
        "event": {"broadcaster_user_id": "123", "chatter_user_id": "456", "chatter_user_name": "FixtureViewer", "message_id": event_id,
                  "message": {"text": "PRIVATE-CHAT-MUST-NOT-BE-RETAINED"}}},
        now=now, subscription_type="channel.chat.message", subscription_version="1")


class FakeSocket:
    def __init__(self, first=None):
        self.queue = asyncio.Queue()
        if first is not None:
            self.queue.put_nowait(first)
        self.closed = False

    async def recv(self):
        value = await self.queue.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        self.closed = True


class Fixture:
    def __init__(self, tmp_path):
        self.now = NOW
        self.audience = AudienceService(tmp_path / "audience.sqlite3", clock=lambda: self.now)
        self.audience.status()
        self.audience.configure(action="save_rule", data={"id": "welcome", "name": "Welcome", "enabled": True, "platform": "twitch", "event": "first_chat",
            "message": "Hello {name}", "animation": "slide", "duration_ms": 3000, "cooldown_seconds": 60}, expected_revision=0, request_id="rule", actor_kind="local_operator")
        self.audience.configure(action="settings", data={"enabled": True}, expected_revision=1, request_id="arm", actor_kind="local_operator")
        self.validation = {"client_id": "fixture-client", "login": "fixture_channel", "user_id": "123", "scopes": ["user:read:chat"], "expires_in": 7200}
        self.calls, self.sockets, self.urls = [], [], []
        self.http_status, self.extra_response, self.reads = None, None, 0
        self.factory_first = None
        self.service = TwitchAudienceConnector(self.audience, self.credentials,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)),
            websocket_factory=self.ws, clock=lambda: self.now)

    def credentials(self):
        self.reads += 1
        return dict(CREDENTIALS)

    async def http(self, request):
        self.calls.append((request.method, str(request.url), json.loads(request.content) if request.content else None))
        if self.http_status:
            return httpx.Response(self.http_status, json={"message": "fixture-private-provider-error"})
        if request.method == "GET":
            return httpx.Response(200, json=self.validation)
        if request.method == "POST":
            body = json.loads(request.content)
            body.update(id="sub-" + str(sum(c[0] == "POST" for c in self.calls)), status="enabled")
            return httpx.Response(202, json=self.extra_response or {"data": [body]})
        return httpx.Response(204)

    async def ws(self, url):
        self.urls.append(url)
        socket = FakeSocket(self.factory_first or welcome("session-" + str(len(self.sockets) + 1)))
        self.sockets.append(socket)
        return socket


async def spin_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.002)
    raise AssertionError("fixture condition not reached")


def test_default_is_disconnected_and_does_not_read_credentials(tmp_path):
    f = Fixture(tmp_path)
    state = f.service.cached_status()
    assert state["state"] == "not_connected" and not state["authorized"] and not state["verified"]
    assert state["available_events"] == [] and state["viewer_join_supported"] is False
    assert not f.calls and not f.urls and f.reads == 0


def test_keepalive_deadline_allows_bounded_jitter_without_reconnecting(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        assert f.service.KEEPALIVE_GRACE_SECONDS == 2
        await f.service.connect()
        # Use short fixture intervals: arrival misses the advertised deadline
        # while staying comfortably within the same bounded grace calculation.
        f.service._keepalive = .06
        f.service.KEEPALIVE_GRACE_SECONDS = .14
        async def delayed():
            await asyncio.sleep(.1)
            f.sockets[0].queue.put_nowait(notification())
        sending = asyncio.create_task(delayed())
        await spin_until(lambda: f.service.cached_status()["received"] == 1)
        await sending
        assert len(f.sockets) == 1 and f.service.cached_status()["connected"]
        assert "last_receive_failure" not in f.service.cached_status()
        await f.service.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("healthy", ["keepalive", "notification"])
def test_validated_healthy_frames_reset_consecutive_reconnect_budget(tmp_path, healthy):
    async def scenario():
        f = Fixture(tmp_path)
        delays = []
        async def sleep(seconds):
            delays.append(seconds)
        original_ws = f.ws
        async def ws(url):
            socket = await original_ws(url)
            if len(f.sockets) > 1:
                count = str(len(f.sockets))
                socket.queue.put_nowait(frame("session_keepalive", {}) if healthy == "keepalive" else notification(
                    session="session-" + count, subscription="sub-" + count, event_id="chat-" + count))
            if len(f.sockets) <= 4:
                socket.queue.put_nowait(ConnectionClosedError(Close(4005, "private provider reason"), None))
            return socket
        f.service._sleep, f.service._websocket_factory = sleep, ws
        await f.service.connect()
        await spin_until(lambda: len(f.sockets) >= 5 or f.service.cached_status()["state"] == "not_connected")
        assert len(f.sockets) == 5 and f.service.cached_status()["connected"]
        assert delays == [.5, .5, .5, .5]
        assert "private" not in json.dumps(f.service.cached_status())
        await f.service.disconnect()
    asyncio.run(scenario())


def test_consecutive_receive_failures_remain_bounded_even_when_welcome_succeeds(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        delays = []
        async def sleep(seconds):
            delays.append(seconds)
        original_ws = f.ws
        async def ws(url):
            socket = await original_ws(url)
            socket.queue.put_nowait(ConnectionClosedError(Close(4002, "private received reason"),
                                                         Close(1000, "private sent reason"), True))
            return socket
        f.service._sleep, f.service._websocket_factory = sleep, ws
        await f.service.connect()
        await spin_until(lambda: f.service.cached_status()["state"] == "not_connected")
        status = f.service.cached_status()
        assert len(f.sockets) == 4 and delays == [.5, 1, 1.5]
        assert status["reason"] == "connection_lost" and status["received"] == status["rejected"] == 0
        assert status["last_receive_failure"] == {"kind": "closed", "received_close_code": 4002, "sent_close_code": 1000}
        assert "private" not in json.dumps(status) and f.service._token is None
        await f.service.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure,expected", [
    (TimeoutError("private timeout URL"), {"kind": "timeout", "received_close_code": None, "sent_close_code": None}),
    (RuntimeError("wss://private.example/private-token"), {"kind": "transport", "received_close_code": None, "sent_close_code": None}),
    (ConnectionClosedError(Close(4001, "private received reason"), Close(1001, "private sent reason"), True),
        {"kind": "closed", "received_close_code": 4001, "sent_close_code": 1001}),
    (ConnectionClosedError(Close(999, "private received reason"), Close(5000, "private sent reason"), True),
        {"kind": "closed", "received_close_code": None, "sent_close_code": None}),
    (ConnectionClosedError(None, None), {"kind": "closed", "received_close_code": None, "sent_close_code": None}),
])
def test_receive_diagnostics_are_constant_bounded_and_never_echo_exception_details(tmp_path, failure, expected):
    async def scenario():
        f = Fixture(tmp_path)
        async def sleep(seconds):
            pass
        original_ws = f.ws
        async def ws(url):
            socket = await original_ws(url)
            if len(f.sockets) == 1:
                socket.queue.put_nowait(failure)
            return socket
        f.service._sleep, f.service._websocket_factory = sleep, ws
        await f.service.connect()
        await spin_until(lambda: len(f.sockets) == 2)
        status = f.service.cached_status()
        assert status["last_receive_failure"] == expected and status["connected"]
        assert "private" not in json.dumps(status) and "wss://" not in json.dumps(status)
        status["last_receive_failure"]["kind"] = "private changed value"
        assert f.service.cached_status()["last_receive_failure"] == expected
        await f.service.disconnect()
    asyncio.run(scenario())


def test_invalid_provider_frame_never_restores_connection_or_weakens_fail_closed(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        async def sleep(seconds):
            pass
        original_ws = f.ws
        async def ws(url):
            socket = await original_ws(url)
            if len(f.sockets) == 1:
                socket.queue.put_nowait(ConnectionClosedError(Close(4005, "private reason"), None))
            else:
                socket.queue.put_nowait(notification(subscription="unowned"))
            return socket
        f.service._sleep, f.service._websocket_factory = sleep, ws
        await f.service.connect()
        await spin_until(lambda: f.service.cached_status()["state"] == "not_connected")
        status = f.service.cached_status()
        assert len(f.sockets) == 2 and status["reason"] == "unexpected_subscription_event"
        assert status["rejected"] == 1 and status["last_receive_failure"]["kind"] == "closed"
        assert not status["authorized"] and f.service._token is None
        await f.service.disconnect()
    asyncio.run(scenario())


def test_open_transport_still_disables_client_pings_and_payload_logging(monkeypatch):
    async def scenario():
        import rareiq.services.twitch_audience_connector as module
        calls = []
        async def opening(url, **options):
            calls.append(options)
            return FakeSocket()
        monkeypatch.setattr(module, "_NoRedirectConnect", opening)
        await _open_websocket(module.TwitchAudienceConnector.SOCKET_URL)
        assert calls[0]["ping_interval"] is None
        assert calls[0]["logger"].disabled is True and calls[0]["compression"] is None
        assert calls[0]["max_size"] == 65536
    asyncio.run(scenario())


def test_opted_in_transcript_is_independent_of_alert_rejection_and_deduplicates(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        transcript = ViewerChatService(clock=lambda: f.now)
        f.service._transcript_sink = transcript.accept
        await f.service.connect()
        f.audience.accept = lambda event: {"ok": False, "reason": "audience_event_capacity"}
        f.service._handle(notification(event_id="before-opt-in"))
        assert transcript.status()["messages"] == []
        transcript.set_listening(True)
        f.service._handle(notification())
        f.service._handle(notification())
        assert len(transcript.status()["messages"]) == 1
        assert transcript.status()["messages"][0]["text"] == "PRIVATE-CHAT-MUST-NOT-BE-RETAINED"
        assert f.service.cached_status()["connected"]
        assert b"PRIVATE-CHAT" not in f.audience.path.read_bytes()
        await f.service.disconnect()
    asyncio.run(scenario())


def test_transcript_never_receives_unbound_messages_and_sink_failures_do_not_disconnect(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        calls = []
        def sink(message):
            calls.append(message)
            raise RuntimeError("private sink fault")
        f.service._transcript_sink = sink
        await f.service.connect()
        with pytest.raises(_ProviderError):
            f.service._handle(notification(subscription="unowned"))
        assert calls == []
        f.service._handle(notification())
        assert len(calls) == 1 and f.service.cached_status()["connected"]
        malformed = json.loads(notification(event_id="malformed-text"))
        malformed["payload"]["event"]["message"]["text"] = "bad\x00text"
        f.service._handle(json.dumps(malformed))
        assert len(calls) == 1 and f.service.cached_status()["connected"]
        await f.service.disconnect()
    asyncio.run(scenario())


def test_explicit_connect_receives_first_chat_once_without_message_body_or_token(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        state = await f.service.connect()
        assert state["connected"] and state["available_events"] == ["first_chat", "featured_chat"]
        assert (await f.service.connect())["connected"] and f.reads == 1
        f.sockets[0].queue.put_nowait(notification())
        f.sockets[0].queue.put_nowait(notification())
        await spin_until(lambda: f.service.cached_status()["received"] == 1)
        assert f.audience.output()["graphic"]["title"] == "Hello FixtureViewer"
        assert f.audience.status()["queued"] == 1
        public = json.dumps(f.service.cached_status()) + (tmp_path / "audience.sqlite3").read_bytes().decode("latin1")
        assert "PRIVATE-CHAT" not in public and "fixture-private-token" not in public
        assert "fixture_channel" not in json.dumps(f.service.cached_status())
        await f.service.disconnect()
        assert f.sockets[0].closed and f.service._token is None
        assert [url for method, url, _ in f.calls if method == "DELETE"] == [f.service.SUBSCRIPTIONS_URL + "?id=sub-1"]
        assert f.service.cached_status()["state"] == "not_connected"
    asyncio.run(scenario())


@pytest.mark.parametrize("change,reason", [({"client_id": "other"}, "token_channel_or_client_mismatch"),
    ({"login": "other"}, "token_channel_or_client_mismatch"), ({"scopes": []}, "chat_scope_required"),
    ({"user_id": None}, "invalid_provider_payload"), ({"expires_in": 20}, "token_expiring")])
def test_invalid_authorization_never_opens_socket_or_subscribes(tmp_path, change, reason):
    async def scenario():
        f = Fixture(tmp_path)
        f.validation.update(change)
        state = await f.service.connect()
        assert not state["connected"] and state["reason"] == reason
        assert not f.urls and not any(c[0] == "POST" for c in f.calls)
        assert f.service._token is None
    asyncio.run(scenario())


@pytest.mark.parametrize("status,reason", [(401, "authorization_rejected"), (429, "provider_rate_limited"), (302, "provider_request_failed")])
def test_provider_failure_is_bounded_and_sanitized(tmp_path, status, reason):
    async def scenario():
        f = Fixture(tmp_path)
        f.http_status = status
        result = await f.service.connect()
        assert result["reason"] == reason and "private-provider" not in json.dumps(result)
        assert len(f.calls) == 1 and not f.urls
        assert (await f.service.connect())["reason"] == "connection_retry_limited"
    asyncio.run(scenario())


@pytest.mark.parametrize("path,value", [("event.broadcaster_user_id", "999"), ("event.source_broadcaster_user_id", "999"),
    ("subscription.id", "not-owned"), ("subscription.type", "channel.follow"), ("event.chatter_user_id", "x"),
    ("event.chatter_user_name", "x" * 81), ("event.message_id", "\nunsafe"), ("subscription.condition.user_id", "999")])
def test_wrong_channel_or_unexpected_payload_fails_closed(tmp_path, path, value):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        raw = json.loads(notification())
        target = raw["payload"]
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        f.sockets[0].queue.put_nowait(json.dumps(raw))
        await spin_until(lambda: f.service.cached_status()["state"] == "not_connected")
        await f.service.disconnect()
        assert f.audience.status()["participants"] == [] and f.service._token is None
    asyncio.run(scenario())


@pytest.mark.parametrize("raw", ["x" * 65537, b"binary", "[]", "{" + "[" * 1200,
    notification(now=NOW - 121), notification(now=NOW + 6), frame("new_unknown_type", {})],
    ids=["oversized", "binary", "array", "deep-json", "old", "future", "unknown"])
def test_oversize_malformed_old_future_unknown_events_are_rejected(tmp_path, raw):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.sockets[0].queue.put_nowait(raw)
        await spin_until(lambda: f.service.cached_status()["state"] == "not_connected")
        await f.service.disconnect()
        assert f.audience.status()["participants"] == []
    asyncio.run(scenario())


@pytest.mark.parametrize("url", ["ws://eventsub.wss.twitch.tv/ws", "wss://evil.example/ws", "wss://eventsub.wss.twitch.tv.evil/ws",
    "wss://user@eventsub.wss.twitch.tv/ws", "wss://eventsub.wss.twitch.tv:444/ws", "wss://eventsub.wss.twitch.tv/private",
    "wss://eventsub.wss.twitch.tv/ws#fragment", "wss://eventsub.wss.twitch.tv/ws?x=\n"])
def test_reconnect_destinations_are_provider_only(url):
    with pytest.raises(_ProviderError):
        TwitchAudienceConnector._reconnect_url(url)


def test_provider_reconnect_preserves_subscription_and_closes_old_socket(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        reconnect = "wss://eventsub.wss.twitch.tv/ws?reconnect=opaque-fixture"
        f.sockets[0].queue.put_nowait(frame("session_reconnect", {"session": {"id": "session-1", "status": "reconnecting", "reconnect_url": reconnect}}))
        f.sockets[0].queue.put_nowait(notification(event_id="before-move-1"))
        f.sockets[0].queue.put_nowait(notification(event_id="before-move-2"))
        await spin_until(lambda: len(f.sockets) == 2 and f.sockets[0].closed)
        assert f.urls[-1] == reconnect and sum(c[0] == "POST" for c in f.calls) == 1
        f.sockets[1].queue.put_nowait(notification(session="session-2"))
        await spin_until(lambda: f.service.cached_status()["received"] == 3)
        await f.service.disconnect()
    asyncio.run(scenario())


def test_lost_connection_creates_new_owned_subscription_without_old_chat_replay(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.sockets[0].queue.put_nowait(notification())
        await spin_until(lambda: f.service.cached_status()["received"] == 1)
        f.sockets[0].queue.put_nowait(ConnectionError("fixture failure"))
        await asyncio.sleep(.55)
        await spin_until(lambda: len(f.sockets) == 2 and f.service.cached_status()["connected"])
        assert sum(c[0] == "POST" for c in f.calls) == 2 and f.sockets[0].closed
        f.sockets[1].queue.put_nowait(notification(session="session-2", subscription="sub-2"))
        f.sockets[1].queue.put_nowait(notification(session="session-2", subscription="sub-2", event_id="chat-2"))
        await spin_until(lambda: f.service.cached_status()["received"] == 2)
        assert f.audience.status()["queued"] == 1
        await f.service.disconnect()
        assert sum(c[0] == "DELETE" for c in f.calls) == 2
    asyncio.run(scenario())


def test_missing_credentials_and_expired_token_never_leave_authorized_state(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        f.service._credentials_provider = lambda: {}
        assert (await f.service.connect())["reason"] == "credentials_required"
        assert not f.calls and not f.urls
        f.now += 6
        f.service._credentials_provider = f.credentials
        await f.service.connect()
        f.now += 7201
        f.http_status = 401
        assert not f.service.cached_status()["authorized"]
        f.sockets[0].queue.put_nowait(frame("session_keepalive", {}, now=f.now))
        await spin_until(lambda: f.service.cached_status()["reason"] == "authorization_rejected")
        await f.service.disconnect()
        assert f.service._token is None and f.service.cached_status()["cleanup_incomplete"]
    asyncio.run(scenario())


def test_malformed_subscription_response_deletes_only_its_owned_id(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        f.extra_response = {"data": [{"id": "owned-malformed", "status": "enabled", "type": "wrong"}]}
        result = await f.service.connect()
        assert result["reason"] == "invalid_subscription_response" and not result["connected"]
        deletes = [url for method, url, _ in f.calls if method == "DELETE"]
        assert deletes == [f.service.SUBSCRIPTIONS_URL + "?id=owned-malformed"]
        assert f.sockets[0].closed
    asyncio.run(scenario())


def test_disconnect_cancels_receiver_and_closes_transport_even_if_close_fails(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        async def failing_close():
            raise RuntimeError("private transport details")
        f.sockets[0].close = failing_close
        state = await f.service.disconnect()
        assert state["cleanup_incomplete"] and state["state"] == "not_connected"
        assert f.service._task is None and f.service._http is None and f.service._token is None
        assert "private transport" not in json.dumps(state)
    asyncio.run(scenario())


def test_revocation_disconnects_and_hourly_validation_is_required(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.now += 3601
        f.sockets[0].queue.put_nowait(frame("session_keepalive", {}, now=f.now))
        await spin_until(lambda: sum(c[0] == "GET" for c in f.calls) == 2)
        f.sockets[0].queue.put_nowait(frame("revocation", {"subscription": {"id": "sub-1", "status": "authorization_revoked"}}, now=f.now))
        await spin_until(lambda: f.service.cached_status()["reason"] == "subscription_revoked")
        await f.service.disconnect()
        assert f.service._token is None and f.sockets[0].closed
    asyncio.run(scenario())


def test_rate_limit_and_http_redirects_are_fail_closed(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        keepalive = frame("session_keepalive", {})
        for _ in range(201):
            f.sockets[0].queue.put_nowait(keepalive)
        await spin_until(lambda: f.service.cached_status()["reason"] == "provider_event_rate_exceeded")
        await f.service.disconnect()
    asyncio.run(scenario())
    error = RuntimeError("redirect fixture")
    assert _NoRedirectConnect.process_redirect(None, error) is error


class FakeConnector:
    def __init__(self):
        self.calls = []

    def cached_status(self):
        return {"state": "not_connected"}

    async def connect(self):
        self.calls.append("connect")
        return self.cached_status()

    async def disconnect(self):
        self.calls.append("disconnect")
        return self.cached_status()


def client(connector, *, local=True, operator=True):
    app = FastAPI()
    app.include_router(create_twitch_audience_router(connector, lambda request: operator))
    return TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1" if local else "192.0.2.10", 1234))


def test_http_control_requires_local_authorized_same_origin_and_no_credentials():
    connector = FakeConnector()
    path = "/api/production/audience/twitch"
    with client(connector) as c:
        assert c.get(path).json()["state"] == "not_connected" and not connector.calls
        assert c.post(path + "/connect", json={}).status_code == 403
        assert c.post(path + "/connect", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
        headers = {"Origin": "http://127.0.0.1:8765"}
        assert c.post(path + "/connect", json={"token": "browser-token"}, headers=headers).status_code == 400
        assert c.post(path + "/connect", json={"x": "x" * 200}, headers=headers).status_code == 400
        assert c.post(path + "/connect", json={}, headers=headers).status_code == 200
        assert c.post(path + "/disconnect", json={}, headers=headers).status_code == 200
        assert connector.calls == ["connect", "disconnect"]
    for kwargs in ({"local": False}, {"operator": False}):
        with client(connector, **kwargs) as c:
            assert c.get(path).status_code == 403
            assert c.post(path + "/connect", json={}, headers=headers).status_code == 403
    with client(connector) as c:
        assert c.post(path + "/connect", json={}, headers={"Host": "rebinding.example", "Origin": "http://rebinding.example"}).status_code == 403


def test_audience_status_merges_cached_connector_without_activation(tmp_path):
    f = Fixture(tmp_path)
    app = FastAPI()
    app.include_router(create_audience_router(f.audience, tmp_path,
        sources_provider=lambda: [f.service.cached_status()]))
    with TestClient(app) as http:
        sources = http.get('/api/production/audience').json()['sources']
        twitch = next(source for source in sources if source['platform'] == 'twitch')
        assert twitch['implemented'] and twitch['state'] == 'not_connected'
        assert twitch['events'] == ['first_chat', 'featured_chat'] and twitch['available_events'] == []
        assert not f.calls and not f.urls and f.reads == 0
        assert all(not source['implemented'] for source in sources if source['platform'] != 'twitch')
