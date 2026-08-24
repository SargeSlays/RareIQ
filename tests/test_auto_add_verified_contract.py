from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_auto_add_is_operator_controlled_and_manual_actions_remain() -> None:
    assert 'id="autoAddVerifiedEnabled"' in HTML
    assert "Pack Speed" in HTML
    assert "Auto-add + clear" in HTML
    assert 'id="approveButton"' in HTML
    assert 'id="rejectButton"' in HTML
    assert 'id="nextClearButton"' in HTML
    assert 'const AUTO_ADD_VERIFIED_KEY="rareiq.autoAddVerified.v1"' in JS


def test_auto_add_is_bound_to_one_exact_recognition_state() -> None:
    auto_add = JS.split("async function maybeAutoAddVerified", 1)[1].split(
        "async function runRecognitionDecision", 1
    )[0]
    assert "context?.verified!==true" in auto_add
    assert "stateId===lastAutoAddStateId" in auto_add
    assert "lastAutoAddStateId=stateId" in auto_add
    assert "/api/session/auto-confirm-recognition?state_id=" in auto_add
    assert 'quietReasons:["stale_recognition_state"]' in auto_add
    assert 'beginCardHandoff("approved")' in auto_add


def test_enabling_auto_add_arms_the_next_card_not_the_current_card() -> None:
    assert 'lastAutoAddStateId=String(window.__rareiqCardContext?.snapshot?.state_id||"")||null' in JS
    assert 'cardRemovalSettings.sensitivity="adaptive"' in JS
    assert "adaptive removal timing enabled." in JS
