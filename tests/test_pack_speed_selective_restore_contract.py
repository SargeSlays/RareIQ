from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_restore_uses_only_operator_selected_fields():
    restore = JS.split("async function restorePackTuningRunConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    assert "selectedPackTuningRestorationFields()" in restore
    for field in ("camera", "workspace", "recognition", "setMode", "set", "viewer"):
        assert f'fields.has("{field}")' in restore
    assert "Revalidation stays paused until every setting matches" in restore

def test_preview_has_checked_per_field_controls_and_select_all():
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert 'data-restore-field="${escapeHtml(row.key)}" checked' in render
    assert 'id="packTuningRestoreSelectAll"' in render
    assert 'querySelectorAll("input[data-restore-field]")' in render
    assert "Restore Selected" in render
    assert "#packTuningRestoreSelectAll" in CSS
    assert "6.8.8-provisional-identity" in HTML
