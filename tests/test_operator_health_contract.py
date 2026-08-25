from pathlib import Path

import rareiq.web.server as server
from rareiq.web.server import (
    BROADCAST_RUNTIME_HEALTH_REFRESH_SECONDS,
    PRODUCTION_HEALTH_JOURNAL_LIMIT,
    _connected_production_camera_count,
    _invalidate_broadcast_runtime_health,
    _record_production_risk_transitions,
    _production_session_risks,
    _refresh_broadcast_runtime_health,
)


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_operator_health_and_safe_recovery_apis_exist():
    assert '@app.get("/api/production/operator-health")' in SERVER
    assert '@app.post("/api/production/safe")' in SERVER
    assert 'camera_manager.session_statuses()' in SERVER
    operator_health = SERVER[
        SERVER.index("async def production_operator_health") :
        SERVER.index('@app.get("/api/production/preflight")')
    ]
    assert "program_camera = _program_camera_readiness(slots, program_slot)" in operator_health
    assert '"program_camera": program_camera' in operator_health
    assert '"session_active": session_active' in operator_health
    assert '"output_intent": output_intent' in operator_health
    assert '"broadcast_runtime": broadcast_runtime' in operator_health
    assert '"risks": risks' in operator_health
    assert '"health_journal": health_journal[-20:]' in operator_health
    assert '"active_risk_ids": [risk["id"] for risk in risks]' in operator_health
    assert 'instant_replay.snapshot()' in SERVER
    assert 'instant_replay.stop_playback()' in SERVER
    assert 'obs.sync_scene, "main-card"' in SERVER
    assert 'response["obs_warning"]' in SERVER
    assert '"pokedex_on_air": False' in SERVER
    assert 'multi_card_recognition.select_slots([])' in SERVER
    assert 'reveal_sequence.cancel_animation()' in SERVER
    assert '"active_scene_id": "main-card"' in SERVER
    assert '"visible": False' in SERVER


def test_active_vision_camera_counts_as_connected_without_preview_session():
    slots = [
        {
            "slot_id": 1,
            "source_id": "camera-active",
            "role": "active",
            "connected": True,
        },
        {
            "slot_id": 2,
            "source_id": None,
            "role": "staging",
            "connected": False,
        },
    ]

    assert _connected_production_camera_count(slots) == 1


def test_only_configured_connected_slots_count_toward_production_health():
    slots = [
        {"slot_id": 1, "source_id": "camera-a", "connected": True},
        {"slot_id": 2, "source_id": "camera-b", "connected": False},
        {"slot_id": 3, "source_id": None, "connected": True},
    ]

    assert _connected_production_camera_count(slots) == 1


def test_operator_dashboard_uses_real_health_fields():
    for token in (
        'class="operator-health"',
        'id="operatorSafeScene"',
        'id="operatorCameraHealth"',
        'id="operatorProgramHealth"',
        'id="operatorRecognitionHealth"',
        'id="operatorAudioHealth"',
        'id="operatorReplayHealth"',
        'id="operatorOutputHealth"',
        'id="operatorHealthAlert"',
        'id="operatorHealthAlertTitle"',
        'id="operatorHealthAlertDetail"',
        'id="operatorHealthAlertAction"',
        'id="operatorHealthJournalCount"',
        'id="operatorHealthJournalList"',
    ):
        assert token in CONTROL
    assert 'async function loadOperatorHealth' in JS
    assert '/api/production/operator-health' in JS
    assert 'async function activateOperatorSafeScene' in JS
    assert '/api/production/safe' in JS
    assert 'stopProductionRundown()' in JS
    assert 'stopAllSoundboardAudio()' in JS
    render = JS[
        JS.index("function renderOperatorHealth") :
        JS.index("async function loadOperatorHealth")
    ]
    assert "programCamera=payload.program_camera||{}" in render
    assert 'healthCard("program",programReady?' in render
    assert 'programCamera.detail||payload.active_scene_id' in render
    assert "const unhealthy=!programReady" in render
    assert 'alert.hidden=!sessionActive||!criticalRisk' in render
    assert 'alert.dataset.riskCount=String(risks.length)' in render
    assert "LIVE SESSION AT RISK" in render
    assert "function renderOperatorHealthJournal" in JS
    assert "renderOperatorHealthJournal(payload.health_journal||[])" in JS


def test_inactive_session_never_claims_an_on_air_risk() -> None:
    risks = _production_session_risks(
        session_active=False,
        program_camera={"ready": False, "detail": "Camera stale"},
    )

    assert risks == []


def test_healthy_live_session_has_no_program_camera_risk() -> None:
    risks = _production_session_risks(
        session_active=True,
        program_camera={"ready": True, "detail": "Fresh frame"},
    )

    assert risks == []


def test_live_session_reports_stale_program_camera_without_auto_action() -> None:
    risks = _production_session_risks(
        session_active=True,
        program_camera={"ready": False, "detail": "Insta360 is connected but stale"},
    )

    assert risks == [
        {
            "id": "program-camera",
            "severity": "critical",
            "title": "Program camera feed interrupted",
            "detail": "Insta360 is connected but stale",
            "action": "Reconnect the camera or take a verified alternate source",
        }
    ]


def test_requested_obs_stream_loss_is_reported_without_false_platform_claims() -> None:
    risks = _production_session_risks(
        session_active=True,
        program_camera={"ready": True},
        output_intent={"obs_stream": True, "verified_destinations": ["Twitch"]},
        broadcast_runtime={
            "obs": {"connected": True, "streaming": False, "recording": False},
            "readiness": {"ready_destinations": ["Twitch"]},
        },
    )

    assert [risk["id"] for risk in risks] == ["obs-stream"]
    assert "reports no active stream" in risks[0]["detail"]


def test_requested_obs_connection_loss_collapses_stream_and_recording_risks() -> None:
    risks = _production_session_risks(
        session_active=True,
        program_camera={"ready": True},
        output_intent={"obs_stream": True, "obs_recording": True},
        broadcast_runtime={"obs": {"connected": False}},
    )

    assert [risk["id"] for risk in risks] == ["obs-connection"]


def test_verified_destination_route_loss_is_reported_only_while_streaming() -> None:
    intent = {"obs_stream": True, "verified_destinations": ["Twitch", "YouTube Live"]}
    runtime = {
        "obs": {"connected": True, "streaming": True, "recording": False},
        "readiness": {"ready_destinations": ["YouTube Live"]},
    }

    risks = _production_session_risks(
        session_active=True,
        program_camera={"ready": True},
        output_intent=intent,
        broadcast_runtime=runtime,
    )

    assert [risk["id"] for risk in risks] == ["destination-route"]
    assert "Twitch" in risks[0]["detail"]


def test_runtime_watchdog_refresh_is_bounded() -> None:
    assert BROADCAST_RUNTIME_HEALTH_REFRESH_SECONDS == 10.0
    operator_health = SERVER[
        SERVER.index("def _refresh_broadcast_runtime_health") :
        SERVER.index('@app.get("/api/production/operator-health")')
    ]
    assert "checked_at - cached_at < BROADCAST_RUNTIME_HEALTH_REFRESH_SECONDS" in operator_health
    assert "broadcast_destinations.refresh_connectors(" in operator_health
    assert "obs.status()" in operator_health


def test_runtime_watchdog_reuses_fresh_evidence(monkeypatch) -> None:
    calls = {"obs": 0, "connectors": 0}

    class FakeObs:
        def status(self):
            calls["obs"] += 1
            return {"enabled": True, "connected": True, "streaming": True, "recording": False}

        def cached_stream_route_probe(self):
            return object()

    class FakeDestinations:
        def refresh_connectors(self, *, obs_route=None):
            assert obs_route is not None
            calls["connectors"] += 1
            return {"twitch": True}

        def snapshot(self, *, obs_status=None):
            assert obs_status["connected"] is True
            return {
                "summary": {"ready": 1, "live": 1},
                "destinations": [
                    {"id": "twitch", "name": "Twitch", "ready": True, "live": True}
                ],
            }

    monkeypatch.setattr(server, "obs", FakeObs())
    monkeypatch.setattr(server, "broadcast_destinations", FakeDestinations())
    _invalidate_broadcast_runtime_health()
    first = _refresh_broadcast_runtime_health(now=100.0)
    cached = _refresh_broadcast_runtime_health(now=105.0)
    refreshed = _refresh_broadcast_runtime_health(now=111.0)
    _invalidate_broadcast_runtime_health()

    assert calls == {"obs": 2, "connectors": 2}
    assert first == cached
    assert refreshed["checked_at"] == 111.0
    assert refreshed["readiness"]["live_destinations"] == ["Twitch"]


def test_health_journal_records_only_meaningful_risk_transitions(monkeypatch) -> None:
    state = {
        "active": True,
        "session_id": "session-test",
        "events": [],
        "health_monitor": {"active_risks": {}, "journal": []},
    }
    monkeypatch.setattr(server, "PRODUCTION_SESSION", state)
    monkeypatch.setattr(server, "_save_production_session", lambda: None)
    risk = {
        "id": "obs-stream",
        "severity": "critical",
        "title": "OBS stream output stopped",
        "detail": "OBS reports no active stream",
        "action": "Inspect OBS output health",
    }

    opened = _record_production_risk_transitions(
        session_active=True,
        risks=[risk],
        now=100.0,
    )
    repeated = _record_production_risk_transitions(
        session_active=True,
        risks=[risk],
        now=101.0,
    )
    updated = _record_production_risk_transitions(
        session_active=True,
        risks=[risk | {"detail": "OBS output remains stopped"}],
        now=102.0,
    )
    resolved = _record_production_risk_transitions(
        session_active=True,
        risks=[],
        now=103.0,
    )

    assert [entry["state"] for entry in opened] == ["active"]
    assert repeated == opened
    assert [entry["state"] for entry in updated] == ["active", "updated"]
    assert [entry["state"] for entry in resolved] == ["active", "updated", "resolved"]
    assert len(state["events"]) == 3
    assert {event["kind"] for event in state["events"]} == {"safety"}


def test_health_journal_is_bounded_independently_of_session_events(monkeypatch) -> None:
    state = {
        "active": True,
        "events": [],
        "health_monitor": {"active_risks": {}, "journal": []},
    }
    monkeypatch.setattr(server, "PRODUCTION_SESSION", state)
    monkeypatch.setattr(server, "_save_production_session", lambda: None)

    for index in range(PRODUCTION_HEALTH_JOURNAL_LIMIT + 6):
        _record_production_risk_transitions(
            session_active=True,
            risks=[{
                "id": "program-camera",
                "severity": "critical",
                "title": "Program camera feed interrupted",
                "detail": f"Frame evidence changed {index}",
                "action": "Inspect Program camera",
            }],
            now=100.0 + index,
        )

    journal = state["health_monitor"]["journal"]
    assert len(journal) == PRODUCTION_HEALTH_JOURNAL_LIMIT == 64
    assert journal[-1]["detail"] == "Frame evidence changed 69"
    assert len(state["events"]) == 70


def test_inactive_health_poll_does_not_create_incident_history(monkeypatch) -> None:
    state = {
        "active": False,
        "events": [],
        "health_monitor": {"active_risks": {}, "journal": []},
    }
    monkeypatch.setattr(server, "PRODUCTION_SESSION", state)
    monkeypatch.setattr(server, "_save_production_session", lambda: None)

    journal = _record_production_risk_transitions(
        session_active=False,
        risks=[{"id": "program-camera", "title": "Camera unavailable"}],
        now=100.0,
    )

    assert journal == []
    assert state["events"] == []
    assert state["health_monitor"]["active_risks"] == {}


def test_show_start_records_only_operator_requested_output_intent() -> None:
    start = SERVER[
        SERVER.index("async def start_production_show") :
        SERVER.index('@app.post("/api/production/session/metadata")')
    ]
    assert 'PRODUCTION_SESSION["output_intent"]' in start
    assert '"obs_stream": bool(request.start_obs_stream)' in start
    assert '"obs_recording": bool(request.start_obs_recording)' in start
    assert '"verified_destinations": list(' in start
    assert '_invalidate_broadcast_runtime_health()' in start
    assert '"health_monitor": {"active_risks": {}, "journal": []}' in SERVER


def test_operator_health_is_themable_and_responsive():
    assert '.operator-health-grid' in CSS
    assert 'article[data-state="bad"]' in CSS
    assert '.operator-safe' in CSS
    assert '.operator-health-alert' in CSS
    assert '.operator-health-alert[hidden]{display:none}' in CSS
    assert '.operator-health-journal' in CSS
    assert '.operator-health-journal article[data-state="resolved"]' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .operator-health' in CSS
