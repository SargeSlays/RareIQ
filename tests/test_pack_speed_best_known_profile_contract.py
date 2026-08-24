from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_best_known_profile_learns_only_from_measured_improvements():
    assert 'PACK_BEST_TUNING_KEY="rareiq.packBestTuning.v1"' in JS
    update = JS.split("function updatePackBestTuning", 1)[1].split("function syncPackTuningHistoryResult", 1)[0]
    assert "!result?.complete" in update
    assert 'result.status!=="improved"' in update
    assert "result.reverted" in update
    assert "Number(current.score)>=score" in update


def test_best_known_profile_is_manual_and_remains_reversible():
    apply = JS.split("async function applyPackBestTuning", 1)[1].split("function renderPackTuningHistory", 1)[0]
    assert "beginPackTuningOutcome(recommendation,previous)" in apply
    assert "renderPackSpeedRun()" in apply
    assert 'id="packBestTuningApply"' in JS
    assert 'addEventListener("click"' in JS
    assert "applyPackBestTuning()" in JS


def test_best_known_profile_has_current_assets():
    assert "#packBestTuningApply" in CSS
    assert "6.8.8-provisional-identity" in HTML
