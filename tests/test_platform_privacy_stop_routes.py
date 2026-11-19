"""History failures must not prevent an authenticated privacy stop/cancel."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.viewer_chat_service import TrustedViewerChatMessage, ViewerChatService
from rareiq.web.kick_audience import create_kick_audience_router
from rareiq.web.platform_accounts import create_platform_accounts_router
from rareiq.web.twitch_audience import create_twitch_audience_router
from rareiq.web.viewer_chat import create_viewer_chat_router
from rareiq.web.youtube_audience import create_youtube_audience_router


ORIGIN = "http://127.0.0.1:8765"
NOW = 1800000000.0


class Audit:
    def __init__(self, stage):
        self.stage, self.calls = stage, []

    def __call__(self, **entry):
        self.calls.append(entry)
        if (self.stage == "both" or self.stage == "before" and entry["outcome"] == "requested"
                or self.stage == "after" and entry["outcome"] != "requested"):
            raise RuntimeError("private history database failure")


class Connector:
    def __init__(self, platform, *, connected):
        self.platform, self.connected = platform, connected
        self.connects = self.disconnects = 0
        self.fail_disconnect = False

    def cached_status(self):
        return {"platform": self.platform, "connected": self.connected,
                "state": "connected" if self.connected else "not_connected",
                "authorized": self.connected, "reason": "observing_chat" if self.connected else "disconnected_by_operator"}

    async def connect(self):
        self.connects += 1
        self.connected = True
        return self.cached_status()

    async def disconnect(self):
        self.disconnects += 1
        if self.fail_disconnect:
            raise RuntimeError("private provider failure")
        self.connected = False
        return self.cached_status()


class Account:
    def __init__(self, platform, *, pending):
        self.platform, self.pending = platform, pending
        self.begins = self.cancels = 0
        self.fail_cancel = False

    def status(self):
        value = {"platform": self.platform, "state": "pending" if self.pending else "not_authorized",
                 "reason": "authorization_pending" if self.pending else "authorization_cancelled",
                 "authorized": False, "app_configured": True}
        if self.pending:
            value.update(flow_id="a" * 32, expires_at=NOW + 600, user_code="ABCD-1234", poll_after=5)
        return value

    async def begin(self):
        self.begins += 1
        self.pending = True
        return self.status()

    async def cancel(self):
        self.cancels += 1
        if self.fail_cancel:
            raise RuntimeError("private cancellation failure")
        self.pending = False
        return self.status()


def client_for(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 1234))


def command(client, path, body=None):
    return client.post(path, json={} if body is None else body, headers={"Origin": ORIGIN})


ROUTERS = {"twitch": create_twitch_audience_router, "youtube": create_youtube_audience_router,
           "kick": create_kick_audience_router}


@pytest.mark.parametrize("platform", list(ROUTERS))
@pytest.mark.parametrize("stage", ["before", "after", "both"])
def test_disconnect_executes_despite_requested_or_outcome_history_failure(platform, stage):
    connector, audit = Connector(platform, connected=True), Audit(stage)
    client = client_for(ROUTERS[platform](connector, lambda request: True, audit=audit))
    reply = command(client, "/api/production/audience/" + platform + "/disconnect")
    assert reply.status_code == 200 and connector.disconnects == 1 and connector.connected is False
    assert reply.json()["state"] == "not_connected" and reply.json()["connected"] is False
    assert reply.json()["activity_history_warning"] is True
    assert [entry["outcome"] for entry in audit.calls] == ["requested", "succeeded"]
    assert "private" not in reply.text


@pytest.mark.parametrize("platform", list(ROUTERS))
@pytest.mark.parametrize("stage", ["before", "after"])
def test_connect_keeps_history_failure_response_and_never_bypasses_requested_audit(platform, stage):
    connector, audit = Connector(platform, connected=False), Audit(stage)
    client = client_for(ROUTERS[platform](connector, lambda request: True, audit=audit))
    reply = command(client, "/api/production/audience/" + platform + "/connect")
    assert reply.status_code == 503 and reply.json()["reason"] == "activity_history_unavailable"
    assert connector.connects == (0 if stage == "before" else 1)
    assert "activity_history_warning" not in reply.json() and "private" not in reply.text


@pytest.mark.parametrize("platform", ["twitch", "youtube"])
@pytest.mark.parametrize("stage", ["before", "after", "both"])
def test_account_cancel_executes_despite_history_failure_and_returns_current_state(platform, stage):
    twitch, youtube, audit = Account("twitch", pending=True), Account("youtube", pending=True), Audit(stage)
    account = twitch if platform == "twitch" else youtube
    client = client_for(create_platform_accounts_router(twitch, lambda request: True, youtube_service=youtube, audit=audit))
    reply = command(client, "/api/production/accounts/" + platform + "/cancel")
    assert reply.status_code == 200 and account.cancels == 1 and not account.pending
    assert reply.json()["account"]["state"] == "not_authorized"
    assert reply.json()["account"]["reason"] == "authorization_cancelled"
    assert reply.json()["activity_history_warning"] is True
    assert len(audit.calls) == 2 and "private" not in reply.text


@pytest.mark.parametrize("platform", ["twitch", "youtube"])
@pytest.mark.parametrize("stage", ["before", "after"])
def test_begin_keeps_history_failure_response_and_never_bypasses_requested_audit(platform, stage):
    twitch, youtube, audit = Account("twitch", pending=False), Account("youtube", pending=False), Audit(stage)
    account = twitch if platform == "twitch" else youtube
    client = client_for(create_platform_accounts_router(twitch, lambda request: True, youtube_service=youtube, audit=audit))
    reply = command(client, "/api/production/accounts/" + platform + "/begin")
    assert reply.status_code == 503 and reply.json()["reason"] == "account_unavailable"
    assert account.begins == (0 if stage == "before" else 1)
    assert "activity_history_warning" not in reply.json() and "private" not in reply.text


def test_listening_disable_always_clears_transcript_and_invalidates_session_if_history_fails():
    service = ViewerChatService(clock=lambda: NOW)
    session = service.set_listening(True)["session_id"]
    service.accept(TrustedViewerChatMessage("twitch", "1", "message", "2", "Viewer", "private chat text", NOW))
    def blocked(**entry):
        raise RuntimeError("private history database failure")
    client = client_for(create_viewer_chat_router(service, lambda request: True, audit=blocked))
    reply = command(client, "/api/production/viewer-chat/listening", {"enabled": False})
    assert reply.status_code == 200 and not service.active
    assert reply.json()["active"] is False and reply.json()["messages"] == []
    assert reply.json()["session_id"] != session and not service._seen
    assert reply.json()["activity_history_warning"] is True
    assert "private" not in reply.text
    denied = command(client, "/api/production/viewer-chat/listening", {"enabled": True})
    assert denied.status_code == 503 and not service.active


@pytest.mark.parametrize("platform", list(ROUTERS))
def test_history_warning_never_masks_a_failed_disconnect_or_exposes_provider_error(platform):
    connector = Connector(platform, connected=True)
    connector.fail_disconnect = True
    client = client_for(ROUTERS[platform](connector, lambda request: True, audit=Audit("both")))
    reply = command(client, "/api/production/audience/" + platform + "/disconnect")
    assert reply.status_code == 503 and reply.json() == {"ok": False, "reason": "provider_unavailable"}
    assert connector.connected and "private" not in reply.text


@pytest.mark.parametrize("platform", ["twitch", "youtube"])
def test_history_warning_never_masks_a_failed_account_cancel(platform):
    twitch, youtube = Account("twitch", pending=True), Account("youtube", pending=True)
    account = twitch if platform == "twitch" else youtube
    account.fail_cancel = True
    client = client_for(create_platform_accounts_router(twitch, lambda request: True, youtube_service=youtube, audit=Audit("both")))
    reply = command(client, "/api/production/accounts/" + platform + "/cancel")
    assert reply.status_code == 503 and reply.json() == {"ok": False, "reason": "account_unavailable"}
    assert account.pending and "private" not in reply.text


def test_warnings_are_absent_when_stop_history_is_saved_normally():
    connector = Connector("youtube", connected=True)
    client = client_for(create_youtube_audience_router(connector, lambda request: True, audit=lambda **entry: None))
    reply = command(client, "/api/production/audience/youtube/disconnect")
    assert reply.status_code == 200 and "activity_history_warning" not in reply.json()
    assert "private" not in json.dumps(reply.json())
