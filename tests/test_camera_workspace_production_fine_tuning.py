from __future__ import annotations

import re
from pathlib import Path

from rareiq.services.camera_source_session import (
    camera_device_key,
    camera_source_id,
)


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    offset = JS.index(start)
    return JS[offset : JS.index(end, offset)]


def test_windows_backend_aliases_share_one_physical_device_identity() -> None:
    directshow = {
        "index": 1,
        "backend": 700,
        "name": "Insta360 Link",
        "path": r"\\?\usb#vid_2e1a&pid_4c01&mi_00#7&1af71f6&0&0000#{65e8773d-8f56-11d0-a3b9-00a0c9223196}\global",
        "vid": 0x2E1A,
        "pid": 0x4C01,
    }
    msmf = {
        **directshow,
        "backend": 1400,
        "path": r"\\?\usb#vid_2e1a&pid_4c01&mi_00#7&1af71f6&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}\global",
    }
    assert camera_source_id(directshow) != camera_source_id(msmf)
    assert camera_device_key(directshow) == camera_device_key(msmf)


def test_slot_health_refresh_reuses_existing_manager_poll() -> None:
    manager = section("async function loadCameraManagerState", "function openCameraPopout")
    sync = section("function syncCameraWorkspaceSlotStates", "async function refreshCameraSlotState")
    assert "syncCameraWorkspaceSlotStates(status.camera_slots||status.slots||[])" in manager
    assert "setInterval(" not in manager
    assert "cameraWorkspaceSlotSignature" in sync
    assert "renderCameraWorkspace()" in sync


def test_physical_source_ownership_uses_device_key_not_backend_option_value() -> None:
    option = section("function cameraOptionValue", "function sortCameraDevices")
    ownership = section("function cameraWorkspaceSourceOwner", "function cameraWorkspaceSlotSignature")
    assert "device_key:camera?.device_key||null" in option
    assert "cameraDeviceKeyFromValue" in ownership
    assert "cameraWorkspacePreferences.sources" in ownership
    assert "cameraWorkspaceSourceOwner(clone.value,slot)" in JS


def test_assignment_failure_restores_previous_truthful_source() -> None:
    assignment = section("async function setCameraWorkspaceSource", "async function setCameraWorkspaceSide")
    assert "const previous=cameraWorkspacePreferences.sources" in assignment
    assert "cameraWorkspacePreferences.sources[String(slot)]=previous" in assignment
    assert 'notify("Camera Assignment Failed"' in assignment
    assert "syncCameraWorkspaceSlotStates([result.slot],{force:true})" in assignment


def test_activation_and_reconnect_are_one_shot_and_backend_confirmed() -> None:
    activation = section("async function promoteCameraWorkspaceSlot", "async function reconnectCameraWorkspaceSlot")
    reconnect = section("async function reconnectCameraWorkspaceSlot", "async function setActiveCameraWorkspaceSource")
    assert "cameraWorkspaceSlotActions.has(actionKey)" in activation
    assert "syncCameraWorkspaceSlotStates(result.slots||[],{force:true})" in activation
    assert "cameraWorkspacePreferences.activeSlot=slot" not in activation
    assert "cameraWorkspaceSlotActions.has(actionKey)" in reconnect
    assert "await refreshCameraSlotState()" in reconnect
    assert "encodeURIComponent(sourceId)" in reconnect


def test_tile_health_roles_and_recovery_controls_are_truthful() -> None:
    assert HTML.count('data-reconnect-camera-slot="') == 3
    assert HTML.count('class="camera-reconnect-control"') == 3
    assert 'id="cameraSlot1Role"' in HTML
    assert 'id="secondaryBayBadge" class="camera-slot-badge"' in HTML
    for state in ("connected", "degraded", "connecting", "unavailable", "unassigned", "disconnected"):
        assert f'data-state="{state}"' in HTML or f'"{state}"' in JS
    assert '.camera-tile-status[data-state="connected"]' in CSS
    assert '.camera-reconnect-control:not([hidden])' in CSS
    assert 'role.dataset.role=roleName' in JS


def test_camera_workspace_cache_marker_and_ids_are_clean() -> None:
    assert HTML.count("shell=6.8.93-camera-workspace1") == 2
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))
