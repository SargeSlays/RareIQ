from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_ready_sound_is_optional_and_persisted():
    assert 'id="cardHandoffSoundEnabled"' in CONTROL
    assert "soundEnabled:saved.soundEnabled===true" in SCRIPT
    assert "soundEnabled:false" in SCRIPT
    assert '$("cardHandoffSoundEnabled")?.addEventListener("change"' in SCRIPT


def test_ready_cue_is_guarded_and_runs_on_completed_handoff():
    assert "function playCardHandoffReadySound()" in SCRIPT
    assert "window.AudioContext||window.webkitAudioContext" in SCRIPT
    assert "if(!cardRemovalSettings.soundEnabled) return" in SCRIPT
    complete = SCRIPT.split('function completeCardHandoff(elapsedMs=null,method="removal"){', 1)[1].split("\n}", 1)[0]
    assert "playCardHandoffReadySound();" in complete


def test_visual_ready_cue_respects_reduced_motion():
    assert '[data-card-handoff="ready"] .result-decision-strip' in STYLES
    assert "@keyframes card-handoff-ready-pulse" in STYLES
    assert "@media(prefers-reduced-motion:reduce)" in STYLES
