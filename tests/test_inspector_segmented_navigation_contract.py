from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_inspector_tabs_expose_live_state_and_recent_scan_count():
    assert 'id="currentCardLiveState"' in HTML
    assert 'id="recentScanCount"' in HTML
    assert 'data-inspector-view="current"' in HTML
    assert 'data-inspector-view="recent"' in HTML


def test_recent_count_and_live_state_are_synchronized_from_real_data():
    assert '$("recentScanCount").textContent=String(ui4RecentScans.length)' in JS
    assert "function syncInspectorNavigationState()" in JS
    assert 'live.dataset.live=active?"true":"false"' in JS
    assert "syncInspectorNavigationState();" in JS


def test_segmented_navigation_is_compact_responsive_and_themed():
    nav_css = CSS[CSS.index("Compact inspector navigation") :]
    assert "min-height:34px" in nav_css
    assert '#currentCardLiveState[data-live="true"]' in nav_css
    assert "html[data-theme=light]" in nav_css
    assert "@media(max-width:390px)" in nav_css
