from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_recovery_telemetry_is_bounded_and_persistent():
    assert 'PACK_RECOVERY_METRICS_KEY="rareiq.packRecoveryMetrics.v1"' in JS
    assert "function loadPackRecoveryMetrics" in JS
    assert "function recordPackRecoveryMetric" in JS
    assert "rows.slice(-50)" in JS


def test_recovery_records_success_and_failure_once():
    recovery = JS.split("async function observePackSpeedStallRecovery", 1)[1].split("async function maybeAutoAddVerified", 1)[0]
    assert 'recordPackRecoveryMetric("recovered"' in recovery
    assert 'recordPackRecoveryMetric("failed"' in recovery
    assert "packRecoveryState.recorded" in recovery
    assert "attemptedAt:Date.now()" in recovery


def test_pack_scoreboard_reports_recovery_effectiveness():
    assert "function packRecoveryMetricSummary" in JS
    assert "successRate" in JS
    assert "averageMs" in JS
    assert 'id="packRecoverySummary"' in JS
    assert "renderPackRecoveryMetrics()" in JS
