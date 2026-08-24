from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_obs_apis_and_scene_sync_exist():
    assert 'ObsService' in SERVER
    assert '@app.get("/api/production/obs")' in SERVER
    assert '@app.post("/api/production/obs/settings")' in SERVER
    assert '@app.post("/api/production/obs/command")' in SERVER
    assert 'obs.sync_scene' in SERVER


def test_obs_operator_panel_and_controls_exist():
    for token in ('class="obs-control"', 'id="obsSettingsForm"', 'id="obsConnectionStatus"', 'id="obsSceneSelect"', 'id="obsStreamToggle"', 'id="obsRecordToggle"', 'id="obsSceneMap"'):
        assert token in CONTROL
    assert 'async function loadObsStatus' in JS
    assert 'async function saveObsSettings' in JS
    assert 'async function obsCommand' in JS
    assert '.obs-control' in CSS
    assert 'controlsEnabled=Boolean(obsState.enabled&&connected)' in JS
    assert 'takeScene.disabled=!controlsEnabled||!names.length' in JS
    assert 'streamToggle.disabled=!controlsEnabled' in JS
    assert 'recordToggle.disabled=!controlsEnabled' in JS
    assert '.obs-live-controls :is(button,select):disabled' in CSS


def test_obs_bootstrap_has_dry_run_and_explicit_create():
    assert 'class ObsBootstrapRequest' in SERVER
    assert '@app.post("/api/production/obs/bootstrap")' in SERVER
    assert 'request.dry_run' in SERVER
    for token in ('class="obs-bootstrap"', 'id="obsBootstrapPreview"', 'id="obsBootstrapCreate"', 'id="obsBootstrapPlan"'):
        assert token in CONTROL
    assert 'async function bootstrapObs' in JS
    assert 'confirm("Create the planned RareIQ scenes' in JS
    assert '.obs-bootstrap-plan' in CSS


def test_obs_bootstrap_creation_is_gated_by_live_preflight():
    assert 'id="obsBootstrapStatus"' in CONTROL
    assert 'id="obsBootstrapCreate" type="button" disabled' in CONTROL
    assert 'create.disabled=!ready' in JS
    assert 'result.diagnostic' in JS
    assert '.obs-bootstrap-readiness' in CSS


def test_obs_connection_diagnostics_are_visible():
    assert 'def diagnostic(self)' in (ROOT / "rareiq/services/obs_service.py").read_text(encoding="utf-8")
    assert 'id="obsDiagnostic"' in CONTROL
    assert 'function renderObsDiagnostic' in JS
    assert '.obs-diagnostic' in CSS
