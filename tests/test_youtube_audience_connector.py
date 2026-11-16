"""Offline provider contract tests. No host credentials, streams or Google calls."""
import asyncio
from collections import deque
from datetime import datetime, timezone
from email.utils import format_datetime
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.audience_service import AudienceService
from rareiq.services.youtube_audience_connector import YouTubeAudienceConnector
from rareiq.web.youtube_audience import create_youtube_audience_router


NOW = 1800000000.0
OWNER, VIEWER, OTHER = "UC" + "a" * 22, "UC" + "b" * 22, "UC" + "c" * 22


def message(event_id="event-1", *, timestamp=NOW + 1, chat="fixture-chat", kind="textMessageEvent"):
    return {"id": event_id, "snippet": {"liveChatId": chat, "type": kind, "authorChannelId": VIEWER,
        "publishedAt": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
        "displayMessage": "PRIVATE-CHAT-MUST-NOT-PERSIST"}, "authorDetails": {"channelId": VIEWER, "displayName": "Fixture viewer"}}


def page(*items, token="next-page", interval=1500, **extra):
    return {"items": list(items), "nextPageToken": token, "pollingIntervalMillis": interval, **extra}


async def spin(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError("fixture condition not reached")


class Fixture:
    def __init__(self, tmp_path):
        self.now, self.reads = NOW, 0
        self.calls, self.closed = [], False
        self.sleeps = asyncio.Queue()
        self.messages = deque([page(message("initial-history", timestamp=NOW - 1), token="initial-cursor")])
        self.token = {"access_token": "fixture-private-access", "token_type": "Bearer", "expires_in": 7200,
                      "scope": "https://www.googleapis.com/auth/youtube.readonly"}
        self.channels = {"items": [{"id": OWNER}]}
        self.broadcasts = {"items": [{"id": "fixture-show", "snippet": {"channelId": OWNER, "liveChatId": "fixture-chat"}, "status": {"lifeCycleStatus": "live"}}]}
        self.override, self.credentials = {}, {"client_id": "fixture-client", "client_secret": "fixture-private-secret",
                                               "refresh_token": "fixture-private-refresh", "channel_id": OWNER}
        self.audience = AudienceService(tmp_path / "audience.sqlite3", clock=lambda: self.now)
        self.audience.status()
        self.audience.configure(action="save_rule", data={"id": "welcome", "name": "Welcome", "enabled": True, "platform": "youtube",
            "event": "first_chat", "message": "Hello {name}", "animation": "slide", "duration_ms": 3000, "cooldown_seconds": 60},
            expected_revision=0, request_id="rule", actor_kind="local_operator")
        self.audience.configure(action="settings", data={"enabled": True}, expected_revision=1, request_id="arm", actor_kind="local_operator")
        self.service = YouTubeAudienceConnector(self.audience, self.load_credentials,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)),
            clock=lambda: self.now, sleep=self.sleep)

    def load_credentials(self):
        self.reads += 1
        return dict(self.credentials)

    async def sleep(self, seconds):
        gate = asyncio.get_running_loop().create_future()
        self.sleeps.put_nowait((seconds, gate))
        await gate

    async def tick(self):
        seconds, gate = await asyncio.wait_for(self.sleeps.get(), .5)
        self.now += seconds
        gate.set_result(None)
        await spin(lambda: not self.sleeps.empty() or self.service._task.done())
        return seconds

    async def http(self, request):
        self.calls.append((request.method, request.url.path, dict(request.url.params)))
        assert "access_token" not in request.url.params
        if request.url.path == "/token":
            assert request.method == "POST" and b"grant_type=refresh_token" in request.content
            value = self.token
        elif request.url.path.endswith("/channels"):
            assert request.url.params.get("mine") == "true"
            value = self.channels
        elif request.url.path.endswith("/liveBroadcasts"):
            assert sum(key in request.url.params for key in ("id", "mine", "broadcastStatus")) == 1
            value = self.broadcasts
        elif request.url.path.endswith("/liveChat/messages"):
            assert "displayMessage" not in request.url.params["fields"] and "messageText" not in request.url.params["fields"]
            value = self.messages.popleft() if self.messages else page(token="empty-cursor")
        else:
            raise AssertionError("unexpected fixture request")
        value = self.override.get(request.url.path, value)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)


def test_default_disconnected_without_credentials_or_network(tmp_path):
    f = Fixture(tmp_path)
    state = f.service.cached_status()
    assert state["state"] == "not_connected" and state["available_events"] == []
    assert state["viewer_join_supported"] is False
    assert not f.calls and f.reads == 0


def test_connect_discards_history_then_observes_first_chat_once_and_preserves_privacy(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        state = await f.service.connect()
        assert state["connected"] and f.audience.status()["participants"] == []
        assert len(f.calls) == 4
        assert (await f.service.connect())["connected"] and f.reads == 1
        f.messages.append(page(message(), message(), message("initial-history"), token="second-cursor"))
        assert await f.tick() == 10
        assert f.service.cached_status()["received"] == 1
        assert f.calls[-1][2]["pageToken"] == "initial-cursor"
        assert f.audience.status()["queued"] == 1
        public = json.dumps(f.service.cached_status()) + (tmp_path / "audience.sqlite3").read_bytes().decode("latin1")
        assert "PRIVATE-CHAT" not in public and "fixture-private" not in public
        assert OWNER not in json.dumps(f.service.cached_status()) and VIEWER not in json.dumps(f.service.cached_status())
        await f.service.disconnect()
        assert f.service._credentials is None and f.service._access_token is None and f.service._http is None
        assert all(method == "GET" or path == "/token" for method, path, _ in f.calls)
    asyncio.run(scenario())


@pytest.mark.parametrize("field,value,reason", [("scope", "", "chat_scope_required"), ("scope", "https://www.googleapis.com/auth/drive", "chat_scope_required"),
    ("scope", None, "chat_scope_required"), ("expires_in", 30, "invalid_access_token"), ("expires_in", True, "invalid_access_token"),
    ("token_type", "mac", "invalid_access_token"), ("access_token", "bad\ntoken", "invalid_provider_payload")])
def test_oauth_validation_stops_before_chat_access(tmp_path, field, value, reason):
    async def scenario():
        f = Fixture(tmp_path)
        f.token[field] = value
        state = await f.service.connect()
        assert state["reason"] == reason and not state["authorized"]
        assert len(f.calls) == 1 and f.service._credentials is None
    asyncio.run(scenario())


def test_channel_ownership_and_single_active_chat_are_required(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        f.channels = {"items": [{"id": OTHER}]}
        assert (await f.service.connect())["reason"] == "channel_identity_mismatch"
        assert len(f.calls) == 2
        f.now += 6
        f.channels = {"items": [{"id": OWNER}]}
        f.broadcasts["items"][0]["snippet"]["channelId"] = OTHER
        assert (await f.service.connect())["reason"] == "no_active_chat"
        f.now += 6
        f.broadcasts["items"][0]["snippet"]["channelId"] = OWNER
        f.broadcasts["items"].append({"id": "second-show", "snippet": {"channelId": OWNER, "liveChatId": "second-chat"}, "status": {"lifeCycleStatus": "live"}})
        assert (await f.service.connect())["reason"] == "multiple_active_chats"
        assert not any(path.endswith("/liveChat/messages") for _, path, _ in f.calls)
    asyncio.run(scenario())


@pytest.mark.parametrize("raw", [page(interval=-1), page(interval=True), page(interval=3600001), page(token="x" * 2049),
    page(*([message()] * 201)), page(offlineAt="2027-01-15T08:00:00Z"), {"items": [], "pollingIntervalMillis": 1000}],
    ids=["negative-interval", "bool-interval", "huge-interval", "huge-token", "oversized-items", "offline", "missing-cursor"])
def test_bad_cursor_interval_or_ended_chat_is_never_connected(tmp_path, raw):
    async def scenario():
        f = Fixture(tmp_path)
        f.messages = deque([raw])
        assert not (await f.service.connect())["connected"]
        assert not f.audience.status()["participants"]
    asyncio.run(scenario())


def test_poll_interval_is_obeyed_and_stale_or_future_events_do_not_become_welcomes(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        f.messages = deque([page(interval=45000), page(message("old", timestamp=NOW - 1), message("future", timestamp=NOW + 1000),
            message("fresh", timestamp=NOW + 44), token="new", interval=20000)])
        await f.service.connect()
        assert await f.tick() == 45
        assert f.service.cached_status()["received"] == 1 and f.service.cached_status()["rejected"] == 2
        assert (await asyncio.wait_for(f.sleeps.get(), .1))[0] == 20
        await f.service.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["wrong-chat", "wrong-author", "unknown-type"])
def test_foreign_chat_author_and_nonchat_events_never_enter_audience(tmp_path, change):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        item = message()
        if change == "wrong-chat":
            item["snippet"]["liveChatId"] = "foreign-chat"
        elif change == "wrong-author":
            item["authorDetails"]["channelId"] = OTHER
        else:
            item["snippet"]["type"] = "newSponsorEvent"
        f.messages.append(page(item))
        await f.tick()
        assert f.audience.status()["participants"] == []
        assert f.service.cached_status()["received"] == 0
        await f.service.disconnect()
    asyncio.run(scenario())


def test_reconnect_discards_outage_backlog_and_keeps_next_page_cursor(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.messages.extend([httpx.Response(503, json={"message": "private provider details"}),
            page(message("outage-event", timestamp=NOW + 19), token="recovered-cursor"),
            page(message("after-recovery", timestamp=NOW + 29), token="fresh-cursor")])
        assert await f.tick() == 10
        assert f.service.cached_status()["state"] == "reconnecting" and not f.service.cached_status()["connected"]
        assert await f.tick() == 10
        assert f.service.cached_status()["connected"] and f.service.cached_status()["received"] == 0
        assert await f.tick() == 10
        assert f.service.cached_status()["received"] == 1 and f.calls[-1][2]["pageToken"] == "recovered-cursor"
        await f.service.disconnect()
    asyncio.run(scenario())


def test_rate_limit_waits_retry_after_and_retries_are_bounded(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.messages.extend([httpx.Response(429, headers={"Retry-After": "120"}, json={})] * 4)
        await f.tick()
        assert f.service.cached_status()["retry_after_seconds"] == 120
        assert await f.tick() == 120
        assert await f.tick() == 120
        assert await f.tick() == 120
        assert f.service.cached_status()["state"] == "not_connected"
        assert (await f.service.connect())["reason"] == "connection_retry_limited"
        assert sum(path.endswith("/liveChat/messages") for _, path, _ in f.calls) == 5
        await f.service.disconnect()
    asyncio.run(scenario())


@pytest.mark.parametrize("retry_after", ["7200", format_datetime(datetime.fromtimestamp(NOW + 7210, timezone.utc), usegmt=True)], ids=["seconds", "http-date"])
def test_long_rate_limit_stops_instead_of_retrying_earlier_than_requested(tmp_path, retry_after):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.messages.append(httpx.Response(429, headers={"Retry-After": retry_after}, json={}))
        await f.tick()
        assert f.service.cached_status()["state"] == "not_connected"
        assert f.service.cached_status()["retry_after_seconds"] >= 7200
        assert (await f.service.connect())["reason"] == "connection_retry_limited"
        assert len(f.calls) == 5
    asyncio.run(scenario())


@pytest.mark.parametrize("reason,expected", [("quotaExceeded", "provider_quota_exhausted"), ("liveChatEnded", "chat_ended"),
    ("liveChatDisabled", "chat_disabled"), ("forbidden", "authorization_rejected")])
def test_fatal_provider_errors_stop_without_retry_and_hide_raw_error(tmp_path, reason, expected):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.messages.append(httpx.Response(403, json={"error": {"message": "PRIVATE-ERROR", "errors": [{"reason": reason}]}}))
        await f.tick()
        assert f.service.cached_status()["reason"] == expected
        assert f.service._access_token is None and "PRIVATE-ERROR" not in json.dumps(f.service.cached_status())
        assert f.service._task.done()
    asyncio.run(scenario())


def test_token_refresh_revalidates_owner_and_does_not_switch_chat(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        f.now += 7200
        f.broadcasts["items"][0]["snippet"]["liveChatId"] = "changed-chat"
        await f.tick()
        assert sum(path == "/token" for _, path, _ in f.calls) == 2
        assert sum(path.endswith("/channels") for _, path, _ in f.calls) == 2
        assert f.service.cached_status()["reason"] == "channel_identity_mismatch"
        assert f.service._credentials is None
    asyncio.run(scenario())


def test_disconnect_cancels_sleep_without_further_requests_or_token_revocation(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        await f.service.connect()
        await spin(lambda: not f.sleeps.empty())
        count = len(f.calls)
        await f.service.disconnect()
        assert len(f.calls) == count and f.service._task is None
        assert f.service.cached_status()["state"] == "not_connected" and f.service._credentials is None
    asyncio.run(scenario())


def test_missing_credentials_oversized_http_and_redirects_fail_closed(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        f.credentials = {}
        assert (await f.service.connect())["reason"] == "credentials_required" and not f.calls
        f.credentials = {"client_id": "fixture-client", "client_secret": "fixture-secret", "refresh_token": "fixture-refresh", "channel_id": OWNER}
        f.now += 6
        f.override["/token"] = httpx.Response(302, headers={"Location": "https://evil.invalid"})
        assert (await f.service.connect())["reason"] == "provider_request_failed"
        f.now += 6
        f.override["/token"] = httpx.Response(200, content=b"x" * 262145)
        assert (await f.service.connect())["reason"] == "provider_payload_too_large"
        assert len(f.calls) == 2 and f.service._credentials is None
    asyncio.run(scenario())


def test_router_is_local_same_origin_explicit_and_accepts_no_browser_secrets():
    class Fake:
        calls = []
        def cached_status(self):
            return {"state": "not_connected"}
        async def connect(self):
            self.calls.append("connect")
            return self.cached_status()
        async def disconnect(self):
            self.calls.append("disconnect")
            return self.cached_status()
    fake, app = Fake(), FastAPI()
    app.include_router(create_youtube_audience_router(fake, lambda request: True))
    path, headers = "/api/production/audience/youtube", {"Origin": "http://127.0.0.1:8765"}
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1)) as http:
        assert http.get(path).json()["state"] == "not_connected" and fake.calls == []
        assert http.post(path + "/connect", json={}).status_code == 403
        assert http.post(path + "/connect", json={}, headers={"Origin": "https://evil.invalid"}).status_code == 403
        assert http.post(path + "/connect", json={}, headers={"Host": "rebind.invalid", "Origin": "http://rebind.invalid"}).status_code == 403
        assert http.post(path + "/connect", json={"token": "browser-value"}, headers=headers).status_code == 400
        assert http.post(path + "/connect", content=b"x" * 129, headers=headers | {"Content-Type": "application/json"}).status_code == 400
        assert http.post(path + "/connect", json={}, headers=headers).status_code == 200
        assert http.post(path + "/disconnect", json={}, headers=headers).status_code == 200
        assert fake.calls == ["connect", "disconnect"]
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("192.0.2.10", 1)) as http:
        assert http.get(path).status_code == 403
        assert http.post(path + "/connect", json={}, headers=headers).status_code == 403
