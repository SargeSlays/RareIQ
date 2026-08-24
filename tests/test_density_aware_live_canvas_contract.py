from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_density_modes_define_distinct_camera_canvas_sizes():
    canvas_css = CSS[CSS.index("Density-aware live canvas") :]
    assert 'data-workspace-density="compact"' in canvas_css
    assert 'data-workspace-density="balanced"' in canvas_css
    assert 'data-workspace-density="focus"' in canvas_css
    assert "min(64dvh,680px)" in canvas_css
    assert "min(76dvh,840px)" in canvas_css
    assert "min(var(--sx-live-available-height),980px)" in canvas_css


def test_live_canvas_is_viewport_safe_in_fullscreen_and_large_desktop_views():
    canvas_css = CSS[CSS.index("Density-aware live canvas") :]
    assert "calc(100dvh - 82px)" in canvas_css
    assert "max-height:var(--sx-live-available-height)" in canvas_css
    assert "@media(min-width:1800px) and (min-height:900px)" in canvas_css
    assert "width:min(100%,1800px)" in canvas_css


def test_density_preference_and_accessibility_behavior_remain_intact():
    assert 'localStorage.setItem("rareiq.workspaceDensity"' in JS
    assert 'setAttribute("aria-pressed"' in JS
    canvas_css = CSS[CSS.index("Density-aware live canvas") :]
    assert "@media(prefers-reduced-motion:reduce)" in canvas_css
    assert "@media(max-width:1100px)" in canvas_css
