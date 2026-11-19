"""Offline native private-pipe contract. No host credentials or provider requests."""
import asyncio
from copy import deepcopy
import hashlib
import json

import httpx
import pytest

from tools import desktop_twitch_account as helper
from rareiq.core.platform_credentials import PlatformCredentialVault
from tests.test_platform_credentials import TestCipher

NOW = 1800000000
REF = hashlib.sha256(b'fixture-client:123').hexdigest()
RECORD = {'client_id': 'fixture-client', 'channel_id': '123', 'channel_login': 'fixture',
    'token_type': 'bearer', 'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh',
    'expires_at': NOW + 7200, 'scopes': ['user:read:chat', 'channel:read:stream_key']}


class Vault:
    def __init__(self):
        self.value = deepcopy(RECORD)
    def get(self, provider):
        assert provider == 'twitch'
        return deepcopy(self.value)


class Fixture:
    def __init__(self):
        self.vault, self.calls = Vault(), []
        self.validation = {'client_id': 'fixture-client', 'user_id': '123', 'login': 'fixture',
                           'scopes': list(RECORD['scopes']), 'expires_in': 7000}
        self.key = {'data': [{'stream_key': 'synthetic-private-stream-key'}]}
        self.key_status = self.validate_status = 200
        self.hook = None
    async def http(self, request):
        self.calls.append(request)
        if request.url == helper.VALIDATE_URL:
            assert request.headers['Authorization'] == 'OAuth synthetic-access'
            return httpx.Response(self.validate_status, json=self.validation)
        assert request.url.host == 'api.twitch.tv' and request.url.path == '/helix/streams/key'
        assert dict(request.url.params) == {'broadcaster_id': '123'}
        assert request.headers['Authorization'] == 'Bearer synthetic-access'
        assert request.headers['Client-Id'] == 'fixture-client'
        if self.hook:
            self.hook()
        return httpx.Response(self.key_status, json=self.key)
    async def resolve(self, ref=REF):
        return await helper.resolve_stream_key(ref, vault=self.vault, clock=lambda: NOW,
            http_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(self.http)))


def test_key_is_returned_only_to_the_private_caller_after_provider_identity_validation(monkeypatch):
    monkeypatch.delenv('RAREIQ_TWITCH_CLIENT_ID', raising=False)
    f = Fixture()
    assert asyncio.run(f.resolve()) == {'ok': True, 'streamKey': 'synthetic-private-stream-key',
                                      'accountRef': REF, 'publicLabel': 'fixture'}
    assert len(f.calls) == 2 and f.vault.value == RECORD


@pytest.mark.parametrize('failure,reason', [('ref', 'account_identity_mismatch'),
    ('scope', 'streaming_scope_required'), ('expiry', 'authorization_refresh_required'),
    ('client', 'account_identity_mismatch'), ('rejected', 'authorization_rejected'),
    ('validation_scope', 'streaming_scope_required'), ('identity', 'account_identity_mismatch'),
    ('eligibility', 'streaming_not_available'), ('changed', 'account_state_changed'),
    ('malformed', 'invalid_provider_response')])
def test_private_helper_failures_never_return_a_key_or_provider_payload(monkeypatch, failure, reason):
    monkeypatch.delenv('RAREIQ_TWITCH_CLIENT_ID', raising=False)
    f = Fixture()
    ref = REF
    if failure == 'ref':
        ref = 'a' * 64
    elif failure == 'scope':
        f.vault.value['scopes'] = ['user:read:chat']
    elif failure == 'expiry':
        f.vault.value['expires_at'] = NOW
    elif failure == 'client':
        monkeypatch.setenv('RAREIQ_TWITCH_CLIENT_ID', 'wrong-client')
    elif failure == 'rejected':
        f.validate_status = 401
    elif failure == 'validation_scope':
        f.validation['scopes'] = ['user:read:chat']
    elif failure == 'identity':
        f.validation['user_id'] = '999'
    elif failure == 'eligibility':
        f.key_status = 403
    elif failure == 'changed':
        f.hook = lambda: f.vault.value.update(access_token='newer-token')
    elif failure == 'malformed':
        f.key = {'data': [{'stream_key': 'private\nkey'}]}
    with pytest.raises(helper.AccountError) as exc:
        asyncio.run(f.resolve(ref))
    assert str(exc.value) == reason and 'synthetic' not in str(exc.value)


def test_helper_reopens_encrypted_vault_without_any_write(tmp_path, monkeypatch):
    monkeypatch.delenv('RAREIQ_TWITCH_CLIENT_ID', raising=False)
    vault = PlatformCredentialVault(tmp_path / 'accounts.json', cipher=TestCipher())
    vault.set('twitch', RECORD)
    before = vault.path.read_bytes()
    f = Fixture()
    f.vault = PlatformCredentialVault(vault.path, cipher=TestCipher())
    assert asyncio.run(f.resolve())['accountRef'] == REF
    assert vault.path.read_bytes() == before
    assert b'synthetic-access' not in before


def test_config_path_resolution_matches_backend_without_initializing_directories(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCER_DESKTOP', raising=False)
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'storage_config.json').write_text(json.dumps({'config_path': 'private-config'}), encoding='utf-8')
    assert helper.credential_path(project) == project / 'private-config/platform_accounts.enc.json'
    assert not (project / 'private-config').exists()
    data = tmp_path / 'profile'
    data.mkdir()
    (data / 'storage_config.json').write_text(json.dumps({'config_path': 'runtime/config'}), encoding='utf-8')
    monkeypatch.setenv('PRODUCER_DESKTOP', '1')
    monkeypatch.setenv('PRODUCER_DESKTOP_DATA_ROOT', str(data))
    assert helper.credential_path(project) == data / 'runtime/config/platform_accounts.enc.json'
    assert not (data / 'runtime').exists()


def test_missing_config_fails_without_creating_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCER_DESKTOP', raising=False)
    with pytest.raises(helper.AccountError, match='account_storage_unavailable'):
        helper.credential_path(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_real_encrypted_vault_disconnect_forgets_all_auth_preserves_public_app_and_other_provider(tmp_path):
    from rareiq.services.twitch_account_service import TwitchAccountService
    async def run():
        path = tmp_path / 'accounts.json'
        vault = PlatformCredentialVault(path, cipher=TestCipher())
        vault.set('twitch', RECORD | {'client_secret': 'synthetic-legacy-secret'})
        vault.set('youtube', {'client_id': 'synthetic-youtube-client', 'refresh_token': 'synthetic-youtube-refresh'})
        other = vault.get('youtube')
        service = TwitchAccountService(vault, client_id_provider=lambda: (vault.get('twitch') or {}).get('client_id'),
                                       clock=lambda: NOW)
        status = await service.disconnect()
        assert not status['authorized'] and status['app_configured']
        reopened = PlatformCredentialVault(path, cipher=TestCipher())
        saved = reopened.get('twitch')
        assert saved['client_id'] == RECORD['client_id']
        assert all(not saved[key] for key in ('access_token', 'refresh_token', 'client_secret', 'channel_id', 'channel_login', 'scopes'))
        assert reopened.get('youtube') == other
        assert TwitchAccountService(reopened, clock=lambda: NOW).status()['authorized'] is False
        await service.close()
    asyncio.run(run())
