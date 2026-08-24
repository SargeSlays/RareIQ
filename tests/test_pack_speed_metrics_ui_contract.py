from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/pack_run_coach.css").read_text(encoding="utf-8")


def test_pack_speed_metrics_are_visible_beside_recognition_signals():
    for field in (
        "packSpeedMetrics", "packFooterMode", "packFooterHitRate",
        "packCaptureP95", "packUnderOneSecond", "packRollingAverage",
    ):
        assert f'id="{field}"' in CONTROL
    assert "function renderPackSpeedMetrics(snapshot={},raw={})" in SCRIPT
    assert "renderPackSpeedMetrics(snapshot,raw)" in SCRIPT
    assert "footer_recognition_only_hit_rate" in SCRIPT
    assert "capture_p95_ms" in SCRIPT
    assert "under_one_second_rate" in SCRIPT
    assert "recognitionLatencySamples" in SCRIPT
    assert 'panel.dataset.performance=performance' in SCRIPT


def test_pack_speed_metrics_are_compact_responsive_and_theme_aware():
    assert ".pack-speed-metrics" in STYLES
    assert 'data-state="fast"' in STYLES
    assert 'data-state="fallback"' in STYLES
    assert 'data-performance="good"' in STYLES
    assert 'data-performance="watch"' in STYLES
    assert 'data-performance="slow"' in STYLES
    assert 'html[data-theme="light"] .pack-speed-metrics' in STYLES
