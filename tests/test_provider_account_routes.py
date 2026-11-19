"""Real account HTTP/audit owner contract with synthetic provider services only."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from rareiq.web.platform_accounts import create_platform_accounts_router
from rareiq.services.greenroom_service import GreenroomService


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
