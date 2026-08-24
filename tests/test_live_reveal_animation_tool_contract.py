from pathlib import Path

CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")

def test_reveal_animation_is_a_live_reorderable_tool():
    assert 'data-studiox-widget="reveal-animations"' in CONTROL
    assert 'data-widget-visibility="reveal-animations"' in CONTROL
    assert 'id="liveRevealAnimationsEnabled"' in CONTROL
    assert '"identify","sarge-advisor","pokedex","reveal-animations"' in STUDIO

def test_live_toggle_uses_persisted_reveal_configuration():
    assert "async function setLiveRevealAnimationsEnabled(enabled)" in STUDIO
    assert "animations_enabled:Boolean(enabled)" in STUDIO
    assert "function renderLiveRevealAnimationTool(state={})" in STUDIO
    assert '$("openRevealCreatorSettings")?.addEventListener' in STUDIO

def test_soundboard_quick_pads_live_in_camera_toolbar():
    assert 'id="cameraSoundboardPads"' in CONTROL
    assert 'quickPads.replaceChildren' in STUDIO
    assert '"camera-sound-pad"' in STUDIO

def test_live_reveal_tool_has_individual_effect_toggles():
    for control in ("liveRevealSoundEnabled", "liveRevealParticlesEnabled", "liveRevealFlashEnabled"):
        assert f'id="{control}"' in CONTROL
    assert "async function setLiveRevealEffect(key,enabled)" in STUDIO
    assert '["liveRevealSoundEnabled","audio_enabled"]' in STUDIO
