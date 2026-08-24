from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "rareiq/services/overlay_state_service.py").read_text(encoding="utf-8")
OVERLAY = (ROOT / "rareiq/web/static/overlay_production_screen.html").read_text(encoding="utf-8")


def test_production_screen_api_and_overlay_routes_exist():
    assert 'class ProductionScreenRequest' in SERVER
    assert '@app.get("/api/production/screen")' in SERVER
    assert '@app.post("/api/production/screen/take")' in SERVER
    assert '@app.post("/api/production/screen/hide")' in SERVER
    assert '@app.get("/production-screen")' in SERVER
    assert '@app.get("/overlay/production-screen")' in SERVER


def test_production_screen_state_is_persisted():
    assert '"production_screen"' in SERVICE
    assert '"started_at"' in SERVICE
    assert '"countdown_seconds"' in SERVICE


def test_operator_controls_restore_on_refresh():
    for token in (
        'id="productionScreenForm"',
        'id="productionScreenMode"',
        'id="productionScreenAccent"',
        'id="productionScreenMinutes"',
        'data-production-screen-preset',
    ):
        assert token in CONTROL
    assert 'function renderProductionScreen' in JS
    assert 'async function loadProductionScreen' in JS
    assert 'loadProductionScreen()' in JS


def test_scenes_can_automate_takeover_screens_and_have_hotkeys():
    assert 'screen_action: str = "keep"' in SERVER
    assert 'screen_mode: str = "starting-soon"' in SERVER
    assert 'screen_countdown_seconds' in SERVER
    assert 'screen_action == "show"' in SERVER
    assert 'screen_action == "hide"' in SERVER
    assert 'event.altKey' in JS
    assert 'event.key.toLowerCase()==="b"' in JS
    assert 'event.key.toLowerCase()==="l"' in JS
    assert 'renderProductionScreen(state.screen||{})' in JS


def test_overlay_countdown_uses_server_start_time():
    assert 'started_at' in OVERLAY
    assert 'countdown_seconds' in OVERLAY
    assert '/api/production/screen' in OVERLAY
    assert 'setInterval' in OVERLAY


def test_production_screen_theme_is_present():
    assert '.production-screens' in CSS
    assert '.production-screen-presets' in CSS
    assert '.production-screens iframe' in CSS


def test_all_production_tools_remain_inside_broadcast_workspace():
    broadcast_start = CONTROL.index('data-workspace="broadcast"')
    creator_start = CONTROL.index('data-workspace="creator"')
    broadcast_markup = CONTROL[broadcast_start:creator_start]
    for token in (
        'production-switcher-shell',
        'production-scenes',
        'production-graphics',
        'production-replay',
        'production-screens',
    ):
        assert token in broadcast_markup
        assert token not in CONTROL[:broadcast_start]
        assert token not in CONTROL[creator_start:]
