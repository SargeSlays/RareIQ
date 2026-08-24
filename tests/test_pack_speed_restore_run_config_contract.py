from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_restore_uses_saved_values_and_existing_control_paths():
    restore = JS.split("async function restorePackTuningRunConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    for call in ("setActiveCameraWorkspaceSource", "selectCamera", "applyWorkspaceLayoutPreset", "setRecognitionMode", "updateRecognitionSetContext", "setStudioXViewerMode"):
        assert call in restore
    assert "parsePackTuningFingerprint(workflow.configurationFingerprint)" in restore


def test_restore_rechecks_every_field_before_resuming():
    restore = JS.split("async function restorePackTuningRunConfiguration", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    assert "packRevalidationConfigurationChanges(workflow)" in restore
    assert "Selected Settings Restored" in restore
    assert "Revalidation stays paused until every setting matches" in restore
    assert "return resumePackTuningRevalidation()" in restore


def test_restore_requires_explicit_action_and_current_assets():
    assert 'id="packTuningRevalidationRestore"' in JS
    assert 'addEventListener("click",requestPackTuningRunConfigurationRestore)' in JS
    assert "#packTuningRevalidationRestore" in CSS
    assert "6.8.8-provisional-identity" in HTML
