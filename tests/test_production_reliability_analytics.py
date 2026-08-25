import pytest

import rareiq.web.server as server
from rareiq.web.server import (
    _acknowledge_production_health_incident,
    _merged_interval_seconds,
    _production_health_analytics,
    _production_session_analytics_payload,
    _record_production_risk_transitions,
)


def _session(*, monitor=None, output_intent=None) -> dict:
    return {
        "active": False,
        "session_id": "reliability-test",
        "started_at": 100.0,
        "ended_at": 200.0,
        "events": [],
        "output_intent": output_intent or {
            "obs_stream": True,
            "obs_recording": True,
            "verified_destinations": ["Twitch", "YouTube Live"],
        },
        "health_monitor": monitor or {
            "active_risks": {},
            "journal": [],
            "incident_history": [],
        },
        "recording": {"verified": True},
    }


def test_interval_union_does_not_double_count_overlapping_outages() -> None:
    assert _merged_interval_seconds(
        [(101.0, 105.0), (103.0, 107.0), (110.0, 111.0)],
        lower=100.0,
        upper=200.0,
    ) == 7.0


def test_clean_requested_outputs_report_truthful_full_uptime() -> None:
    analytics = _production_health_analytics(_session(), now=200.0)

    assert analytics["duration_seconds"] == 100.0
    assert analytics["incident_count"] == 0
    assert analytics["unresolved_incident_count"] == 0
    assert analytics["session_quality"]["status"] == "clean"
    assert analytics["uptime"]["program_camera"]["uptime_percent"] == 100.0
    assert analytics["uptime"]["obs_stream"]["uptime_percent"] == 100.0
    assert analytics["uptime"]["obs_recording"]["uptime_percent"] == 100.0
    assert analytics["uptime"]["destination_route"]["uptime_percent"] == 100.0


def test_lifecycle_metrics_include_ack_recovery_unresolved_and_platform_uptime() -> None:
    completed = [
        {
            "incident_id": "camera-1",
            "risk_id": "program-camera",
            "state": "resolved",
            "title": "Program camera feed interrupted",
            "started_at": 110.0,
            "acknowledged_at": 112.0,
            "resolved_at": 120.0,
            "duration_seconds": 10.0,
            "acknowledgment_seconds": 2.0,
        },
        {
            "incident_id": "stream-1",
            "risk_id": "obs-stream",
            "state": "resolved",
            "title": "OBS stream output stopped",
            "started_at": 130.0,
            "resolved_at": 150.0,
            "duration_seconds": 20.0,
            "acknowledgment_seconds": None,
        },
        {
            "incident_id": "route-1",
            "risk_id": "destination-route",
            "state": "resolved",
            "title": "Verified destination route lost",
            "affected_destinations": ["Twitch"],
            "started_at": 140.0,
            "resolved_at": 160.0,
            "duration_seconds": 20.0,
            "acknowledgment_seconds": None,
        },
    ]
    active = {
        "obs-recording": {
            "incident_id": "recording-1",
            "severity": "critical",
            "title": "OBS recording stopped",
            "detail": "No active recording",
            "started_at": 190.0,
            "acknowledged_at": 195.0,
            "acknowledged_by": "operator",
        }
    }
    analytics = _production_health_analytics(
        _session(monitor={
            "active_risks": active,
            "journal": [],
            "incident_history": completed,
        }),
        now=200.0,
    )

    assert analytics["incident_count"] == 4
    assert analytics["resolved_incident_count"] == 3
    assert analytics["unresolved_incident_count"] == 1
    assert analytics["acknowledged_incident_count"] == 2
    assert analytics["acknowledgment_coverage_percent"] == 50.0
    assert analytics["average_acknowledgment_seconds"] == 3.5
    assert analytics["average_recovery_seconds"] == pytest.approx(16.667)
    assert analytics["session_quality"]["status"] == "attention"
    assert analytics["uptime"]["program_camera"]["uptime_percent"] == 90.0
    assert analytics["uptime"]["obs_stream"]["uptime_percent"] == 80.0
    assert analytics["uptime"]["obs_recording"]["uptime_percent"] == 90.0
    assert analytics["uptime"]["destination_route"]["uptime_percent"] == 70.0
    assert analytics["platform_uptime"]["Twitch"]["uptime_percent"] == 70.0
    assert analytics["platform_uptime"]["YouTube Live"]["uptime_percent"] == 80.0


def test_outputs_not_requested_never_claim_uptime() -> None:
    analytics = _production_health_analytics(
        _session(output_intent={
            "obs_stream": False,
            "obs_recording": False,
            "verified_destinations": [],
        }),
        now=200.0,
    )

    assert analytics["uptime"]["obs_stream"] == {
        "requested": False,
        "status": "not_requested",
        "uptime_seconds": None,
        "downtime_seconds": None,
        "uptime_percent": None,
    }
    assert analytics["platform_uptime"] == {}


def test_unresolved_incident_duration_freezes_when_session_ends() -> None:
    state = _session(monitor={
        "active_risks": {
            "program-camera": {
                "incident_id": "camera-open",
                "severity": "critical",
                "title": "Program camera feed interrupted",
                "started_at": 180.0,
            }
        },
        "journal": [],
        "incident_history": [],
    })

    analytics = _production_health_analytics(state, now=500.0)

    assert analytics["incident_lifecycles"][0]["duration_seconds"] == 20.0
    assert analytics["uptime"]["program_camera"]["downtime_seconds"] == 20.0


def test_record_acknowledge_and_resolve_preserve_exact_lifecycle(monkeypatch) -> None:
    state = _session()
    state["active"] = True
    state["ended_at"] = 0.0
    monkeypatch.setattr(server, "PRODUCTION_SESSION", state)
    monkeypatch.setattr(server, "_save_production_session", lambda: None)
    risk = {
        "id": "program-camera",
        "severity": "critical",
        "title": "Program camera feed interrupted",
        "detail": "Frame is stale",
        "action": "Inspect Program camera",
        "journal_key": "program-camera:stale",
    }

    journal = _record_production_risk_transitions(
        session_active=True,
        risks=[risk],
        now=100.0,
    )
    _acknowledge_production_health_incident(journal[0]["id"], now=103.0)
    _record_production_risk_transitions(
        session_active=True,
        risks=[],
        now=110.0,
    )
    state["active"] = False
    state["ended_at"] = 120.0
    analytics = _production_session_analytics_payload(state, now=120.0)

    incident = analytics["incident_lifecycles"][0]
    assert incident["started_at"] == 100.0
    assert incident["acknowledged_at"] == 103.0
    assert incident["resolved_at"] == 110.0
    assert incident["duration_seconds"] == 10.0
    assert incident["acknowledgment_seconds"] == 3.0
    assert analytics["unresolved_incidents"] == []
    assert analytics["session_quality"]["status"] == "recovered"
