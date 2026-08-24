from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_confidence_requires_two_successful_measurements():
    confidence = JS.split("function packBestTuningConfidence", 1)[1].split("function updatePackBestTuning", 1)[0]
    assert 'runs>=4?"proven":runs>=2?"trusted":"provisional"' in confidence
    assert "recommended:fresh&&runs>=2" in confidence
    assert "needed:fresh?Math.max(0,2-runs):2" in confidence


def test_successes_accumulate_only_for_the_same_tuning_action():
    update = JS.split("function updatePackBestTuning", 1)[1].split("function syncPackTuningHistoryResult", 1)[0]
    assert "current?.action===result.action" in update
    assert "successfulRuns:runs" in update
    assert 'result.status!=="improved"' in update


def test_untrusted_profile_cannot_be_applied_or_recommended():
    apply = JS.split("async function applyPackBestTuning", 1)[1].split("function renderPackTuningHistory", 1)[0]
    render = JS.split("function renderPackTuningHistory", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert "!confidence.recommended" in apply
    assert "bestButton.hidden=!best||!confidence.recommended" in render
    assert 'id="packBestTuningConfidence"' in render
    assert "#packBestTuningConfidence" in CSS
    assert "6.8.8-provisional-identity" in HTML
