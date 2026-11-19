"""Actual HTTP/audit owner, with no external provider or media operations."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.greenroom_service import GreenroomService
from rareiq.web.stream_metadata import create_stream_metadata_router


class Service:
    def __init__(self):
        self.calls = []
        self.state = 'applied'
        self.error = None

    async def inspect(self, platform, broadcast_id=None):
        self.calls.append('inspect')
        return {'platform': platform, 'authorized': True, 'editable': False, 'fields': {}}

    async def categories(self, platform, query):
        self.calls.append('categories')
        return {'platform': platform, 'categories': []}

    async def apply(self, platform, values, request_id, expected_channel_id, broadcast_id=None):
        self.calls.append('apply')
        if self.error:
            raise ValueError(self.error)
        return {'platform': platform, 'state': self.state, 'request_id': request_id}


def fixture(tmp_path, *, host='127.0.0.1', operator=True, idle=True, audit_mode=None):
    service, room = Service(), GreenroomService(tmp_path / 'history.sqlite3')
    def audit(*, platform, outcome):
        if audit_mode == 'before' or audit_mode == 'after' and outcome != 'requested':
            raise OSError('private fixture failure')
        return room.record_production_event('platform.metadata.apply', platform, outcome)
    app = FastAPI()
    app.include_router(create_stream_metadata_router(service, lambda _: operator, audit=audit, can_apply=lambda: idle))
    client = TestClient(app, base_url='http://127.0.0.1:8765', client=(host, 12000))
    return client, service, room


HEADERS = {'Origin': 'http://127.0.0.1:8765'}
PAYLOAD = {'request_id': 'fixture-1', 'expected_channel_id': '123', 'values': {'title': 'Public fixture title'}}


@pytest.mark.parametrize('platform', ['twitch', 'youtube', 'kick'])
def test_real_audit_owner_accepts_metadata_without_logging_title(tmp_path, platform):
    client, service, room = fixture(tmp_path)
    response = client.post('/api/production/stream-metadata/' + platform + '/apply', json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 200 and response.json()['state'] == 'applied'
    assert service.calls == ['apply']
    events = room.history()['events']
    assert [e['outcome'] for e in events] == ['succeeded', 'requested']
    assert all(e['details'] == {} and e['target'] == platform for e in events)
    assert 'Public fixture title' not in str(events)


@pytest.mark.parametrize('case', ['remote', 'no_operator', 'origin', 'content_type', 'oversized', 'unknown_fields', 'active'])
def test_metadata_commands_fail_before_service_when_not_authorized_or_idle(tmp_path, case):
    client, service, _ = fixture(tmp_path, host='10.1.2.3' if case == 'remote' else '127.0.0.1', operator=case != 'no_operator', idle=case != 'active')
    headers = {} if case == 'origin' else HEADERS
    payload = {**PAYLOAD, 'extra': True} if case == 'unknown_fields' else PAYLOAD
    if case == 'content_type':
        response = client.post('/api/production/stream-metadata/twitch/apply', content='{}', headers=headers)
    elif case == 'oversized':
        response = client.post('/api/production/stream-metadata/twitch/apply', content='x' * 32769, headers={**headers, 'Content-Type': 'application/json'})
    else:
        response = client.post('/api/production/stream-metadata/twitch/apply', json=payload, headers=headers)
    assert response.status_code in {400, 403, 409}
    assert service.calls == []


def test_audit_failure_before_write_blocks_but_after_write_warns_separately(tmp_path):
    client, service, _ = fixture(tmp_path, audit_mode='before')
    response = client.post('/api/production/stream-metadata/twitch/apply', json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 503 and service.calls == []
    client, service, _ = fixture(tmp_path, audit_mode='after')
    response = client.post('/api/production/stream-metadata/twitch/apply', json=PAYLOAD, headers=HEADERS)
    assert response.json()['state'] == 'applied' and response.json()['activity_history_warning']
    assert service.calls == ['apply']


def test_unconfirmed_update_is_not_a_success_and_private_errors_are_redacted(tmp_path):
    client, service, room = fixture(tmp_path)
    service.state = 'unconfirmed'
    result = client.post('/api/production/stream-metadata/kick/apply', json=PAYLOAD, headers=HEADERS).json()
    assert result['state'] == 'unconfirmed' and room.history()['events'][0]['outcome'] == 'failed'
    service.error = 'private provider detail'
    result = client.post('/api/production/stream-metadata/kick/apply', json=PAYLOAD, headers=HEADERS).json()
    assert result == {'ok': False, 'reason': 'provider_unavailable'}
