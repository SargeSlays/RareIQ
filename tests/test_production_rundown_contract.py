from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_rundown_operator_controls_exist():
    for token in (
        'class="production-rundown"',
        'id="productionRundownList"',
        'id="rundownCueType"',
        'id="rundownCueTarget"',
        'id="rundownAdd"',
        'id="rundownGo"',
        'id="rundownPrevious"',
        'id="rundownNext"',
    ):
        assert token in CONTROL


def test_rundown_persists_reorders_and_executes_cue_types():
    assert 'rareiq.production.rundown.v1' in JS
    assert 'function saveProductionRundown' in JS
    assert 'function loadProductionRundown' in JS
    assert 'row.draggable=true' in JS
    assert 'async function executeProductionCue' in JS
    for cue_type in ('scene', 'screen', 'graphic', 'replay', 'live', 'sound-stop'):
        assert f'cue.type==="{cue_type}"' in JS


def test_go_advances_and_has_keyboard_shortcut():
    assert 'async function goProductionRundown' in JS
    assert 'productionRundownIndex++' in JS
    assert 'event.key.toLowerCase()==="g"' in JS


def test_timed_autofollow_and_rehearsal_safety_exist():
    assert 'id="rundownCueDelay"' in CONTROL
    assert 'id="rundownCueAutoFollow"' in CONTROL
    assert 'id="rundownRehearsal"' in CONTROL
    assert 'id="rundownStop"' in CONTROL
    assert 'delay_seconds' in JS
    assert 'auto_follow' in JS
    assert 'rehearsal=false' in JS
    assert 'if(rehearsal)' in JS
    assert 'function stopProductionRundown' in JS
    assert 'productionRundownTimer' in JS


def test_templates_import_export_duplicate_and_preflight_exist():
    for token in (
        'id="rundownTemplateSelect"',
        'id="rundownTemplateSave"',
        'id="rundownTemplateLoad"',
        'id="rundownDuplicate"',
        'id="rundownExport"',
        'id="rundownImport"',
        'id="rundownPreflight"',
        'id="rundownPreflightResults"',
    ):
        assert token in CONTROL
    assert 'rareiq.production.rundown.templates.v1' in JS
    assert 'function saveRundownTemplate' in JS
    assert 'function loadRundownTemplate' in JS
    assert 'function duplicateProductionCue' in JS
    assert 'function exportProductionRundown' in JS
    assert 'async function importProductionRundown' in JS
    assert 'async function preflightProductionRundown' in JS
    assert 'scene is unavailable' in JS
    assert 'no replay highlight is ready' in JS


def test_rundown_is_themed_and_responsive():
    assert '.production-rundown' in CSS
    assert '.production-rundown-list li.is-next' in CSS
    assert 'className:"is-empty"' in JS
    assert '.production-rundown-list li.is-empty' in CSS
    assert 'html[data-theme="light"] body.studiox-ui4 .production-rundown' in CSS
    assert 'html[data-theme="light"] .rundown-safety' in CSS
    assert 'html[data-theme="light"] .production-scene-card' in CSS
