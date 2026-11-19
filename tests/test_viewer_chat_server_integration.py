"""Actual operator/guest boundary, without opening providers or a server lifespan."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from rareiq.services.viewer_chat_service import ViewerChatService, TrustedViewerChatMessage
from rareiq.web import server
from rareiq.web.guest_ingress import GuestOnlyIngress


@pytest.fixture(autouse=True)
def private_test_boundaries(monkeypatch):
    class EmptyVault:
        def get(self, platform):
            return {}

        def status(self, platform):
            return {"state": "empty", "stored": False}

    vault = EmptyVault()
    events = []
    if server.platform_credential_vault is not None:
        monkeypatch.setattr(server.platform_credential_vault, "status", vault.status)
    monkeypatch.setattr(server, "platform_credential_vault", vault)
    monkeypatch.setattr(server.twitch_account_service, "_vault", vault)
    monkeypatch.setattr(server.youtube_account_service, "_vault", vault)
    monkeypatch.setattr(server.greenroom_service, "record_production_event",
                        lambda *args, **kwargs: events.append((args, kwargs)))
    for name in ("TWITCH_CLIENT_ID", "TWITCH_CHANNEL_LOGIN", "TWITCH_USER_ACCESS_TOKEN",
                 "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID"):
        monkeypatch.delenv("RAREIQ_" + name, raising=False)
    return events


def test_integrated_feed_is_opt_in_and_never_reads_platform_credentials(monkeypatch):
    service = ViewerChatService()
    monkeypatch.setattr(server.viewer_chat_service, "status", service.status)
    monkeypatch.setattr(server.viewer_chat_service, "set_listening", service.set_listening)
    def forbidden():
        raise AssertionError("A status read accessed authorization")
    for connector in (server.twitch_audience_connector, server.youtube_audience_connector,
                      server.kick_audience_connector):
        monkeypatch.setattr(connector, "_credentials_provider", forbidden)
    client = TestClient(server.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 12000))
    result = client.get("/api/production/viewer-chat")
    assert result.status_code == 200
    assert result.json()["active"] is False
    assert result.json()["messages"] == []
    assert {source["platform"] for source in result.json()["sources"]} == {"twitch", "youtube", "kick"}
    assert client.post("/api/production/viewer-chat/listening", json={"enabled": True}).status_code == 403
    enabled = client.post("/api/production/viewer-chat/listening", json={"enabled": True},
                          headers={"Origin": "http://127.0.0.1:8765"})
    assert enabled.status_code == 200
    assert enabled.json()["active"] is True


def test_private_guest_listener_cannot_read_or_enable_viewer_chat():
    app = GuestOnlyIngress(server.app, public_origin="https://guest.example.invalid:8445")
    client = TestClient(app, base_url="https://guest.example.invalid:8445", client=("127.0.0.1", 12000))
    assert client.get("/api/production/viewer-chat").status_code == 404
    assert client.post("/api/production/viewer-chat/listening", json={"enabled": True}).status_code == 404
    assert client.get("/api/production/accounts").status_code == 404
    assert client.post("/api/production/accounts/twitch/begin", json={}).status_code == 404
    assert client.get("/api/production/accounts/youtube/authorization?flow_id=" + "a" * 32).status_code == 404


def test_viewer_records_omit_raw_ids_and_have_no_guest_feed_alias():
    service = ViewerChatService(clock=lambda: 1000)
    service.set_listening(True)
    accepted = service.accept(TrustedViewerChatMessage("twitch", "channel", "message", "author",
                                                      "Viewer", "literal viewer text", 1000))
    assert accepted["ok"]
    record = service.status()["messages"][0]
    assert record["text"] == "literal viewer text"
    assert "channel_id" not in record and "author_id" not in record
    assert all(getattr(route, "path", "") != "/guest/viewer-chat" for route in server.app.routes)


def test_account_setup_is_mounted_without_automatically_contacting_providers(monkeypatch):
    async def forbidden():
        raise AssertionError("Status must not begin authorization")
    monkeypatch.setattr(server.twitch_account_service, "begin", forbidden)
    monkeypatch.setattr(server.youtube_account_service, "begin", forbidden)
    client = TestClient(server.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 12000))
    response = client.get("/api/production/accounts")
    assert response.status_code == 200
    assert {a["platform"] for a in response.json()["accounts"]} == {"twitch", "youtube", "kick"}
    assert not any(a["authorized"] for a in response.json()["accounts"])
    assert client.post("/api/production/accounts/twitch/begin", json={}).status_code == 403


def test_twitch_credential_precedence_never_mixes_accounts(monkeypatch):
    stored = {"client_id": "saved-app", "channel_login": "saved-channel", "access_token": "saved-token"}
    monkeypatch.setattr(server, "_stored_platform_credentials", lambda platform: stored)
    expected = {"client_id": "saved-app", "channel_login": "saved-channel", "user_access_token": "saved-token"}
    assert server._twitch_audience_credentials() == expected
    monkeypatch.setenv("RAREIQ_TWITCH_CLIENT_ID", "saved-app")
    assert server._twitch_audience_credentials() == expected
    monkeypatch.setenv("RAREIQ_TWITCH_CLIENT_ID", "another-app")
    assert server._twitch_audience_credentials() == {"client_id": "another-app", "channel_login": "", "user_access_token": ""}
    monkeypatch.setenv("RAREIQ_TWITCH_CHANNEL_LOGIN", "ExplicitChannel")
    assert server._twitch_audience_credentials() == {"client_id": "another-app", "channel_login": "explicitchannel", "user_access_token": ""}


def test_youtube_configuration_and_credentials_are_atomic(monkeypatch):
    stored = {"client_id": "saved-app", "client_secret": "saved-secret", "refresh_token": "saved-refresh", "channel_id": "saved-channel"}
    monkeypatch.setattr(server, "_stored_platform_credentials", lambda platform: stored)
    assert server._youtube_audience_credentials() == stored
    assert server._youtube_app_configuration() == {"client_id": "saved-app", "client_secret": "saved-secret"}
    monkeypatch.setenv("RAREIQ_YOUTUBE_CLIENT_ID", "another-app")
    assert server._youtube_audience_credentials() == {"client_id": "another-app", "client_secret": "", "refresh_token": "", "channel_id": ""}
    assert server._youtube_app_configuration() == {"client_id": "another-app", "client_secret": ""}


def test_twitch_refresh_runs_only_for_stored_account_setup(monkeypatch):
    calls = []
    async def refresh():
        calls.append(True)
    monkeypatch.setattr(server.twitch_account_service, "ensure_credentials", refresh)
    asyncio.run(server._prepare_twitch_audience_connection())
    monkeypatch.setenv("RAREIQ_TWITCH_CLIENT_ID", "public-app")
    asyncio.run(server._prepare_twitch_audience_connection())
    assert calls == [True, True]
    monkeypatch.setenv("RAREIQ_TWITCH_USER_ACCESS_TOKEN", "legacy-token")
    asyncio.run(server._prepare_twitch_audience_connection())
    assert calls == [True, True]


def test_account_and_listening_history_contains_only_safe_local_control_metadata(private_test_boundaries):
    server._platform_account_audit(action="twitch.begin", outcome="pending")
    server._platform_account_audit(action="youtube.cancel", outcome="not_authorized")
    server._viewer_chat_audit(enabled=True)
    assert private_test_boundaries == [
        (("platform.account.begin", "twitch", "requested"), {"actor_kind": "local_operator"}),
        (("platform.account.cancel", "youtube", "succeeded"), {"actor_kind": "local_operator"}),
        (("viewer_chat.listening", "viewer_chat", "requested"), {"actor_kind": "local_operator", "details": {"enabled": True}}),
    ]


def test_youtube_stored_authorization_uses_service_and_legacy_mode_is_explicit(monkeypatch):
    calls = []
    authorization = {"access_token": "synthetic-access", "channel_id": "synthetic-channel", "expires_at": 2000000000, "scopes": ["https://www.googleapis.com/auth/youtube.readonly"]}
    async def ready():
        calls.append(True)
        return authorization
    monkeypatch.setattr(server.youtube_account_service, "ensure_authorization", ready)
    assert asyncio.run(server._youtube_chat_authorization()) == authorization
    monkeypatch.setenv("RAREIQ_YOUTUBE_CLIENT_ID", "configured-app")
    assert asyncio.run(server._youtube_chat_authorization()) == authorization
    monkeypatch.setenv("RAREIQ_YOUTUBE_REFRESH_TOKEN", "legacy-refresh")
    assert asyncio.run(server._youtube_chat_authorization()) is None
    assert calls == [True, True]
    monkeypatch.delenv("RAREIQ_YOUTUBE_REFRESH_TOKEN")
    monkeypatch.delenv("RAREIQ_YOUTUBE_CLIENT_ID")
    async def missing():
        return None
    monkeypatch.setattr(server.youtube_account_service, "ensure_authorization", missing)
    with pytest.raises(ValueError, match="authorization_refresh_required"):
        asyncio.run(server._youtube_chat_authorization())
