from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8-sig")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8-sig")


def test_mobile_workflow_choice_is_compact_and_accessible() -> None:
    assert 'class="recognition-workflow-prompt" role="dialog"' in HTML
    assert 'aria-labelledby="recognitionWorkflowPromptTitle"' in HTML
    assert 'id="workflowIdentifyButton" type="button" class="primary">Identify Card<' in HTML
    assert 'id="workflowPackButton" type="button">Scan Pack<' in HTML
    mobile = CSS[CSS.index("@media(max-width:959px){.recognition-workflow-prompt") :]
    assert "grid-template-columns:minmax(0,1fr) auto auto" in mobile
    assert "top:112px" in mobile
    assert ".recognition-workflow-prompt span{display:none}" in mobile
    assert "min-height:34px" in mobile


def test_mobile_workflow_choice_preserves_existing_actions() -> None:
    assert '$("workflowIdentifyButton")?.addEventListener("click",()=>chooseRecognitionWorkflow("identify")' in JS
    assert '$("workflowPackButton")?.addEventListener("click",()=>chooseRecognitionWorkflow("pack")' in JS
    assert "Continue with Card Identify" not in HTML
