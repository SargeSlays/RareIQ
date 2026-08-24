from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_workbench_context_explains_each_category():
    for element_id in ("studioxWorkbenchContext", "workbenchEyebrow", "workbenchTitle", "workbenchDescription", "workbenchPrimaryAction"):
        assert f'id="{element_id}"' in HTML
    assert "STUDIOX_WORKBENCH_CONTEXT" in JS
    for title in ("Card profile and intelligence", "Evidence and verification", "Audience effects and audio", "Value and commerce"):
        assert title in JS

def test_context_primary_actions_use_existing_behaviors():
    assert "function runStudioXWorkbenchAction" in JS
    assert "switchDock(\"candidates\")" in JS
    assert "stopAllSoundboardAudio()" in JS
    assert 'querySelector("#widgetManager>summary")' in JS

def test_context_header_is_sticky_responsive_and_themed():
    assert ".studiox-workbench-context" in CSS
    assert "position:sticky" in CSS
    assert "@media(max-width:600px)" in CSS
