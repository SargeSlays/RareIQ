from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_tuning_captures_a_baseline_and_next_three_cards():
    assert 'PACK_TUNING_OUTCOME_KEY="rareiq.packTuningOutcome.v1"' in JS
    begin = JS.split("function beginPackTuningOutcome", 1)[1].split("function packTuningOutcomeResult", 1)[0]
    result = JS.split("function packTuningOutcomeResult", 1)[1].split("function renderPackTuningOutcome", 1)[0]
    assert ".slice(-3)" in begin
    assert "baselineAverage" in begin
    assert ".slice(0,3)" in result
    assert "values.length>=3" in result
    assert 'difference>0?"faster":"slower"' in result


def test_tuning_measurement_starts_only_after_successful_manual_apply():
    apply = JS.split("async function applyPackSessionHealthRecommendation", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert "beginPackTuningOutcome(recommendation,previous)" in apply
    assert "if(applied)beginPackTuningOutcome(recommendation,previous)" in apply
    assert 'addEventListener("click",applyPackSessionHealthRecommendation)' in JS


def test_tuning_outcome_is_compact_responsive_and_cache_busted():
    assert 'id="packSessionHealthOutcome"' in JS
    assert "#packSessionHealthOutcome" in CSS
    assert 'data-status="improved"' in CSS
    assert "6.8.8-provisional-identity" in HTML
