from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_each_historical_receipt_expands_to_exact_field_names():
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert 'class="pack-restore-history-item"' in render
    assert "Restored settings" in render
    assert "Remaining mismatches" in render
    assert "PACK_TUNING_CONFIGURATION_LABELS[key]||key" in render
    assert 'second:"2-digit"' in render
    assert "escapeHtml((item.restored||[])" in render
    assert "escapeHtml((item.remaining||[])" in render

def test_history_details_are_collapsed_responsive_and_current():
    assert ".pack-restore-history-item" in CSS
    assert '.pack-restore-history-item[open]' in CSS
    assert "grid-template-columns:1fr" in CSS
    assert "6.8.8-provisional-identity" in HTML
