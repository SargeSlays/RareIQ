import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_voice_mod_is_a_dedicated_studio_app():
    assert 'data-target="voice-mod"' in CONTROL
    assert 'aria-label="Voice Mod"' in CONTROL
    assert 'data-workspace="voice-mod"' in CONTROL
    assert 'id="voiceModStart"' in CONTROL
    assert 'id="voiceModStop"' in CONTROL
    assert 'id="voiceModRefresh"' in CONTROL


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


def test_voice_mod_has_complete_dark_light_and_responsive_styling():
    assert "/* Voice Mod streamer app. */" in CSS
    assert ".voice-mod-workspace" in CSS
    assert ".voice-mod-meter" in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .voice-mod-shell' in CSS
    assert "@media(max-width:620px)" in CSS
    version = re.search(r'data-studiox-build="([^"]+)"', CONTROL).group(1)
    assert f"/static/studiox_update15.css?v={version}" in CONTROL


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


def test_voice_mod_route_uses_success_color_only_while_live():
    assert 'class="voice-mod-meter-card" data-state="idle"' in CONTROL
    assert "if(meter)meter.dataset.state=state" in STUDIO
    assert '.voice-mod-meter-card[data-state="live"] .voice-mod-readout span' in CSS
    assert '.voice-mod-meter-card[data-state="error"] .voice-mod-readout span' in CSS
