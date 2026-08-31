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
    assert SERVER.count("connected = _connected_production_camera_count(slots)") == 1
    assert "_program_camera_readiness(" in SERVER
    assert "PRODUCTION_CAMERA_FRESHNESS_SECONDS = 2.0" in SERVER
    assert "broadcast_destinations.refresh_connectors," in SERVER
    assert "destination_status = broadcast_destinations.snapshot(obs_status=obs_status)" in SERVER
    assert "_broadcast_go_live_readiness(destination_status, obs_status)" in SERVER
    assert '"broadcast_ready": local_ready and broadcast_readiness["ready"]' in SERVER
    assert '"on_air_verified": broadcast_readiness["platform_live_verified"]' in SERVER


def test_preflight_ui_has_readiness_verdict_and_checks():
    for token in ('id="showPreflight"', 'id="showPreflightVerdict"', 'id="showPreflightChecks"', 'id="showPreflightRefresh"', 'id="showPreflightSignals"', 'id="showPreflightLocalSignal"', 'id="showPreflightObsSignal"', 'id="showPreflightDestinationSignal"', 'id="showPreflightLiveSignal"'):
        assert token in CONTROL
    assert "async function loadShowPreflight" in JS
    assert 'api("/api/production/preflight?workflow="+encodeURIComponent(workflow)' in JS
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
    assert "function syncShowStartAvailability" in JS
    assert '"LOCAL SHOW READY"' in JS
    assert '"READY TO GO LIVE"' in JS
    assert 'showStartObsStream")?.addEventListener("change",syncShowStartAvailability)' in JS
    assert "if(payload.destinations)renderBroadcastDestinations(payload.destinations)" in JS
    broadcast_start = JS.index('if(name==="broadcast")')
    broadcast_activation = JS[broadcast_start : JS.index("return true;", broadcast_start)]
    assert "loadShowPreflight()" in broadcast_activation
    assert "loadBroadcastDestinations()" not in broadcast_activation


def test_unverified_destination_blocks_only_requested_obs_stream_start():
    start = SERVER[
        SERVER.index("async def start_production_show") :
        SERVER.index('@app.post("/api/production/session/metadata")')
    ]
    assert 'if request.start_obs_stream and not preflight.get("broadcast_ready")' in start
    assert '"reason": "broadcast_destination_unverified"' in start
    assert start.index(
        'if request.start_obs_stream and not preflight.get("broadcast_ready")'
    ) < start.index("safe_state = await production_safe_recovery()")
    assert "start_obs_recording and not preflight" not in start


def test_preflight_is_themable_and_responsive():
    assert ".show-preflight-checks" in CSS
    assert 'article[data-state="fail"]' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .show-preflight' in CSS
    assert "@media(max-width:680px)" in CSS
    assert ".show-start-controls" in CSS
    assert ".show-preflight-signals" in CSS
    assert ".production-session-end-status" in CSS
