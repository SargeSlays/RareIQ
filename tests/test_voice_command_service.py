import io
import threading
import time
import wave
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rareiq.services.production_action_service import ActionSpec, ProductionActions
from rareiq.services.voice_command_service import VoiceCommandService, interpret_command


def audio_bytes():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0' * 16000)
    return output.getvalue()


@pytest.fixture
def voice():
    calls = []
    actions = ProductionActions()
    for name in ('program.take', 'clip.save'):
        actions.register(ActionSpec(name, lambda value: value,
            lambda params: calls.append(params) or {'ok': True, 'program_slot': 2, 'actual_seconds': 4, 'shorter_than_requested': True}, 'fixture'))
    recognizer = SimpleNamespace(capability=lambda: {'available': True},
        recognize=lambda _wav: {'text': 'Sarge camera two', 'confidence': .95})
    keys = SimpleNamespace(start=lambda _mode: {'ok': True}, stop=lambda: None, status=lambda: {'ptt_down': False}, permits=lambda _end, _start: False)
    service = VoiceCommandService(recognizer, actions, emergency_probe=lambda: False, key_monitor=keys)
    yield service, recognizer, calls
    service.close()
    actions.close()


@pytest.mark.parametrize('phrase', ['camera two', 'Sarge start stream', 'Sarge camera two delete clips', 'Someone said Sarge camera two', 'Producer please run powershell'])
def test_only_complete_allowlisted_wake_commands_parse(phrase):
    assert interpret_command(phrase, 10) is None


def test_practice_never_executes_and_real_clip_keeps_audio_timestamp(voice):
    service, recognizer, calls = voice
    session = service.start()['session_id']
    result = service.audio(session, 1, time.time(), audio_bytes())
    assert result['last_result']['state'] == 'validated' and not calls
    service.stop(session)
    recognizer.recognize = lambda _wav: {'text': 'Sarge save the last sixty seconds', 'confidence': .95}
    session = service.start(practice=False)['session_id']
    ended = time.time() - 2
    result = service.audio(session, 1, ended, audio_bytes())
    assert calls == [{'seconds': 60, 'name': 'Voice highlight', 'ending_at': ended}]
    assert 'Less history' in result['last_result']['message']
    assert 'text' not in result['last_result']


def test_ptt_requires_entire_utterance_window_before_recognition(voice):
    service, recognizer, calls = voice
    recognized = []
    recognizer.recognize = lambda _wav: recognized.append(True) or {'text': 'Sarge camera two', 'confidence': .99}
    session = service.start(practice=False, mode='ptt')['session_id']
    now = time.time()
    assert service.audio(session, 1, now, audio_bytes(), now-1)['last_result']['reason'] == 'hold_to_talk_required'
    assert not recognized and not calls
    service.keys.permits = lambda end, start: start == now-.5 and end == now
    result = service.audio(session, 2, now, audio_bytes(), now-.5)
    assert result['last_result']['state'] == 'succeeded' and len(calls) == 1
    assert len(recognized) == 1
    service.stop(session)
    recognizer.recognize = lambda _wav: {'text': 'camera two', 'confidence': .99}
    session = service.start(practice=False)['session_id']
    assert service.audio(session, 1, now, audio_bytes())['last_result']['state'] == 'rejected'
    assert len(calls) == 1


@pytest.mark.parametrize('prefix', ['Sarge', 'Hey Sarge'])
@pytest.mark.parametrize('alias', ['camera', 'cam'])
@pytest.mark.parametrize('number,slot', [('one', 1), ('two', 2), ('three', 3), ('four', 4), ('1', 1), ('2', 2), ('3', 3), ('4', 4)])
def test_camera_aliases_parse_with_all_supported_prefixes(prefix, alias, number, slot):
    assert interpret_command(f'{prefix} {alias} {number}', 10) == ('program.take', {'preview_slot': slot, 'transition': 'cut'})


@pytest.mark.parametrize('mode', ['wake', 'ptt'])
@pytest.mark.parametrize('phrase', ['cam two', 'camera 2', 'clip that', 'save the last thirty seconds', 'Producer please camera two'])
def test_both_modes_reject_known_bare_commands_by_default(voice, mode, phrase):
    service, recognizer, calls = voice
    service.keys.permits = lambda _end, _start: True
    recognizer.recognize = lambda _wav: {'text': phrase, 'confidence': .95}
    session = service.start(practice=False, mode=mode)['session_id']
    now = time.time()
    result = service.audio(session, 1, now, audio_bytes(), now - 1)
    assert result['open_flow'] is False
    assert result['last_result']['reason'] == 'wake_phrase_required'
    assert 'Hey Sarge' in result['last_result']['message'] and 'No action' in result['last_result']['message']
    assert not calls


@pytest.mark.parametrize('mode', ['wake', 'ptt'])
@pytest.mark.parametrize('phrase', ['Sarge cam 2', 'Hey Sarge cam two'])
def test_both_modes_dispatch_prefixed_aliases_without_open_flow(voice, mode, phrase):
    service, recognizer, calls = voice
    service.keys.permits = lambda _end, _start: True
    recognizer.recognize = lambda _wav: {'text': phrase, 'confidence': .95}
    session = service.start(practice=False, mode=mode)['session_id']
    now = time.time()
    assert service.audio(session, 1, now, audio_bytes(), now - 1)['last_result']['state'] == 'succeeded'
    assert calls == [{'preview_slot': 2, 'transition': 'cut'}]


@pytest.mark.parametrize('mode', ['wake', 'ptt'])
@pytest.mark.parametrize('phrase', ['cam two', 'camera 2', 'clip that', 'Producer please camera two'])
def test_only_explicit_open_flow_permits_bare_commands(voice, mode, phrase):
    service, recognizer, calls = voice
    service.keys.permits = lambda _end, _start: True
    recognizer.recognize = lambda _wav: {'text': phrase, 'confidence': .95}
    started = service.start(practice=False, mode=mode, open_flow=True)
    assert started['open_flow'] is True
    now = time.time()
    assert service.audio(started['session_id'], 1, now, audio_bytes(), now - 1)['last_result']['state'] == 'succeeded'
    assert len(calls) == 1


def test_open_flow_never_bypasses_ptt_interval_guard(voice):
    service, recognizer, calls = voice
    recognizer.recognize = lambda _wav: pytest.fail('recognition before PTT authorization')
    session = service.start(practice=False, mode='ptt', open_flow=True)['session_id']
    now = time.time()
    assert service.audio(session, 1, now, audio_bytes(), now - 1)['last_result']['reason'] == 'hold_to_talk_required'
    assert not calls


@pytest.mark.parametrize('value', [None, 0, 1, 'false', 'true', [], {}, .5])
def test_malformed_open_flow_cannot_arm_or_change_session(voice, value):
    service, _, calls = voice
    assert service.start(open_flow=value) == {'ok': False, 'reason': 'invalid_open_flow'}
    assert service.status()['state'] == 'stopped' and service.status()['open_flow'] is False
    assert not calls


def test_open_flow_is_immutable_until_stop_and_fresh_sessions_default_off(voice):
    service, _, _ = voice
    session = service.start(open_flow=True)['session_id']
    assert service.start(open_flow=False)['reason'] == 'voice_session_active_or_finishing'
    assert service.stop('wrong-session')['ok'] is False
    assert service.status()['open_flow'] is True
    assert service.stop(session)['open_flow'] is False
    assert service.start()['open_flow'] is False


@pytest.mark.parametrize('phrase', ['Someone said Hey Sarge cam two', 'Hey Sarge cam two delete clips', 'cam two then camera one', 'please cam two', 'Hey Sarge start stream'])
def test_open_flow_does_not_accept_substrings_or_unknown_actions(phrase):
    assert interpret_command(phrase, 10, allow_bare=True) is None


def test_ptt_shortcut_conflict_does_not_arm(voice):
    service, _, _ = voice
    service.keys.start = lambda _mode: {'ok': False, 'reason': 'shortcut_conflict'}
    assert service.start(mode='ptt') == {'ok': False, 'reason': 'shortcut_conflict'}
    assert service.status()['state'] == 'stopped'


def test_session_diagnostics_distinguish_key_presses_audio_and_fresh_results(voice):
    service, _, _ = voice
    service.keys.status = lambda: {'available': True, 'press_count': 3, 'last_pressed_at': 100}
    session = service.start()['session_id']
    assert service.status()['diagnostics'] == {'shortcut_presses': 3, 'last_shortcut_at': 100, 'audio_sequence': 0}
    now, data = time.time(), audio_bytes()
    result = service.audio(session, 1, now, data)
    assert result['diagnostics']['audio_sequence'] == 1
    timestamp = result['last_result']['at']
    assert timestamp >= now
    assert service.audio(session, 1, now, data)['last_result']['at'] == timestamp
    service.stop(session)
    service.start()
    assert service.status()['diagnostics']['audio_sequence'] == 0
    assert service.status()['last_result'] is None


def test_lost_key_observer_revokes_wake_session(voice):
    service, _, calls = voice
    session = service.start(practice=False)['session_id']
    service.keys.status = lambda: {'available': False, 'ptt_down': False}
    assert service.audio(session, 1, time.time(), audio_bytes())['state'] == 'stopped'
    deadline = time.monotonic() + 1
    while service.status()['state'] != 'stopped' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['reason'] == 'voice_shortcut_unavailable' and not calls


def test_duplicate_audio_conflicts_and_low_confidence_fail_closed(voice):
    service, recognizer, calls = voice
    session = service.start(practice=False)['session_id']
    ended, wav = time.time(), audio_bytes()
    service.audio(session, 1, ended, wav)
    service.audio(session, 1, ended, wav)
    assert len(calls) == 1
    assert service.audio(session, 1, ended + .01, wav)['reason'] == 'voice_sequence_conflict'
    assert service.audio(session, 2, ended - 20, wav)['reason'] == 'stale_voice_audio'
    assert service.audio(session, 2, ended, b'bad')['reason'] == 'invalid_voice_audio'
    recognizer.recognize = lambda _wav: {'text': 'Sarge camera one', 'confidence': .4}
    assert service.audio(session, 2, ended, wav)['last_result']['state'] == 'rejected'
    assert len(calls) == 1


def test_stop_during_recognition_discards_result_and_never_dispatches(voice):
    service, recognizer, calls = voice
    entered, release = threading.Event(), threading.Event()
    def pending(_wav):
        entered.set()
        assert release.wait(3)
        return {'text': 'Sarge camera two', 'confidence': .99}
    recognizer.recognize = pending
    session = service.start(practice=False)['session_id']
    worker = threading.Thread(target=service.audio, args=(session, 1, time.time(), audio_bytes()))
    worker.start()
    assert entered.wait(1)
    assert service.audio(session, 2, time.time(), audio_bytes())['reason'] == 'voice_busy'
    assert service.stop('another-session')['ok'] is False
    service.stop(session)
    assert service.start()['ok'] is False
    release.set()
    worker.join(3)
    assert not worker.is_alive() and not calls
    assert service.status()['state'] == 'stopped' and service.status()['last_result'] is None


def test_emergency_shortcut_stops_only_voice_and_lease_expires(voice):
    service, _, calls = voice
    service._probe = lambda: True
    service.start(practice=False)
    deadline = time.monotonic() + 1
    while service.status()['state'] != 'stopped' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['reason'] == 'emergency_stop' and not calls
    service._probe = lambda: False
    service.start()
    service._heartbeat_at = time.monotonic()-31
    deadline = time.monotonic() + 1
    while service.status()['state'] != 'stopped' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['reason'] == 'input_session_expired'


def test_recognition_error_still_obeys_emergency_stop(voice):
    service, recognizer, calls = voice
    recognizer.recognize = lambda _wav: (_ for _ in ()).throw(RuntimeError('private diagnostic'))
    session = service.start()['session_id']
    assert service.audio(session, 1, time.time(), audio_bytes())['state'] == 'error'
    service._probe = lambda: True
    deadline = time.monotonic() + 1
    while service.status()['state'] != 'stopped' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['reason'] == 'emergency_stop' and not calls


def test_late_adapter_completion_is_observed_without_reexecuting(voice):
    service, _, calls = voice
    release = threading.Event()
    original = service.actions._specs['program.take']
    def execute(params):
        assert release.wait(3)
        return original.execute(params)
    service.actions._specs['program.take'] = ActionSpec('program.take', original.validate, execute, 'fixture', .01)
    session = service.start(practice=False)['session_id']
    result = service.audio(session, 1, time.time(), audio_bytes())
    assert result['last_result']['state'] == 'executing' and not calls
    release.set()
    deadline = time.monotonic() + 1
    while service.status()['last_result']['state'] == 'executing' and time.monotonic() < deadline:
        time.sleep(.01)
    assert service.status()['last_result']['state'] == 'succeeded' and len(calls) == 1


def test_http_audio_practice_loopback_and_body_limits(voice, monkeypatch):
    from rareiq.web import server
    service, _, calls = voice
    monkeypatch.setattr(server, 'voice_commands', service)
    client = TestClient(server.app, client=('127.0.0.1', 50000))
    try:
        started = client.post('/api/production/voice/start', json={}).json()
        assert started['open_flow'] is False
        session = started['session_id']
        response = client.post('/api/production/voice/audio', params={'session_id': session, 'sequence': 1, 'ended_at': time.time()}, content=audio_bytes(), headers={'Content-Type': 'audio/wav'})
        assert response.status_code == 200 and response.json()['last_result']['state'] == 'validated'
        assert not calls
        assert client.post('/api/production/voice/audio', content=b'x' * 192045).status_code == 413
        assert client.post('/api/production/voice/stop', json={'session_id': session}).json()['state'] == 'stopped'
    finally:
        client.close()
    client = TestClient(server.app, client=('192.168.1.9', 50000))
    try:
        assert client.post('/api/production/voice/start', json={}).status_code in (401, 403)
    finally:
        client.close()


@pytest.mark.parametrize('value', ['true', 1, None])
def test_http_rejects_coerced_open_flow_before_arming(voice, monkeypatch, value):
    from rareiq.web import server
    service, _, calls = voice
    monkeypatch.setattr(server, 'voice_commands', service)
    client = TestClient(server.app, client=('127.0.0.1', 50000))
    try:
        response = client.post('/api/production/voice/start', json={'open_flow': value})
        assert response.status_code == 422
        assert service.status()['state'] == 'stopped' and service.status()['open_flow'] is False
        assert not calls
    finally:
        client.close()


def test_http_explicit_open_flow_round_trip_is_true(voice, monkeypatch):
    from rareiq.web import server
    service, recognizer, calls = voice
    recognizer.recognize = lambda _wav: {'text': 'cam two', 'confidence': .95}
    monkeypatch.setattr(server, 'voice_commands', service)
    client = TestClient(server.app, client=('127.0.0.1', 50000))
    try:
        started = client.post('/api/production/voice/start', json={'open_flow': True}).json()
        assert started['open_flow'] is True and service.status()['open_flow'] is True
        response = client.post('/api/production/voice/audio', params={'session_id': started['session_id'], 'sequence': 1, 'ended_at': time.time()}, content=audio_bytes(), headers={'Content-Type': 'audio/wav'})
        assert response.json()['last_result']['state'] == 'validated' and not calls
        assert client.post('/api/production/voice/stop', json={'session_id': started['session_id']}).json()['open_flow'] is False
    finally:
        client.close()
