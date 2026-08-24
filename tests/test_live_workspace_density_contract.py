from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_live_workspace_has_three_persistent_density_modes():
    assert 'id="workspaceDensityControl"' in HTML
    for mode in ("compact", "balanced", "focus"):
        assert f'data-workspace-density="{mode}"' in HTML
        assert f'data-workspace-density={mode}' in CSS
    assert 'localStorage.getItem("rareiq.workspaceDensity")' in JS
    assert 'localStorage.setItem("rareiq.workspaceDensity"' in JS

def test_compact_mode_rebalances_camera_and_tools():
    assert "--premium-result-width:clamp(540px,30vw,700px)" in CSS
    assert "height:min(72vh,760px)" in CSS
    assert ".intelligence-tools-list" in CSS
    assert "repeat(2,minmax(0,1fr))" in CSS

def test_density_control_is_accessible_and_responsive():
    assert 'role="group" aria-label="Live workspace density"' in HTML
    assert 'setAttribute("aria-pressed"' in JS
    assert "@media(max-width:1100px)" in CSS
