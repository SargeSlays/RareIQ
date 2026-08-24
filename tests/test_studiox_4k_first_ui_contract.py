from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_native_4k_design_tier_is_explicit():
    assert "@media (min-width:3400px) and (min-height:1800px)" in CSS
    assert "--sx-ui-scale:1.3" in CSS
    assert "--sx-custom-inspector-width:clamp(920px,29vw,1120px)" in CSS


def test_workspace_consumes_viewport_without_uncapped_stage():
    assert "height:calc(100dvh - var(--sx-command-height))!important" in CSS
    assert "grid-template-rows:var(--sx-toolbar-height) var(--sx-camera-header-height) minmax(0,1fr)!important" in CSS
    assert "object-fit:contain!important" in CSS


def test_4k_assets_are_cache_busted_together():
    css_marker = next(value for value in HTML.splitlines() if "studiox_update15.css?v=" in value)
    script_marker = next(value for value in HTML.splitlines() if "studiox.js?v=" in value)
    assert css_marker.split("?v=", 1)[1].split('"', 1)[0] == script_marker.split("?v=", 1)[1].split('"', 1)[0]


def test_light_mode_is_preserved_by_final_layer():
    assert 'html[data-theme="light"] body.studiox-ui4.studiox-premium .ui4-desktop-shell' in CSS
