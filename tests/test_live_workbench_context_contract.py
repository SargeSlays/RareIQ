from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_workbench_context_explains_each_category():
    for element_id in ("studioxWorkbenchContext", "workbenchEyebrow", "workbenchTitle", "workbenchDescription", "workbenchSargeAction", "workbenchPrimaryAction"):
        assert f'id="{element_id}"' in HTML
    assert "STUDIOX_WORKBENCH_CONTEXT" in JS
    for title in ("Card profile and intelligence", "Evidence and verification", "Audience effects and audio", "Value and commerce"):
        assert title in JS

def test_context_primary_actions_use_existing_behaviors():
    assert "function runStudioXWorkbenchAction" in JS
    assert "openMatchCorrectionWorkflow()" in JS
    assert "stopAllSoundboardAudio()" in JS
    assert 'querySelector("#widgetManager>summary")' in JS

def test_sarge_quick_action_reveals_without_submitting():
    start = JS.index("function openLiveSargeAdvisor")
    end = JS.index("function setStudioXWorkbenchTab", start)
    action = JS[start:end]
    assert 'id!=="sarge-advisor"' in action
    assert 'applyStudioXWidgetLayout({persist:true})' in action
    assert 'scrollIntoView({block:"start",behavior})' in action
    assert '$("liveSargeAdvisorQuestion")?.focus()' in action
    assert "requestSargeAdvisor" not in action
    assert "/api/ai/advisor/ask" not in action

def test_context_header_is_sticky_responsive_and_themed():
    assert ".studiox-workbench-context" in CSS
    assert "position:sticky" in CSS
    assert "@media(max-width:600px)" in CSS
    assert ".studiox-workbench-actions" in CSS
