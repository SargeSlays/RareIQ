from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_receipt_history_is_persistent_and_bounded():
    update = JS.split("function packTuningRestoreReceiptUpdate", 1)[1].split("function requestPackTuningRunConfigurationRestore", 1)[0]
    assert "workflow?.restoreReceipts||[]" in update
    assert ".slice(-10)" in update
    restore = JS.split("async function restorePackTuningRunConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    assert "packTuningRestoreReceiptUpdate(workflow,receipt)" in restore
    assert "...receiptUpdate" in restore

def test_previous_receipts_are_inspectable_without_overwhelming_the_panel():
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert ".slice(0,-1).reverse().slice(0,9)" in render
    assert "Previous restoration attempts" in render
    assert 'item.resumed?"Resumed":"Stayed paused"' in render
    assert "item.restored?.length" in render
    assert "item.remaining?.length" in render
    assert "#packTuningRestoreReceipt>details" in CSS
    assert "6.8.8-provisional-identity" in HTML
