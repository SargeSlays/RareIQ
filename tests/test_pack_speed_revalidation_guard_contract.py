from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_active_revalidation_auto_pauses_on_configuration_change():
    guard = JS.split("function guardPackTuningRevalidationConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    assert "packRevalidationConfigurationChanges(workflow)" in guard
    assert "paused:true" in guard
    assert "autoPaused:true" in guard
    assert 'pauseReason:"configuration-changed"' in guard
    assert "changedFields" in guard


def test_resume_is_blocked_until_original_configuration_is_restored():
    resume = JS.split("function resumePackTuningRevalidation", 1)[1].split("function recordPackTuningRevalidation", 1)[0]
    assert "packRevalidationConfigurationChanges(workflow)" in resume
    assert 'notify("Restore Configuration First"' in resume
    assert "return false" in resume
    assert "autoPaused:false" in resume


def test_guard_is_rendered_and_current():
    assert "workflow=guardPackTuningRevalidationConfiguration()" in JS
    assert 'data-state="auto-paused"' in CSS
    assert "6.8.8-provisional-identity" in HTML
