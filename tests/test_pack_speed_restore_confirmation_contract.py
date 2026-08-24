from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_restore_requires_an_explicit_confirmation_step():
    request = JS.split("function requestPackTuningRunConfigurationRestore", 1)[1].split("function guardPackTuningRevalidationConfiguration", 1)[0]
    assert 'packTuningRestoreConfirmation' in request
    assert 'confirmation.dataset.fields=JSON.stringify([...fields])' in request
    assert 'row.current} → ${row.saved}' in request
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert 'addEventListener("click",requestPackTuningRunConfigurationRestore)' in render
    assert 'id="packTuningRestoreApply"' in render
    assert 'id="packTuningRestoreCancel"' in render
    assert "restorePackTuningRunConfiguration(new Set(fields))" in render

def test_confirmation_is_invalidated_when_selection_changes():
    render = JS.split("function renderPackTuningHistory", 1)[1]
    assert 'input.addEventListener("change",()=>{if(confirmation)confirmation.hidden=true})' in render
    assert "#packTuningRestoreConfirmation" in CSS
    assert "6.8.8-provisional-identity" in HTML
