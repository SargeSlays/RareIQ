from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")


def test_mobile_camera_and_card_visibility_rules_are_live_only() -> None:
    for view, target in (("camera", ".ui4-inspector-column"), ("card", ".ui4-center-column")):
        selector = f'[data-ui4-workspace="live"][data-mobile-operator-view="{view}"] {target}'
        assert selector in CSS


def test_mobile_non_live_workspace_owns_the_center_column() -> None:
    selector = '[data-ui4-workspace]:not([data-ui4-workspace="live"])'
    assert f"{selector} .ui4-center-column{{display:grid!important;grid-template-rows:minmax(0,1fr)!important;width:100%!important}}" in CSS
    assert f"{selector} .ui4-command-bar{{display:none!important}}" in CSS
    assert f"{selector} .ui4-inspector-column{{display:none!important}}" in CSS


def test_non_live_notifications_reserve_only_the_mobile_navigation_height() -> None:
    selector = '[data-ui4-workspace]:not([data-ui4-workspace="live"]) .notification-stack'
    assert selector in CSS
    assert "bottom:calc(78px + env(safe-area-inset-bottom,0px))!important" in CSS


def test_broadcast_navigation_keeps_existing_workspace_switch_handler() -> None:
    assert HTML.count('class="workspace" data-workspace="broadcast"') == 1
    assert HTML.count('data-target="broadcast"') == 1
    assert 'switchWorkspace(button.dataset.target)' in JS


def test_active_mobile_workspace_navigation_scrolls_into_view() -> None:
    section = JS[JS.index("function switchWorkspace") : JS.index("function voiceModPreferences")]
    assert 'window.matchMedia("(max-width: 959px)").matches' in section
    assert "activeNavigationItem.scrollIntoView" in section
    assert 'block:"nearest"' in section
    assert 'inline:"center"' in section
    assert 'prefers-reduced-motion: reduce' in section
