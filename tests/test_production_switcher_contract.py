from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
PROGRAM = Path("rareiq/web/static/program_view.html").read_text(encoding="utf-8")


def test_production_switcher_api_tracks_preview_program_and_transitions():
    assert '@app.get("/api/production/switcher")' in SERVER
    assert '@app.post("/api/production/switcher/preview")' in SERVER
    assert '@app.post("/api/production/switcher/take")' in SERVER
    assert '"program_slot": 1' in SERVER
    assert '"preview_slot": 2' in SERVER
    assert 'transition in {"cut", "fade", "slide", "zoom"}' in SERVER
    assert '"generation"' in SERVER


def test_broadcast_workspace_has_preview_program_buses_and_four_inputs():
    assert 'class="production-switcher-shell"' in CONTROL
    assert 'id="productionProgramPreview"' in CONTROL
    assert 'id="productionPreviewPreview"' in CONTROL
    assert 'id="productionCut"' in CONTROL
    assert 'id="productionAuto"' in CONTROL
    assert CONTROL.count('data-production-slot=') == 4
    assert 'id="productionTransition"' in CONTROL
    assert 'id="productionDuration"' in CONTROL


def test_switcher_ui_and_program_output_follow_shared_state():
    assert 'function loadProductionSwitcher()' in STUDIO
    assert 'function setProductionPreview' in STUDIO
    assert 'function takeProductionShot' in STUDIO
    assert 'function handleProductionShortcut' in STUDIO
    assert '.production-monitors' in CSS
    assert '.program-monitor' in CSS
    assert '.preview-monitor' in CSS
    assert '/api/production/switcher' in PROGRAM
    assert '/api/camera-slots/${state.program_slot}/stream' in PROGRAM


def test_production_scenes_persist_and_recall_camera_audio_actions():
    assert '@app.get("/api/production/scenes")' in SERVER
    assert '@app.post("/api/production/scenes")' in SERVER
    assert '@app.delete("/api/production/scenes/{scene_id}")' in SERVER
    assert '@app.post("/api/production/scenes/{scene_id}/take")' in SERVER
    assert 'DEFAULT_PRODUCTION_SCENES' in SERVER
    assert 'production_scenes.json' in SERVER
    assert 'id="productionSceneGrid"' in CONTROL
    assert 'id="productionSceneEditor"' in CONTROL
    assert 'function loadProductionScenes()' in STUDIO
    assert 'function takeProductionScene' in STUDIO
    assert 'function deleteProductionScene' in STUDIO
    assert 'spotifyCommand(scene.spotify_action)' in STUDIO
    assert 'stopAllSoundboardAudio()' in STUDIO
    assert '.production-scene-grid' in CSS
