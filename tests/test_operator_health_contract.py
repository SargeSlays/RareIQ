from pathlib import Path

from rareiq.web.server import _connected_production_camera_count


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


def test_operator_health_is_themable_and_responsive():
    assert '.operator-health-grid' in CSS
    assert 'article[data-state="bad"]' in CSS
    assert '.operator-safe' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .operator-health' in CSS
