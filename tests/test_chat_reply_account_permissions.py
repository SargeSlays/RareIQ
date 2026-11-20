"""Explicit reply consent with mocked providers and owned loopback callbacks only."""
import asyncio
from copy import deepcopy
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import test_twitch_account_service as twitch
import test_youtube_account_service as youtube
import test_kick_account_service as kick
from test_metadata_account_permissions import fixture
from rareiq.web.platform_accounts import create_platform_accounts_router, _kick_authorization_url, _google_authorization_url


async def complete(f, provider, *, grant=True, identity=True, denied=False, missing_base=False):
    scopes = list(f.service._pending["scopes"])
    if not grant:
        scopes.remove(f.service.CHAT_REPLY_SCOPE)
    if missing_base:
        scopes.remove(f.service.SCOPE.split()[0])
    if provider == "twitch":
        f.validation["scopes"] = scopes
        if not identity:
            f.validation["user_id"] = "456"
        f.tokens.append((400, {"error": "access_denied"}) if denied else twitch.token())
        await f.tick()
    elif provider == "youtube":
        f.token_response["scope"] = " ".join(scopes)
        if not identity:
            f.channels["items"][0]["id"] = "UC" + "b" * 22
        await f.callback(query={"state": f.service._pending["state"], "error": "access_denied"}) if denied else await f.callback()
    else:
        f.introspection["scope"] = " ".join(scopes)
        if not identity:
            f.users[0]["user_id"] = f.channels[0]["broadcaster_user_id"] = 456
        await kick.callback(f, error="access_denied") if denied else await kick.callback(f)


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
@pytest.mark.parametrize("outcome", ["success", "missing_scope", "missing_base", "identity", "denied", "cancel", "vault_changed"])
def test_explicit_reply_consent_is_purpose_bound_and_only_saves_complete_same_account_grant(provider, outcome):
    async def run():
        f = fixture(provider)
        before = deepcopy(f.vault.value)
        assert not f.service.status()["chat_reply_authorized"] and not f.calls
        pending = await f.service.begin_replies()
        assert pending["state"] == "pending" and pending["authorization_kind"] == "replies"
        assert pending["authorized"] and not pending["chat_reply_authorized"]
        if provider == "twitch":
            requested = f.calls[-1][2]["scopes"].split()
        else:
            requested = parse_qs(urlsplit(f.service.authorization_url(pending["flow_id"])).query)["scope"][0].split()
        assert len(requested) == len(set(requested))
        assert set(requested) == set(before["scopes"]) | {f.service.CHAT_REPLY_SCOPE}
        if provider in {"twitch", "kick"}:
            assert f.service.METADATA_SCOPE not in requested
        if outcome == "cancel":
            await f.service.cancel()
        else:
            if outcome == "vault_changed":
                f.vault.value["access_token"] = "newer-external-synthetic-access"
            await complete(f, provider, grant=outcome != "missing_scope", identity=outcome != "identity",
                           denied=outcome == "denied", missing_base=outcome == "missing_base")
        status = f.service.status()
        assert status["chat_reply_authorized"] is (outcome == "success")
        assert "private-" not in str(status) and "synthetic-access" not in str(status)
        if outcome == "success":
            assert set(f.vault.value["scopes"]) == set(requested)
        else:
            assert not f.vault.saves
            expected = {"missing_scope": "chat_send_permission_required", "identity": "account_identity_mismatch",
                "denied": "authorization_denied", "cancel": "authorization_cancelled", "vault_changed": "account_state_changed",
                "missing_base": "streaming_scope_required" if provider == "kick" else "chat_scope_required"}[outcome]
            assert status["reason"] == expected
            if outcome != "vault_changed":
                assert f.vault.value == before
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
@pytest.mark.parametrize("metadata", [False, True])
def test_legacy_sign_in_retains_existing_reply_and_metadata_grants_without_new_privilege(provider, metadata):
    async def run():
        f = fixture(provider, edit=metadata)
        f.vault.value["scopes"] = list(dict.fromkeys([*f.vault.value["scopes"], f.service.CHAT_REPLY_SCOPE]))
        before = set(f.vault.value["scopes"])
        assert f.service.status()["chat_reply_authorized"]
        status = await f.service.begin()
        assert status["authorization_kind"] == "chat"
        assert set(f.service._pending["scopes"]) == before
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_fresh_ordinary_sign_in_does_not_request_reply_permission(provider):
    async def run():
        module = {"twitch": twitch, "youtube": youtube, "kick": kick}[provider]
        f = module.Fixture(stored=module.record())
        before_calls = len(f.calls)
        for _ in range(2):
            assert not f.service.status()["chat_reply_authorized"]
        assert len(f.calls) == before_calls
        await f.service.begin()
        assert f.service.CHAT_REPLY_SCOPE not in f.service._pending["scopes"]
        assert f.service.METADATA_SCOPE not in f.service._pending["scopes"]
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_reply_upgrade_preserves_previously_approved_metadata_permission(provider):
    async def run():
        f = fixture(provider, edit=True)
        expected = set(f.vault.value["scopes"]) | {f.service.CHAT_REPLY_SCOPE}
        await f.service.begin_replies()
        assert set(f.service._pending["scopes"]) == expected
        assert len(f.service._pending["scopes"]) == len(expected)
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["twitch", "youtube", "kick"])
def test_reply_begin_route_requires_explicit_empty_same_origin_command_and_projects_purpose(provider):
    class Owner:
        def __init__(self):
            self.begins = 0
        def status(self):
            return {"platform": provider, "state": "pending" if self.begins else "authorized",
                "reason": "authorization_pending" if self.begins else "account_authorized", "authorized": True,
                "app_configured": True, "chat_reply_authorized": False, "authorization_kind": "replies",
                "flow_id": "a" * 32, "expires_at": 1800000600, "user_code": "TEST-1234", "poll_after": 5,
                "access_token": "private-should-never-cross-route"}
        async def begin_replies(self):
            self.begins += 1
    owner, app, audits = Owner(), FastAPI(), []
    app.include_router(create_platform_accounts_router(owner, lambda request: True, youtube_service=owner, kick_service=owner,
        audit=lambda **value: audits.append(value)))
    path = f"/api/production/accounts/{provider}/replies/begin"
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1)) as client:
        assert client.post(path, json={}).status_code == 403
        headers = {"Origin": "http://127.0.0.1:8765"}
        assert client.post(path, headers=headers, json={"scope": "injected"}).status_code == 400
        assert owner.begins == 0
        result = client.post(path, headers=headers, json={})
        assert result.status_code == 200
        assert result.json()["account"]["authorization_kind"] == "replies"
        assert result.json()["account"]["chat_reply_authorized"] is False
        assert "private-" not in result.text
        assert audits == [{"action": provider + ".begin_replies", "outcome": "requested"}, {"action": provider + ".begin_replies", "outcome": "pending"}]
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("192.0.2.1", 1)) as remote:
        assert remote.post(path, headers={"Origin": "http://127.0.0.1:8765"}, json={}).status_code == 403
    assert owner.begins == 1


@pytest.mark.parametrize("metadata", [False, True])
def test_kick_reply_authorization_url_boundary_accepts_only_exact_base_preserved_metadata_and_reply_scope(metadata):
    async def run():
        f = fixture("kick", edit=metadata)
        await f.service.begin_replies()
        url = f.service.authorization_url(f.service.status()["flow_id"])
        # Test uses an ephemeral callback listener; the public boundary pins installed port 8770.
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        query["redirect_uri"] = "http://localhost:8770/callback"
        pinned = f.service.AUTHORIZE_URL + "?" + urlencode(query)
        assert _kick_authorization_url(pinned) == pinned
        with pytest.raises(ValueError):
            _kick_authorization_url(pinned.replace("chat%3Awrite", "moderation%3Aban"))
        await f.service.close()
    asyncio.run(run())


def test_youtube_reply_scope_url_is_readonly_then_force_ssl_and_retains_pkce():
    async def run():
        f = fixture("youtube")
        await f.service.begin_replies()
        url = f.service.authorization_url(f.service.status()["flow_id"])
        assert _google_authorization_url(url) == url
        query = parse_qs(urlsplit(url).query)
        assert query["scope"] == [f.service.SCOPE + " " + f.service.CHAT_REPLY_SCOPE]
        assert query["code_challenge_method"] == ["S256"] and len(query["code_challenge"][0]) == 43
        await f.service.close()
    asyncio.run(run())
