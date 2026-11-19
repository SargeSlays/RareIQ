"""Synthetic YouTube selection/pipe/HTTP tests; no grants or provider writes."""
import asyncio
from copy import deepcopy
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.services.youtube_account_service import YouTubeAccountService
from rareiq.services import youtube_destination_service as module
from rareiq.web.youtube_destinations import create_youtube_destination_router
from tools import desktop_youtube_account as helper

NOW = 1000.0
CHANNEL = "UC1234567890123456789012"


class Vault:
    def __init__(self):
        self.value = {"client_id": "synthetic.apps.googleusercontent.com", "client_secret": "private-client-secret",
                      "channel_id": CHANNEL, "public_label": "Synthetic channel", "token_type": "bearer",
                      "access_token": "private-access-token", "refresh_token": "private-refresh-token",
                      "scopes": [YouTubeAccountService.SCOPE], "expires_at": NOW + 3600}
        self.writes = 0

    def get(self, platform):
        assert platform == "youtube"
        return deepcopy(self.value)

    def set(self, *args):
        self.writes += 1
        pytest.fail("read-only operations must not write credentials")


class Fixture:
    def __init__(self):
        self.vault, self.calls, self.hook = Vault(), [], None
        self.broadcasts = [{"id": "event_1", "snippet": {"channelId": CHANNEL, "title": "Existing event", "private": "discard"},
                            "status": {"lifeCycleStatus": "ready", "privacyStatus": "unlisted"},
                            "contentDetails": {"boundStreamId": "stream_1", "enableAutoStart": False, "enableAutoStop": True}}]
        self.streams = [{"id": "stream_1", "snippet": {"channelId": CHANNEL}, "status": {"streamStatus": "ready"},
                         "cdn": {"ingestionType": "rtmp", "ingestionInfo": {"streamName": "private-stream-key",
                            "rtmpsIngestionAddress": "rtmps://a.rtmps.youtube.com/live2",
                            "ingestionAddress": "rtmp://a.rtmp.youtube.com/live2"}}}]
        self.next_page = None
        self.persistent_broadcasts = []
        self.response_override = None
        self.owner = YouTubeAccountService(self.vault, clock=lambda: NOW,
            http_factory=self.factory)
        self.service = module.YouTubeDestinationService(self.owner, http_factory=self.factory, clock=lambda: NOW)

    def factory(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), follow_redirects=False)

    async def handle(self, request):
        self.calls.append(request)
        assert request.method == "GET", "No refresh or provider write is permitted in these operations"
        assert str(request.url).split("?", 1)[0] in {module.CHANNELS_URL, module.BROADCASTS_URL, module.STREAMS_URL}
        assert request.headers["authorization"] == "Bearer private-access-token"
        if self.hook:
            await self.hook(request)
        if self.response_override is not None:
            return self.response_override(request)
        if request.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": CHANNEL}]})
        if request.url.path.endswith("/liveBroadcasts"):
            assert request.url.params["mine"] == "true"
            assert set(request.url.params).intersection({"mine", "id", "broadcastStatus"}) == {"mine"}
            assert request.url.params["broadcastType"] == "all"
            items = self.broadcasts + (self.persistent_broadcasts if request.url.params.get("broadcastType") == "all" else [])
            return httpx.Response(200, json={"items": items, **({"nextPageToken": self.next_page} if self.next_page else {})})
        ids = request.url.params["id"].split(",")
        return httpx.Response(200, json={"items": [item for item in self.streams if item["id"] in ids]})

    def request(self):
        ref = module.account_ref(self.vault.value)
        return {"accountRef": ref, "broadcastId": "event_1", "streamId": "stream_1",
                "settingsFingerprint": module.settings_fingerprint(ref, "event_1", "stream_1", False, True, "unlisted")}


def test_saved_status_and_readonly_selection_use_existing_owner_without_refresh_or_secret_exposure():
    async def run():
        f = Fixture()
        status = f.owner.status()
        assert status["streaming_authorized"] and status["account_ref"] == module.account_ref(f.vault.value)
        assert f.calls == []
        listed = await f.service.list_broadcasts()
        selection = await f.service.inspect_broadcast("event_1")
        assert listed["broadcasts"] == [selection]
        assert selection["auto_start"] is False and selection["auto_stop"] is True
        assert selection["privacy_status"] == "unlisted"
        assert selection["stream_status"] == "ready" and selection["lifecycle"] == "ready"
        assert selection["settings_fingerprint"] == f.request()["settingsFingerprint"]
        public = json.dumps([status, listed, selection])
        for private in ["private-", "rtmps://", "streamName", "client_secret", "access_token", "refresh_token"]:
            assert private not in public
        assert f.vault.writes == 0 and all(call.method == "GET" for call in f.calls)
    asyncio.run(run())


@pytest.mark.parametrize("change,reason", [
    ("foreign_broadcast", "youtube_broadcast_not_owned"),
    ("foreign_stream", "youtube_stream_not_owned"),
    ("unbound", "youtube_stream_unavailable"),
    ("completed", "youtube_broadcast_unavailable"),
    ("missing_flags", "invalid_provider_response"),
    ("missing_privacy", "invalid_provider_response"),
    ("invalid_privacy", "invalid_provider_response"),
    ("stream_error", "youtube_stream_unavailable"),
    ("stream_created", "youtube_stream_unavailable"),
    ("shared", "youtube_stream_shared"),
    ("rtmp_only", "secure_ingest_unavailable"),
])
def test_inspection_fails_closed_for_unowned_unusable_or_ambiguous_selections(change, reason):
    async def run():
        f = Fixture()
        if change == "foreign_broadcast": f.broadcasts[0]["snippet"]["channelId"] = "UCforeign"
        elif change == "foreign_stream": f.streams[0]["snippet"]["channelId"] = "UCforeign"
        elif change == "unbound": f.broadcasts[0]["contentDetails"].pop("boundStreamId")
        elif change == "completed": f.broadcasts[0]["status"]["lifeCycleStatus"] = "complete"
        elif change == "missing_flags": f.broadcasts[0]["contentDetails"].pop("enableAutoStart")
        elif change == "missing_privacy": f.broadcasts[0]["status"].pop("privacyStatus")
        elif change == "invalid_privacy": f.broadcasts[0]["status"]["privacyStatus"] = "friends-only"
        elif change == "stream_error": f.streams[0]["status"]["streamStatus"] = "error"
        elif change == "stream_created": f.streams[0]["status"]["streamStatus"] = "created"
        elif change == "shared": f.broadcasts.append({**deepcopy(f.broadcasts[0]), "id": "event_other"})
        else: f.streams[0]["cdn"]["ingestionInfo"].pop("rtmpsIngestionAddress")
        with pytest.raises(ValueError, match="^" + reason + "$"):
            await f.service.inspect_broadcast("event_1")
        assert f.vault.writes == 0
    asyncio.run(run())


def test_changed_account_during_provider_await_suppresses_the_result():
    async def run():
        f = Fixture()
        async def change(_request):
            f.vault.value["access_token"] = "other-private-account-token"
        f.hook = change
        with pytest.raises(ValueError, match="^account_state_changed$"):
            await f.service.list_broadcasts()
    asyncio.run(run())


def test_persistent_broadcasts_are_included_when_checking_for_a_shared_stream():
    async def run():
        f = Fixture()
        persistent = deepcopy(f.broadcasts[0])
        persistent["id"] = "persistent_broadcast"
        persistent["snippet"]["isDefaultBroadcast"] = True
        f.persistent_broadcasts = [persistent]
        assert (await f.service.list_broadcasts())["broadcasts"] == []
        with pytest.raises(ValueError, match="^youtube_stream_shared$"):
            await f.service.inspect_broadcast("event_1")
        assert all(call.url.params["broadcastType"] == "all" for call in f.calls if call.url.path.endswith("/liveBroadcasts"))
        assert f.vault.writes == 0
    asyncio.run(run())


@pytest.mark.parametrize("failure,reason", [("redirect", "provider_unavailable"), ("oversized", "provider_response_too_large"),
    ("wrong_type", "invalid_provider_response"), ("looping_page", "invalid_provider_response")])
def test_transport_and_pagination_are_bounded_without_returning_provider_text(failure, reason):
    async def run():
        f = Fixture()
        if failure == "redirect": f.response_override = lambda _: httpx.Response(302, headers={"Location": "https://foreign.invalid/private"})
        elif failure == "oversized": f.response_override = lambda _: httpx.Response(200, content=b"x" * (module.MAX_BYTES + 1), headers={"Content-Type": "application/json"})
        elif failure == "wrong_type": f.response_override = lambda _: httpx.Response(200, text="private provider diagnostics")
        else: f.next_page = "same_page"
        with pytest.raises(ValueError, match="^" + reason + "$"):
            await f.service.list_broadcasts()
        assert len(f.calls) <= 3
    asyncio.run(run())


def test_private_helper_returns_only_exact_current_ingest_over_its_private_contract():
    async def run():
        f = Fixture()
        result = await helper.resolve_stream_key(f.request(), vault=f.vault, http_factory=f.factory, clock=lambda: NOW)
        assert result == {"ok": True, "platform": "youtube", **f.request(), "autoStart": False, "autoStop": True, "privacyStatus": "unlisted",
                          "serverUrl": "rtmps://a.rtmps.youtube.com/live2", "streamKey": "private-stream-key"}
        assert f.vault.writes == 0 and len(f.calls) == 3
        assert not any("oauth" in str(call.url) for call in f.calls)
    asyncio.run(run())


@pytest.mark.parametrize("privacy", ["public", "unlisted", "private"])
def test_reviewed_visibility_is_explicit_and_pinned_in_the_v2_private_contract(privacy):
    async def run():
        f = Fixture()
        f.broadcasts[0]["status"]["privacyStatus"] = privacy
        selection = await f.service.inspect_broadcast("event_1")
        request = {**f.request(), "settingsFingerprint": selection["settings_fingerprint"]}
        result = await helper.resolve_stream_key(request, vault=f.vault, http_factory=f.factory, clock=lambda: NOW)
        assert selection["privacy_status"] == result["privacyStatus"] == privacy
        assert selection["settings_fingerprint"] == module.settings_fingerprint(request["accountRef"], "event_1", "stream_1", False, True, privacy)
        assert len({module.settings_fingerprint(request["accountRef"], "event_1", "stream_1", False, True, value)
                    for value in module.PRIVACY_STATES}) == 3
    asyncio.run(run())


@pytest.mark.parametrize("change,reason", [("auto_start", "broadcast_selection_changed"), ("auto_stop", "broadcast_selection_changed"),
    ("privacy", "broadcast_selection_changed"),
    ("binding", "broadcast_selection_changed"), ("expired", "authorization_refresh_required"),
    ("scope", "streaming_scope_required"), ("account", "account_identity_mismatch"), ("vault_race", "account_state_changed")])
def test_private_helper_rechecks_reviewed_settings_identity_expiry_and_vault(change, reason):
    async def run():
        f = Fixture()
        request = f.request()
        if change in {"auto_start", "auto_stop"}:
            field = "enableAutoStart" if change == "auto_start" else "enableAutoStop"
            f.broadcasts[0]["contentDetails"][field] = not f.broadcasts[0]["contentDetails"][field]
        elif change == "privacy": f.broadcasts[0]["status"]["privacyStatus"] = "public"
        elif change == "binding":
            f.broadcasts[0]["contentDetails"]["boundStreamId"] = "stream_other"
            f.streams[0]["id"] = "stream_other"
        elif change == "expired": f.vault.value["expires_at"] = NOW + 29
        elif change == "scope": f.vault.value["scopes"] = []
        elif change == "account": request["accountRef"] = "a" * 64
        else:
            async def hook(_request): f.vault.value["access_token"] = "changed-private-token"
            f.hook = hook
        with pytest.raises(ValueError, match="^" + reason + "$"):
            await helper.resolve_stream_key(request, vault=f.vault, http_factory=f.factory, clock=lambda: NOW)
        assert f.vault.writes == 0
        if change in {"expired", "scope", "account"}: assert f.calls == []
    asyncio.run(run())


def test_selection_http_guard_projection_and_error_redaction():
    f = Fixture()
    app = FastAPI()
    allowed = True
    app.include_router(create_youtube_destination_router(f.service, lambda _: allowed))
    client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234))
    path = "/api/production/accounts/youtube/"
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert client.post(path + "broadcasts", json={}).status_code == 403 and f.calls == []
    assert client.post(path + "broadcasts", json={}, headers={"Origin": "https://foreign.invalid"}).status_code == 403
    assert client.post(path + "inspect-broadcast", json={"broadcast_id": "../private"}, headers=headers).status_code == 400
    assert client.post(path + "broadcasts", content=b"x" * 1025, headers={**headers, "Content-Type": "application/json"}).status_code == 400
    result = client.post(path + "broadcasts", json={}, headers=headers)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    selection = client.post(path + "inspect-broadcast", json={"broadcast_id": "event_1"}, headers=headers).json()["selection"]
    assert result.json()["broadcasts"] == [selection]
    assert "private-" not in result.text and "streamKey" not in result.text and "rtmps://" not in result.text
    allowed = False
    assert client.post(path + "broadcasts", json={}, headers=headers).status_code == 403
    allowed = True
    async def failed(): raise RuntimeError("private provider diagnostic and credential")
    f.service.list_broadcasts = failed
    failure = client.post(path + "broadcasts", json={}, headers=headers)
    assert failure.status_code == 409 and failure.json() == {"ok": False, "reason": "provider_unavailable"}


def test_native_helper_rejects_extra_private_input_fields_before_access():
    async def run():
        f = Fixture()
        for invalid in [{**f.request(), "streamKey": "untrusted"}, {**f.request(), "settingsFingerprint": "bad"}, {**f.request(), "broadcastId": "../private"}]:
            with pytest.raises(ValueError):
                await helper.resolve_stream_key(invalid, vault=f.vault, http_factory=f.factory, clock=lambda: NOW)
        assert f.calls == [] and f.vault.writes == 0
    asyncio.run(run())


def test_helper_cli_bounds_and_redacts_invalid_private_input(monkeypatch, capsys):
    monkeypatch.setattr(helper.sys, "argv", ["desktop_youtube_account.py"])
    for data in [b'{"private-provider-value":', b"x" * 1025, b"\xff"]:
        monkeypatch.setattr(helper.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
        assert helper.main() == 2
        assert json.loads(capsys.readouterr().out) == {"ok": False, "reason": "invalid_account_request"}
