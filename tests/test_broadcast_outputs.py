import asyncio
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rareiq.services.camera_manager_service import CameraManagerService
from rareiq.services.soundboard_output_service import SoundboardOutputService
from rareiq.services.vision_service import VisionService
from rareiq.web import server


ASSETS = {"sound": {"id": "sound", "kind": "audio", "url": "/api/creator/assets/sound"}}
VOICE = {"id": "play-1", "asset_id": "sound", "position": .25, "volume": .4}


def test_audio_routing_persists_but_active_sounds_do_not(tmp_path):
    path = tmp_path / "audio-routing.json"
    output = SoundboardOutputService(settings_path=path)
    assert output.settings() == {"enabled": False, "local_monitor": True, "revision": 0}
    configured = output.configure_settings({"enabled": True, "local_monitor": False})
    assert configured == {"enabled": True, "local_monitor": False, "revision": 1}
    output.publish("tab", 1, [VOICE], ASSETS)
    restored = SoundboardOutputService(settings_path=path)
    assert restored.settings() == configured
    assert restored.snapshot()["voices"] == []
    assert restored.configure_settings({"enabled": True}) == configured


@pytest.mark.parametrize("value", [{"enabled": "false"}, {"local_monitor": 0}, {"revision": 9}])
def test_audio_settings_reject_invalid_changes(value):
    output = SoundboardOutputService()
    before = output.settings()
    with pytest.raises(ValueError):
        output.configure_settings(value)
    assert output.settings() == before


def test_failed_audio_settings_save_keeps_previous_state(monkeypatch):
    output = SoundboardOutputService()
    before = output.settings()
    def fail(_):
        raise OSError("disk unavailable")
    monkeypatch.setattr(output, "_persist_settings", fail)
    with pytest.raises(OSError):
        output.configure_settings({"enabled": True})
    assert output.settings() == before


def test_audio_settings_api_reports_save_failure(monkeypatch):
    from starlette.requests import Request
    output = SoundboardOutputService()
    monkeypatch.setattr(server, "soundboard_output", output)
    def fail(_):
        raise OSError("disk unavailable")
    monkeypatch.setattr(output, "_persist_settings", fail)
    async def receive():
        return {"type":"http.request", "body":b'{"enabled":true}', "more_body":False}
    with pytest.raises(server.HTTPException) as error:
        asyncio.run(server.configure_soundboard_output_settings(Request({"type":"http", "headers":[]}, receive)))
    assert error.value.status_code == 409
    assert asyncio.run(server.soundboard_output_settings())["enabled"] is False


def test_cancelled_audio_publication_does_not_publish_partial_state(monkeypatch):
    from starlette.requests import Request

    output = SoundboardOutputService()
    output.publish("tab", 1, [VOICE], ASSETS)
    monkeypatch.setattr(server, "soundboard_output", output)
    messages = iter([
        {"type": "http.request", "body": b'{"owner":"tab",', "more_body": True},
        {"type": "http.disconnect"},
    ])
    async def receive():
        return next(messages)

    request = Request({"type": "http", "headers": []}, receive)
    response = asyncio.run(server.publish_soundboard_output(request))
    assert response.status_code == 204
    assert len(output.snapshot()["voices"]) == 1


def test_audio_snapshot_is_ephemeral_and_stop_cannot_be_undone_by_old_request():
    now = [100.]
    output = SoundboardOutputService(lambda: now[0])
    output.connect("obs")
    assert output.publish("tab", 1, [VOICE], ASSETS)["receivers"] == 1
    now[0] += .5
    assert output.snapshot()["voices"][0]["position"] == .75
    output.publish("tab", 3, [], ASSETS)
    assert output.publish("tab", 2, [VOICE], ASSETS)["accepted"] is False
    assert output.snapshot()["voices"] == []
    output.publish("tab", 4, [VOICE], ASSETS)
    now[0] += 4
    assert output.snapshot()["voices"] == []
    output.disconnect("obs")
    assert output.snapshot()["receivers"] == 0


@pytest.mark.parametrize("change", [{"asset_id":"unknown"}, {"position":float("nan")}, {"volume":2}, {"position":-1}, {"id":""}])
def test_audio_rejects_invalid_assets_and_values_atomically(change):
    output = SoundboardOutputService()
    output.publish("tab", 1, [VOICE], ASSETS)
    with pytest.raises(ValueError):
        output.publish("tab", 2, [{**VOICE, **change}], ASSETS)
    assert len(output.snapshot()["voices"]) == 1


def test_audio_layer_ids_are_namespaced_and_resource_limits_enforced():
    output = SoundboardOutputService()
    output.publish("one", 1, [VOICE], ASSETS)
    output.publish("two", 1, [VOICE], ASSETS)
    assert {v["id"] for v in output.snapshot()["voices"]} == {"one:play-1", "two:play-1"}
    with pytest.raises(ValueError):
        output.publish("one", 2, [VOICE] * 17, ASSETS)
    with pytest.raises(ValueError):
        output.publish("one", 2, [VOICE] * 2, ASSETS)


def test_clean_output_is_full_frame_cached_unannotated_and_stale_safe(monkeypatch):
    vision = VisionService.__new__(VisionService)
    vision._lock = threading.Lock()
    vision._output_jpeg_lock = threading.Lock()
    vision._running = True
    vision._stream_session_id = 1
    vision._latest_frame_at = time.time()
    vision._latest_frame = np.full((120, 80, 3), 80, dtype=np.uint8)
    vision._latest_jpeg = b"annotated-preview"
    vision._output_jpeg_key = None
    vision._output_jpeg = None
    real_encode, calls = cv2.imencode, []
    def encode(*args):
        calls.append(1)
        return real_encode(*args)
    monkeypatch.setattr(cv2, "imencode", encode)
    first = vision.clean_output_jpeg()
    assert vision.clean_output_jpeg() is first
    assert len(calls) == 1
    decoded = cv2.imdecode(np.frombuffer(first, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (120, 80, 3)
    assert np.all(decoded == 80)
    vision._latest_frame_at -= 3
    assert vision.clean_output_jpeg() is None


def test_output_lease_releases_original_session_after_slot_reassignment():
    manager = CameraManagerService.__new__(CameraManagerService)
    manager._operation_lock = threading.RLock()
    manager._slots = {slot:{"source_id":f"cam-{slot}", "role":"active" if slot==1 else "staging"} for slot in range(1,5)}
    calls = []
    session = SimpleNamespace(subscribe=lambda:calls.append("subscribe"), unsubscribe=lambda:calls.append("release-original"),
                              latest_jpeg=lambda:b"clean", status=lambda:{"connected":True})
    manager._ensure_preview_session = lambda source: session
    manager.vision = SimpleNamespace(clean_output_jpeg=lambda:b"scan")
    read, release = manager.acquire_output(2)
    assert read() == b"clean"
    manager._slots[2]["source_id"] = "different"
    assert read() is None
    release()
    assert calls == ["subscribe", "release-original"]
    read, release = manager.acquire_output(1)
    assert read() == b"scan"
    manager._slots[1]["source_id"] = "replacement"
    assert read() is None
    release()
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["scan", "all", "1", "2", "3", "4"])
def test_camera_output_pages_exist_and_invalid_slots_fail_closed(name):
    response = asyncio.run(server.camera_output_page(name))
    assert response.path.name == "camera_output.html"
    with pytest.raises(server.HTTPException):
        asyncio.run(server.camera_output_page("5"))


def test_obs_output_plan_has_every_camera_and_isolated_audio():
    from rareiq.services.obs_service import ObsService
    plan = ObsService.bootstrap_plan("http://127.0.0.1:9040")
    assert all(any(item["url"].endswith(f"/output/camera/{slot}") for item in plan) for slot in ["scan", "all", 1,2,3,4])
    audio = [item for item in plan if item.get("audio")]
    assert len(audio) == 1 and audio[0]["url"].endswith("/output/soundboard")


def test_camera_websocket_multiplexes_slots_and_releases_every_lease(monkeypatch):
    frames, released = [], []
    slots = [{"slot_id":slot,"source_id":f"camera-{slot}"} for slot in range(1,5)]
    manager = SimpleNamespace(active_slot_id=lambda:1, camera_slots=lambda:slots,
        acquire_output=lambda slot:(lambda:bytes([slot,99]),lambda:released.append(slot)))
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(camera_manager=manager))
    monkeypatch.setattr(server, "REMOTE_ACCESS", SimpleNamespace(authorizes=lambda *_:True))
    class Socket:
        client = SimpleNamespace(host="127.0.0.1")
        cookies = {}
        async def accept(self): pass
        async def send_json(self, value): assert value["active_slot"] == 1
        async def send_bytes(self, value):
            frames.append(value)
            if len(frames) == 4:
                raise server.WebSocketDisconnect()
    asyncio.run(server.camera_output_socket(Socket(), "all"))
    assert frames == [bytes([slot,slot,99]) for slot in range(1,5)]
    assert released == [1,2,3,4]


def test_camera_websocket_requires_remote_pairing(monkeypatch):
    monkeypatch.setattr(server, "REMOTE_ACCESS", SimpleNamespace(authorizes=lambda *_:False))
    codes = []
    class Socket:
        client = SimpleNamespace(host="192.168.1.2")
        cookies = {}
        async def close(self, code, **kwargs): codes.append(code)
    asyncio.run(server.camera_output_socket(Socket(), "scan"))
    assert codes == [4401]
