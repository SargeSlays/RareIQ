from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
PAUSED = (ROOT / "docs/PAUSED_WORK.md").read_text(encoding="utf-8")


def test_paused_work_register_tracks_obs_and_cadence():
    assert "Live OBS connection and bootstrap" in PAUSED
    assert "every 20 completed implementation updates" in PAUSED


def test_show_analytics_api_aggregates_session_events():
    assert '@app.get("/api/production/session/analytics")' in SERVER
    assert 'camera_usage' in SERVER
    assert 'scene_usage' in SERVER
    assert 'average_cue_interval_seconds' in SERVER
    assert 'recording_verified' in SERVER
    assert '_production_session_analytics_payload' in SERVER
    assert 'incident_lifecycles' in SERVER
    assert 'platform_uptime' in SERVER
    assert 'unresolved_incidents' in SERVER


def test_show_analytics_dashboard_exists():
    for token in ('class="show-analytics"', 'id="analyticsDuration"', 'id="analyticsEvents"', 'id="analyticsCueGap"', 'id="analyticsIncidents"', 'id="analyticsUnresolved"', 'id="analyticsAckTime"', 'id="analyticsRecoveryTime"', 'id="analyticsProgramUptime"', 'id="analyticsObsUptime"', 'id="analyticsRecordingUptime"', 'id="analyticsDestinationUptime"', 'id="analyticsScenes"', 'id="analyticsCameras"', 'id="analyticsIncidentList"', 'id="analyticsQualitySummary"'):
        assert token in CONTROL
    assert 'function renderShowAnalytics' in JS
    assert 'async function loadShowAnalytics' in JS
    assert '.show-analytics-panels' in CSS
    assert '.analytics-row' in CSS
    assert '.analytics-incident[data-state="active"]' in CSS
    assert 'data.incident_lifecycles||[]' in JS
    assert 'formatUptime' in JS
