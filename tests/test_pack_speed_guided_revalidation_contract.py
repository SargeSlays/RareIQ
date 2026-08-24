from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_revalidation_workflow_is_scoped_and_requires_two_results():
    assert 'PACK_TUNING_REVALIDATION_KEY="rareiq.packTuningRevalidation.v1"' in JS
    start = JS.split("function startPackTuningRevalidation", 1)[1].split("function cancelPackTuningRevalidation", 1)[0]
    record = JS.split("function recordPackTuningRevalidation", 1)[1].split("function updatePackBestTuning", 1)[0]
    assert "scope=packTuningScope()" in start
    assert "required:2" in start
    assert "result.scope!==workflow.scope" in record
    assert "result.action!==workflow.targetAction" in record
    assert "workflow.configurationFingerprint!==packTuningConfigurationFingerprint()" in record


def test_revalidation_can_be_cancelled_without_deleting_profile():
    cancel = JS.split("function cancelPackTuningRevalidation", 1)[1].split("function recordPackTuningRevalidation", 1)[0]
    assert "cancelledAt" in cancel
    assert "savePackBestTuning" not in cancel
    assert "removeItem(PACK_BEST_TUNING_KEY" not in cancel


def test_guided_progress_is_visible_and_build_is_current():
    for control in ("packTuningRevalidation", "packTuningRevalidationProgress", "packTuningRevalidationStart", "packTuningRevalidationCancel"):
        assert f'id="{control}"' in JS
    assert "#packTuningRevalidation" in CSS
    assert "6.8.8-provisional-identity" in HTML
