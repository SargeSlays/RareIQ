from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def adaptive_body() -> str:
    return JS.split("function packRecoveryThresholdMs", 1)[1].split("function renderPackRecoveryMetrics", 1)[0]


def test_recovery_threshold_starts_conservative_and_remains_bounded():
    body = adaptive_body()
    assert "summary.attempts<4" in body
    assert "PACK_STALL_RECOVERY_MS" in body
    assert "Math.max(1600" in body
    assert "Math.min(2400" in body
    assert "return 3500" in body


def test_recovery_threshold_responds_to_measured_success():
    body = adaptive_body()
    assert "summary.successRate>=75" in body
    assert "summary.averageMs+750" in body
    assert "summary.successRate<40" in body
    observer = JS.split("async function observePackSpeedStallRecovery", 1)[1].split("async function maybeAutoAddVerified", 1)[0]
    assert "Date.now()-packRecoveryState.startedAt<packRecoveryThresholdMs()" in observer


def test_operator_can_see_the_active_threshold():
    render = JS.split("function renderPackRecoveryMetrics", 1)[1].split("function loadPackSpeedRun", 1)[0]
    assert "threshold=packRecoveryThresholdMs()" in render
    assert "threshold/1000" in render
    assert "retry threshold" in render
