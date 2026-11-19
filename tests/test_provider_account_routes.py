"""Real account HTTP/audit owner contract with synthetic provider services only."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from rareiq.web.platform_accounts import create_platform_accounts_router
from rareiq.services.greenroom_service import GreenroomService


def test_youtube_destination_account_metadata_is_bounded_and_never_contains_private_setup():
    from rareiq.web.platform_accounts import _youtube_status
    raw = dict(platform='youtube', state='authorized', reason='account_authorized',
               authorized=True, app_configured=True, streaming_authorized=True,
               account_ref='a' * 64, access_token='private-token', streamKey='private-key',
               client_secret='private-client')
    public = _youtube_status(raw)
    assert public['streaming_authorized'] is True and public['account_ref'] == 'a' * 64
    assert not any('private' in str(value) for value in public.values())
    assert 'account_ref' not in _youtube_status({**raw, 'account_ref': 'invalid'})
    for state in ('not_authorized', 'unavailable'):
        public = _youtube_status({**raw, 'state': state, 'authorized': False})
        assert public['streaming_authorized'] is False and 'account_ref' not in public


class Account:
    def __init__(self, platform):
        self.platform = platform
        self.connected = True
    def status(self):
        return dict(platform=self.platform, state="authorized" if self.connected else "not_authorized",
                    authorized=self.connected, app_configured=True,
                    reason="account_authorized" if self.connected else "account_disconnected", public_label="Fixture")
    async def check(self):
        pass
    async def disconnect(self):
        self.connected = False
    async def begin(self):
        pass
    async def cancel(self):
        pass


@pytest.mark.parametrize("platform", ["youtube", "kick"])
def test_provider_routes_share_real_audit_guards_and_forget_even_when_history_fails(tmp_path, platform):
    room = GreenroomService(tmp_path / 'events.sqlite3')
    accounts = {p: Account(p) for p in ['twitch', 'youtube', 'kick']}
    stopped = []
    broken = False
    def audit(*, action, outcome):
        if broken:
            raise OSError('private path')
        provider, operation = action.split('.')
        result = 'requested' if outcome in {'requested', 'pending'} else 'succeeded' if outcome in {'authorized', 'not_authorized'} else 'failed'
        room.record_production_event('platform.account.' + operation, provider, result)
    async def stop():
        stopped.append(platform)
    app = FastAPI()
    app.include_router(create_platform_accounts_router(accounts['twitch'], lambda _: True,
        youtube_service=accounts['youtube'], kick_service=accounts['kick'], audit=audit,
        youtube_disconnect=stop, kick_disconnect=stop))
    client = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 12000))
    path = '/api/production/accounts/' + platform
    headers = {'Origin': 'http://127.0.0.1:8765'}
    assert client.post(path + '/begin', json={}).status_code == 403
    assert client.post(path + '/check', json={}, headers=headers).json()['account']['authorized']
    assert len(room.history()['events']) == 2
    broken = True
    result = client.post(path + '/disconnect', json={}, headers=headers).json()
    assert not result['account']['authorized'] and result['activity_history_warning']
    assert stopped == [platform]
    assert 'private' not in str(result)


def test_kick_setup_route_is_not_shadowed_by_account_actions_and_uses_real_audit(tmp_path):
    from rareiq.web.platform_app_setup import create_platform_app_setup_router
    room = GreenroomService(tmp_path / 'setup-history.sqlite3')
    accounts = {p: Account(p) for p in ['twitch', 'youtube', 'kick']}
    class Setup:
        async def configure(self, platform, value):
            assert platform == 'kick' and set(value) == {'client_id', 'client_secret'}
            return dict(configured=True, replayed=False, platform=platform)
    def audit(*, action, outcome):
        provider, operation = action.split('.')
        room.record_production_event('platform.account.' + operation, provider,
            'succeeded' if outcome == 'configured' else 'requested')
    app = FastAPI()
    app.include_router(create_platform_accounts_router(accounts['twitch'], lambda _: True,
        youtube_service=accounts['youtube'], kick_service=accounts['kick']))
    app.include_router(create_platform_app_setup_router(Setup(), lambda _: True, audit=audit))
    client = TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 12000))
    result = client.post('/api/production/accounts/kick/configure-app',
        json={'client_id': 'synthetic-app', 'client_secret': 'synthetic-private-setup'},
        headers={'Origin': 'http://127.0.0.1:8765'})
    assert result.status_code == 200 and result.json()['configured']
    assert 'synthetic-private-setup' not in result.text
    events = room.history()['events']
    assert [e['outcome'] for e in events] == ['succeeded', 'requested']
    assert all(e['action'] == 'platform.account.configure_app' and e['details'] == {} for e in events)
