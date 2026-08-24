from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_session_event_and_report_endpoints_exist():
    assert 'class ProductionEventRequest' in SERVER
    assert '@app.get("/api/production/session")' in SERVER
    assert '@app.post("/api/production/session/start")' in SERVER
    assert '@app.post("/api/production/session/stop")' in SERVER
    assert '@app.post("/api/production/session/events")' in SERVER
    assert '@app.get("/api/production/session/report")' in SERVER
    assert 'rareiq-production-report-v1' in SERVER
    assert 'RAREIQ_RECORDING_COMMAND' in SERVER
    assert 'RecordingService' in SERVER
    assert 'recording.start(' in SERVER
    assert 'recording.stop()' in SERVER
    assert '"recording": recording.status()' in SERVER


def test_session_controls_clock_incidents_and_report_exist():
    for token in (
        'class="production-session"',
        'id="productionSessionClock"',
        'id="productionSessionStart"',
        'id="productionSessionStop"',
        'id="productionSessionReport"',
        'id="productionIncidentForm"',
        'id="productionEventLog"',
        'id="productionRecordingStatus"',
    ):
        assert token in CONTROL
    assert 'async function loadProductionSession' in JS
    assert 'function updateProductionSessionClock' in JS
    assert 'async function setProductionSession' in JS
    assert 'async function markProductionIncident' in JS


def test_session_ui_is_responsive_and_themable():
    assert '.production-session-body' in CSS
    assert '.production-event-log' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .production-session' in CSS


def test_recording_settings_and_test_workflow_exist():
    assert '@app.get("/api/production/recording/settings")' in SERVER
    assert '@app.post("/api/production/recording/settings")' in SERVER
    assert '@app.post("/api/production/recording/test")' in SERVER
    for token in ('id="recordingSettingsForm"', 'id="recordingPreset"', 'id="recordingOutputDir"', 'id="recordingCommand"', 'id="recordingTest"', 'id="recordingDiskEstimate"'):
        assert token in CONTROL
    assert 'async function loadRecordingSettings' in JS
    assert 'async function saveRecordingSettings' in JS
    assert 'async function testRecordingSettings' in JS
    assert '.recording-settings' in CSS


def test_guided_encoder_setup_and_browser_sources_exist():
    assert 'recording.capabilities()' in SERVER
    assert '"browser_sources"' in SERVER
    for token in ('class="encoder-guide"', 'id="recordingFfmpegStatus"', 'id="recordingObsStatus"', 'id="recordingUseTestPreset"', 'id="recordingUseDevicePreset"', 'id="recordingBrowserSources"'):
        assert token in CONTROL
    assert 'function renderEncoderGuide' in JS
    assert 'navigator.clipboard.writeText' in JS
    assert '.browser-source-grid' in CSS


def test_live_production_actions_log_into_active_session():
    assert 'async function logProductionEvent' in JS
    for token in (
        'logProductionEvent("scene"',
        'logProductionEvent("camera"',
        'logProductionEvent("graphic"',
        'logProductionEvent("replay"',
        'logProductionEvent("screen"',
        'logProductionEvent("safety"',
    ):
        assert token in JS
    assert 'if(!productionSessionState.active)return null' in JS
