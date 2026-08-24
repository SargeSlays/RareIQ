from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_direct_swap_requires_a_distinct_authoritative_card_state():
    observer = JS.split("function observeCompletedCardRemoval", 1)[1].split("function completeCardHandoff", 1)[0]
    assert 'let cardHandoffStateId=""' in JS
    assert 'cardHandoffStateId=String(window.__rareiqCardContext?.snapshot?.state_id||"")' in JS
    assert 'const stateId=String(snapshot?.state_id||"")' in observer
    assert "Boolean(stateId)&&stateId!==cardHandoffStateId" in observer
    assert "generation>cardHandoffGeneration" in observer


def test_confirmed_direct_swap_rearms_without_clearing_the_new_card():
    observer = JS.split("function observeCompletedCardRemoval", 1)[1].split("function completeCardHandoff", 1)[0]
    direct = observer.split("if(directReplacement)", 1)[1].split("if(!present&&phase", 1)[0]
    assert 'resetRecognitionPresentation("verified_direct_replacement")' in direct
    assert 'completeCardHandoff(elapsed,"replacement")' in direct
    assert "requestNextRecognition()" not in direct
    assert "cardHandoffStateId=stateId" in direct
