from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_preview_compares_only_changed_saved_and_current_fields():
    preview = JS.split("function packTuningRestorationPreview", 1)[1].split("function guardPackTuningRevalidationConfiguration", 1)[0]
    assert "packRevalidationConfigurationChanges(workflow)" in preview
    assert "PACK_TUNING_CONFIGURATION_LABELS[key]" in preview
    assert "saved:" in preview
    assert "current:" in preview


def test_preview_is_safe_and_visible_only_during_auto_pause():
    render = JS.split("function renderPackTuningHistory", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert 'id="packTuningRestorationPreview"' in render
    assert "activeWorkflow?.autoPaused?packTuningRestorationPreview" in render
    assert "escapeHtml(row.current)" in render
    assert "escapeHtml(row.saved)" in render
    assert "restorationPreview.hidden=!previewRows.length" in render


def test_preview_is_responsive_and_current():
    assert "#packTuningRestorationPreview" in CSS
    assert "6.8.8-provisional-identity" in HTML
