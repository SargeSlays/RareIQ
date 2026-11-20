"""Offline public-device authorization/rotation; no host credentials or network."""
import asyncio
from collections import deque
from copy import deepcopy
import json
from urllib.parse import parse_qs

import httpx
import pytest

from rareiq.services.twitch_account_service import TwitchAccountService


NOW = 1800000000.0
CLIENT = "fixture-client"
PRIVATE_DEVICE = "private-device-code"
PRIVATE_ACCESS = "private-access-token"
PRIVATE_REFRESH = "private-refresh-token"


def record(*, expires=NOW + 3600, access=PRIVATE_ACCESS, refresh=PRIVATE_REFRESH):
    return {"client_id": CLIENT, "access_token": access, "refresh_token": refresh,
            "token_type": "bearer", "expires_at": expires, "scopes": ["user:read:chat"],
            "channel_login": "fixture_channel", "channel_id": "123", "public_label": "fixture_channel"}


def token(**changes):
    return {"access_token": PRIVATE_ACCESS, "refresh_token": PRIVATE_REFRESH,
            "token_type": "bearer", "expires_in": 3600} | changes


class FakeVault:
    def __init__(self, stored=None):
        self.value, self.saves = deepcopy(stored), []
        self.fail_get = self.fail_set = False

    def get(self, platform):
        assert platform == "twitch"
        if self.fail_get:
            raise RuntimeError("private vault path")
        return deepcopy(self.value)

    def set(self, platform, value):
        assert platform == "twitch"
        if self.fail_set:
            raise RuntimeError("private vault failure")
        self.value = deepcopy(value)
        self.saves.append(deepcopy(value))


async def until(predicate):
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(.001)
    raise AssertionError("fixture condition not reached")


class Fixture:
    def __init__(self, *, stored=None, client_id=CLIENT):
        self.now = NOW
        self.vault = FakeVault(stored)
        self.calls, self.closed = [], 0
        self.tokens = deque()
        self.device = {"device_code": PRIVATE_DEVICE, "user_code": "abcd-1234",
                       "verification_uri": "https://untrusted.example/private", "expires_in": 1800, "interval": 2}
        self.validation = {"client_id": CLIENT, "login": "fixture_channel", "user_id": "123",
                           "scopes": ["user:read:chat"], "expires_in": 3500}
        self.sleeps = asyncio.Queue()
        self.hook = None
        self.service = TwitchAccountService(self.vault, client_id_provider=lambda: client_id,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)),
            clock=lambda: self.now, sleep=self.sleep)

    async def sleep(self, seconds):
        gate = asyncio.get_running_loop().create_future()
        self.sleeps.put_nowait((seconds, gate))
        await gate

    async def tick(self):
        seconds, gate = await asyncio.wait_for(self.sleeps.get(), .5)
        self.now += seconds
        gate.set_result(None)
        await until(lambda: not self.sleeps.empty() or self.service._task is None)
        return seconds

    async def http(self, request):
        assert request.url.scheme == "https" and request.url.host == "id.twitch.tv"
        assert not request.url.query
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        self.calls.append((request.method, request.url.path, form, dict(request.headers)))
        if self.hook is not None:
            response = await self.hook(request, form)
            if response is not None:
                return response
        if request.url.path == "/oauth2/device":
            assert form["client_id"] == CLIENT and form["scopes"] in (
                "user:read:chat", "user:read:chat channel:read:stream_key",
                "user:read:chat channel:manage:broadcast",
                "user:read:chat channel:read:stream_key channel:manage:broadcast",
                "user:read:chat user:write:chat",
                "user:read:chat channel:read:stream_key user:write:chat",
                "user:read:chat channel:manage:broadcast user:write:chat",
                "user:read:chat channel:read:stream_key channel:manage:broadcast user:write:chat") and set(form) == {"client_id", "scopes"}
            value = self.device
        elif request.url.path == "/oauth2/token":
            assert "client_secret" not in form
            value = self.tokens.popleft() if self.tokens else (400, {"message": "authorization_pending"})
        elif request.url.path == "/oauth2/validate":
            assert request.method == "GET" and request.headers["Authorization"].startswith("OAuth ")
            value = self.validation
        else:
            raise AssertionError("unexpected fixture endpoint")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, httpx.Response):
            return value
        code, body = value if isinstance(value, tuple) else (200, value)
        return httpx.Response(code, json=body)


def assert_redacted(status):
    text = json.dumps(status)
    assert all(secret not in text for secret in (PRIVATE_DEVICE, PRIVATE_ACCESS, PRIVATE_REFRESH,
                                                 "private vault", "untrusted.example"))
    assert all(key not in status for key in ("access_token", "refresh_token", "device_code", "channel_id"))


def test_status_is_read_only_and_missing_app_configuration_makes_no_network_call():
    async def run():
        f = Fixture(client_id=None)
        assert f.service.status()["state"] == "not_authorized"
        assert f.service.status()["app_configured"] is False
        assert f.calls == []
        assert (await f.service.begin())["reason"] == "app_setup_required"
        assert f.calls == [] and f.vault.saves == []
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("client_id,configured", [(None, False), ("", False), (CLIENT, True),
    ("bad client", False), ("private\nclient", False), (True, False), ({"private": "value"}, False)])
def test_public_app_configuration_is_a_validated_boolean_without_exposing_the_id(client_id, configured):
    f = Fixture(client_id=client_id)
    status = f.service.status()
    assert status["app_configured"] is configured and status["authorized"] is False
    assert CLIENT not in json.dumps(status) and "private" not in json.dumps(status)
    assert f.calls == [] and f.vault.saves == []


def test_public_id_only_vault_configuration_recovers_setup_feedback_without_network():
    async def run():
        f = Fixture(client_id=None)
        f.service._client_id_provider = lambda: (f.vault.get("twitch") or {}).get("client_id")
        assert (await f.service.begin())["reason"] == "app_setup_required"
        assert f.service.status()["app_configured"] is False
        f.vault.set("twitch", {"client_id": CLIENT})
        status = f.service.status()
        assert status["app_configured"] is True
        assert status["authorized"] is False and status["reason"] == "authorization_required"
        assert CLIENT not in json.dumps(status) and f.calls == []
        assert f.vault.value == {"client_id": CLIENT}
        assert await f.service.ensure_credentials() is None and f.calls == []
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("expires", [NOW + 3600, NOW + 30, NOW - 1])
def test_a_different_configured_app_cannot_claim_return_or_refresh_stored_account_tokens(expires):
    async def run():
        previous = record(expires=expires)
        f = Fixture(stored=previous, client_id="different-public-client")
        status = f.service.status()
        assert status["app_configured"] is True and status["authorized"] is False
        assert status["reason"] == "account_identity_mismatch"
        assert "public_label" not in status and "expires_at" not in status
        assert await f.service.ensure_credentials() is None
        assert f.calls == [] and not f.vault.saves and f.vault.value == previous
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_a_failing_or_invalid_public_app_provider_is_redacted_and_blocks_token_use():
    async def run():
        f = Fixture(stored=record())
        def failed():
            raise RuntimeError("private public-app provider error")
        f.service._client_id_provider = failed
        status = f.service.status()
        assert not status["app_configured"] and not status["authorized"]
        assert status["reason"] == "app_setup_required" and "private" not in json.dumps(status)
        assert await f.service.ensure_credentials() is None and f.calls == []
        f.service._client_id_provider = lambda: "bad client id"
        assert await f.service.ensure_credentials() is None and f.calls == []
        assert not f.service.status()["authorized"] and not f.vault.saves
        await f.service.close()
    asyncio.run(run())


def test_pending_then_approved_is_verified_saved_and_redacted_without_chat_claim():
    async def run():
        f = Fixture()
        pending = await f.service.begin()
        assert pending["state"] == "pending" and pending["user_code"] == "ABCD-1234"
        assert pending["verification_url"] == "https://www.twitch.tv/activate"
        assert pending["poll_after"] == 5 and pending["flow_id"]
        assert len(f.calls) == 1 and not f.vault.saves
        assert_redacted(pending)
        assert await f.tick() == 5
        assert f.service.status()["state"] == "pending" and not f.vault.saves
        f.tokens.append(token())
        assert await f.tick() == 5
        state = f.service.status()
        assert state["state"] == "authorized" and state["authorized"]
        assert state["public_label"] == "fixture_channel" and "connected" not in state
        assert state["expires_at"] == f.now + 3500
        assert len(f.vault.saves) == 1
        assert f.calls[1][2] == {"client_id": CLIENT, "scopes": "user:read:chat",
                               "device_code": PRIVATE_DEVICE, "grant_type": TwitchAccountService.DEVICE_GRANT}
        assert_redacted(state)
        count = len(f.calls)
        assert await f.service.ensure_credentials() == {
            "client_id": CLIENT, "channel_login": "fixture_channel", "user_access_token": PRIVATE_ACCESS}
        assert len(f.calls) == count  # A fresh stored authorization needs no implicit request.
        await f.service.close()
    asyncio.run(run())


def test_slow_down_increases_interval_and_never_polls_after_expiry():
    async def run():
        f = Fixture()
        f.device["expires_in"] = 21
        f.tokens.extend([(400, {"error": "slow_down"}), (400, {"message": "authorization_pending"})])
        await f.service.begin()
        assert await f.tick() == 5
        assert f.service.status()["poll_after"] == 10
        assert await f.tick() == 10
        assert await f.tick() == 6
        assert f.service.status()["reason"] == "authorization_expired"
        assert len([call for call in f.calls if call[1] == "/oauth2/token"]) == 2
        assert not f.vault.saves and f.service._pending is None
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure,reason", [
    ((400, {"error": "access_denied"}), "authorization_denied"),
    ((400, {"message": "authorization_declined"}), "authorization_denied"),
    ((400, {"error": "expired_token"}), "authorization_expired"),
    ((401, {"message": "private provider text"}), "authorization_rejected"),
    (httpx.Response(302, headers={"Location": "https://untrusted.example"}), "provider_unavailable"),
    (httpx.Response(200, content=b"x" * 16385), "provider_response_too_large"),
])
def test_denial_expiry_and_provider_failures_preserve_an_existing_authorized_account(failure, reason):
    async def run():
        previous = record()
        f = Fixture(stored=previous)
        f.tokens.append(failure)
        await f.service.begin()
        await f.tick()
        assert f.service.status()["reason"] == reason
        assert f.service.status()["authorized"] and f.vault.value == previous and not f.vault.saves
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("changes,reason", [
    ({"client_id": "wrong-client"}, "account_identity_mismatch"),
    ({"scopes": ["other:scope"]}, "chat_scope_required"),
    ({"user_id": True}, "account_identity_mismatch"),
    ({"login": "bad\nlogin"}, "account_identity_mismatch"),
    ({"expires_in": True}, "invalid_provider_response"),
])
def test_approved_tokens_require_matching_validated_client_scope_identity_and_expiry(changes, reason):
    async def run():
        f = Fixture()
        f.validation.update(changes)
        f.tokens.append(token())
        await f.service.begin()
        await f.tick()
        assert f.service.status()["reason"] == reason and not f.vault.saves
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("changes", [{"device_code": ""}, {"user_code": "bad code"},
    {"expires_in": 1801}, {"interval": 0}, {"interval": True}])
def test_malformed_device_responses_never_start_polling(changes):
    async def run():
        f = Fixture()
        f.device.update(changes)
        assert (await f.service.begin())["reason"] == "invalid_provider_response"
        assert f.service._task is None and f.service._pending is None
        assert len(f.calls) == 1 and not f.vault.saves
        await f.service.close()
    asyncio.run(run())


def test_cancel_clears_private_pending_state_and_late_approval_cannot_save():
    async def run():
        f = Fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(request, form):
            if request.url.path == "/oauth2/validate":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # Simulated late provider completion after cancellation.
                return httpx.Response(200, json=f.validation)
        f.hook = hook
        f.tokens.append(token())
        f.service.CLOSE_TIMEOUT_SECONDS = .01
        await f.service.begin()
        seconds, gate = await asyncio.wait_for(f.sleeps.get(), .5)
        f.now += seconds
        gate.set_result(None)
        await asyncio.wait_for(entered.wait(), .5)
        old_task = f.service._task
        status = await asyncio.wait_for(f.service.cancel(), .2)
        assert status["reason"] == "authorization_cancelled" and f.service._pending is None
        release.set()
        await asyncio.wait_for(old_task, .5)
        assert not f.vault.saves and f.service.status()["state"] == "not_authorized"
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_new_device_flow_invalidates_an_older_inflight_begin():
    async def run():
        f = Fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        first = True
        async def hook(request, form):
            nonlocal first
            if request.url.path == "/oauth2/device" and first:
                first = False
                entered.set()
                await release.wait()
                return httpx.Response(200, json=f.device | {"user_code": "OLD1-CODE"})
        f.hook = hook
        old_begin = asyncio.create_task(f.service.begin())
        await asyncio.wait_for(entered.wait(), .5)
        current = await f.service.begin()
        release.set()
        await old_begin
        assert f.service.status()["flow_id"] == current["flow_id"]
        assert f.service.status()["user_code"] == "ABCD-1234"
        await f.service.close()
    asyncio.run(run())


def test_new_begin_wins_over_older_begin_waiting_for_stalled_poll_cleanup():
    async def run():
        f = Fixture()
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(request, form):
            if request.url.path == "/oauth2/validate":
                entered.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                return httpx.Response(200, json=f.validation)
        f.hook = hook
        f.tokens.append(token())
        f.service.CLOSE_TIMEOUT_SECONDS = .03
        await f.service.begin()
        seconds, gate = await f.sleeps.get()
        f.now += seconds
        gate.set_result(None)
        await asyncio.wait_for(entered.wait(), .5)
        original_poll = f.service._task
        older_begin = asyncio.create_task(f.service.begin())
        await asyncio.sleep(.001)
        newer = await f.service.begin()
        release.set()
        await asyncio.wait_for(original_poll, .5)
        await asyncio.wait_for(older_begin, .5)
        assert f.service.status()["flow_id"] == newer["flow_id"]
        assert not f.vault.saves
        assert len([call for call in f.calls if call[1] == "/oauth2/device"]) == 2
        await f.service.close()
    asyncio.run(run())


def test_racing_refreshes_rotate_once_and_keep_new_tokens_internal():
    async def run():
        f = Fixture(stored=record(expires=NOW + 30))
        f.tokens.append(token(access_token="rotated-private-access", refresh_token="rotated-private-refresh"))
        first, second = await asyncio.gather(f.service.ensure_credentials(), f.service.ensure_credentials())
        assert first == second and first["user_access_token"] == "rotated-private-access"
        assert f.vault.value["refresh_token"] == "rotated-private-refresh" and len(f.vault.saves) == 1
        assert [call[1] for call in f.calls] == ["/oauth2/token", "/oauth2/validate"]
        assert f.calls[0][2] == {"client_id": CLIENT, "grant_type": "refresh_token", "refresh_token": PRIVATE_REFRESH}
        assert "rotated-private" not in json.dumps(f.service.status())
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["refresh_rejected", "wrong_account", "vault_save", "vault_read"])
def test_refresh_and_storage_failures_are_redacted_and_do_not_destroy_the_previous_record(failure):
    async def run():
        previous = record(expires=NOW - 1)
        f = Fixture(stored=previous)
        f.tokens.append((400, {"error": "invalid_grant"}) if failure == "refresh_rejected" else token())
        if failure == "wrong_account":
            f.validation["user_id"] = "999"
        if failure == "vault_save":
            f.vault.fail_set = True
        if failure == "vault_read":
            f.vault.fail_get = True
        assert await f.service.ensure_credentials() is None
        assert f.vault.value == previous and not f.vault.saves
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_newer_vault_record_is_not_overwritten_by_an_inflight_refresh():
    async def run():
        f = Fixture(stored=record(expires=NOW + 30))
        newer = record(access="newer-account-access", refresh="newer-account-refresh")
        async def hook(request, form):
            if request.url.path == "/oauth2/validate":
                f.vault.value = newer
        f.hook = hook
        f.tokens.append(token())
        result = await f.service.ensure_credentials()
        assert result["user_access_token"] == "newer-account-access"
        assert f.vault.value == newer and not f.vault.saves
        await f.service.close()
    asyncio.run(run())


def test_close_prevents_future_begin_refresh_or_background_polling():
    async def run():
        f = Fixture(stored=record(expires=NOW + 30))
        await f.service.begin()
        count = len(f.calls)
        await f.service.close()
        assert f.service._pending is None and f.service.status()["reason"] == "account_service_closed"
        assert (await f.service.begin())["state"] == "unavailable"
        assert await f.service.ensure_credentials() is None
        assert len(f.calls) == count and not f.vault.saves
    asyncio.run(run())


def test_status_expires_stored_authorization_without_network_and_denies_refresh_missing_identity():
    async def run():
        f = Fixture(stored=record())
        f.service._reason = "account_authorized"
        f.now += 3600
        assert not f.service.status()["authorized"]
        assert f.service.status()["reason"] == "authorization_refresh_required"
        assert f.calls == []
        f.vault.value.pop("channel_id")
        assert await f.service.ensure_credentials() is None and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_continuous_slow_down_stops_instead_of_ignoring_additional_requested_delay():
    async def run():
        f = Fixture()
        f.device["interval"] = 60
        f.tokens.append((400, {"error": "slow_down"}))
        await f.service.begin()
        assert await f.tick() == 60
        assert f.service.status()["reason"] == "provider_rate_limited"
        assert not f.vault.saves and f.service._task is None
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["/oauth2/token", "/oauth2/validate"])
def test_approval_arriving_after_device_flow_expiry_cannot_save(endpoint):
    async def run():
        f = Fixture()
        f.device["expires_in"] = 20
        f.tokens.append(token())
        async def hook(request, form):
            if request.url.path == endpoint:
                f.now += 20
        f.hook = hook
        await f.service.begin()
        await f.tick()
        assert not f.vault.saves and f.service.status()["reason"] == "authorization_expired"
        assert "user_code" not in f.service.status()
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["app", "vault"])
def test_device_approval_cannot_overwrite_a_newer_app_or_account(change):
    async def run():
        f = Fixture()
        newer = record(access="newer-account-access")
        async def hook(request, form):
            if request.url.path == "/oauth2/validate":
                if change == "app":
                    f.service._client_id_provider = lambda: "newer-app"
                else:
                    f.vault.value = newer
        f.hook = hook
        f.tokens.append(token())
        await f.service.begin()
        await f.tick()
        assert not f.vault.saves
        assert f.vault.value == (newer if change == "vault" else None)
        assert f.service.status()["reason"] == ("account_identity_mismatch" if change == "app" else "account_state_changed")
        assert_redacted(f.service.status())
        await f.service.close()
    asyncio.run(run())


def test_streaming_upgrade_is_explicit_pins_existing_identity_and_reopens_saved_account():
    async def run():
        f = Fixture(stored=record())
        previous = deepcopy(f.vault.value)
        status = await f.service.begin_streaming()
        assert status['authorized'] and not status['streaming_authorized']
        assert status['authorization_kind'] == 'streaming' and f.vault.value == previous
        assert f.calls[0][2]['scopes'] == 'user:read:chat channel:read:stream_key'
        f.validation['scopes'].append('channel:read:stream_key')
        f.tokens.append(token())
        await f.tick()
        status = f.service.status()
        assert status['authorized'] and status['streaming_authorized'] and len(status['account_ref']) == 64
        reopened = TwitchAccountService(f.vault, client_id_provider=lambda: CLIENT, clock=lambda: f.now)
        assert reopened.status()['account_ref'] == status['account_ref']
        assert reopened.status()['streaming_authorized']
        assert_redacted(status)
        await f.service.close()
        await reopened.close()
    asyncio.run(run())


@pytest.mark.parametrize('outcome', ['cancel', 'denied', 'scope', 'identity'])
def test_failed_streaming_upgrade_preserves_prior_chat_grant(outcome):
    async def run():
        f = Fixture(stored=record())
        previous = deepcopy(f.vault.value)
        await f.service.begin_streaming()
        if outcome == 'cancel':
            await f.service.cancel()
        else:
            f.tokens.append((400, {'error': 'access_denied'}) if outcome == 'denied' else token())
            if outcome == 'identity':
                f.validation.update(user_id='999', scopes=['user:read:chat', 'channel:read:stream_key'])
            await f.tick()
        assert f.vault.value == previous and not f.vault.saves
        assert f.service.status()['authorized'] and not f.service.status()['streaming_authorized']
        expected = {'cancel': 'authorization_cancelled', 'denied': 'authorization_denied',
                    'scope': 'streaming_scope_required', 'identity': 'account_identity_mismatch'}
        assert f.service.status()['reason'] == expected[outcome]
        await f.service.close()
    asyncio.run(run())


def test_saved_login_validates_on_first_use_and_hourly_and_explicit_check_can_detect_revocation():
    async def run():
        f = Fixture(stored=record(expires=NOW + 7200))
        f.validation['expires_in'] = 7100
        assert f.calls == []
        assert await f.service.ensure_credentials()
        assert [call[1] for call in f.calls] == ['/oauth2/validate']
        assert await f.service.ensure_credentials()
        assert len(f.calls) == 1
        f.now += 3601
        assert await f.service.ensure_credentials()
        assert len(f.calls) == 2
        f.validation = (401, {'message': 'private provider failure'})
        status = await f.service.check()
        assert not status['authorized'] and not status['streaming_authorized']
        assert 'account_ref' not in status and status['reason'] == 'authorization_rejected'
        assert_redacted(status)
        await f.service.close()
    asyncio.run(run())


def test_refresh_detects_stream_scope_loss_without_falsely_removing_chat_access():
    async def run():
        saved = record(expires=NOW + 10)
        saved['scopes'].append('channel:read:stream_key')
        f = Fixture(stored=saved)
        f.tokens.append(token())
        assert await f.service.ensure_credentials()
        assert f.service.status()['authorized'] and not f.service.status()['streaming_authorized']
        assert f.vault.value['scopes'] == ['user:read:chat']
        await f.service.close()
    asyncio.run(run())


def test_disconnect_preserves_app_setup_and_late_validation_cannot_restore_login():
    async def run():
        f = Fixture(stored=record())
        entered, release = asyncio.Event(), asyncio.Event()
        async def hook(request, form):
            if request.url.path == '/oauth2/validate':
                entered.set()
                await release.wait()
        f.hook = hook
        checking = asyncio.create_task(f.service.check())
        await entered.wait()
        disconnecting = asyncio.create_task(f.service.disconnect())
        await asyncio.sleep(.001)
        release.set()
        await checking
        status = await disconnecting
        assert not status['authorized'] and status['app_configured']
        assert f.vault.value['client_id'] == CLIENT and f.vault.value['access_token'] == ''
        assert not f.vault.value['refresh_token'] and f.vault.value['scopes'] == []
        assert len(f.vault.saves) == 1 and status['reason'] == 'account_disconnected'
        assert await f.service.ensure_credentials() is None
        await f.service.close()
    asyncio.run(run())


def test_disconnect_failed_storage_still_invalidates_current_process_grant():
    async def run():
        f = Fixture(stored=record())
        f.vault.fail_set = True
        status = await f.service.disconnect()
        assert not status['authorized'] and status['reason'] == 'account_storage_unavailable'
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize('operation', ['check', 'refresh'])
def test_owned_check_or_refresh_during_pending_stream_upgrade_does_not_invalidate_consent(operation):
    async def run():
        f = Fixture(stored=record(expires=NOW + (10 if operation == 'refresh' else 3600)))
        old = deepcopy(f.vault.value)
        pending = await f.service.begin_streaming()
        flow = pending['flow_id']
        if operation == 'refresh':
            f.tokens.append(token(access_token='rotated-access', refresh_token='rotated-refresh'))
            assert await f.service.ensure_credentials()
        else:
            checked = await f.service.check()
            assert checked['state'] == 'pending' and checked['flow_id'] == flow
        assert f.vault.value != old
        assert f.service._pending['stored_before'] == f.vault.value
        assert not f.service.status()['streaming_authorized']
        f.validation['scopes'] = ['user:read:chat', 'channel:read:stream_key']
        f.tokens.append(token(access_token='upgraded-access', refresh_token='upgraded-refresh'))
        await f.tick()
        final = f.service.status()
        assert final['reason'] == 'account_authorized' and final['streaming_authorized']
        assert f.vault.value['access_token'] == 'upgraded-access' and len(f.vault.saves) == 2
        await f.service.close()
    asyncio.run(run())


def test_external_vault_write_after_owned_check_still_invalidates_pending_upgrade():
    async def run():
        f = Fixture(stored=record())
        await f.service.begin_streaming()
        await f.service.check()
        owned = deepcopy(f.vault.value)
        external = record(access='external-newer-access')
        f.vault.value = external
        f.validation['scopes'] = ['user:read:chat', 'channel:read:stream_key']
        f.tokens.append(token())
        await f.tick()
        assert f.service.status()['reason'] == 'account_state_changed'
        assert f.vault.value == external and f.vault.saves == [owned]
        await f.service.close()
    asyncio.run(run())
