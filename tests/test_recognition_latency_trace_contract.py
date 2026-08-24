from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_latency_trace_exposes_four_compact_operator_stages():
    assert 'id="recognitionLatencyTrace"' in CONTROL
    assert 'id="latencyHealthLabel"' in CONTROL
    for field in ("latencyDetectValue", "latencyCandidateValue", "latencyVerifyValue", "latencyTotalValue"):
        assert f'id="{field}"' in CONTROL
    assert 'id="latencyTrend"' in CONTROL
    assert 'id="latencyTrendBars"' in CONTROL


def test_latency_trace_uses_existing_backend_stage_timings():
    assert "function renderRecognitionLatencyTrace(snapshot={},raw={})" in SCRIPT
    for timing in ("queue_ms", "prepare_ms", "artwork_search_ms", "ocr_ms", "ranking_ms"):
        assert f'"{timing}"' in SCRIPT
    assert "timings.total_ms" in SCRIPT
    assert "renderRecognitionLatencyTrace(snapshot,raw)" in SCRIPT
    assert "renderRecognitionLatencyTrace();" in SCRIPT


def test_latency_trace_surfaces_end_to_end_pack_cycle_timing():
    assert "raw?.pack_cycle_timings" in SCRIPT
    assert "removal_to_verified_ms" in SCRIPT
    assert "Pack ${Math.round(packCycleTotal)} ms" in SCRIPT


def test_latency_trace_is_responsive_and_theme_aware():
    assert ".recognition-latency-trace" in STYLES
    assert "html[data-theme=light] .recognition-latency-trace" in STYLES
    assert "@media(max-width:520px)" in STYLES


def test_latency_trace_flags_health_and_attributes_the_slowest_stage():
    assert 'total>=650?"slow":total>=300?"elevated":"normal"' in SCRIPT
    assert 'data.bottleneck' not in SCRIPT
    assert "trace.dataset.bottleneck=bottleneck" in SCRIPT
    assert 'elevated:`Elevated · ${bottleneck}`' in SCRIPT
    assert '[data-health="slow"]' in STYLES
    assert '[data-bottleneck="detect"]' in STYLES


def test_latency_trace_keeps_deduplicated_rolling_session_samples():
    assert "let recognitionLatencySamples=loadRecognitionLatencySamples()" in SCRIPT
    assert "let lastRecognitionLatencySampleKey" in SCRIPT
    assert "sampleKey!==lastRecognitionLatencySampleKey" in SCRIPT
    assert 'snapshot?.generation??"",total' in SCRIPT
    assert "recognitionLatencySamples.slice(-12)" in SCRIPT
    assert 'delta>.12?"degrading":delta<-.12?"improving":"stable"' in SCRIPT
    assert 'trace.dataset.trend=trend' in SCRIPT
    assert ".latency-trend>i>b" in STYLES
