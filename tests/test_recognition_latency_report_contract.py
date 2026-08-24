from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_latency_samples_persist_for_the_browser_session():
    assert 'id="latencyReportExport"' in CONTROL
    assert 'RECOGNITION_LATENCY_SESSION_KEY="rareiq.recognitionLatency.session.v1"' in SCRIPT
    assert "sessionStorage.getItem(RECOGNITION_LATENCY_SESSION_KEY)" in SCRIPT
    assert "sessionStorage.setItem(RECOGNITION_LATENCY_SESSION_KEY" in SCRIPT
    assert "recognitionLatencySamples.slice(-12)" in SCRIPT


def test_latency_report_contains_operator_statistics_and_stage_distribution():
    assert "function buildRecognitionLatencyReport()" in SCRIPT
    for field in ("scan_count", "average_ms", "median_ms", "p95_ms", "maximum_ms", "stage_distribution"):
        assert field in SCRIPT
    assert "{detect:0,candidate:0,verify:0,unknown:0}" in SCRIPT


def test_latency_report_exports_timestamped_json():
    assert "function exportRecognitionLatencyReport()" in SCRIPT
    assert 'type:"application/json"' in SCRIPT
    assert "rareiq-latency-${new Date().toISOString()" in SCRIPT
    assert '$("latencyReportExport")?.addEventListener("click",exportRecognitionLatencyReport)' in SCRIPT
