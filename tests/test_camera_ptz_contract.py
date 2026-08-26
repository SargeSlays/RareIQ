from pathlib import Path

import numpy as np

from rareiq.services.vision_service import VisionService


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
DECK_CSS = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
MANAGER = (ROOT / "rareiq/services/camera_manager_service.py").read_text(encoding="utf-8")


class FakeCapture:
    def __init__(self):
        self.values = {33: 0.0, 34: 0.0, 27: 100.0}

    def get(self, prop):
        return self.values.get(prop, 0.0)

    def set(self, prop, value):
        self.values[prop] = float(value)
        return True


def test_ptz_surface_and_routes_are_wired():
    assert 'id="cameraPtzButton"' in HTML
    assert 'id="cameraPtzPanel"' in HTML
    assert "positionCameraPtzPanel" in JS
    assert "document.body.append(panel)" in JS
    assert ".camera-ptz-panel.ptz-floating" in CSS
    assert 'data-ptz-action="recenter"' in HTML
    assert 'id="cameraPtzDevice"' in HTML
    assert 'id="cameraPtzCapabilities"' in HTML
    assert 'data-camera-imaging-toggle="autofocus"' in HTML
    assert 'data-camera-imaging="exposure"' in HTML
    assert "runCameraPtzAction" in JS
    assert "setCameraImagingControl" in JS
    assert 'api("/api/camera/ptz"' in JS
    assert ".camera-ptz-panel" in CSS
    assert '@app.get("/api/camera/ptz")' in SERVER
    assert '@app.post("/api/camera/ptz")' in SERVER
    assert "def ptz_status" in MANAGER
    assert "return self.vision.camera_control" in MANAGER
    assert "def camera_control_devices" in MANAGER
    assert "Insta360 intelligent PTZ" in MANAGER
    assert "physical_devices.setdefault" in MANAGER


def test_ptz_discovery_allows_for_uncached_windows_device_enumeration():
    assert "const CAMERA_PTZ_DISCOVERY_TIMEOUT_MS=15000" in JS
    refresh = JS[
        JS.index("async function refreshCameraPtzStatus") : JS.index(
            "async function activateCameraPtzDevice"
        )
    ]
    assert (
        'api("/api/camera/ptz",{timeoutMs:CAMERA_PTZ_DISCOVERY_TIMEOUT_MS})'
        in refresh
    )
    assert "timeoutMs:5000" not in refresh


def test_ptz_presentation_has_one_modern_owner_and_preserves_controls():
    assert HTML.count('id="cameraPtzPanel"') == 1
    assert 'class="camera-ptz-source"' in HTML
    assert 'class="camera-ptz-console"' in HTML
    assert 'class="camera-ptz-movement"' in HTML
    assert "PTZ Director" in HTML
    assert "Movement, framing, and image tuning" in HTML
    assert "PTZ base positioning only" in CSS
    assert "Update 6.4.61 — camera-owner-safe PTZ command deck" not in CSS
    assert "Authoritative PTZ controller" in DECK_CSS
    assert "grid-template-columns: 172px minmax(0, 1fr)" in DECK_CSS
    assert "--sx-control-height: 38px" in DECK_CSS
    assert "width=Math.min(480,Math.max(280,window.innerWidth-32))" in JS
    for action in ("tilt_up", "pan_left", "recenter", "pan_right", "tilt_down", "zoom_out", "zoom_in"):
        assert HTML.count(f'data-ptz-action="{action}"') == 1


def test_camera_profiles_distinguish_intelligent_and_virtual_sources(tmp_path):
    service = VisionService(lambda _event: None, tmp_path)
    from rareiq.services.camera_manager_service import CameraManagerService

    manager = CameraManagerService(service, tmp_path / "cameras.json")
    insta = manager._control_profile({"name": "Insta360 Link"})
    virtual = manager._control_profile({"name": "ByteCast VirtualCamera1"})
    assert insta["class"] == "insta360_link"
    assert insta["capabilities"]["pan"] is True
    assert insta["transport"]["tracking"] == "insta360-controller"
    assert virtual["class"] == "virtual"
    assert virtual["control_score"] == 0


def test_ptz_commands_are_executed_by_camera_owner(tmp_path):
    service = VisionService(lambda _event: None, tmp_path)
    capture = FakeCapture()
    service._initialize_ptz(capture, "Insta360 Link")
    command = {
        "action": "pan_right",
        "speed": "medium",
        "preset": None,
        "completed": __import__("threading").Event(),
        "result": None,
    }
    service._ptz_commands.append(command)
    service._run_ptz_commands(capture)
    assert command["result"]["ok"] is True
    assert capture.values[33] == 3.0
    assert command["completed"].is_set()
    assert service.ptz_status()["properties"]["pan"]["confirmed"] is True


def test_ptz_recenter_and_presets_do_not_need_a_second_capture(tmp_path):
    service = VisionService(lambda _event: None, tmp_path)
    capture = FakeCapture()
    service._initialize_ptz(capture, "Insta360 Link")
    service._ptz_status["presets"]["1"] = {"pan": 8.0, "tilt": -3.0, "zoom": 105.0}
    command = {
        "action": "recall_preset",
        "speed": "slow",
        "preset": 1,
        "completed": __import__("threading").Event(),
        "result": None,
    }
    service._ptz_commands.append(command)
    service._run_ptz_commands(capture)
    assert command["result"]["ok"] is True
    assert capture.values[33] == 8.0
    assert capture.values[34] == -3.0
    assert capture.values[27] == 105.0
