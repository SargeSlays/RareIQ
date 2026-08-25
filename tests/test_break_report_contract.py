from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_human_break_report_preserves_json_export():
    assert '@app.get("/production/session/report")' in SERVER
    assert '@app.get("/api/production/session/report")' in SERVER
    assert 'id="productionSessionPrintReport"' in HTML
    assert 'href="/api/production/session/report"' in HTML
    assert '"analytics": _production_session_analytics_payload(session)' in SERVER


def test_break_report_is_printable_and_honest_about_unknown_values():
    assert "window.print()" in SERVER
    assert "@media print" in SERVER
    assert "Minimum verified return" in SERVER
    assert "Missing prices are excluded, never treated as zero" in SERVER
    assert "All-time inventory sales are intentionally excluded" in SERVER
    assert "Production Reliability" in SERVER
    assert "Incident Lifecycle" in SERVER
    assert "Platform Uptime" in SERVER


def test_break_report_escapes_catalog_and_operator_text():
    assert "html.escape(str(card.get" in SERVER
    assert "html.escape(str(event.get" in SERVER
    assert "Strongest Verified Pulls" in SERVER
    assert "Operator Incidents" in SERVER
