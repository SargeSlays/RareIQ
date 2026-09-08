from pathlib import Path
import re

STATIC = Path("rareiq/web/static")
CONTROL = (STATIC / "control.html").read_text(encoding="utf-8")
STUDIO = (STATIC / "studiox.js").read_text(encoding="utf-8")
ADAPTER = (STATIC / "studio_motion.js").read_text(encoding="utf-8")


def test_runtime_is_operator_only_and_preserves_appearance_owner():
    assert CONTROL.index("/static/producer-please.motion.css") > CONTROL.index("/static/studio_shell.css")
    assert CONTROL.index("/static/producer-please.motion.js") < CONTROL.index("/static/studio_motion.js") < CONTROL.index("/static/studiox.js")
    assert "studio_appearance.js" in CONTROL
    for path in STATIC.glob("*.html"):
        if path.name != "control.html":
            assert "producer-please.motion" not in path.read_text(encoding="utf-8")
    for tag in re.findall(r"<(?:img|video|canvas|iframe)\b[^>]*>", CONTROL, flags=re.S):
        assert "data-pp-motion-exclude" in tag


def test_motion_never_owns_commands_capture_or_fake_signal():
    for forbidden in ("fetch(", "setInterval(", "getUserMedia", "AudioContext", "requestAnimationFrame", "updateLevel("):
        assert forbidden not in ADAPTER
    assert "obsState.streaming===true" in STUDIO
    assert "window.StudioMotion?.recognition(key)" in STUDIO
    assert "window.StudioMotion?.notification(node)" in STUDIO
    assert '"SARGE CONNECTED"' not in STUDIO
    assert '"ADVISOR CONFIGURED"' in STUDIO
    for prefix in ("sargeAdvisor", "liveSargeAdvisor"):
        assert f'StudioMotion?.advisor("{prefix}Status","busy")' in STUDIO
        assert f'StudioMotion?.advisor("{prefix}Status","error")' in STUDIO
        assert f'StudioMotion?.advisor("{prefix}Status",payload.answer?' in STUDIO


def test_motion_preferences_have_native_keyboard_semantics():
    for mode in ("expressive", "studio", "reduced", "off"):
        assert f'data-studio-motion="{mode}"' in CONTROL
    assert 'role="radiogroup" aria-label="Motion intensity"' in CONTROL
    assert 'id="studioMotionStatus" role="status"' in CONTROL
    assert "ArrowRight" in ADAPTER and "ArrowLeft" in ADAPTER
    assert "preference is not saved" in ADAPTER
