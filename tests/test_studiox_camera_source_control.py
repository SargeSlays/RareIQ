from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq" / "web" / "static"
HTML = (STATIC / "control.html").read_text(encoding="utf-8")
JS = (STATIC / "studiox.js").read_text(encoding="utf-8")
CSS = (STATIC / "studiox_update15.css").read_text(encoding="utf-8")


def js_section(start: str, end: str) -> str:
    return JS[JS.index(start):JS.index(end, JS.index(start))]


def test_source_discovery_controls_are_visible_in_command_bar() -> None:
    source = HTML[
        HTML.index('class="command-group premium-source-control"'):
        HTML.index('class="command-group studiox-layout-control"')
    ]
    assert 'id="cameraSelect"' in source
    assert 'aria-label="Active camera source"' in source
    assert 'id="activeCameraName"' in source
    assert '<option value="refresh">Refresh Cameras</option>' in source
    assert '<option value="reconnect">Reconnect Camera</option>' in source
    assert 'value="restart">Restart Camera</option>' in source
    assert HTML.count('id="cameraSelect"') == 1
    assert HTML.count('id="restartFeedBtn"') == 1
    assert 'onchange="runCameraSourceAction(this)"' in source


def test_manual_refresh_forces_device_rediscovery_and_empty_state_is_truthful() -> None:
    discovery = js_section("async function loadCameraList", "function updateActiveCameraName")
    assert 'const force=options.force??!silent' in discovery
    assert 'api(`/api/cameras?force=${force?"true":"false"}`)' in discovery
    assert 'No cameras detected</option>' in discovery
    assert 'if(action==="refresh") await loadCameraList({force:true})' in JS


def test_physical_cameras_sort_before_virtual_and_insta360_is_prioritized() -> None:
    assert 'const VIRTUAL_CAMERA_TERMS=[' in JS
    for term in (
        "virtual", "obs", "streamlabs", "manycam", "snap camera", "ndi",
        "intcast", "xsplit", "iriun", "epoccam", "droidcam",
    ):
        assert f'"{term}"' in JS
    assert 'appendCameraGroup(select,"Physical Cameras"' in JS
    assert 'appendCameraGroup(select,"Virtual Cameras"' in JS
    assert 'Number(!/insta360/i.test(left?.name||""))' in JS
    assert 'option.textContent=`${camera.name' in JS


def test_saved_source_persists_but_missing_source_never_selects_a_different_camera() -> None:
    discovery = js_section("async function loadCameraList", "function updateActiveCameraName")
    autostart = js_section("async function attemptCameraAutostart", "async function restartFeed")
    assert 'localStorage.getItem("rareiq.selectedCamera")' in discovery
    assert 'Saved camera unavailable -- select a camera' in discovery
    assert 'Saved virtual camera requires confirmation' in discovery
    assert 'if(savedAvailable&&!savedVirtual)' in discovery
    assert 'select.value=""' in discovery
    assert 'localStorage.setItem("rareiq.selectedCamera",value)' in JS
    assert 'const first=cameras[0]' not in autostart
    assert 'if(!camera) throw new Error("Select a camera source.")' in autostart


def test_selection_reconnects_only_the_active_source_and_reports_its_name() -> None:
    selection = js_section("async function selectCamera", "async function startSelectedCamera")
    assert 'secondaryBayPreferences.activeSource=$("cameraSelect")?.value||null' in selection
    assert "normalizeSecondarySourcePair()" in selection
    assert "await ensureCameraStarted(true)" in selection
    assert 'updateActiveCameraName(selectedCamera,"active")' in selection
    assert 'state==="disconnected"?`${label} -- disconnected`' in JS
    reconnect = js_section("async function reconnectCamera", "async function captureCamera")
    assert "const camera=readSelectedCamera()" in reconnect
    assert "await ensureCameraStarted(true)" in reconnect
    assert 'api("/api/camera/recover"' not in reconnect


def test_staging_source_cannot_overwrite_active_source_implicitly() -> None:
    staging = js_section(
        "function setSecondaryStagingSource",
        "async function promoteSecondaryStagingSource",
    )
    assert "ensureCameraStarted" not in staging
    assert "selectCamera" not in staging
    assert "resetRecognitionPresentation" not in staging
    assert "secondaryBayPreferences.stagingSource===secondaryBayPreferences.activeSource" in JS


def test_restart_requires_an_explicit_selected_camera() -> None:
    restart = js_section("async function restartFeed", "async function startBackgroundInitialization")
    assert "const camera=readSelectedCamera()" in restart
    assert 'showOperatorToast("Select a camera before restarting it."' in restart
    assert "await ensureCameraStarted(true)" in restart
    assert "attemptCameraAutostart()" not in restart


def test_cache_is_advanced_and_ids_remain_unique() -> None:
    version = re.search(r'data-studiox-build="([^"]+)"', HTML).group(1)
    assert f"/static/studiox_ui4_tokens.css?v={version}" in HTML
    assert f"/static/studiox_update15.css?v={version}" in HTML
    assert f"/static/studiox.js?v={version}" in HTML
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))
    assert ".camera-source-compact-menu" in CSS
    assert "@media(min-width:2560px)" in CSS


def test_compact_toolbar_uses_camera_action_menu_without_absolute_positioning() -> None:
    assert 'class="camera-source-compact-menu"' in HTML
    assert 'onchange="runCameraSourceAction(this)"' in HTML
    assert 'window.matchMedia("(max-width: 1180px)")' in JS
    cleanup_css = CSS[CSS.index("/* Surgical UI cleanup") :]
    assert ".camera-source-compact-menu" in cleanup_css
    compact_start = cleanup_css.index(
        "body.studiox-ui4.studiox-premium .camera-source-compact-menu{"
    )
    compact_menu = cleanup_css[compact_start:cleanup_css.index("}", compact_start)]
    assert "position:absolute" not in compact_menu
    assert "margin:-" not in compact_menu


def test_disconnected_camera_cannot_present_ready_to_scan() -> None:
    disconnected = js_section("function setCameraDisconnectedPresentation", "function readSelectedCamera")
    assert 'title:"DISCONNECTED"' in disconnected
    assert 'placeholderTitle:"Camera Disconnected"' in disconnected
    assert 'Select a physical camera or refresh devices' in disconnected
    assert 'capture.disabled=!connected' in JS
    assert 'auto.disabled=!connected' in JS


def test_active_camera_label_synchronizes_the_existing_selector_only() -> None:
    active_name = js_section("function updateActiveCameraName", "function updateViewerInspectionHeader")
    assert 'const select=$("cameraSelect")' in active_name
    assert "decodeCameraValue(option.value)" in active_name
    assert "if(select&&matchingOption) select.value=matchingOption.value" in active_name
    assert "/api/camera/start" not in active_name
