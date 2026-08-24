from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_preflight_api_covers_core_production_systems():
    assert '@app.get("/api/production/preflight")' in SERVER
    for token in ("camera_manager.session_statuses()", "recording.settings()", "recording.capabilities()", "instant_replay.snapshot()", "obs.status", '"blockers"', '"warnings"'):
        assert token in SERVER
    assert '@app.post("/api/production/show/start")' in SERVER
    assert "preflight_blocked" in SERVER
    assert "production_safe_recovery()" in SERVER
    assert '@app.post("/api/production/show/stop")' in SERVER
    assert 'obs.command, "stop-record"' in SERVER
    assert 'obs.command, "stop-stream"' in SERVER


def test_preflight_ui_has_readiness_verdict_and_checks():
    for token in ('id="showPreflight"', 'id="showPreflightVerdict"', 'id="showPreflightChecks"', 'id="showPreflightRefresh"'):
        assert token in CONTROL
    assert "async function loadShowPreflight" in JS
    assert 'api("/api/production/preflight")' in JS
    assert "renderShowPreflight" in JS
    assert "const escapeHtml" in JS
    assert 'id="showStartButton"' in CONTROL
    assert 'id="showStartObsStream"' in CONTROL
    assert "async function startProductionShow" in JS
    assert 'api("/api/production/show/start"' in JS
    assert "requestError.payload=payload" in JS
    assert 'id="productionSessionEndStatus"' in CONTROL
    assert "async function stopProductionShow" in JS
    assert 'api("/api/production/show/stop"' in JS


def test_preflight_is_themable_and_responsive():
    assert ".show-preflight-checks" in CSS
    assert 'article[data-state="fail"]' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .show-preflight' in CSS
    assert "@media(max-width:680px)" in CSS
    assert ".show-start-controls" in CSS
    assert ".production-session-end-status" in CSS
