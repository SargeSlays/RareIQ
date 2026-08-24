from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_recovery_records_card_context_for_operator_review():
    record = JS.split("function recordPackRecoveryMetric", 1)[1].split("function packRecoveryMetricSummary", 1)[0]
    for field in ("card_name", "collector_number", "set_name", "reference_image_url"):
        assert field in record
    assert "context?.card" in record


def test_pack_session_has_collapsible_recovery_history():
    render = JS.split("function renderPackRecoveryHistory", 1)[1].split("function loadPackSpeedRun", 1)[0]
    assert 'history=document.createElement("details")' in render
    assert 'id="packRecoveryHistorySummary"' in render
    assert 'id="packRecoveryHistoryRows"' in render
    assert "rows.map((row,index)=>({...row,_index:index})).slice(-10).reverse()" in render
    assert "Recovered" in render
    assert "Needs review" in render


def test_recovery_history_is_responsive_and_theme_aware():
    assert ".pack-recovery-history" in CSS
    assert 'article[data-outcome="failed"]' in CSS
    assert "html[data-theme=light] .pack-recovery-history" in CSS
    assert "@media(max-width:560px)" in CSS
