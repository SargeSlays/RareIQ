from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_soundboard_api_and_reorderable_tool_exist():
    assert '@app.get("/api/soundboard")' in SERVER
    assert '@app.post("/api/soundboard")' in SERVER
    assert 'data-studiox-widget="soundboard"' in CONTROL
    assert 'data-widget-visibility="soundboard"' in CONTROL
    assert 'id="soundboardUpload"' in CONTROL

def test_soundboard_plays_and_stops_host_selected_audio():
    assert "function playSoundboardPad(pad)" in STUDIO
    assert "player.play().then(startSoundboardPlaybackSync).catch" in STUDIO
    assert '$("soundboardStop")?.addEventListener' in STUDIO
    assert 'accept="audio/mpeg,audio/wav,audio/ogg"' in CONTROL

def test_soundboard_supports_overlap_stop_all_and_persistent_volume():
    assert 'id="soundboardVolume"' in CONTROL
    assert "const activeSoundboardPlayers=new Set()" in STUDIO
    assert "const player=new Audio(pad.asset.url)" in STUDIO
    assert "function stopAllSoundboardAudio()" in STUDIO
    assert 'localStorage.setItem("rareiq.soundboard.volume"' in STUDIO

def test_soundboard_upload_automatically_creates_and_saves_a_pad():
    assert "async function uploadSoundboardAudio(file)" in STUDIO
    assert "asset_id:asset.id" in STUDIO
    assert 'notify("Sound Pad Added"' in STUDIO
    assert 'uploadSoundboardFiles(event.target.files)' in STUDIO

def test_compact_and_full_soundboards_share_fifty_pad_and_multi_upload_behavior():
    assert "soundboardState.pads.length>=12" not in STUDIO
    assert STUDIO.count("soundboardState.pads.length>=50") >= 2
    assert STUDIO.count("uploadSoundboardFiles(event.target.files)") >= 2
    assert 'const audioAssets=soundboardState.assets.filter(asset=>asset.kind==="audio")' in STUDIO
    assert "#soundboardAppRenamePreset,body.studiox-ui4 #soundboardAppAddPad{display:none}" not in CSS

def test_soundboard_is_a_themed_left_rail_app_with_fifty_pads():
    assert 'data-target="soundboard"' in CONTROL
    assert 'data-workspace="soundboard"' in CONTROL
    assert 'id="soundboardAppGrid"' in CONTROL
    assert 'id="soundboardSearch"' in CONTROL
    assert 'multiple accept="audio/mpeg,audio/wav,audio/ogg"' in CONTROL
    assert "soundboardState.pads.length>=50" in STUDIO
    assert "function renderSoundboardApp()" in STUDIO

def test_right_soundboard_tool_is_themed_square_and_five_columns():
    assert 'id="soundboardToolPadCount"' in CONTROL
    assert 'multiple accept="audio/mpeg,audio/wav,audio/ogg"' in CONTROL
    assert ".studiox-soundboard-pads{display:grid;grid-template-columns:repeat(5" in CSS
    assert ".studiox-sound-pad{aspect-ratio:1/1" in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .studiox-soundboard' in CSS

def test_sound_pads_support_uploaded_button_images():
    assert "function addSoundboardImageControls()" in STUDIO
    assert "async function uploadSoundboardPadImage(index,file)" in STUDIO
    assert "image_asset_id" in STUDIO
    assert ".has-pad-image" in CSS

def test_soundboard_app_uses_compact_performance_deck_layout():
    assert 'class="soundboard-app-deck"' in CONTROL
    assert "Performance deck" in CONTROL
    assert ".soundboard-app-shell{display:flex!important;flex-direction:column" in CSS
    assert ".soundboard-app-deck{display:grid" in CSS

def test_soundboard_drag_lock_and_ten_preset_contract():
    assert 'id="soundboardAppPreset"' in CONTROL
    assert 'id="soundboardToolPreset"' in CONTROL
    assert 'id="soundboardAppLock"' in CONTROL
    assert 'id="soundboardToolLock"' in CONTROL
    assert "while(soundboardLayouts.presets.length<10)" in STUDIO
    assert "function enableSoundboardDrag" in STUDIO
    assert "button.draggable=true" in STUDIO
    assert "SOUNDBOARD_LAYOUT_KEY" in STUDIO
    assert ".is-drag-over" in CSS
    assert '[aria-pressed="true"]' in CSS

def test_soundboard_now_playing_time_progress_and_active_pad_contract():
    assert 'id="soundboardToolNowPlaying"' in CONTROL
    assert 'id="soundboardAppNowPlaying"' in CONTROL
    assert 'id="soundboardToolNowPlayingTime"' in CONTROL
    assert 'id="soundboardAppNowPlayingProgress"' in CONTROL
    assert "function syncSoundboardPlayback()" in STUDIO
    assert "formatSoundboardTime" in STUDIO
    assert 'button.classList.toggle("is-playing"' in STUDIO
    assert "requestAnimationFrame(syncSoundboardPlayback)" in STUDIO
    assert ".soundboard-now-playing-track" in CSS
    assert ".is-playing" in CSS

def test_soundboard_supports_sequential_queue_and_simultaneous_layer_modes():
    assert 'id="soundboardToolPlaybackMode"' in CONTROL
    assert 'id="soundboardAppPlaybackMode"' in CONTROL
    assert '<option value="queue">' in CONTROL
    assert '<option value="layer">' in CONTROL
    assert 'id="soundboardToolQueueCount"' in CONTROL
    assert "const soundboardQueue=[]" in STUDIO
    assert 'localStorage.setItem("rareiq.soundboard.playbackMode"' in STUDIO
    assert 'soundboardQueue.push(pad)' in STUDIO
    assert 'startSoundboardPad(soundboardQueue.shift(),true)' in STUDIO
    assert "soundboardQueue.splice(0)" in STUDIO
    assert ".studiox-soundboard-playback-controls" in CSS

def test_soundboard_has_dedicated_editable_queue_panels():
    assert 'id="soundboardToolQueue"' in CONTROL
    assert 'id="soundboardAppQueue"' in CONTROL
    assert 'id="soundboardToolClearQueue"' in CONTROL
    assert 'id="soundboardAppClearQueue"' in CONTROL
    assert "function renderSoundboardQueueList" in STUDIO
    assert "function removeSoundboardQueueItem" in STUDIO
    assert "function moveSoundboardQueueItem" in STUDIO
    assert "function clearSoundboardQueue" in STUDIO
    assert ".soundboard-queue-panel" in CSS
