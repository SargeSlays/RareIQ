from concurrent.futures import ThreadPoolExecutor
import io
import json
import sqlite3
import threading
import time
from types import SimpleNamespace
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.production_action_service import ActionSpec, ProductionActions
from rareiq.services.voice_command_service import VoiceCommandService, interpret_command
from rareiq.services.voice_rule_store import VoiceRuleStore
from rareiq.services.windows_speech_recognizer import WindowsSpeechRecognizer
from rareiq.web.voice_rules_api import voice_rules_router


def binding(phrase="close up", action="program.take", params=None):
    return {"phrase": phrase, "action_id": action, "params": params or {"preview_slot": 2, "transition": "fade", "duration_ms": 500}}


def audio():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 16000)
    return output.getvalue()


@pytest.fixture
def setup(tmp_path):
    actions = ProductionActions()
    calls, grammars = [], []

    def validate(params):
        if not isinstance(params.get("preview_slot"), int) or not 1 <= params["preview_slot"] <= 4:
            raise ValueError("invalid_slot")
        return params

    for name in ("program.take", "scene.take", "clip.save"):
        actions.register(ActionSpec(name, validate if name == "program.take" else lambda params: params,
                        lambda params: calls.append(params) or {"ok": True, "program_slot": 2}, "fixture"))
    store = VoiceRuleStore(tmp_path / "rules.sqlite3", actions.validate_parameters)
    recognizer = SimpleNamespace(capability=lambda: {"available": True}, recognize=lambda wav: {"text": "Sarge camera one", "confidence": .99})
    recognizer.recognize_with_phrases = lambda wav, phrases: grammars.append(phrases) or {"text": "Hey Sarge close up", "confidence": .99}
    keys = SimpleNamespace(start=lambda mode: {"ok": True}, stop=lambda: None, status=lambda: {"ptt_down": False}, permits=lambda end, start: True)
    service = VoiceCommandService(recognizer, actions, rules=store, emergency_probe=lambda: False, key_monitor=keys)
    yield service, store, calls, grammars
    service.close()
    actions.close()


def test_persisted_rules_validate_without_dispatch_and_keep_audit_separate_from_phrases(setup):
    service, store, calls, _ = setup
    result = service.replace_rules([binding("  Close   Up  ")], 0)
    assert result["ok"] and result["revision"] == 1
    assert result["rules"][0]["phrase"] == "close up"
    assert not calls
    restarted = VoiceRuleStore(store.path, store.validate_action)
    assert restarted.snapshot() == result
    assert restarted.replace([binding()], 0) == result  # Lost response retry is an unchanged operation.
    events = restarted.history()["events"]
    assert len(events) == 1 and not events[0]["identity_verified"]
    assert "close up" not in json.dumps(events)


@pytest.mark.parametrize("rules", [
    [binding("Sarge close up")], [binding("camera two")], [binding("save the last 30 seconds")],
    [binding("close; shutdown")], [binding("x" * 61)], [binding("up")],
    [binding(), binding("CLOSE UP")], [binding(action="stream.start")],
    [binding(params={"preview_slot": 99})], [binding() | {"actor": "owner"}],
    [binding(phrase=f"custom {n}") for n in range(25)],
])
def test_invalid_rules_never_persist_or_execute(setup, rules):
    service, store, calls, _ = setup
    assert not service.replace_rules(rules, 0)["ok"]
    assert store.snapshot()["revision"] == 0 and not calls


def test_concurrent_configuration_changes_cannot_overwrite_newer_revision(setup):
    _, store, _, _ = setup
    store.snapshot()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda phrase: store.replace([binding(phrase)], 0), ("close up", "wide shot")))
    assert sum(result["ok"] for result in results) == 1
    assert store.snapshot()["revision"] == 1


def test_rule_history_failure_rolls_back_configuration(setup):
    _, store, _, _ = setup
    original = store.snapshot()
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER reject_voice_history BEFORE INSERT ON voice_rule_activity BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.replace([binding()], 0)
    assert store.snapshot() == original


def test_session_parser_and_finite_grammar_share_captured_revision(setup):
    service, store, calls, grammars = setup
    service.replace_rules([binding()], 0)
    session = service.start(practice=False)["session_id"]
    assert service.status()["rules_revision"] == 1
    assert not service.rules_status()["editable"]
    assert service.replace_rules([binding("wide shot")], 1)["reason"] == "stop_voice_before_editing_rules"
    # A second process/configuration editor cannot change an already captured session.
    store.replace([binding("wide shot", params={"preview_slot": 4})], 1)
    result = service.audio(session, 1, time.time(), audio())
    assert result["last_result"]["state"] == "succeeded"
    assert grammars == [["close up"]] and calls[0]["preview_slot"] == 2
    service.stop(session)
    assert service.rules_status()["editable"]
    assert service.start()["rules_revision"] == 2


def test_custom_rules_keep_practice_wake_ptt_and_duplicate_guards(setup):
    service, _, calls, _ = setup
    service.replace_rules([binding()], 0)
    session = service.start()["session_id"]
    result = service.audio(session, 1, time.time(), audio())
    assert result["last_result"]["state"] == "validated" and not calls
    service.stop(session)
    service.recognizer.recognize_with_phrases = lambda wav, phrases: {"text": "close up", "confidence": .99}
    session = service.start(practice=False)["session_id"]
    assert service.audio(session, 1, time.time(), audio())["last_result"]["reason"] == "wake_phrase_required"
    assert not calls
    service.stop(session)
    session = service.start(practice=False, open_flow=True)["session_id"]
    assert service.audio(session, 1, time.time(), audio())["last_result"]["state"] == "succeeded"
    service.audio(session, 2, time.time(), audio())
    assert len(calls) == 1
    service.stop(session)
    service.keys.permits = lambda end, start: False
    session = service.start(practice=False, mode="ptt", open_flow=True)["session_id"]
    now = time.time()
    assert service.audio(session, 1, now, audio(), now - 1)["last_result"]["reason"] == "hold_to_talk_required"
    assert len(calls) == 1


def test_custom_clip_uses_current_audio_timestamp_not_saved_parameter():
    rule = binding("keep that moment", "clip.save", {"seconds": 30, "ending_at": 1})
    assert interpret_command("Sarge keep that moment", 100, rules=[rule]) == ("clip.save", {"seconds": 30, "ending_at": 100})
    assert rule["params"]["ending_at"] == 1


def test_custom_voice_requires_grammar_capability_and_storage_failure_does_not_arm(setup):
    service, store, _, _ = setup
    service.replace_rules([binding()], 0)
    del service.recognizer.recognize_with_phrases
    assert service.start()["reason"] == "custom_voice_grammar_unavailable"
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE voice_rules SET rules='bad json'")
    assert service.start()["reason"] == "voice_rules_storage_unavailable"
    assert service.status()["state"] == "stopped"


def test_recognizer_sends_bounded_custom_grammar_as_data_never_shell_arguments(monkeypatch):
    recognizer = WindowsSpeechRecognizer()
    received = []
    monkeypatch.setattr(recognizer, "_invoke", lambda mode, data: received.append((mode, data)) or {"ok": True, "text": "Sarge close up", "confidence": .99})
    recognizer.recognize_with_phrases(audio(), ["Close up"])
    payload = json.loads(received[0][1])
    assert received[0][0] == "recognize" and payload["phrases"] == ["close up"]
    assert payload["audio"].startswith("UklGR")
    with pytest.raises(ValueError):
        recognizer.recognize_with_phrases(audio(), ["close up; exit"])
    assert len(received) == 1


def test_settings_routes_enforce_loopback_revision_and_disarmed_state(setup):
    service, store, calls, _ = setup
    app = FastAPI()
    app.include_router(voice_rules_router(service))
    remote = TestClient(app, client=("192.0.2.1", 50000))
    local = TestClient(app, client=("127.0.0.1", 50000))
    try:
        path = "/api/production/voice/rules"
        assert remote.get(path, headers={"x-forwarded-for": "127.0.0.1"}).status_code == 403
        assert remote.put(path, json={"expected_revision": 0, "rules": [binding()]}).status_code == 403
        response = local.get(path)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert local.put(path, json={"expected_revision": True, "rules": []}).status_code == 400
        assert local.put(path, json={"expected_revision": 0, "rules": [], "actor": "owner"}).status_code == 400
        assert local.put(path, content="x" * 65537, headers={"Content-Type": "application/json"}).status_code == 413
        assert local.put(path, json={"expected_revision": 0, "rules": [binding()]}).status_code == 200
        assert local.put(path, json={"expected_revision": 0, "rules": [binding("wide shot")]}).status_code == 409
        session = service.start()["session_id"]
        assert local.put(path, json={"expected_revision": 1, "rules": []}).status_code == 409
        service.stop(session)
        assert local.put(path, json={"expected_revision": 1, "rules": []}).status_code == 200
        assert store.snapshot()["rules"] == [] and not calls
    finally:
        local.close()
        remote.close()
