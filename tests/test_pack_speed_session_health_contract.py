from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_session_health_combines_latency_and_recovery_outcomes():
    health = JS.split("function packSessionHealth", 1)[1].split("function renderPackSessionHealth", 1)[0]
    assert "packSpeedRun.records" in health
    assert "loadPackRecoveryMetrics()" in health
    assert "value>=1000" in health
    assert "average>1500" in health
    assert 'row.outcome==="failed"' in health
    assert "failures>=2" in health


def test_session_health_has_operator_facing_states_and_reasons():
    render = JS.split("function renderPackSessionHealth", 1)[1].split("function loadPackSpeedRun", 1)[0]
    for state in ("healthy", "watch", "critical"):
        assert state in render
    assert 'id="packSessionHealthTitle"' in render
    assert 'id="packSessionHealthDetail"' in render
    assert 'health.state==="critical"?"alert":"status"' in render


def test_session_health_is_theme_aware_and_responsive():
    assert ".pack-session-health" in CSS
    assert 'data-state="watch"' in CSS
    assert 'data-state="critical"' in CSS
    assert "html[data-theme=light] .pack-session-health" in CSS
