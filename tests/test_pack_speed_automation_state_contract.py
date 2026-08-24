from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_pack_speed_exposes_live_automation_state():
    assert "function renderPackSpeedAutomationState" in JS
    assert 'host?.querySelector("small")' in JS
    for state in ("manual", "armed", "adding", "remove", "ready", "pack-complete"):
        assert state in JS
    assert 'data-automation-state="remove"' in CSS
    assert 'data-automation-state="ready"' in CSS


def test_automatic_success_is_inline_while_manual_success_keeps_toast():
    auto_add = JS.split("async function maybeAutoAddVerified", 1)[1].split("async function runRecognitionDecision", 1)[0]
    decision = JS.split("async function runRecognitionDecision", 1)[1].split("async function operatorApprove", 1)[0]
    assert "silentSuccess:true" in auto_add
    assert "silentSuccess=false" in decision
    assert 'if(!silentSuccess)notify(successTitle,successDetail,"success")' in decision
