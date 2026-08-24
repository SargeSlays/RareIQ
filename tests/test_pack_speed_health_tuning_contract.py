from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_health_tuning_is_bounded_and_operator_initiated():
    recommendation = JS.split("function packSessionHealthRecommendation", 1)[1].split("async function applyPackSessionHealthRecommendation", 1)[0]
    apply = JS.split("async function applyPackSessionHealthRecommendation", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert 'health.state==="healthy"' in recommendation
    assert 'health.recoveryFailures>=2' in recommendation
    assert 'action:"safe-handoff"' in recommendation
    assert 'latency.action==="lock-set"' in recommendation
    assert 'cardRemovalSettings.sensitivity="safe"' in apply
    assert "applyPackRunRecommendation()" in apply
    assert "/api/camera" not in apply


def test_health_tuning_requires_a_visible_button_click():
    render = JS.split("function renderPackSessionHealth", 1)[1].split("function loadPackSpeedRun", 1)[0]
    assert 'id="packSessionHealthApply"' in render
    assert 'addEventListener("click",applyPackSessionHealthRecommendation)' in render
    assert "button.hidden=!currentPackSessionHealthRecommendation.action" in render


def test_health_tuning_is_responsive_and_cache_busted():
    assert "#packSessionHealthApply" in CSS
    assert ":has(#packSessionHealthApply:not([hidden]))" in CSS
    assert "6.8.8-provisional-identity" in HTML
