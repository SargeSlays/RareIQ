from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "rareiq/web/static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8")
CSS = (STATIC / "studiox_camera_workspace.css").read_text(encoding="utf-8")
JS = (STATIC / "studiox.js").read_text(encoding="utf-8")


def test_camera_geometry_has_one_component_owner_after_the_shell_styles():
    assert HTML.index('/static/studiox_camera_workspace.css') > HTML.index('/static/studiox_command_deck.css')
    assert HTML.count('id="cameraWorkspace"') == 1
    assert '#cameraWorkspace #viewerInspectionHeader' in CSS
    assert 'width: var(--cw-width) !important' in CSS
    assert 'height: calc(var(--cw-height) - var(--cw-header)) !important' in CSS
    assert 'grid-template: "identity action" 26px "source side" 52px' in CSS
    assert 'transition: none !important' in CSS


def test_every_secondary_camera_has_a_named_picker_and_direct_empty_state_action():
    for slot in (2, 3, 4):
        assert f'aria-label="Camera {slot} source"' in HTML
        assert HTML.count(f'data-choose-camera-slot="{slot}"') == 1
    assert 'addEventListener("click",manageCameraWorkspace)' in JS
    manager = JS[JS.index('function manageCameraWorkspace('):JS.index('async function setCameraWorkspaceSource(')]
    assert 'setCameraWorkspaceLayout("quad")' in manager
    assert 'select?.focus()' in manager


def test_hidden_media_and_recovery_copy_cannot_overlay_camera_controls():
    assert '#cameraWorkspace #cameraPlaceholder.hidden' in CSS
    assert '#cameraWorkspace #cameraRecovery.visible:not(.suppressed)' in CSS
    assert '.camera-stage-inner .camera-feed-state-shield { top: 12px' in CSS
    assert 'object-fit: contain !important' in CSS
    assert 'if(source&&visible.has(slot))' in JS
    assert 'cameraWorkspaceVisibleSlots().includes(2)' in JS
    assert '@container camera-workspace (max-width: 800px)' in CSS
    assert '#recognitionWorkflowPrompt > div { grid-column: 1 / -1 !important; }' in CSS


def test_camera_two_has_no_separate_destructive_dropdown_renderer():
    renderer = JS[JS.index('function syncSecondarySourceOptions('):JS.index('function truthfulLockedCapture(')]
    assert 'syncCameraWorkspaceSourceOptions()' in renderer
    assert 'innerHTML=' not in renderer
    assert 'replaceChildren' not in renderer
