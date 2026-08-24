from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_tuning_history_retains_bounded_operator_changes():
    assert 'PACK_TUNING_HISTORY_KEY="rareiq.packTuningHistory.v1"' in JS
    assert "rows.slice(-20)" in JS
    assert "rows.slice(-5).reverse()" in JS
    assert 'id="packTuningHistory"' in JS


def test_rollback_is_latest_only_and_restores_exact_prior_setting():
    revert = JS.split("async function revertLatestPackTuning", 1)[1].split("function renderPackTuningHistory", 1)[0]
    assert "latest.id!==tuning.id" in revert
    assert "tuning.reverted" in revert
    assert "tuning.previous?.sensitivity" in revert
    assert "tuning.previous?.mode" in revert
    assert "updateRecognitionSetContext()" in revert


def test_rollback_requires_explicit_click_and_has_current_build_assets():
    assert 'id="packSessionHealthRevert"' in JS
    assert 'addEventListener("click",revertLatestPackTuning)' in JS
    assert "#packSessionHealthRevert" in CSS
    assert ".pack-tuning-history" in CSS
    assert "6.8.8-provisional-identity" in HTML
