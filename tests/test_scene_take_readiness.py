import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('slot', [None, {'slot_id': 2, 'source_id': None, 'connected': True}, {'slot_id': 2, 'source_id': 'fixture', 'connected': False}])
def test_scene_rejects_unavailable_camera_before_any_effect(monkeypatch, slot):
    from rareiq.web import server
    state = {'program_slot': 1, 'preview_slot': 2, 'generation': 0}
    before = deepcopy(state)
    def forbidden(*_args):
        pytest.fail('A rejected scene must not change overlays or OBS')
    monkeypatch.setattr(server, 'PRODUCTION_SWITCHER_STATE', state)
    monkeypatch.setattr(server, 'PRODUCTION_SCENES', [{'id': 'fixture', 'program_slot': 2, 'screen_action': 'show'}])
    monkeypatch.setattr(server, 'orchestrator', SimpleNamespace(camera_manager=SimpleNamespace(camera_slots=lambda: [slot] if slot else []), overlay_state=SimpleNamespace(get=forbidden, update=forbidden)))
    monkeypatch.setattr(server, 'obs', SimpleNamespace(sync_scene=forbidden))
    # No lifespan: exercise the real route without opening cameras or services.
    client = TestClient(server.app, client=('127.0.0.1', 50000))
    try:
        response = client.post('/api/production/scenes/fixture/take')
        assert response.status_code == 409
        assert response.json()['reason'] == 'camera_slot_unavailable'
    finally:
        client.close()
    assert state == before


def test_ready_scene_still_applies_camera_screen_and_reports_obs_failure(monkeypatch):
    from rareiq.web import server
    updates = []
    def unavailable(_scene_id):
        raise RuntimeError('OBS unavailable')
    monkeypatch.setattr(server, 'PRODUCTION_SWITCHER_STATE', {'program_slot': 1, 'preview_slot': 2, 'generation': 0})
    monkeypatch.setattr(server, 'PRODUCTION_SCENES', [{'id': 'fixture', 'program_slot': 2, 'screen_action': 'show'}])
    monkeypatch.setattr(server, 'orchestrator', SimpleNamespace(camera_manager=SimpleNamespace(camera_slots=lambda: [{'slot_id': 2, 'source_id': 'fixture', 'connected': True}]), overlay_state=SimpleNamespace(get=lambda: {}, update=updates.append)))
    monkeypatch.setattr(server, 'obs', SimpleNamespace(sync_scene=unavailable))
    response = asyncio.run(server.take_production_scene('fixture'))
    assert response['ok'] and response['program_slot'] == 2 and response['generation'] == 1
    assert updates[0]['production_screen']['visible'] is True
    assert response['obs_warning'] == 'OBS unavailable'
