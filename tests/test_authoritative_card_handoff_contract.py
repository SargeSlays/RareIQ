from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8")


def test_server_confirmed_empty_state_completes_handoff_without_second_clear():
    observer = SCRIPT[SCRIPT.index("function observeCompletedCardRemoval"):SCRIPT.index("function completeCardHandoff")]
    assert 'phase==="EMPTY"' in observer
    assert 'resetRecognitionPresentation("physical_removal_confirmed")' in observer
    assert "completeCardHandoff(elapsed)" in observer
    assert observer.index('phase==="EMPTY"') < observer.index("requestNextRecognition()")


def test_handoff_reports_observed_transition_latency():
    assert "cardHandoffStartedAt=Date.now()" in SCRIPT
    assert "Removal confirmed${timing} · ready for next" in SCRIPT
    assert "New card confirmed${timing} · recognition continuing" in SCRIPT


def test_verified_direct_replacement_completes_handoff_without_manual_clear():
    observer = SCRIPT[SCRIPT.index("function observeCompletedCardRemoval"):SCRIPT.index("function operatorDetails")]
    assert "stateId!==cardHandoffStateId" in observer
    assert "replacementStateConfirmed" in observer
    assert "generation>cardHandoffGeneration" in observer
    assert '["CHANGING","ACQUIRING","STABLE","RECOGNIZING"].includes(phase)' in observer
    assert 'resetRecognitionPresentation("verified_direct_replacement")' in observer
    assert 'completeCardHandoff(elapsed,"replacement")' in observer
