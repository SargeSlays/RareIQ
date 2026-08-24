from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_guidance_waits_for_a_meaningful_baseline():
    assert 'id="latencyReportGuidance" data-state="waiting"' in CONTROL
    assert "function deriveRecognitionLatencyRecommendation" in SCRIPT
    assert "if(samples.length<4)" in SCRIPT


def test_guidance_requires_sustained_latency_and_maps_real_subsystems():
    assert "average>=300&&dominant[1]>=Math.ceil(recent.length/2)" in SCRIPT
    assert "Check camera delivery" in SCRIPT
    assert "Check artwork-index search" in SCRIPT
    assert "Check OCR and verification load" in SCRIPT
    assert "recommendation:deriveRecognitionLatencyRecommendation()" in SCRIPT


def test_guidance_is_rendered_and_visually_distinct():
    assert '$("latencyReportGuidance").dataset.state=report.recommendation.state' in SCRIPT
    assert '.latency-report-guidance[data-state="action"]' in STYLES
    assert 'html[data-theme=light] .latency-report-guidance' in STYLES
