from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_workflow_chrome_uses_current_build_and_pack_only_stats():
    assert "6.8.8-provisional-identity" in HTML
    assert "function renderRecognitionWorkflowChrome" in JS
    assert "stats.hidden=!pack" in JS
    assert ".pack-speed-run[hidden]{display:none!important}" in CSS


def test_identify_mode_clears_stale_pack_state_and_uses_single_card_copy():
    assert "if(!pack&&packRearmGate.active)clearNextPackGate()" in JS
    assert 'pack&&packRearmGate.active?"pack-complete"' in JS
    assert 'pack?"Pack Speed":"Auto Next"' in JS
    assert 'pack?"Auto-add + clear":"Remove card to continue"' in JS
