from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/pack_run_coach.css").read_text(encoding="utf-8")


def test_reference_cache_metrics_are_visible_in_live_diagnostics():
    for field in (
        "referenceCacheMetrics", "referenceCacheState", "referenceCacheHits",
        "referenceCacheCold", "referenceCacheSaved",
    ):
        assert f'id="{field}"' in CONTROL
    assert "function renderReferenceCacheMetrics(snapshot={},raw={})" in SCRIPT
    assert "reference_cache_timing" in SCRIPT
    assert "estimated_saved_ms" in SCRIPT
    assert "renderReferenceCacheMetrics(snapshot,raw)" in SCRIPT


def test_reference_cache_metrics_are_compact_responsive_and_theme_aware():
    assert ".reference-cache-metrics" in STYLES
    assert 'data-state="warm"' in STYLES
    assert 'html[data-theme="light"] .reference-cache-metrics' in STYLES
    assert "@media (max-width: 1500px)" in STYLES
