from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_latency_report_has_accessible_in_app_viewer():
    assert 'id="latencyReportView"' in CONTROL
    assert 'id="latencyReportOverlay" hidden' in CONTROL
    assert 'role="dialog" aria-modal="true"' in CONTROL
    assert 'aria-labelledby="latencyReportTitle"' in CONTROL


def test_viewer_renders_summary_distribution_and_recent_samples():
    assert "function renderRecognitionLatencyReport()" in SCRIPT
    for target in ("latencyReportMetrics", "latencyReportStages", "latencyReportSamples"):
        assert f'$("{target}")' in SCRIPT
    assert "function setRecognitionLatencyReportOpen(open)" in SCRIPT
    assert "setRecognitionLatencyReportOpen(false);" in SCRIPT
    assert '$("latencyReportDownload")?.addEventListener("click",exportRecognitionLatencyReport)' in SCRIPT


def test_viewer_is_responsive_and_light_theme_aware():
    assert ".latency-report-overlay[hidden]" in STYLES
    assert "html[data-theme=light] .latency-report-panel" in STYLES
    assert "@media(max-width:620px)" in STYLES
