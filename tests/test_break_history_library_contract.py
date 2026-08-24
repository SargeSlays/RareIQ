from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_archived_session_has_detail_api_and_frozen_report():
    assert '@app.get("/api/production/session/history/{session_id}")' in SERVER
    assert '@app.get("/production/session/history/{session_id}/report")' in SERVER
    assert "archived_session_not_found" in SERVER
    assert "frozen end-of-session snapshot" in SERVER

def test_history_library_search_filter_sort_and_report_links():
    for element_id in ("breakHistorySearch", "breakHistoryFilter", "breakHistorySort"):
        assert f'id="{element_id}"' in HTML
    assert "function applyBreakHistoryFilters" in JS
    assert 'filter==="profitable"' in JS
    assert 'sort==="margin"' in JS
    assert "Open Frozen Report" in JS

def test_history_library_is_responsive_and_printable():
    assert ".break-history-controls" in CSS
    assert "@media(max-width:760px)" in CSS
    assert "@media print" in SERVER
