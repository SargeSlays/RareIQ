from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_card_identify_is_safe_default_and_pack_scan_is_explicit():
    assert 'id="recognitionWorkflowPrompt"' in HTML
    assert 'id="workflowIdentifyButton"' in HTML
    assert 'id="workflowPackButton"' in HTML
    assert 'localStorage.getItem(STUDIOX_PACK_AUTO_DETECT_KEY)==="true"' in JS
    assert 'localStorage.setItem(STUDIOX_SET_MODE_KEY,"auto")' in JS
    assert 'localStorage.setItem(STUDIOX_PACK_AUTO_DETECT_KEY,"false")' in JS
    assert 'chooseRecognitionWorkflow("pack")' in JS
    assert "Card Identify Ready" in JS


def test_set_selector_supports_keyword_filtering_and_session_choice():
    assert 'id="setContextSearch"' in HTML
    assert "renderRecognitionSetOptions" in JS
    assert "set_name,item.name,item.set_id,item.id,item.language,item.provider" in JS
    assert "STUDIOX_WORKFLOW_SESSION_KEY" in JS
    assert ".recognition-workflow-prompt" in CSS
    assert "6.8.8-provisional-identity" in HTML
