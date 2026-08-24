from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8-sig")


def section(start: str, end: str) -> str:
    return SCRIPT[SCRIPT.index(start) : SCRIPT.index(end, SCRIPT.index(start))]


def test_live_shortcuts_ignore_interactive_targets_modified_keys_and_repeats() -> None:
    keyboard = section('document.addEventListener("keydown",event=>{', "function applyCardZoom")
    assert "function isInteractiveShortcutTarget" in SCRIPT
    for selector in ('button', 'a[href]', 'summary', '[role="tab"]'):
        assert selector in SCRIPT
    assert "if(isInteractiveShortcutTarget(event.target)) return;" in keyboard
    assert "if(event.defaultPrevented||event.isComposing) return;" in keyboard
    assert "if(activeStudioXModal()) return;" in keyboard
    assert "const plainShortcut=!event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey;" in keyboard
    for action in ('event.key===" "', 'event.key.toLowerCase()==="a"', 'event.key.toLowerCase()==="r"'):
        assert f"{action}&&!event.repeat" in keyboard
    assert 'if(event.key==="Escape")' in keyboard
    assert "captureRecognitionMode();" in keyboard
    assert "captureCamera();" not in keyboard
    assert '!event.repeat&&event.altKey&&document.body.dataset.ui4Workspace==="live"' in keyboard


def test_capture_shares_the_card_mutation_busy_gate() -> None:
    assert "function recognitionMutationInFlight(){return recognitionDecisionInFlight||recognitionClearInFlight||recognitionCaptureInFlight}" in SCRIPT
    single = section("async function captureCamera()", "function startCameraStream")
    multi = section("async function captureMultiCardGrid()", "async function toggleMultiCardOutput")
    busy = section("function setRecognitionCaptureBusy", "async function captureCamera")
    assert "if(recognitionMutationInFlight())return null;" in single
    assert "if(recognitionMutationInFlight())return null;" in multi
    assert "syncRecognitionMutationControls();" in busy


def test_broadcast_shortcuts_cannot_fire_from_controls_or_browser_combinations() -> None:
    production = section("function handleProductionShortcut", "function productionGraphicPayload")
    assert "isTypingTarget(event.target)" in production
    assert "isInteractiveShortcutTarget(event.target)" in production
    assert "event.repeat" in production
    assert "event.altKey||event.ctrlKey||event.metaKey||event.shiftKey" in production
    assert "event.altKey&&!event.ctrlKey&&!event.metaKey" in production


def test_creator_shortcuts_block_controls_and_key_repeat_without_losing_escape() -> None:
    creator = section("function creatorShortcutTargetIsEditable", "async function runCreatorAction")
    assert "creatorShortcutTargetIsEditable(event.target)&&event.key!==\"Escape\"" in creator
    assert "event.repeat" in creator
    assert 'event.code==="Space"&&!event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey' in creator
    assert 'event.key==="Escape"&&armed' in creator
