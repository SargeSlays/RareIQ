from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_completed_sessions_are_archived_without_duplicate_ids():
    assert "PRODUCTION_HISTORY_PATH" in SERVER
    assert "_archive_current_production_session()" in SERVER
    assert 'item.get("session_id") == session_id' in SERVER
    assert "history[-100:]" in SERVER

def test_history_api_reports_honest_aggregate_economics():
    assert '@app.get("/api/production/session/history")' in SERVER
    for token in ('"verified_return"', '"verified_margin"', '"unresolved_cards"', '"strongest_pull"', '"average_seconds_between_cards"'):
        assert token in SERVER

def test_break_history_ui_is_responsive_and_refreshable():
    for element_id in ("breakHistoryRefresh", "historyCompleted", "historyMargin", "historyUnresolved", "breakHistoryList"):
        assert f'id="{element_id}"' in HTML
    assert "function renderBreakHistory" in JS
    assert "async function loadBreakHistory" in JS
    assert ".break-history" in CSS
