from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def landscape_css() -> str:
    marker = "/* Update 6.8.9 — short landscape operator mode."
    return CSS[CSS.index(marker) :]


def test_short_landscape_mode_is_strictly_bounded_to_mobile_height():
    section = landscape_css()
    assert "@media(max-width:959px) and (orientation:landscape) and (max-height:600px)" in section
    assert "height:calc(100dvh - 116px - env(safe-area-inset-bottom,0px))!important" in section
    assert "overflow:hidden!important" in section


def test_landscape_mode_keeps_camera_and_inspector_side_by_side():
    section = landscape_css()
    assert "grid-template-columns:minmax(0,56fr) minmax(300px,44fr)!important" in section
    assert ".ui4-center-column" in section and "grid-column:1!important" in section
    assert ".ui4-inspector-column" in section and "grid-column:2!important" in section
    assert ".ui4-inspector-column>.inspector" in section
    assert "overflow:auto!important" in section


def test_landscape_camera_preserves_containment_and_existing_feed():
    section = landscape_css()
    assert "#cameraFeed" in section
    assert "object-fit:contain!important" in section
    assert HTML.count('id="cameraFeed"') == 1
    assert "scan-zone" not in section
    assert "card-polygon" not in section


def test_landscape_replaces_tall_command_chrome_with_touch_deck():
    section = landscape_css()
    assert ".ui4-command-bar{display:none!important}" in section
    assert ".camera-workspace-layout-control.camera-workspace-toolbar{display:none!important}" in section
    assert ".camera-workspace>.pipeline-rail{display:none!important}" in section
    assert ".ui4-mobile-action-region" in section
    assert "min-height:44px!important" in section
    assert "bottom:calc(54px + env(safe-area-inset-bottom,0px))!important" in section
