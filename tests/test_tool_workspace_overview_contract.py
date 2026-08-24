from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_tool_titles_toggle_only_their_own_persisted_panel():
    assert "function setStudioXWidgetOverviewFocus(id)" in JS
    assert 'updateStudioXWidgetLayout(id,"collapse")' in JS
    assert 'titleToggle.setAttribute("aria-expanded",String(expanded))' in JS
    assert 'workspace.dataset.activeOverviewWidget=id' not in JS


def test_tool_title_click_preserves_multi_panel_saved_layout():
    assert "setStudioXWidgetOverviewFocus(focusButton.dataset.widgetFocus)" in JS
    assert "saveStudioXWidgetLayout()" in JS
    assert "studioXWidgetLayout.collapsed" in JS
    assert 'widget.classList.remove("is-overview-active","is-overview-card","is-focused")' in JS


def test_workspace_supports_bulk_expand_and_collapse():
    assert "function setAllStudioXWidgetsCollapsed(collapsed)" in JS
    assert "data-widget-expand-all" in (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
    assert "data-widget-collapse-all" in (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
    assert 'content:"−"' in CSS
    assert 'content:"+"' in CSS
