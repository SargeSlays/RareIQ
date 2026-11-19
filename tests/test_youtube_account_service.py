"""Own transient loopback listener plus fake Google responses; no external calls."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from rareiq.services.youtube_account_service import YouTubeAccountService


NOW = 1800000000.0
CLIENT = "fixture-app.apps.googleusercontent.com"
SECRET = "private-google-client-secret"
ACCESS = "private-google-access-token"
REFRESH = "private-google-refresh-token"
CODE = "private-google-authorization-code"
CHANNEL = "UC" + "a" * 22
SCOPE = YouTubeAccountService.SCOPE
CONFIG = {"client_id": CLIENT, "client_secret": SECRET}
_DEFAULT = object()


def record(**changes):
    return {**CONFIG, "access_token": ACCESS, "refresh_token": REFRESH, "token_type": "bearer",
            "expires_at": NOW + 3600, "scopes": [SCOPE], "channel_id": CHANNEL,
            "public_label": "Fixture channel"} | changes


def test_explicit_check_verifies_the_owned_channel_without_extending_token_expiry_or_exposing_secrets():
    async def run():
        f = Fixture(stored=record())
        async def delay(_request, _form):
            f.now += 8
        f.hook = delay
        status = await f.service.check()
        assert status["authorized"] and status["reason"] == "account_authorized"
        assert len(f.calls) == 1 and f.calls[0][0] == "GET"
        assert f.vault.value["expires_at"] == NOW + 3600
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("response,reason", [
    ((401, {"error": "private-provider-detail"}), "authorization_rejected"),
    ({"items": [{"id": "UC" + "b" * 22, "snippet": {"title": "Different channel"}}]}, "account_identity_mismatch"),
])
def test_check_rejects_revoked_or_switched_channel_and_never_serves_its_cached_authorization(response, reason):
    async def run():
        f = Fixture(stored=record())
        f.channels = response
        status = await f.service.check()
        assert not status["authorized"] and status["reason"] == reason
        assert await f.service.ensure_authorization() is None
        assert len(f.calls) == 1 and f.vault.saves == []
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


def test_check_provider_outage_preserves_saved_record_but_reports_the_failure():
    async def run():
        previous = record()
        f = Fixture(stored=previous)
        f.channels = (500, {"error": "private-provider-detail"})
        status = await f.service.check()
        assert status["authorized"] and status["reason"] == "provider_unavailable"
        assert f.vault.value == previous and f.vault.saves == []
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("remaining", [3600, 20])
def test_owned_check_or_refresh_during_pending_sign_in_preserves_the_callback_snapshot(remaining):
    async def run():
        f = Fixture(stored=record(expires_at=NOW + remaining))
        await f.service.begin()
        flow = f.service._pending["flow_id"]
        checked = await f.service.check()
        assert checked["state"] == "pending" and checked["flow_id"] == flow
        response = await f.callback()
        assert b"Sign-in complete" in response
        assert f.service.status()["reason"] == "account_authorized"
        await f.service.close()
    asyncio.run(run())


def test_external_vault_write_after_owned_check_still_rejects_stale_sign_in():
    async def run():
        f = Fixture(stored=record())
        await f.service.begin()
        await f.service.check()
        f.vault.value["access_token"] = "newer-external-private-token"
        await f.callback()
        assert f.service.status()["reason"] == "account_state_changed"
        assert f.vault.value["access_token"] == "newer-external-private-token"
        await f.service.close()
    asyncio.run(run())


def test_disconnect_invalidates_an_inflight_check_and_forgets_only_authorization():
    async def run():
        f = Fixture(stored=record())
        entered, release = asyncio.Event(), asyncio.Event()
        async def hold(_request, _form):
            entered.set()
            await release.wait()
        f.hook = hold
        checking = asyncio.create_task(f.service.check())
        await entered.wait()
        disconnecting = asyncio.create_task(f.service.disconnect())
        await asyncio.sleep(0)
        release.set()
        await checking
        status = await disconnecting
        assert not status["authorized"] and status["reason"] == "account_disconnected"
        assert status["app_configured"]
        assert f.vault.value["client_id"] == CLIENT and f.vault.value["client_secret"] == SECRET
        assert all(not f.vault.value[k] for k in ["access_token", "refresh_token", "channel_id", "scopes", "public_label"])
        assert len(f.vault.saves) == 1
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


def test_disconnect_survives_encrypted_vault_reopen_and_preserves_other_accounts(tmp_path):
    from rareiq.core.platform_credentials import PlatformCredentialVault
    class Cipher:
        available = True
        def encrypt(self, value):
            return b"synthetic-cipher:" + value[::-1]
        def decrypt(self, value):
            assert value.startswith(b"synthetic-cipher:")
            return value[len(b"synthetic-cipher:"):][::-1]
    async def run():
        path = tmp_path / "accounts.json"
        vault = PlatformCredentialVault(path, cipher=Cipher())
        vault.set("youtube", record())
        vault.set("twitch", {"client_id": "other-client", "refresh_token": "other-private-refresh"})
        other = vault.get("twitch")
        service = YouTubeAccountService(vault, clock=lambda: NOW)
        assert (await service.disconnect())["reason"] == "account_disconnected"
        reopened = PlatformCredentialVault(path, cipher=Cipher())
        saved = reopened.get("youtube")
        assert saved["client_id"] == CLIENT and saved["client_secret"] == SECRET
        assert all(not saved[k] for k in ["access_token", "refresh_token", "channel_id", "scopes", "public_label"])
        assert reopened.get("twitch") == other
        assert YouTubeAccountService(reopened, clock=lambda: NOW).status()["authorized"] is False
        assert ACCESS not in path.read_text() and REFRESH not in path.read_text()
        await service.close()
    asyncio.run(run())


def test_missing_configuration_check_disconnect_are_network_free_and_storage_failures_are_redacted():
    async def run():
        f = Fixture(stored=None)
        assert not (await f.service.check())["app_configured"] and f.calls == []
        assert not (await f.service.disconnect())["authorized"] and f.calls == []
        await f.service.close()
        f = Fixture(stored=record())
        f.vault.fail_set = True
        status = await f.service.disconnect()
        assert status["reason"] == "account_storage_unavailable" and f.vault.value == record()
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


def token(**changes):
    return {"access_token": ACCESS, "refresh_token": REFRESH, "token_type": "Bearer",
            "expires_in": 3600, "scope": SCOPE} | changes


class FakeVault:
    def __init__(self, value):
        self.value, self.saves = deepcopy(value), []
        self.fail_get = self.fail_set = False

    def get(self, platform):
        assert platform == "youtube"
        if self.fail_get:
            raise RuntimeError("private vault path")
        return deepcopy(self.value)

    def set(self, platform, value):
        assert platform == "youtube"
        if self.fail_set:
            raise RuntimeError("private vault write")
        self.value = deepcopy(value)
        self.saves.append(deepcopy(value))


def test_cached_private_authorization_does_not_refresh_or_expose_refresh_credentials():
    async def run():
        f = Fixture(stored=record())
        authorization = await f.service.ensure_authorization()
        assert authorization == {"access_token": ACCESS, "channel_id": CHANNEL,
            "expires_at": NOW + 3600, "scopes": [SCOPE]}
        authorization["scopes"].clear()
        assert f.vault.value["scopes"] == [SCOPE] and f.calls == []
        assert await f.service.ensure_credentials() == {**CONFIG, "refresh_token": REFRESH, "channel_id": CHANNEL}
        await f.service.close()
    asyncio.run(run())


def test_private_authorization_and_legacy_api_share_one_refresh_and_preserve_omitted_scope():
    async def run():
        f = Fixture(stored=record(expires_at=NOW + 20))
        f.token_response = token(access_token="rotated-private-access", refresh_token="rotated-private-refresh")
        f.token_response.pop("scope")
        first, second, legacy = await asyncio.gather(f.service.ensure_authorization(),
            f.service.ensure_authorization(), f.service.ensure_credentials())
        assert first == second == {"access_token": "rotated-private-access", "channel_id": CHANNEL,
            "expires_at": NOW + 3600, "scopes": [SCOPE]}
        assert legacy == {**CONFIG, "refresh_token": "rotated-private-refresh", "channel_id": CHANNEL}
        assert len(f.calls) == 2 and len(f.vault.saves) == 1
        assert f.vault.value["refresh_token"] == "rotated-private-refresh"
        await f.service.close()
    asyncio.run(run())


def test_cancel_during_private_authorization_refresh_does_not_save_or_return_old_tokens():
    async def run():
        f = Fixture(stored=record(expires_at=NOW + 20))
        async def hook(request, _form):
            if request.url.path == "/youtube/v3/channels":
                await f.service.cancel()
        f.hook = hook
        assert await f.service.ensure_authorization() is None and f.vault.saves == []
        await f.service.close()
        assert await f.service.ensure_authorization() is None
    asyncio.run(run())


class Fixture:
    def __init__(self, stored=_DEFAULT, config_provider=None):
        self.now = NOW
        self.vault = FakeVault(CONFIG if stored is _DEFAULT else stored)
        self.calls = []
        self.token_response = token()
        self.channels = {"items": [{"id": CHANNEL, "snippet": {"title": "Fixture channel"}}]}
        self.hook = None
        self.sleeps = asyncio.Queue()
        self.service = YouTubeAccountService(self.vault, app_config_provider=config_provider,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)),
            clock=lambda: self.now, sleep=self.sleep)

    async def sleep(self, seconds):
        gate = asyncio.get_running_loop().create_future()
        self.sleeps.put_nowait((seconds, gate))
        await gate

    async def http(self, request):
        assert request.url.scheme == "https" and "access_token" not in request.url.params
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.calls.append((request.method, str(request.url), form, dict(request.headers)))
        if self.hook:
            response = await self.hook(request, form)
            if response is not None:
                return response
        if str(request.url) == YouTubeAccountService.TOKEN_URL:
            assert request.method == "POST" and not request.url.query
            value = self.token_response
        elif request.url.host == "www.googleapis.com" and request.url.path == "/youtube/v3/channels":
            assert request.method == "GET" and request.headers["Authorization"].startswith("Bearer ")
            assert request.url.params["mine"] == "true"
            assert set(request.url.params) == {"part", "mine", "maxResults", "fields"}
            value = self.channels
        else:
            raise AssertionError("unexpected fake Google endpoint")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        code, body = value if isinstance(value, tuple) else (200, value)
        return httpx.Response(code, json=body)

    async def callback(self, *, query=None, method="GET", host=None, path="/callback", extra_headers="", raw=None):
        pending = self.service._pending
        port = int(pending["host"].rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        if raw is None:
            query = {"state": pending["state"], "code": CODE} if query is None else query
            target = path + "?" + (query if isinstance(query, str) else urlencode(query))
            raw = (method + " " + target + " HTTP/1.1\r\nHost: " + (host or pending["host"])
                   + "\r\n" + extra_headers + "\r\n").encode("ascii")
        writer.write(raw)
        await writer.drain()
        try:
            return await asyncio.wait_for(reader.read(), 2)
        except ConnectionResetError:
            return b""
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionResetError:
                pass


def assert_redacted(status):
    public = json.dumps(status)
    assert all(value not in public for value in (SECRET, ACCESS, REFRESH, CODE, CHANNEL, "private vault"))
    assert all(key not in status for key in ("access_token", "refresh_token", "client_secret", "client_id", "channel_id", "code_verifier"))


async def until(predicate):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError("fixture condition not reached")


def test_status_and_missing_configuration_never_open_a_listener_or_contact_google():
    async def run():
        f = Fixture(stored=None)
        assert f.service.status()["app_configured"] is False
        assert f.service._pending is None and f.calls == []
        assert (await f.service.begin())["reason"] == "app_setup_required"
        assert f.service._pending is None and f.calls == []
        f.vault.value = dict(CONFIG)
        state = f.service.status()
        assert state["app_configured"] and state["reason"] == "authorization_required"
        assert not state["authorized"] and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_begin_binds_only_random_loopback_and_builds_offline_readonly_pkce_url():
    async def run():
        f = Fixture()
        state = await f.service.begin()
        pending = f.service._pending
        url = urlsplit(state["authorization_url"])
        query = parse_qs(url.query)
        assert url.scheme == "https" and url.netloc == "accounts.google.com" and url.path == "/o/oauth2/v2/auth"
        assert query["scope"] == [SCOPE] and query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
        assert query["response_type"] == ["code"] and query["code_challenge_method"] == ["S256"]
        redirect = urlsplit(query["redirect_uri"][0])
        assert redirect.scheme == "http" and redirect.hostname == "127.0.0.1" and redirect.port > 0
        assert redirect.path == "/callback" and pending["server"].sockets[0].getsockname()[0] == "127.0.0.1"
        expected = base64.urlsafe_b64encode(hashlib.sha256(pending["verifier"].encode()).digest()).rstrip(b"=").decode()
        assert query["code_challenge"] == [expected] and 43 <= len(pending["verifier"]) <= 128
        assert pending["verifier"] not in json.dumps(state)
        assert f.service.authorization_url(state["flow_id"]) == state["authorization_url"]
        assert f.service.authorization_url("wrong-flow") is None
        assert f.calls == [] and not f.vault.saves
        assert_redacted(state)
        await f.service.close()
    asyncio.run(run())


def test_valid_callback_exchanges_pkce_code_validates_owned_channel_and_saves_once():
    async def run():
        f = Fixture()
        state = await f.service.begin()
        pending = f.service._pending
        verifier, redirect, port = pending["verifier"], pending["redirect_uri"], pending["host"].rsplit(":", 1)[1]
        response = await f.callback(query={"state": pending["state"], "code": CODE,
                                          "scope": SCOPE, "authuser": "0", "prompt": "consent"})
        assert b"Sign-in complete" in response and CODE.encode() not in response
        assert b"history.replaceState" in response and b"Content-Security-Policy:" in response
        assert b"Referrer-Policy: no-referrer" in response and b"Cache-Control: no-store" in response
        assert b"<script nonce=" in response and b"default-src 'none'" in response
        assert f.calls[0][2] == {**CONFIG, "code": CODE, "grant_type": "authorization_code",
                                "redirect_uri": redirect, "code_verifier": verifier}
        assert len(f.vault.saves) == 1 and f.vault.value["channel_id"] == CHANNEL
        assert f.service.status()["state"] == "authorized" and "connected" not in f.service.status()
        assert f.service.authorization_url(state["flow_id"]) is None
        assert f.service._pending is None and not pending["tasks"] and not pending["writers"]
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", int(port))
        assert_redacted(f.service.status())
        assert await f.service.ensure_credentials() == {**CONFIG, "refresh_token": REFRESH, "channel_id": CHANNEL}
        assert len(f.calls) == 2
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["state", "duplicate_state", "duplicate_code", "unknown", "bad_percent",
    "host", "duplicate_host", "path", "absolute_target", "method", "body", "transfer", "bad_code", "large_code", "headers"])
def test_invalid_callback_requests_do_not_consume_a_valid_flow_or_contact_google(change):
    async def run():
        f = Fixture()
        await f.service.begin()
        pending = f.service._pending
        query = {"state": pending["state"], "code": CODE}
        options = {}
        if change == "state": query["state"] = "wrong"
        if change == "duplicate_state": query = urlencode(query) + "&state=wrong"
        if change == "duplicate_code": query = urlencode(query) + "&code=second"
        if change == "unknown": query["unknown"] = "private"
        if change == "bad_percent": query = urlencode(query) + "&scope=%ZZ"
        if change == "host": options["host"] = "evil.example"
        if change == "duplicate_host": options["extra_headers"] = "Host: " + pending["host"] + "\r\n"
        if change == "path": options["path"] = "/other"
        if change == "absolute_target": options["path"] = "http://" + pending["host"] + "/callback"
        if change == "method": options["method"] = "POST"
        if change == "body": options["extra_headers"] = "Content-Length: 2\r\n"
        if change == "transfer": options["extra_headers"] = "Transfer-Encoding: chunked\r\n"
        if change == "bad_code": query["code"] = "bad\x00"
        if change == "large_code": query["code"] = "x" * 2049
        if change == "headers": options["extra_headers"] = "X-Large: " + "x" * 8192 + "\r\n"
        await f.callback(query=query, **options)
        assert f.calls == [] and f.vault.saves == []
        assert f.service._pending is pending and pending["claimed"] is False
        assert f.service.authorization_url(pending["flow_id"]) is not None
        await f.service.close()
    asyncio.run(run())


def test_valid_denial_consumes_and_closes_listener_preserving_existing_account():
    async def run():
        previous = record()
        f = Fixture(stored=previous)
        await f.service.begin()
        pending = f.service._pending
        response = await f.callback(query={"state": pending["state"], "error": "access_denied",
                                          "error_description": "private provider reason"})
        assert b"Sign-in was not completed" in response and b"private" not in response
        assert f.service.status()["reason"] == "authorization_denied" and f.service.status()["authorized"]
        assert f.service._pending is None and f.calls == [] and f.vault.value == previous
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure,reason", [
    ("missing_refresh", "offline_access_required"), ("scope", "chat_scope_required"),
    ("expiry", "invalid_provider_response"), ("token_type", "invalid_provider_response"),
    ("empty_channels", "youtube_channel_required"), ("multiple_channels", "channel_selection_required"),
    ("channel_pagination", "channel_selection_required"), ("bad_channel", "invalid_provider_response"),
    ("bad_title", "invalid_provider_response"), ("provider_error", "authorization_rejected"),
    ("redirect", "provider_unavailable"), ("oversize", "provider_response_too_large"),
    ("corruption", "provider_unavailable"), ("vault", "account_storage_unavailable"),
])
def test_bad_or_unverifiable_authorization_never_replaces_an_existing_account(failure, reason):
    async def run():
        previous = record()
        f = Fixture(stored=previous)
        if failure == "missing_refresh": f.token_response.pop("refresh_token")
        if failure == "scope": f.token_response["scope"] = "other:scope"
        if failure == "expiry": f.token_response["expires_in"] = True
        if failure == "token_type": f.token_response["token_type"] = "wrong"
        if failure == "empty_channels": f.channels["items"] = []
        if failure == "multiple_channels": f.channels["items"] *= 2
        if failure == "channel_pagination": f.channels["nextPageToken"] = "private-page"
        if failure == "bad_channel": f.channels["items"][0]["id"] = "wrong"
        if failure == "bad_title": f.channels["items"][0]["snippet"]["title"] = "private\nname"
        if failure == "provider_error": f.token_response = (400, {"error": "private provider text"})
        if failure == "redirect": f.token_response = httpx.Response(302, headers={"Location": "https://evil.example"})
        if failure == "oversize": f.token_response = httpx.Response(200, content=b"x" * 16385)
        if failure == "corruption": f.token_response = httpx.Response(200, content=b"not-json-private")
        if failure == "vault": f.vault.fail_set = True
        await f.service.begin()
        response = await f.callback()
        assert f.service.status()["reason"] == reason
        assert f.vault.value == previous and not f.vault.saves and f.service._pending is None
        assert b"private" not in response
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_expiry_closes_listener_and_invalidates_authorization_link_without_requests():
    async def run():
        f = Fixture()
        state = await f.service.begin()
        pending = f.service._pending
        seconds, gate = await asyncio.wait_for(f.sleeps.get(), .5)
        f.now += seconds
        assert f.service.authorization_url(state["flow_id"]) is None
        gate.set_result(None)
        await until(lambda: f.service._pending is None)
        assert f.service.status()["reason"] == "authorization_expired"
        assert not pending["server"].is_serving() and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_callback_is_one_use_even_when_two_requests_arrive_before_token_exchange_finishes():
    async def run():
        f = Fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(request, form):
            if request.url.host == "oauth2.googleapis.com":
                entered.set()
                await release.wait()
        f.hook = hook
        state = await f.service.begin()
        pending = f.service._pending
        port = int(pending["host"].rsplit(":", 1)[1])
        second_reader, second_writer = await asyncio.open_connection("127.0.0.1", port)
        first = asyncio.create_task(f.callback())
        await asyncio.wait_for(entered.wait(), .5)
        assert f.service.authorization_url(state["flow_id"]) is None
        query = urlencode({"state": pending["state"], "code": "second-private-code"})
        second_writer.write(("GET /callback?" + query + " HTTP/1.1\r\nHost: " + pending["host"] + "\r\n\r\n").encode())
        await second_writer.drain()
        await asyncio.wait_for(second_reader.read(), .5)
        second_writer.close()
        release.set()
        await first
        assert len([call for call in f.calls if call[1] == YouTubeAccountService.TOKEN_URL]) == 1
        assert len(f.vault.saves) == 1
        await f.service.close()
    asyncio.run(run())


def test_cancel_or_new_begin_prevents_late_approval_from_saving():
    async def run():
        f = Fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(request, form):
            if request.url.host == "oauth2.googleapis.com":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
        f.hook = hook
        f.service.CLOSE_TIMEOUT_SECONDS = .01
        old_state = await f.service.begin()
        old_pending = f.service._pending
        callback = asyncio.create_task(f.callback())
        await asyncio.wait_for(entered.wait(), .5)
        await asyncio.wait_for(f.service.cancel(), .2)
        assert f.service.authorization_url(old_state["flow_id"]) is None
        new_state = await f.service.begin()
        release.set()
        await callback
        await until(lambda: not old_pending["tasks"])
        assert f.service.status()["flow_id"] == new_state["flow_id"] and not f.vault.saves
        await f.service.close()
    asyncio.run(run())


def test_concurrent_refresh_preserves_omitted_refresh_token_and_scope_and_rotates_once():
    async def run():
        f = Fixture(stored=record(expires_at=NOW + 30))
        f.token_response = {"access_token": "rotated-private-access", "token_type": "Bearer", "expires_in": 3600}
        first, second = await asyncio.gather(f.service.ensure_credentials(), f.service.ensure_credentials())
        assert first == second == {**CONFIG, "refresh_token": REFRESH, "channel_id": CHANNEL}
        assert f.vault.value["access_token"] == "rotated-private-access" and f.vault.value["refresh_token"] == REFRESH
        assert f.vault.value["scopes"] == [SCOPE] and len(f.vault.saves) == 1
        assert len(f.calls) == 2 and f.calls[0][2] == {**CONFIG, "refresh_token": REFRESH, "grant_type": "refresh_token"}
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure,reason", [("app_mismatch", "account_identity_mismatch"),
    ("channel_mismatch", "account_identity_mismatch"), ("refresh_denied", "authorization_refresh_required"),
    ("vault", "account_storage_unavailable")])
def test_refresh_checks_app_and_channel_identity_without_overwriting_failed_records(failure, reason):
    async def run():
        previous = record(expires_at=NOW - 1)
        config = CONFIG | {"client_id": "other-app.apps.googleusercontent.com"} if failure == "app_mismatch" else CONFIG
        f = Fixture(stored=previous, config_provider=lambda: config)
        if failure == "channel_mismatch": f.channels["items"][0]["id"] = "UC" + "b" * 22
        if failure == "refresh_denied": f.token_response = (400, {"error": "private invalid grant"})
        if failure == "vault": f.vault.fail_set = True
        assert await f.service.ensure_credentials() is None
        assert f.service.status()["reason"] == reason and not f.vault.saves and f.vault.value == previous
        if failure == "app_mismatch": assert f.calls == [] and not f.service.status()["authorized"]
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_newer_vault_record_and_cancel_during_refresh_block_old_save():
    async def run():
        for cancelled in (False, True):
            f = Fixture(stored=record(expires_at=NOW + 30))
            newer = record(access_token="newer-private-token")
            async def hook(request, form):
                if request.url.path == "/youtube/v3/channels":
                    if cancelled:
                        await f.service.cancel()
                    else:
                        f.vault.value = deepcopy(newer)
            f.hook = hook
            result = await f.service.ensure_credentials()
            assert not f.vault.saves
            assert result is None if cancelled else result == {**CONFIG, "refresh_token": REFRESH, "channel_id": CHANNEL}
            assert f.vault.value != newer if cancelled else f.vault.value == newer
            await f.service.close()
    asyncio.run(run())


def test_close_shuts_pending_connections_and_prevents_future_work():
    async def run():
        f = Fixture()
        state = await f.service.begin()
        pending = f.service._pending
        port = int(pending["host"].rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"GET /callback HTTP/1.1\r\n")
        await writer.drain()
        await f.service.close()
        assert await asyncio.wait_for(reader.read(), .5) == b""
        writer.close()
        assert f.service.authorization_url(state["flow_id"]) is None
        assert not pending["server"].is_serving() and not pending["tasks"]
        assert (await f.service.begin())["state"] == "unavailable"
        assert await f.service.ensure_credentials() is None and f.calls == []
    asyncio.run(run())


@pytest.mark.parametrize("value", [{}, {"client_id": CLIENT}, {"client_id": "bad-id", "client_secret": SECRET},
    {"client_id": CLIENT, "client_secret": "bad\nsecret"}])
def test_incomplete_or_invalid_installed_app_configuration_never_opens_a_listener(value):
    async def run():
        f = Fixture(stored=value)
        status = await f.service.begin()
        assert status["reason"] == "app_setup_required" and not status["app_configured"]
        assert f.service._pending is None and f.calls == [] and not f.vault.saves
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


def test_provider_configuration_failure_and_vault_corruption_are_redacted_and_read_only():
    async def run():
        def failed():
            raise RuntimeError("private configuration failure")
        f = Fixture(stored=record(), config_provider=failed)
        assert not f.service.status()["authorized"] and not f.service.status()["app_configured"]
        assert await f.service.ensure_credentials() is None and f.calls == []
        assert_redacted(f.service.status())
        f.vault.fail_get = True
        assert f.service.status()["reason"] == "account_storage_unavailable"
        assert await f.service.ensure_credentials() is None and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_expired_callback_exchange_and_newer_vault_record_cannot_save():
    async def run():
        for expired in (True, False):
            f = Fixture()
            newer = record(access_token="newer-private-account-token")
            async def hook(request, form):
                if request.url.host == "oauth2.googleapis.com":
                    if expired:
                        f.now += f.service.FLOW_LIFETIME_SECONDS
                    else:
                        f.vault.value = deepcopy(newer)
            f.hook = hook
            await f.service.begin()
            await f.callback()
            assert f.service.status()["reason"] == ("authorization_expired" if expired else "account_state_changed")
            assert not f.vault.saves and f.service._pending is None
            if expired:
                assert len(f.calls) == 1  # Do not start channel lookup after authorization expiry.
            else:
                assert f.vault.value == newer
            await f.service.close()
    asyncio.run(run())


def test_channel_title_and_verified_record_match_real_vault_field_limits():
    async def run():
        from rareiq.core.platform_credentials import _values
        f = Fixture()
        f.channels["items"][0]["snippet"]["title"] = "C" * 100
        await f.service.begin()
        await f.callback()
        assert f.service.status()["authorized"] and len(f.service.status()["public_label"]) == 80
        assert _values("youtube", f.vault.value) == f.vault.value
        await f.service.close()
    asyncio.run(run())


def test_incomplete_headers_timeout_without_consuming_the_flow():
    async def run():
        f = Fixture()
        f.service.CALLBACK_TIMEOUT_SECONDS = .01
        await f.service.begin()
        pending = f.service._pending
        response = await f.callback(raw=b"GET /callback HTTP/1.1\r\n")
        assert b"Sign-in was not completed" in response
        assert f.service._pending is pending and not pending["claimed"]
        assert f.calls == [] and not f.vault.saves
        await f.service.close()
    asyncio.run(run())
