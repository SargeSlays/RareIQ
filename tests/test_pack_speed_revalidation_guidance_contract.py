from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_guidance_is_specific_to_safe_handoff_and_set_lock():
    guidance = JS.split("function packTuningRevalidationInstruction", 1)[1].split("function updatePackBestTuning", 1)[0]
    assert 'workflow.targetAction==="safe-handoff"' in guidance
    assert "fully remove each card" in guidance
    assert 'workflow.targetAction==="lock-set"' in guidance
    assert "from this exact set" in guidance
    assert "without changing camera or workspace settings" in guidance


def test_guidance_tracks_cards_remaining_and_current_run():
    guidance = JS.split("function packTuningRevalidationInstruction", 1)[1].split("function updatePackBestTuning", 1)[0]
    assert "Number(workflow.completed||0)+1" in guidance
    assert "3-samples" in guidance
    assert "measurement.samples" in guidance


def test_guidance_is_visible_and_current():
    assert 'id="packTuningRevalidationInstruction"' in JS
    assert "packTuningRevalidationInstruction(activeWorkflow)" in JS
    assert "#packTuningRevalidationInstruction" in CSS
    assert "6.8.8-provisional-identity" in HTML
