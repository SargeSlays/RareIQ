from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_sticky_result_strip_contains_core_operator_decision_data():
    for element_id in ("resultDecisionStrip", "decisionVerdict", "decisionCardName", "decisionCollectorNumber", "decisionConfidence", "decisionApproveButton", "decisionRejectButton", "decisionNextButton"):
        assert f'id="{element_id}"' in HTML

def test_result_strip_reuses_existing_actions_and_live_values():
    assert "function syncResultDecisionStrip" in JS
    assert 'addEventListener("click",operatorApprove)' in JS
    assert 'addEventListener("click",operatorReject)' in JS
    assert '$("nextClearButton")?.click()' in JS
    assert "new MutationObserver(syncResultDecisionStrip)" in JS

def test_result_strip_is_sticky_responsive_and_themed():
    assert ".result-decision-strip" in CSS
    assert "position:sticky" in CSS
    assert "@media(max-width:520px)" in CSS
    assert "html[data-theme=light] .result-decision-strip" in CSS
