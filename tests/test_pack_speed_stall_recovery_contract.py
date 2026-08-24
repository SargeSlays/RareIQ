from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def recovery_body() -> str:
    return JS.split("async function observePackSpeedStallRecovery", 1)[1].split("async function maybeAutoAddVerified", 1)[0]


def test_pack_speed_stall_recovery_is_bounded_and_safe():
    body = recovery_body()
    assert "PACK_STALL_RECOVERY_MS=2500" in JS
    assert "autoAddVerifiedEnabled()" in body
    assert 'context?.verified===true' in body
    assert '["STABLE","RECOGNIZING"].includes(phase)' in body
    assert "packRecoveryState.attempted" in body
    assert 'api("/api/camera/capture"' in body
    assert body.count('api("/api/camera/capture"') == 1
    assert "/api/session/auto-confirm-recognition" not in body


def test_pack_speed_stall_recovery_reports_inline_states():
    for state in ("watching", "retrying", "submitted", "attention"):
        assert state in JS
        assert f'data-automation-state="{state}"' in CSS
    assert "Needs operator review" in JS
