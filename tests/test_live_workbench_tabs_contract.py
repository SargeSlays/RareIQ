from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_workbench_has_clear_remembered_categories():
    assert 'id="studioxWorkbenchTabs"' in HTML
    for tab in ("card", "recognition", "stream", "business", "all"):
        assert f'data-workbench-tab="{tab}"' in HTML
    assert "STUDIOX_WORKBENCH_CATEGORIES" in JS
    assert "STUDIOX_WORKBENCH_TAB_KEY" in JS
    assert "localStorage.setItem(STUDIOX_WORKBENCH_TAB_KEY" in JS

def test_tabs_filter_without_removing_or_rebuilding_widgets():
    assert "function setStudioXWorkbenchTab" in JS
    assert 'classList.toggle("workbench-category-hidden"' in JS
    assert ".studiox-widget.workbench-category-hidden" in CSS
    assert "document.createElement(\"section\")" not in JS[JS.index("function setStudioXWorkbenchTab"):JS.index("const STUDIOX_DEFAULT_WIDGET_LAYOUT")]

def test_workbench_tabs_are_accessible_responsive_and_themed():
    assert 'aria-label="Intelligence tool categories"' in HTML
    assert 'setAttribute("aria-selected"' in JS
    assert ".studiox-workbench-tabs" in CSS
    assert "@media(max-width:520px)" in CSS
