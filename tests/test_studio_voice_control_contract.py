from pathlib import Path

STATIC = Path("rareiq/web/static")
CONTROL = (STATIC / "control.html").read_text(encoding="utf-8")
APP = (STATIC / "studiox.js").read_text(encoding="utf-8")
VOICE = (STATIC / "studio_voice_control.js").read_text(encoding="utf-8")
WORKLET = (STATIC / "studio_voice_capture.worklet.js").read_text(encoding="utf-8")


def test_speech_borrows_active_raw_voice_mod_and_stops_before_device_cleanup():
    assert "borrow:()=>voiceModState,request:api" in APP
    assert "input.source.connect(worklet)" in VOICE
    assert "sink.gain.value=0" in VOICE
    cleanup = APP[APP.index("async function stopVoiceMod()"):APP.index("async function handleVoiceModInputEnded(")]
    assert cleanup.index("StudioVoiceControl?.stop") < cleanup.index("voiceModState={")
    for forbidden in ("getUserMedia", "new AudioContext", "track.stop", "localStorage", ".play("):
        assert forbidden not in VOICE + WORKLET


def test_practice_and_arming_are_explicit_with_one_cache_busted_worklet():
    assert 'id="studioVoicePractice" type="checkbox" checked' in CONTROL
    assert 'studio_voice_control.js?v=20260908-3' in CONTROL
    assert 'studio_voice_capture.worklet.js?v=20260908-2' in VOICE
    assert "node('studioVoicePractice').checked=true" in VOICE
    assert "host.StudioVoiceControlFactory={create}" in VOICE
    assert "setInterval" not in VOICE
    assert "'/api/production/voice/status?session_id='" in VOICE


def test_audio_is_bounded_timestamped_and_never_persisted_or_logged():
    assert "data.wav.byteLength>192044" in VOICE
    assert "clockOffset+data.endedContextTime" in VOICE
    assert "this.frames.length<600" in WORKLET
    assert "channel.fill(0)" in WORKLET
    for forbidden in ("console.", "localStorage", "indexedDB", "fetch("):
        assert forbidden not in WORKLET


def test_sarge_console_precedes_existing_input_card_without_duplicating_controls():
    grid = CONTROL[CONTROL.index('<div class="voice-mod-grid">'):]
    console = grid[:grid.index('class="voice-mod-control-card')]
    assert 'id="studioVoiceControls"' in console
    assert '<details class="sarge-console-details">' in console
    assert 'Commands may be heard on Program' in console
    assert '<article><span>Switch camera</span>' in console
    for control_id in ('studioVoiceControls', 'studioVoiceStart', 'studioVoiceStop', 'studioVoicePractice', 'studioVoiceMode', 'studioVoiceStatus', 'studioVoiceOutcome'):
        assert CONTROL.count(f'id="{control_id}"') == 1
