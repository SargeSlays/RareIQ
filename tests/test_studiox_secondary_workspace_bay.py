from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_secondary_bay_has_stable_accessible_controls():
    for element_id in (
        "secondaryWorkspaceBay",
        "secondaryBayMode",
        "stagingSourceSelect",
        "secondaryBaySize",
        "swapSourcesButton",
        "promoteStagingButton",
        "collapseSecondaryBay",
        "secondaryBayImage",
        "secondaryBroadcastPreview",
    ):
        assert HTML.count(f'id="{element_id}"') == 1
    for mode in (
        "hidden",
        "camera-2",
        "card-focus",
        "locked-capture",
        "broadcast-preview",
        "recent-captures",
    ):
        assert f'value="{mode}"' in HTML


def test_preferences_are_versioned_and_invalid_values_normalize():
    assert 'STUDIOX_SECONDARY_BAY_KEY="rareiq.studiox.secondaryBayPreferences.v1"' in JS
    assert "function normalizeSecondaryBayPreferences" in JS
    assert 'const requestedMode=modes.includes(value?.mode)?value.mode:"camera-2"' in JS
    assert 'requestedMode==="hidden"||' in JS
    assert '(requestedMode==="card-focus"&&value?.manualPinned!==true)' in JS
    assert 'sizes.includes(value?.size)?value.size:"standard"' in JS
    assert "visible:true" in JS


def test_staging_is_independent_and_source_pair_is_safe():
    staging = JS[JS.index("function setSecondaryStagingSource"):JS.index("async function promoteSecondaryStagingSource")]
    assert "resetRecognitionPresentation" not in staging
    assert "ensureCameraStarted" not in staging
    assert "cameraDeviceKeyFromValue(secondaryBayPreferences.stagingSource)===cameraDeviceKeyFromValue(secondaryBayPreferences.activeSource)" in JS
    assert "secondaryBayPreferences.stagingSource=null" in JS
    active = JS[JS.index("async function selectCamera"):JS.index("async function startSelectedCamera")]
    assert 'resetRecognitionPresentation("active_source_changed")' in active


def test_camera_two_uses_its_own_truthful_stream_and_safe_empty_states():
    assert 'No camera selected\\nChoose a source from Manage Cameras' in JS
    camera_two = JS[JS.index('if(mode==="camera-2")'):JS.index('}else if(mode==="card-focus")')]
    assert 'const source="/api/camera-slots/2/stream"' in camera_two
    assert 'image.onerror=' in camera_two
    assert 'setSecondaryBayUnavailable("CAMERA 2","Camera disconnected")' in camera_two
    assert "reference_image_url" not in JS[JS.index("function truthfulLockedCapture"):JS.index("function setSecondaryBayUnavailable")]
    assert "No locked capture" in JS
    assert "No recent capture frames" in JS


def test_streams_are_mode_bound_and_not_recreated_on_render():
    assert 'const source=lockedCapture?.url||"/api/camera/stream?viewer=secondary-card-focus"' in JS
    assert 'if(image.getAttribute("src")!==source) image.src=source' in JS
    assert 'if(!frame.getAttribute("src")) frame.src="/program?embedded=1"' in JS
    assert 'image.removeAttribute("src")' in JS
    assert 'broadcast.removeAttribute("src")' in JS


def test_collapsed_bay_releases_space_and_responsive_contract_remains():
    assert ".studiox-secondary-bay[hidden]{display:none}" in CSS
    assert ".camera-workspace.has-secondary-bay .camera-stage-inner" in CSS
    assert "@media(max-width:1440px)" in CSS
    assert "@media(max-width:1100px)" in CSS


def test_camera_two_is_the_truthful_permanent_default():
    assert 'data-bay-mode="camera-2"' in HTML
    assert '<strong id="secondaryBayStateTitle">CAMERA 2</strong>' in HTML
    assert 'mode:"camera-2"' in JS
    assert 'visible:true' in JS
    camera_two = JS[JS.index('if(mode==="camera-2")'):JS.index('}else if(mode==="card-focus")')]
    assert 'const source="/api/camera-slots/2/stream"' in camera_two
    assert '#collapseSecondaryBay{display:none}' in CSS


def test_camera_two_empty_state_is_a_framed_viewer_surface():
    assert "--secondary-bay-standard:500px" in CSS
    assert '.studiox-secondary-bay[data-bay-mode="camera-2"] .secondary-bay-content' in CSS
    assert '.secondary-bay-unavailable::before' in CSS
    assert "var(--premium-signature-gradient) border-box" in CSS
    assert "grid-template-rows:60px minmax(0,1fr)" in CSS
    assert "grid-template-rows:44px minmax(0,1fr)" in CSS
    assert "white-space:pre-line" in CSS
    assert "transform:translateY(-24px)" in CSS


def test_desktop_camera_stack_uses_width_driven_sixteen_by_nine_geometry():
    assert "fit both camera bays inside the visible desktop workspace" in CSS
    assert "height:calc(100dvh - var(--premium-command-height) - (2 * var(--sx-element-gap)))" in CSS
    assert "height:56.25cqw" in CSS
    assert "aspect-ratio:16/9" in CSS
    assert "height:calc(100% - 56.25cqw - var(--sx-element-gap))" in CSS
    assert "max-height:100%" in CSS
    assert "overflow:hidden" in CSS
