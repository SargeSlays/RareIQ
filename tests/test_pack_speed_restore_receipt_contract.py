from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_restore_persists_an_auditable_result():
    restore = JS.split("async function restorePackTuningRunConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    assert "packTuningRestoreReceiptUpdate(workflow,receipt)" in restore
    assert "...receiptUpdate" in restore
    assert "completedAt:new Date().toISOString()" in restore
    assert "requested:[...fields]" in restore
    assert "restored:[...fields].filter" in restore
    assert "remaining,resumed:!remaining.length" in restore

def test_receipt_reports_restored_remaining_and_resume_state():
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert 'id="packTuningRestoreReceipt"' in render
    assert 'receipt.resumed?"resumed":"paused"' in render
    assert "Configuration verified · revalidation resumed" in render
    assert "Partial restore · revalidation paused" in render
    assert "restored.join" in render and "remaining.join" in render
    assert "#packTuningRestoreReceipt" in CSS
    assert "6.8.8-provisional-identity" in HTML
