import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
LEGACY_CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def test_voice_mod_is_a_dedicated_studio_app():
    assert 'data-target="voice-mod"' in CONTROL
    assert 'aria-label="Voice Mod"' in CONTROL
    assert 'data-workspace="voice-mod"' in CONTROL
    assert 'id="voiceModStart"' in CONTROL
    assert 'id="voiceModStop"' in CONTROL
    assert 'id="voiceModRefresh"' in CONTROL
    assert 'id="voiceModState" data-state="idle" role="status" aria-live="polite"' in CONTROL


def test_voice_mod_exposes_input_and_processing_controls():
    for control_id in (
        "voiceModInput",
        "voiceModPreset",
        "voiceModGain",
        "voiceModMix",
        "voiceModOutput",
        "voiceModMonitor",
        "voiceModMeterFill",
    ):
        assert f'id="{control_id}"' in CONTROL
    for preset in ("clean", "deep", "robot", "radio", "megaphone"):
        assert f'value="{preset}"' in CONTROL
    assert 'id="voiceModMonitor" type="checkbox"' in CONTROL
    assert "Use headphones" in CONTROL


def test_voice_mod_builds_a_processed_media_stream():
    assert "navigator.mediaDevices.enumerateDevices" in STUDIO
    assert "navigator.mediaDevices.getUserMedia" in STUDIO
    assert "context.createMediaStreamSource(stream)" in STUDIO
    assert "context.createMediaStreamDestination()" in STUDIO
    assert "window.rareiqVoiceModStream=destination.stream" in STUDIO
    assert "window.rareiqVoiceModStream=null" in STUDIO
    assert "function connectVoiceModPreset" in STUDIO
    assert "function meterVoiceMod" in STUDIO


def test_voice_mod_persists_preferences_and_stops_capture_cleanly():
    assert 'VOICE_MOD_PREFERENCES_KEY="rareiq.voiceMod.preferences.v1"' in STUDIO
    assert "function restoreVoiceModPreferences" in STUDIO
    assert "voiceModState.inputStream?.getTracks().forEach(track=>track.stop())" in STUDIO
    assert "voiceModState.context.close()" in STUDIO
    assert 'navigator.mediaDevices?.addEventListener?.("devicechange",()=>refreshVoiceModInputs()' in STUDIO


def test_voice_mod_has_one_semantic_responsive_style_owner():
    assert "/* Voice Mod */" in CSS
    assert '.workspace[data-workspace="voice-mod"]' in CSS
    assert ".voice-mod-meter" in CSS
    assert "background: var(--sx-surface-raised) !important" in CSS
    assert "border-left: 3px solid var(--sx-accent-strong) !important" in CSS
    assert "accent-color: var(--sx-accent-strong) !important" in CSS
    assert "@media (max-width: 620px)" in CSS
    assert "/* Voice Mod streamer app. */" not in LEGACY_CSS
    assert "rgba(61,48,120,.14)" not in LEGACY_CSS
    version = re.search(r'data-studiox-build="([^"]+)"', CONTROL).group(1)
    assert f"/static/studiox_command_deck.css?v={version}" in CONTROL


def test_voice_mod_console_does_not_inherit_the_legacy_full_height_stretch():
    voice_mod = CSS[CSS.index("/* Voice Mod */") : CSS.index("/* Camera FX */")]
    assert "grid-template-rows: auto auto !important" in voice_mod
    assert "align-content: start !important" in voice_mod
    assert "min-height: 0 !important" in voice_mod


def test_voice_mod_uses_a_compact_desktop_control_grid_with_safe_fallbacks():
    voice_mod = CSS[CSS.index("/* Voice Mod */") : CSS.index("/* Camera FX */")]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr)) !important" in voice_mod
    assert ".voice-mod-control-card > :is(header, .voice-mod-sliders, .voice-mod-monitor, .voice-mod-actions)" in voice_mod
    assert "grid-column: 1 / -1 !important" in voice_mod
    assert ".voice-mod-control-card > label" in voice_mod
    assert "align-content: start !important" in voice_mod
    assert "@media (max-width: 1100px)" in voice_mod
    assert "@media (max-width: 900px)" in voice_mod


def test_voice_mod_reports_truthful_microphone_discovery_state():
    assert 'id="voiceModInputStatus" role="status" aria-live="polite"' in CONTROL
    assert "function setVoiceModInputStatus" in STUDIO
    assert "selectable=devices.filter(device=>device.deviceId)" in STUDIO
    assert '"No microphones detected. Connect an input, then refresh."' in STUDIO
    assert '"permission"' in STUDIO
    assert ".voice-mod-input-status" in CSS


def test_voice_mod_recovers_when_the_active_microphone_disconnects():
    assert "async function handleVoiceModInputEnded(track)" in STUDIO
    assert 'addEventListener("ended",event=>handleVoiceModInputEnded(event.target).catch' in STUDIO
    assert 'setVoiceModStatus("error","Microphone disconnected")' in STUDIO
    assert 'window.rareiqVoiceModStream=null' in STUDIO


def test_voice_mod_startup_failure_releases_acquired_media_resources():
    start = STUDIO[STUDIO.index("async function startVoiceMod") : STUDIO.index("function restoreVoiceModPreferences")]
    assert "let stream=null,context=null" in start
    assert "stream?.getTracks().forEach(track=>track.stop())" in start
    assert 'context.close().catch(()=>{})' in start
    assert 'setVoiceModStatus("error","Microphone unavailable")' in start


def test_voice_mod_pending_permission_can_be_cancelled_without_leaking_audio():
    assert "let voiceModRequestGeneration=0" in STUDIO
    assert "voiceModRequestGeneration+=1" in STUDIO
    assert "const requestGeneration=++voiceModRequestGeneration" in STUDIO
    assert 'stop.disabled=!["live","starting"].includes(state)' in STUDIO
    assert 'stop.textContent=state==="starting"?"Cancel":"Stop"' in STUDIO
    assert "if(requestGeneration!==voiceModRequestGeneration){stream.getTracks().forEach(track=>track.stop());return}" in STUDIO
    assert "if(requestGeneration!==voiceModRequestGeneration){stream?.getTracks().forEach(track=>track.stop())" in STUDIO


def test_voice_mod_route_uses_success_color_only_while_live():
    assert 'class="voice-mod-meter-card" data-state="idle"' in CONTROL
    assert "if(meter)meter.dataset.state=state" in STUDIO
    assert '.voice-mod-meter-card[data-state="live"] .voice-mod-readout span' in CSS
    assert '.voice-mod-meter-card[data-state="error"] .voice-mod-readout span' in CSS
    assert 'id="voiceModRoute" role="status"' in CONTROL
    assert "Production Audio Handoff" in CONTROL
