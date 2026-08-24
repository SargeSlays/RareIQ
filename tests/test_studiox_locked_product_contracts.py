from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8-sig")
SCRIPT = (STATIC / "studiox.js").read_text(encoding="utf-8-sig")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8-sig")


def test_active_control_does_not_load_retired_override_layers() -> None:
    styles = re.findall(r'<link[^>]+href="([^"]+\.css)[^"]*"', HTML)
    assert not any("studiox_60.css" in style for style in styles)
    assert not any("studiox_604.css" in style for style in styles)
    assert "/static/studiox_update15.css" in HTML


def test_every_visible_intelligence_tool_is_registered_for_saved_layout() -> None:
    widget_ids = set(re.findall(r'data-studiox-widget="([^"]+)"', HTML))
    visibility_ids = set(re.findall(r'data-widget-visibility="([^"]+)"', HTML))
    assert visibility_ids <= widget_ids
    for widget_id in widget_ids:
        assert f'{widget_id}:"' in SCRIPT or f'"{widget_id}":"' in SCRIPT


def test_tool_order_is_user_owned_and_persistent() -> None:
    for marker in (
        'data-widget-drag-handle="${id}"',
        'widgetWorkspace.addEventListener("dragstart"',
        'widgetWorkspace.addEventListener("drop"',
        'localStorage.setItem(',
        'applyStudioXWidgetLayout({persist:true})',
    ):
        assert marker in SCRIPT
    assert 'sourceId==="identify"' not in SCRIPT
    assert 'targetId==="identify"' not in SCRIPT
    assert ".studiox-widget.is-drop-before::before" in CSS


def test_reference_artwork_has_a_non_broken_fallback_chain() -> None:
    for marker in (
        "const imageSources =",
        "reference_image_url",
        "localImage",
        'imageElement?.addEventListener("error"',
    ):
        assert marker in SCRIPT


def test_4k_is_an_explicit_supported_layout_tier() -> None:
    assert "@media (min-width:3400px) and (min-height:1800px)" in CSS
    assert "--sx-custom-inspector-width" in CSS
    assert "height:100dvh!important" in CSS
