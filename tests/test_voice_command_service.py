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
    service = VoiceCommandService(recognizer, actions, emergency_probe=lambda: False)
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
    recognizer.recognize = lambda _wav: {'text': 'Producer please save the last sixty seconds', 'confidence': .95}
    session = service.start(practice=False)['session_id']
    ended = time.time() - 2
    result = service.audio(session, 1, ended, audio_bytes())
    assert calls == [{'seconds': 60, 'name': 'Voice highlight', 'ending_at': ended}]
    assert 'Less history' in result['last_result']['message']
    assert 'text' not in result['last_result']


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
        session = client.post('/api/production/voice/start', json={}).json()['session_id']
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
