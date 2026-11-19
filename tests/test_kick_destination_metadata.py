"""Public account status must never expose Kick ingest material."""
import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.web.platform_accounts import create_platform_accounts_router, _kick_status
from tests.test_kick_account_service import Fixture, record


@pytest.mark.parametrize('authorized,state', [(False, 'not_authorized'), (True, 'unavailable')])
def test_false_or_unavailable_authorization_cannot_carry_ref_or_streaming_flag(authorized, state):
    status = _kick_status({'state': state, 'reason': 'authorization_required', 'authorized': authorized,
        'app_configured': True, 'streaming_authorized': True, 'account_ref': 'a' * 64,
        'streamKey': 'synthetic-private-key', 'serverUrl': 'rtmps://private.invalid/app'})
    assert not status['authorized'] and not status['streaming_authorized'] and 'account_ref' not in status
    assert 'streamKey' not in status and 'serverUrl' not in status


@pytest.mark.parametrize('ref', [None, 'private-account-id', 'a' * 63, 'A' * 64, True])
def test_invalid_account_references_are_omitted_without_coercion(ref):
    status = _kick_status({'state': 'authorized', 'reason': 'account_authorized', 'authorized': True,
        'app_configured': True, 'streaming_authorized': True, 'account_ref': ref})
    assert status['streaming_authorized'] and 'account_ref' not in status


def test_actual_kick_owner_public_status_contains_only_safe_linking_metadata():
    f = Fixture(stored=record())
    app = FastAPI()
    twitch = SimpleNamespace(status=lambda: {'state': 'not_authorized', 'reason': 'authorization_required'})
    app.include_router(create_platform_accounts_router(twitch, lambda _: True, kick_service=f.service))
    client = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 1234))
    response = client.get('/api/production/accounts')
    assert response.status_code == 200
    kick = response.json()['accounts'][2]
    assert kick['streaming_authorized'] and len(kick['account_ref']) == 64
    assert set(kick) == {'platform', 'state', 'reason', 'authorized', 'app_configured',
                         'metadata_authorized', 'streaming_authorized', 'account_ref', 'public_label', 'expires_at'}
    assert all(word not in json.dumps(kick) for word in ('synthetic', 'streamKey', 'access_token', 'client_secret', 'channel_id'))
    assert f.calls == [] and not f.vault.saves
    asyncio.run(f.service.close())
