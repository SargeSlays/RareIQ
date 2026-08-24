from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_pack_run_exposes_prediction_readiness():
    assert 'id="packNextReady"' in HTML
    assert 'id="packNextReadyValue"' in HTML
    assert "function renderPackPredictionReadiness" in JS
    assert "prediction_prefetch" in JS
    assert 'renderPackPredictionReadiness(snapshot,raw)' in JS
    assert "function packRunPredictionSample" in JS
    assert "prediction hit" in JS
    assert "function renderPackPredictionSummary" in JS
    assert "function packPredictionSpeedComparison" in JS
    for element_id in ("packPredictionHits", "packPredictionSaved", "packPredictionAverage", "packPredictionCoverage"):
        assert element_id in JS
    for element_id in ("packPredictedSpeed", "packStandardSpeed", "packPredictionDifference"):
        assert element_id in JS
    assert '"faster"' in JS
    assert '"slower"' in JS
    assert '"collecting"' in JS


def test_prediction_readiness_has_all_operator_states():
    for state in ("warming", "ready", "unavailable", "idle"):
        assert f'"{state}"' in JS
