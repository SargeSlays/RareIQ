from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")


def test_mobile_broadcast_tabs_scroll_without_page_overflow() -> None:
    assert "overscroll-behavior-x:contain!important" in CSS
    assert "scroll-snap-type:x proximity!important" in CSS
    assert "scroll-snap-align:center!important" in CSS
    assert "scrollbar-width:none!important" in CSS


def test_selected_mobile_broadcast_tab_scrolls_into_view() -> None:
    section = JS[JS.index("function setBroadcastWorkspaceView") : JS.index("function initializeBroadcastWorkspace")]
    assert "let selectedTab=null" in section
    assert 'window.matchMedia("(max-width: 820px)").matches' in section
    assert 'selectedTab.scrollIntoView({' in section
    assert 'block:"nearest",inline:"center"' in section


def test_broadcast_tab_scrolling_does_not_add_data_or_polling_behavior() -> None:
    section = JS[JS.index("function setBroadcastWorkspaceView") : JS.index("function initializeBroadcastWorkspace")]
    assert "fetch(" not in section
    assert "api(" not in section
    assert "setInterval" not in section
