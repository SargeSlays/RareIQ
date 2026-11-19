"""Explicit metadata upgrades and private operation guards, using synthetic accounts only."""
import asyncio
from copy import deepcopy
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rareiq.web.platform_accounts import create_platform_accounts_router, _google_authorization_url, _kick_authorization_url

import test_twitch_account_service as twitch
import test_youtube_account_service as youtube
import test_kick_account_service as kick


def fixture(provider, *, edit=False):
    module = {"twitch": twitch, "youtube": youtube, "kick": kick}[provider]
    stored = module.record()
    if provider == "twitch":
        stored["scopes"].append("channel:read:stream_key")
    service_type = {"twitch": twitch.TwitchAccountService, "youtube": youtube.YouTubeAccountService,
                    "kick": kick.KickAccountService}[provider]
    if edit:
        stored["scopes"].append(service_type.METADATA_SCOPE)
    f = module.Fixture(stored=stored)
    if provider == "twitch":
        f.validation["scopes"] = list(stored["scopes"])
    elif provider == "kick":
        f.introspection["scope"] = " ".join(stored["scopes"])
    return f


async def complete(f, provider, *, grant=True, identity=True, denied=False):
    if provider == "twitch":
        if grant:
            f.validation["scopes"].append(f.service.METADATA_SCOPE)
        if not identity:
            f.validation["user_id"] = "456"
        f.tokens.append((400, {"error": "access_denied"}) if denied else twitch.token())
        await f.tick()
    elif provider == "youtube":
        if grant:
            f.token_response["scope"] += " " + f.service.METADATA_SCOPE
        if not identity:
            f.channels["items"][0]["id"] = "UC" + "b" * 22
        await f.callback(query={"state": f.service._pending["state"], "error": "access_denied"}) if denied else await f.callback()
    else:
        if grant:
            f.introspection["scope"] += " " + f.service.METADATA_SCOPE
        if not identity:
            f.users[0]["user_id"] = f.channels[0]["broadcaster_user_id"] = 456
        await kick.callback(f, error="access_denied") if denied else await kick.callback(f)


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
@pytest.mark.parametrize("outcome", ["success", "missing_scope", "identity", "denied", "cancel"])
def test_metadata_consent_preserves_base_permissions_and_only_replaces_verified_same_account(provider, outcome):
    async def run():
        f = fixture(provider)
        before = deepcopy(f.vault.value)
        assert f.service.status()["authorized"] and not f.service.status()["metadata_authorized"]
        status = await f.service.begin_metadata()
        assert status["state"] == "pending" and status["authorization_kind"] == "metadata"
        assert status["authorized"] and not status["metadata_authorized"]
        if provider == "twitch":
            requested = f.calls[-1][2]["scopes"].split()
        else:
            requested = parse_qs(urlsplit(f.service.authorization_url(status["flow_id"])).query)["scope"][0].split()
        assert set(requested) == set(before["scopes"]) | {f.service.METADATA_SCOPE}
        if outcome == "cancel":
            await f.service.cancel()
        else:
            await complete(f, provider, grant=outcome != "missing_scope", identity=outcome != "identity",
                           denied=outcome == "denied")
        final = f.service.status()
        assert final["authorized"]
        assert final["metadata_authorized"] is (outcome == "success")
        if outcome != "success":
            assert f.vault.value == before and not f.vault.saves
            expected = {"missing_scope": "metadata_scope_required", "identity": "account_identity_mismatch",
                        "denied": "authorization_denied", "cancel": "authorization_cancelled"}[outcome]
            assert final["reason"] == expected
        else:
            assert set(f.vault.value["scopes"]) == set(requested)
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_reauthorization_retains_existing_metadata_grant(provider):
    async def run():
        f = fixture(provider, edit=True)
        status = await f.service.begin()
        requested = f.service._pending["scopes"]
        assert f.service.METADATA_SCOPE in requested and status["metadata_authorized"]
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_private_hook_keeps_old_read_grants_usable_and_edit_fails_closed(provider):
    async def run():
        f = fixture(provider)
        called = []
        async def read(record, guard):
            assert f.service._credential_lock.locked()
            guard()
            assert all(record.get(key) for key in ("access_token", "client_id", "channel_id", "scopes"))
            record["scopes"].clear()
            called.append(True)
            return {"title": "Synthetic title"}
        assert await f.service.with_stream_info_access(read) == {"title": "Synthetic title"}
        with pytest.raises(Exception, match="^metadata_scope_required$"):
            await f.service.with_stream_info_access(read, require_edit=True)
        assert called == [True] and f.service.status()["authorized"]
        assert f.vault.value["scopes"]
        await f.service.close()
        with pytest.raises(Exception, match="^account_state_changed$|^authorization_required$"):
            await f.service.with_stream_info_access(read)
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
@pytest.mark.parametrize("change", ["cancel", "token", "channel", "config"])
def test_private_hook_guard_rejects_midoperation_account_changes(provider, change):
    async def run():
        f = fixture(provider, edit=True)
        async def update(_record, guard):
            guard()
            if change == "cancel":
                await f.service.cancel()
            elif change == "config":
                if provider == "twitch":
                    f.service._client_id_provider = lambda: "different-app"
                else:
                    f.service._app_config_provider = lambda: {"client_id": "different.apps.googleusercontent.com"
                        if provider == "youtube" else "different-app", "client_secret": "synthetic-secret"}
            else:
                f.vault.value["access_token" if change == "token" else "channel_id"] = "changed"
            guard()
            raise AssertionError("stale operation must not continue")
        with pytest.raises(Exception, match="^account_state_changed$"):
            await f.service.with_stream_info_access(update, require_edit=True)
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_private_hook_rejects_missing_grant_and_guard_expires_when_operation_ends(provider):
    async def run():
        f = fixture(provider, edit=True)
        held = []
        async def operation(_record, guard):
            held.append(guard)
            guard()
        await f.service.with_stream_info_access(operation, require_edit=True)
        with pytest.raises(Exception, match="^account_state_changed$"):
            held[0]()
        f.vault.value = None
        reason = "app_setup_required" if provider == "youtube" else "authorization_required"
        with pytest.raises(Exception, match="^" + reason + "$"):
            await f.service.with_stream_info_access(operation)
        assert len(held) == 1
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
@pytest.mark.parametrize("reason", [
    "app_setup_required", "provider_unavailable", "invalid_provider_response", "provider_rate_limited",
    "account_storage_unavailable", "authorization_refresh_required", "authorization_rejected",
    "account_identity_mismatch", "synthetic-private-detail", None,
])
def test_private_hook_preserves_only_safe_owner_failures_without_entering_metadata_operation(provider, reason):
    async def run():
        f = fixture(provider)
        before = deepcopy(f.vault.value)
        async def unavailable():
            f.service._reason = reason
            return None
        if provider == "twitch":
            f.service.ensure_credentials = unavailable
        else:
            f.service.ensure_authorization = unavailable
        called = []
        async def operation(record, guard):
            called.append(record)
            raise AssertionError("Failed authorization must never provide credentials")
        expected = "authorization_required" if reason in {None, "synthetic-private-detail"} else reason
        for require_edit in (False, True):
            with pytest.raises(Exception, match="^" + expected + "$"):
                await f.service.with_stream_info_access(operation, require_edit=require_edit)
        assert not called and not f.calls and f.vault.value == before and not f.vault.saves
        assert f.service.status()["authorized"]
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_validation_outage_keeps_saved_read_authorization_but_blocks_metadata_with_retryable_failure(provider):
    async def run():
        f = fixture(provider)
        if provider == "youtube":
            f.vault.value["expires_at"] = f.now + 20
        before = deepcopy(f.vault.value)
        async def unavailable(*_args):
            return httpx.Response(503, json={"error": "synthetic-private-detail"})
        f.hook = unavailable
        called = []
        async def operation(record, guard):
            called.append(record)
        with pytest.raises(Exception, match="^provider_unavailable$"):
            await f.service.with_stream_info_access(operation)
        assert not called and f.calls and f.vault.value == before and not f.vault.saves
        assert f.service.status()["authorized"]
        assert f.service.status()["reason"] == "provider_unavailable"
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_metadata_routes_keep_operator_origin_body_audit_and_public_status_boundaries(provider):
    class Account:
        starts = 0
        def status(self):
            return {"platform": provider, "state": "authorized", "reason": "account_authorized",
                    "authorized": True, "metadata_authorized": True, "app_configured": True,
                    "access_token": "synthetic-private-access", "channel_id": "synthetic-private-channel"}
        async def begin_metadata(self):
            self.starts += 1
    account, audits = Account(), []
    app = FastAPI()
    app.include_router(create_platform_accounts_router(account, lambda _: True,
        youtube_service=account, kick_service=account, audit=lambda **event: audits.append(event)))
    client = TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234))
    path = "/api/production/accounts/" + provider + "/begin-metadata"
    assert client.post(path, json={}).status_code == 403
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert client.post(path, json={"scope": "arbitrary:write"}, headers=headers).status_code == 400
    result = client.post(path, json={}, headers=headers)
    assert result.status_code == 200 and result.json()["account"]["metadata_authorized"]
    assert account.starts == 1 and "synthetic-private" not in result.text
    assert audits == [{"action": provider + ".begin_metadata", "outcome": "requested"},
                      {"action": provider + ".begin_metadata", "outcome": "authorized"}]


@pytest.mark.parametrize("provider", ["youtube", "kick"])
def test_authorization_url_boundary_accepts_only_exact_base_or_metadata_scope_sets(provider):
    if provider == "youtube":
        validate = _google_authorization_url
        endpoint = youtube.YouTubeAccountService.AUTHORIZE_URL
        base, extra = [youtube.SCOPE], youtube.YouTubeAccountService.METADATA_SCOPE
        query = {"client_id": youtube.CLIENT, "redirect_uri": "http://127.0.0.1:54321/callback",
                 "response_type": "code", "access_type": "offline", "prompt": "consent"}
    else:
        validate = _kick_authorization_url
        endpoint = kick.KickAccountService.AUTHORIZE_URL
        base, extra = kick.SCOPES.split(), kick.KickAccountService.METADATA_SCOPE
        query = {"client_id": kick.CONFIG["client_id"], "redirect_uri": "http://localhost:8770/callback",
                 "response_type": "code"}
    query.update(state="s" * 43, code_challenge="c" * 43, code_challenge_method="S256")
    for scopes in (base, base + [extra], [extra] + base):
        url = endpoint + "?" + urlencode({**query, "scope": " ".join(scopes)})
        assert validate(url) == url
    for scopes in ([extra], base + [extra, extra], base + ["arbitrary:write"], base + ["", extra]):
        with pytest.raises(ValueError, match="^invalid_authorization_url$"):
            validate(endpoint + "?" + urlencode({**query, "scope": " ".join(scopes)}))
