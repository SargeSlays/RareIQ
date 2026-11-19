"""Owned loopback callbacks and synthetic Kick transport only; no real accounts."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from rareiq.core.platform_credentials import PlatformCredentialVault
from rareiq.services.kick_account_service import KickAccountService


NOW = 1800000000
CONFIG = {"client_id": "fixture-kick-app", "client_secret": "synthetic-private-app-secret"}
ACCESS, REFRESH = "synthetic-access", "synthetic-refresh"
SCOPES = KickAccountService.SCOPE


def record(**changes):
    return {**CONFIG, "access_token": ACCESS, "refresh_token": REFRESH, "token_type": "bearer",
            "expires_at": NOW + 3600, "scopes": SCOPES.split(), "channel_id": "123",
            "channel_slug": "fixture_channel", "public_label": "fixture_channel"} | changes


class Vault:
    def __init__(self, value=None):
        self.value = deepcopy(CONFIG if value is None else value)
        self.saves = []
    def get(self, provider):
        assert provider == 'kick'
        return deepcopy(self.value)
    def set(self, provider, value):
        assert provider == 'kick'
        self.value = (self.value or {}) | deepcopy(value)
        self.saves.append(deepcopy(value))


class Fixture:
    def __init__(self, stored=None, vault=None, config=None):
        self.vault = vault or Vault(stored)
        self.config = CONFIG if config is None else config
        self.now, self.calls, self.hook = NOW, [], None
        self.token = {'access_token': ACCESS, 'refresh_token': REFRESH, 'token_type': 'bearer', 'expires_in': 3600, 'scope': SCOPES}
        self.introspection = {'active': True, 'token_type': 'user', 'client_id': CONFIG['client_id'], 'scope': SCOPES, 'exp': NOW + 3600}
        self.users = [{'user_id': 123, 'name': 'fixture_channel'}]
        self.channels = [{'broadcaster_user_id': 123, 'slug': 'fixture_channel'}]
        self.service = KickAccountService(self.vault, app_config_provider=lambda: self.config,
            clock=lambda: self.now, callback_port=0,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)))
    async def http(self, request):
        assert request.url.scheme == 'https' and 'access_token' not in request.url.params
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((request.method, str(request.url), form))
        if self.hook:
            result = await self.hook(request)
            if result is not None:
                return result
        if str(request.url) == self.service.TOKEN_URL:
            return httpx.Response(200, json=self.token)
        if str(request.url) == self.service.INTROSPECT_URL:
            return httpx.Response(200, json={'data': self.introspection})
        if str(request.url) == self.service.USERS_URL:
            return httpx.Response(200, json={'data': self.users})
        if str(request.url) == self.service.CHANNELS_URL:
            return httpx.Response(200, json={'data': self.channels})
        raise AssertionError('Unexpected provider endpoint')


async def callback(f, *, state=None, code='synthetic-code', error=None, host=None):
    pending = f.service._pending
    query = {'state': state if state is not None else pending['state']}
    query.update({'error': error} if error else {'code': code})
    uri = urlsplit(pending['redirect_uri'])
    reader, writer = await asyncio.open_connection('127.0.0.1', uri.port)
    writer.write(('GET /callback?' + urlencode(query) + ' HTTP/1.1\r\nHost: ' + (host or pending['host']) + '\r\n\r\n').encode('ascii'))
    await writer.drain()
    data = await asyncio.wait_for(reader.read(), 3)
    writer.close()
    await writer.wait_closed()
    return data


def test_status_is_offline_and_missing_configuration_never_opens_a_listener():
    async def run():
        f = Fixture(config={})
        assert f.service.status()['platform'] == 'kick' and f.calls == []
        result = await f.service.begin()
        assert result['reason'] == 'app_setup_required' and f.service._pending is None and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_pkce_callback_verifies_identity_and_stores_only_after_introspection():
    async def run():
        f = Fixture()
        status = await f.service.begin()
        assert status['state'] == 'pending'
        url = f.service.authorization_url(status['flow_id']);query = parse_qs(urlsplit(url).query)
        assert set(query) == {'response_type','client_id','redirect_uri','scope','state','code_challenge','code_challenge_method'}
        assert query['scope'] == [SCOPES] and query['code_challenge_method'] == ['S256']
        assert 'synthetic-private-app-secret' not in json.dumps(status)
        verifier = f.service._pending['verifier']
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode()
        assert query['code_challenge'] == [expected]
        result = await callback(f)
        assert b'Sign-in complete' in result
        assert f.service.status()['authorized'] and f.vault.value['channel_id'] == '123'
        assert f.calls[0][2]['code_verifier'] == verifier and f.calls[0][2]['client_secret'] == CONFIG['client_secret']
        public = json.dumps(f.service.status())
        assert ACCESS not in public and REFRESH not in public and CONFIG['client_secret'] not in public
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['invalid-state','wrong-host','denied','missing-scope','wrong-client','inactive','wrong-user','wrong-channel'])
def test_invalid_or_denied_signin_does_not_replace_saved_account(kind):
    async def run():
        f = Fixture(stored=record())
        await f.service.begin()
        before = deepcopy(f.vault.value)
        kwargs = {}
        if kind == 'invalid-state': kwargs['state'] = 'wrong-state'
        elif kind == 'wrong-host': kwargs['host'] = 'untrusted.invalid'
        elif kind == 'denied': kwargs['error'] = 'access_denied'
        elif kind == 'missing-scope': f.introspection['scope'] = 'user:read channel:read'
        elif kind == 'wrong-client': f.introspection['client_id'] = 'different-app'
        elif kind == 'inactive': f.introspection['active'] = False
        elif kind == 'wrong-user': f.users[0]['user_id'] = 456;f.channels[0]['broadcaster_user_id'] = 456
        elif kind == 'wrong-channel': f.channels[0]['broadcaster_user_id'] = 999
        await callback(f, **kwargs)
        assert f.vault.value == before and f.vault.saves == []
        if kind in {'invalid-state','wrong-host'}:
            assert f.service.status()['state'] == 'pending' and f.calls == []
        await f.service.close()
    asyncio.run(run())


def test_validation_and_refresh_share_one_owner_and_preserve_missing_refresh_rotation():
    async def run():
        f = Fixture(stored=record(expires_at=NOW + 20))
        f.token.pop('refresh_token')
        first, second = await asyncio.gather(f.service.ensure_authorization(), f.service.ensure_authorization())
        assert first == second and first['access_token'] == ACCESS
        assert len([call for call in f.calls if call[1] == f.service.TOKEN_URL]) == 1
        assert f.vault.value['refresh_token'] == REFRESH and len(f.vault.saves) == 1
        f.calls.clear();await f.service.ensure_authorization();assert f.calls == []
        f.now += 3601;f.introspection['exp'] = f.now + 3600
        await f.service.ensure_authorization();assert f.calls
        await f.service.close()
    asyncio.run(run())


@pytest.mark.parametrize('action', ['cancel','disconnect','external','configuration'])
def test_stale_validation_cannot_restore_old_authorization(action):
    async def run():
        f = Fixture(stored=record())
        async def hook(request):
            if str(request.url) == f.service.USERS_URL:
                if action == 'cancel': await f.service.cancel()
                elif action == 'disconnect':
                    # Invalidate without waiting on the lock held by this validation.
                    f.service._invalidate('account_disconnected');f.vault.set('kick',{'access_token':'','refresh_token':''})
                elif action == 'external': f.vault.set('kick',{'access_token':'newer-synthetic-token'})
                else: f.config = CONFIG | {'client_secret':'changed-app-secret'}
        f.hook = hook
        assert await f.service.ensure_authorization() is None
        assert len(f.vault.saves) == (1 if action in {'external','disconnect'} else 0)
        await f.service.close()
    asyncio.run(run())


def test_expiry_cancel_and_disconnect_release_listener_and_retain_app_setup():
    async def run():
        f = Fixture(stored=record())
        status = await f.service.begin();server = f.service._pending['server']
        f.now += 601
        assert f.service.authorization_url(status['flow_id']) is None
        await f.service.cancel();assert not server.is_serving()
        await f.service.disconnect()
        assert not f.service.status()['authorized'] and f.service.status()['app_configured']
        assert f.vault.value['client_secret'] == CONFIG['client_secret']
        assert not f.vault.value['access_token'] and not f.vault.value['scopes']
        await f.service.close()
    asyncio.run(run())


def test_saved_login_reopens_from_an_encrypted_vault(tmp_path):
    class Cipher:
        available = True
        def encrypt(self, value): return b'fixture-cipher:' + base64.b64encode(value)
        def decrypt(self, value): return base64.b64decode(value.removeprefix(b'fixture-cipher:'))
    async def run():
        path = tmp_path / 'accounts.enc.json';vault = PlatformCredentialVault(path,cipher=Cipher());vault.set('kick',CONFIG)
        f = Fixture(vault=vault);await f.service.begin();await callback(f)
        reopened = PlatformCredentialVault(path,cipher=Cipher())
        second = KickAccountService(reopened,clock=lambda:NOW)
        assert second.status()['authorized'] and second.status()['public_label'] == 'fixture_channel'
        assert ACCESS not in path.read_text() and REFRESH not in path.read_text()
        await second.disconnect();assert not KickAccountService(PlatformCredentialVault(path,cipher=Cipher()),clock=lambda:NOW).status()['authorized']
        await f.service.close();await second.close()
    asyncio.run(run())


def test_check_during_pending_consent_does_not_invalidate_the_owned_snapshot():
    async def run():
        f = Fixture(stored=record(expires_at=NOW+2000));await f.service.begin()
        await f.service.check();assert f.service.status()['state']=='pending'
        await callback(f);assert f.service.status()['authorized'] and f.service.status()['state']=='authorized'
        await f.service.close()
    asyncio.run(run())
