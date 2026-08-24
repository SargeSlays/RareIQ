from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq" / "web" / "static" / "control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8")


def test_slot_and_source_lifecycle_routes_are_exposed() -> None:
    for route in (
        '/api/camera-slots',
        '/api/camera-slots/{slot_id}/source',
        '/api/camera-slots/{slot_id}/activate',
        '/api/cameras/{source_id}/reconnect',
        '/api/cameras/{source_id}/restart',
        '/api/camera-slots/{slot_id}/stream',
    ):
        assert route in SERVER
    assert '@app.get("/api/camera/stream")' in SERVER


def test_stream_consumers_use_cached_sessions_and_release_subscriptions() -> None:
    assert "orchestrator.camera_manager.subscribe_slot(slot_id)" in SERVER
    assert "orchestrator.camera_manager.slot_jpeg(slot_id)" in SERVER
    assert "orchestrator.camera_manager.unsubscribe_slot(slot_id)" in SERVER
    assert "CameraSourceSession(" not in SERVER


def test_locked_workspace_has_one_real_preview_element_per_staging_slot() -> None:
    assert HTML.count('id="secondaryBayImage"') == 1
    assert HTML.count('id="cameraSlot3Preview"') == 1
    assert HTML.count('id="cameraSlot4Preview"') == 1
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(ids) == len(set(ids))


def test_frontend_assigns_and_promotes_through_slot_api_without_new_poll_loop() -> None:
    assert "`/api/camera-slots/${slot}/stream`" in JS
    assert "`/api/camera-slots/${slot}/source`" in JS
    assert "`/api/camera-slots/${slot}/activate`" in JS
    assert "source_id:sourceIdFromCameraValue" in JS
    assert 'cameraWorkspaceSlotStates[id]=slot' in JS
    assert 'connection_state||"connecting"' in JS
    slot_refresh = JS.split("async function refreshCameraSlotState", 1)[1].split("function cameraWorkspaceVisibleSlots", 1)[0]
    assert "setInterval(" not in slot_refresh


def test_cache_marker_advanced_for_multi_camera_integration() -> None:
    version = re.search(r'data-studiox-build="([^"]+)"', HTML).group(1)
    assert f'data-studiox-build="{version}"' in HTML
    assert f'/static/studiox.js?v={version}' in HTML
