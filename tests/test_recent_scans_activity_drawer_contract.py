from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_recent_scans_render_with_compact_drawer_header_and_close_action():
    assert 'header.className="ui4-history-drawer-head"' in JS
    assert 'eyebrow.textContent="SESSION ACTIVITY"' in JS
    assert 'title.textContent="Recent Scans"' in JS
    assert 'close.addEventListener("click",()=>setUI4InspectorView("current",false,true))' in JS


def test_opening_history_keeps_live_workspace_mounted_under_drawer():
    assert "if(current) current.hidden=false" in JS
    assert 'current?.setAttribute("aria-hidden",String(ui4InspectorView!=="current"))' in JS
    drawer_css = CSS[CSS.index("Recent scans activity drawer") :]
    assert '.inspector[data-primary-view="recent"] .ui4-current-card-view{display:flex!important' in drawer_css
    assert "pointer-events:none" in drawer_css


def test_history_drawer_is_compact_responsive_and_themed():
    drawer_css = CSS[CSS.index("Recent scans activity drawer") :]
    assert "position:absolute" in drawer_css
    assert "grid-template-columns:42px minmax(0,1fr) auto" in drawer_css
    assert "html[data-theme=light]" in drawer_css
    assert "@media(max-width:520px)" in drawer_css
