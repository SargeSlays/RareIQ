import asyncio
import io
import json
import subprocess
import threading
from pathlib import Path

import pytest

from rareiq.services import recording_service as module
from rareiq.services.recording_service import RecordingService
from rareiq.web import server


class Encoder:
    pid = 4321

    def __init__(self):
        self.stdin = io.BytesIO()
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture
def encoder(tmp_path, monkeypatch):
    service = RecordingService(tmp_path / "video with spaces", "encoder {output}")
    process = Encoder()
    calls = []
    def launch(args, **kwargs):
        calls.append((args, kwargs))
        return process
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    monkeypatch.setattr(service, "_free_bytes", lambda: 10 * 1024**3)
    return service, process, calls


def output(service):
    path = Path(service.status()["output_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"encoded test output")
    return path


def test_output_placeholder_is_one_argument_even_with_spaces(encoder):
    service, _process, calls = encoder
    result = service.start("session")
    assert result["started"] is True
    assert calls[0][0] == ["encoder", result["output_path"]]
    assert calls[0][1]["shell"] is False
    if module.os.name == "nt":
        assert calls[0][1]["creationflags"] & subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(module.os.name != "nt", reason="Windows encoder command grammar")
def test_windows_quoted_executable_and_device_names(encoder):
    service, _process, calls = encoder
    service.command_template = r'"C:\Program Files\Encoder\ffmpeg.exe" -i video="Camera A":audio="Mic B" "{output}"'
    result = service.start("session")
    assert calls[0][0] == [r"C:\Program Files\Encoder\ffmpeg.exe", "-i", "video=Camera A:audio=Mic B", result["output_path"]]


def test_recording_paths_are_unique_within_the_same_second(encoder, monkeypatch):
    service, process, _calls = encoder
    monkeypatch.setattr(module.time, "strftime", lambda _format: "same-second")
    first = service.start("session")
    output(service)
    service.stop()
    process.stdin = io.BytesIO()
    process.returncode = None
    second = service.start("session")
    assert first["output_path"] != second["output_path"]


def test_running_encoder_without_output_is_not_healthy(encoder):
    service, _process, _calls = encoder
    assert service.start("session")["healthy"] is False
    output(service)
    assert service.status()["healthy"] is True


def test_encoder_crash_cannot_verify_a_partial_file(encoder):
    service, process, _calls = encoder
    service.start("session")
    output(service)
    process.returncode = 7
    assert service.status()["last_error"]
    result = service.stop()
    assert result["verified"] is False
    assert result["exit_code"] == 7


def test_verified_result_survives_status_refresh_and_repeat_stop(encoder):
    service, _process, _calls = encoder
    service.start("session")
    output(service)
    assert service.stop()["verified"] is True
    assert service.status()["verified"] is True
    assert service.stop()["verified"] is True


def test_old_test_cleanup_cannot_stop_another_session(encoder):
    service, process, _calls = encoder
    service.start("new-session")
    result = service.stop(expected_session_id="old-test")
    assert result["stopped"] is False
    assert result["reason"] == "recording_session_changed"
    assert process.returncode is None
    assert process.stdin.getvalue() == b""


def test_stop_escalation_keeps_partial_output_unverified(encoder, monkeypatch):
    service, process, _calls = encoder
    service.start("session")
    output(service)
    def wait(timeout):
        if not process.killed:
            raise subprocess.TimeoutExpired("encoder", timeout)
        return -9
    monkeypatch.setattr(process, "wait", wait)
    result = service.stop()
    assert process.terminated and process.killed
    assert result["stopped"] is True
    assert result["verified"] is False
    assert process.stdin.closed


@pytest.mark.parametrize("payload", [[], None, {"minimum_free_gb": "nan"}, {"minimum_free_gb": "inf"}, {"preset": []}])
def test_malformed_recording_settings_recover_safely(tmp_path, payload):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    service = RecordingService(tmp_path / "video", "", config_path=config)
    assert service.status()["minimum_free_bytes"] > 0
    assert service.settings()["preset"] == "balanced"


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_failed_config_save_keeps_disk_and_runtime_settings(tmp_path, monkeypatch, failure):
    service = RecordingService(tmp_path / "video", "", config_path=tmp_path / "config.json")
    service.configure(output_dir=str(service.output_dir), command_template="encoder {output}", preset="balanced", minimum_free_gb=2)
    before = service.settings()
    disk = service.config_path.read_bytes()
    def fail(*_args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(module.os, failure, fail)
    result = service.configure(output_dir=str(tmp_path / "other"), command_template="other {output}", preset="quality", minimum_free_gb=3)
    assert result["updated"] is False
    assert result["reason"] == "recording_storage_unavailable"
    after = service.settings()
    for key in ("output_dir", "command_template", "preset", "minimum_free_gb"):
        assert after[key] == before[key]
    assert service.config_path.read_bytes() == disk


def test_status_is_read_only_and_storage_errors_fail_closed(tmp_path, monkeypatch):
    target = tmp_path / "not-created"
    service = RecordingService(target, "encoder {output}")
    service.status()
    assert not target.exists()
    def fail(*_args):
        raise OSError("storage unavailable")
    monkeypatch.setattr(module.shutil, "disk_usage", fail)
    assert service.status()["storage_available"] is False
    assert service.start("session")["reason"] == "recording_storage_unavailable"


def test_recording_presets_are_detached_from_returned_settings(encoder):
    service, _process, _calls = encoder
    service.settings()["presets"]["quality"]["video_bitrate_kbps"] = 1
    assert service.settings()["presets"]["quality"]["video_bitrate_kbps"] == 10000


def test_cancelled_recording_test_finalizes_only_its_encoder(encoder, monkeypatch):
    service, process, _calls = encoder
    monkeypatch.setattr(server, "recording", service)
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": False})
    async def cancelled(_seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(server.asyncio, "sleep", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server.test_recording_settings())
    assert process.returncode is not None
    assert service.status()["active"] is False


def test_new_unconfigured_session_cannot_inherit_previous_verified_output(encoder):
    service, _process, _calls = encoder
    service.start("first")
    output(service)
    assert service.stop()["verified"] is True
    service.command_template = ""
    result = service.start("second")
    assert result["started"] is False
    assert result["verified"] is False
    assert result["output_path"] is None
    assert result["session_id"] == "second"


def test_encoder_that_cannot_stop_stays_owned_and_blocks_another_start(encoder, monkeypatch):
    service, process, calls = encoder
    service.start("first")
    def timeout(seconds=None, **kwargs):
        raise subprocess.TimeoutExpired("encoder", 1)
    def denied():
        raise OSError("process unavailable")
    monkeypatch.setattr(process, "wait", timeout)
    monkeypatch.setattr(process, "terminate", denied)
    monkeypatch.setattr(process, "kill", denied)
    assert service.stop()["stopped"] is False
    assert service.status()["active"] is True
    assert service.start("second")["reason"] == "already_recording"
    assert len(calls) == 1


def test_recording_test_refuses_to_start_during_a_show(encoder, monkeypatch):
    service, _process, calls = encoder
    monkeypatch.setattr(server, "recording", service)
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": True})
    response = asyncio.run(server.test_recording_settings())
    assert response.status_code == 409
    assert calls == []


def test_production_session_cannot_claim_a_running_test_encoder(encoder, monkeypatch):
    service, _process, _calls = encoder
    service.start("test-session")
    monkeypatch.setattr(server, "recording", service)
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": False})
    response = asyncio.run(server.start_production_session(server.ProductionSessionMetadataRequest()))
    assert response.status_code == 409
    assert server.PRODUCTION_SESSION["active"] is False


def test_test_encoder_does_not_overwrite_the_last_session_report(encoder, monkeypatch):
    service, _process, _calls = encoder
    service.start("test-session")
    monkeypatch.setattr(server, "recording", service)
    saved = {"session_id": "old-session", "verified": True, "output_path": "old.mkv"}
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": False, "session_id": "old-session", "recording": saved})
    assert asyncio.run(server.production_session_status())["session"]["recording"] == saved


def test_failed_recording_test_returns_an_error_response(encoder, monkeypatch):
    service, process, _calls = encoder
    monkeypatch.setattr(server, "recording", service)
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": False})
    async def encoder_exits(_seconds):
        output(service)
        process.returncode = 1
    monkeypatch.setattr(server.asyncio, "sleep", encoder_exits)
    response = asyncio.run(server.test_recording_settings())
    assert response.status_code == 409
    assert json.loads(response.body)["test"]["verified"] is False


def test_session_finalization_does_not_block_status_and_archives_once(encoder, monkeypatch):
    service, process, _calls = encoder
    service.start("show")
    output(service)
    monkeypatch.setattr(server, "recording", service)
    monkeypatch.setattr(server, "PRODUCTION_SESSION", {"active": True, "session_id": "show", "recording": {}})
    archived = []
    monkeypatch.setattr(server, "_production_event", lambda *_args: None)
    monkeypatch.setattr(server, "_save_production_session", lambda: None)
    monkeypatch.setattr(server, "_archive_current_production_session", lambda: archived.append(True))
    entered, release = threading.Event(), threading.Event()
    def slow_wait(timeout):
        entered.set()
        assert release.wait(timeout=2)
        process.returncode = 0
        return 0
    monkeypatch.setattr(process, "wait", slow_wait)
    async def run():
        task = asyncio.create_task(server.stop_production_session())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            status = await server.production_session_status()
            assert status["session"]["recording"]["stopping"] is True
        finally:
            release.set()
        assert (await task)["session"]["recording"]["verified"] is True
        assert (await server.stop_production_session())["already_stopped"] is True
    asyncio.run(run())
    assert archived == [True]


def test_stop_response_is_snapshotted_before_another_start_can_acquire_the_lock(encoder, monkeypatch):
    service, _process, _calls = encoder
    service.start("show")
    output(service)
    real_status = service.status
    def checked_status():
        assert service._lock._is_owned(), "Stop result must be captured under the recording lock"
        return real_status()
    monkeypatch.setattr(service, "status", checked_status)
    result = service.stop()
    assert result["session_id"] == "show"
    assert result["verified"] is True
