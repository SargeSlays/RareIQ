from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_pause_and_resume_are_persistent_and_preserve_progress():
    pause = JS.split("function pausePackTuningRevalidation", 1)[1].split("function resumePackTuningRevalidation", 1)[0]
    resume = JS.split("function resumePackTuningRevalidation", 1)[1].split("function recordPackTuningRevalidation", 1)[0]
    assert "paused:true" in pause
    assert "pausedAt:new Date().toISOString()" in pause
    assert "workflow.pauses" in resume
    assert "startedAt:workflow.pausedAt" in resume
    assert "paused:false" in resume


def test_scans_during_pause_are_excluded_from_measurement_and_progress():
    include = JS.split("function packRevalidationIncludesTimestamp", 1)[1].split("function packTuningOutcomeResult", 1)[0]
    record = JS.split("function recordPackTuningRevalidation", 1)[1].split("function packTuningRevalidationInstruction", 1)[0]
    assert "workflow.pauses" in include
    assert "workflow.paused&&time>=Date.parse(workflow.pausedAt)" in include
    assert "workflow.paused||result.status" in record


def test_pause_resume_controls_are_visible_and_current():
    for control in ("packTuningRevalidationPause", "packTuningRevalidationResume"):
        assert f'id="{control}"' in JS
        assert f"#{control}" in CSS
    assert 'addEventListener("click",pausePackTuningRevalidation)' in JS
    assert 'addEventListener("click",resumePackTuningRevalidation)' in JS
    assert "6.8.8-provisional-identity" in HTML
