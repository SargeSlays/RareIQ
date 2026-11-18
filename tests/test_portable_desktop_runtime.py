"""Portable path/ownership contracts. No server, socket, or hardware is started."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rareiq.core import runtime_paths
from rareiq.core.secrets import SecretsManager
from rareiq.core.storage import StorageManager
from tools import desktop_backend as desktop, server_control as control


@pytest.fixture
def portable(tmp_path, monkeypatch):
    resources, data = tmp_path / "resources/backend", tmp_path / "profile/backend"
    resources.mkdir(parents=True)
    embedded = tmp_path / "resources/python/python.exe"
    embedded.parent.mkdir(parents=True)
    embedded.write_bytes(b"")
    (resources / "app.py").write_text("# inert test entrypoint", encoding="utf-8")
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(data))
    monkeypatch.setenv("PRODUCER_DESKTOP_PYTHON", str(embedded))
    return SimpleNamespace(resources=resources, data=data, python=embedded)


def test_portable_defaults_never_import_resource_configuration_or_environment_keys(portable, monkeypatch):
    for filename in ("storage_config.json", "storage_config.example.json", "rareiq_secrets.json"):
        (portable.resources / filename).write_text('{"private_developer_setting":"never import"}', encoding="utf-8")
    original_read = Path.read_text
    def guarded_read(path, *args, **kwargs):
        assert path.parent != portable.resources, "portable startup read developer configuration"
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", guarded_read)
    monkeypatch.setenv("POKEMONTCG_API_KEY", "host-environment-key-must-not-transfer")
    storage = StorageManager(project_root=portable.resources)
    storage.initialize()
    assert storage.config_file == portable.data / "storage_config.json"
    assert storage.config == runtime_paths.portable_storage_defaults()
    assert all(path.is_relative_to(portable.data) for path in storage.paths.values())
    secrets = SecretsManager(portable.resources / "rareiq_secrets.json")
    assert secrets.path == portable.data / "rareiq_secrets.json"
    assert secrets.get("pokemontcg_api_key") is None
    secrets.update({"profile_value": "synthetic-profile-only"})
    assert secrets.get("profile_value") == "synthetic-profile-only"
    assert list(portable.resources.glob("runtime*")) == []


def test_existing_profile_and_operator_selected_data_paths_are_preserved(portable, tmp_path):
    portable.data.mkdir(parents=True)
    config = runtime_paths.portable_storage_defaults()
    config["capture_path"] = str(tmp_path / "operator-selected-captures")
    config_path = portable.data / "storage_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    before = config_path.read_bytes()
    storage = StorageManager(project_root=portable.resources)
    storage.initialize()
    assert config_path.read_bytes() == before
    assert storage.get_path("capture_path") == tmp_path / "operator-selected-captures"
    secret_path = portable.data / "rareiq_secrets.json"
    secret_path.write_text('{"keep":"existing-profile-value"}', encoding="utf-8")
    secrets = SecretsManager()
    secrets.update({"added": "new-profile-value"})
    assert json.loads(secret_path.read_text()) == {"keep": "existing-profile-value", "added": "new-profile-value"}


def test_parallel_first_use_publishes_complete_defaults_without_overwrite(portable):
    def load(_index):
        manager = StorageManager(project_root=portable.resources)
        manager.initialize()
        return manager.config
    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(load, range(12)))
    assert all(value == runtime_paths.portable_storage_defaults() for value in values)
    assert list(portable.data.glob(".storage-*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows final-path spelling")
@pytest.mark.parametrize("spelling, expected", [
    (r"\\?\F:\profile\backend", "F:/profile/backend"),
    (r"\\?\UNC\host\share\profile", "//host/share/profile"),
])
def test_windows_resolved_path_prefix_has_one_containment_spelling(monkeypatch, spelling, expected):
    monkeypatch.setattr(Path, "resolve", lambda _path: Path(spelling))
    assert runtime_paths._resolved(Path("synthetic")) == Path(expected)


def test_portable_hooks_are_inert_for_normal_web_and_development(portable, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "0")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", "invalid-relative-path")
    monkeypatch.setenv("PRODUCER_DESKTOP_PYTHON", "also-relative")
    assert runtime_paths.desktop_data_root() is None
    assert runtime_paths.desktop_python() is None
    (portable.resources / "storage_config.example.json").write_text(json.dumps(runtime_paths.portable_storage_defaults()), encoding="utf-8")
    storage = StorageManager(project_root=portable.resources)
    storage.initialize()
    assert storage.config_file == portable.resources / "storage_config.json"
    assert storage.get_path("capture_path").is_relative_to(portable.resources)
    path = portable.resources / "legacy-secrets.json"
    assert SecretsManager(path).path == path


def test_portable_paths_reject_relative_roots_resource_writes_and_escape(portable, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", "relative-profile")
    with pytest.raises(ValueError, match="absolute"):
        runtime_paths.desktop_data_root()
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(Path(runtime_paths.__file__).resolve().parents[2]))
    with pytest.raises(ValueError, match="outside bundled"):
        runtime_paths.desktop_data_root()
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(portable.data))
    with pytest.raises(ValueError, match="inside its data root"):
        runtime_paths.desktop_config_path("../escaped.json")
    monkeypatch.setenv("PRODUCER_DESKTOP_PYTHON", "relative-python")
    with pytest.raises(ValueError, match="absolute"):
        runtime_paths.desktop_python()


def test_portable_spotify_does_not_read_resource_settings_or_host_environment(portable, monkeypatch):
    from rareiq.services.spotify_service import SpotifyService
    source = portable.resources / "spotify_settings.json"
    source.write_text('{"client_id":"developer-client"}', encoding="utf-8")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "inherited-host-client")
    service = SpotifyService(source)
    assert service.settings_path == portable.data / "spotify_settings.json"
    assert service.client_id == ""


def _fake_launch(monkeypatch, replies):
    process = SimpleNamespace(pid=5151, poll=Mock(return_value=None), terminate=Mock(), wait=Mock(), kill=Mock())
    spawn = Mock(return_value=process)
    monkeypatch.setattr(control.subprocess, "Popen", spawn)
    monkeypatch.setattr(control, "_ping", Mock(side_effect=replies))
    monkeypatch.setattr(control, "_pid_alive", lambda pid: pid == process.pid)
    return process, spawn


def test_embedded_launch_uses_bundle_python_and_profile_cwd_without_venv(portable, monkeypatch):
    reply = {"ok": True, "pid": 5151, "server_session_id": "portable-session"}
    process, spawn = _fake_launch(monkeypatch, [None, None, reply, reply])
    managed = portable.data / "server/server-control-8767.json"
    result = control.start_server(portable.resources, state_path=managed, port=8767, timeout=1)
    args, kwargs = spawn.call_args
    assert args[0] == [str(portable.python), "-B", str(portable.resources / "app.py")]
    assert kwargs["cwd"] == str(portable.data)
    assert kwargs["env"]["RAREIQ_PORT"] == "8767"
    assert result["state"] == "running"
    assert all(call.args[1] == 8767 for call in control._ping.call_args_list)
    assert not (portable.resources / ".venv").exists()
    process.terminate.assert_not_called()


@pytest.mark.parametrize("foreign_pid", [7000, "malformed", True])
def test_startup_cannot_adopt_another_server_that_wins_the_port_race(portable, monkeypatch, foreign_pid):
    process, spawn = _fake_launch(monkeypatch, [None, None,
        {"ok": True, "pid": foreign_pid, "server_session_id": "foreign-session"}])
    monkeypatch.setattr(control, "_force_stop", Mock(side_effect=AssertionError("never stop foreign PID")))
    managed = portable.data / "server/server-control-8767.json"
    with pytest.raises(control.ServerControlError, match="did not become ready"):
        control.start_server(portable.resources, state_path=managed, port=8767, timeout=1)
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    process.kill.assert_not_called()
    control._force_stop.assert_not_called()
    assert not managed.exists()
    assert spawn.call_count == 1


def test_status_checks_requested_port_without_a_state_file(portable, monkeypatch):
    ping = Mock(return_value=None)
    monkeypatch.setattr(control, "_ping", ping)
    result = control.server_status(portable.resources, state_path=portable.data / "test.json", port=8767)
    assert result["state"] == "stopped" and result["url"] == "http://127.0.0.1:8767"
    ping.assert_called_once_with("127.0.0.1", 8767)


def test_desktop_never_adopts_server_owned_by_a_different_profile(portable, monkeypatch):
    reply = {"ok": True, "pid": 7000, "server_session_id": "other-profile"}
    monkeypatch.setattr(control, "_ping", Mock(return_value=reply))
    spawn = Mock(side_effect=AssertionError("must not launch beside an unmanaged server"))
    monkeypatch.setattr(control.subprocess, "Popen", spawn)
    receipt = portable.data / "owner.json"
    result = desktop.start(portable.resources, receipt, port=8767)
    assert result["ok"] is False
    assert result["owned"] is False
    assert result["reason"] == "unmanaged_server"
    assert not receipt.exists()
    spawn.assert_not_called()


def test_desktop_port_roundtrip_has_separate_state_and_stop_origin(portable, monkeypatch):
    receipt = portable.data / "owner.json"
    canonical = portable.data / "runtime/logs/server/server-control.json"
    current = {"state": "stopped"}
    status_calls = []
    def get_status(_project, **kwargs):
        status_calls.append(kwargs)
        return dict(current)
    def start_server(_project, **kwargs):
        assert kwargs["port"] == 8767
        current.update(state="running", managed=True, healthy=True, bind_host="127.0.0.1",
                       url="http://127.0.0.1:8767", pid=5151, server_session_id="test-port")
        return {**current, "started": True}
    monkeypatch.setattr(control, "server_status", get_status)
    monkeypatch.setattr(control, "start_server", start_server)
    monkeypatch.setattr(control, "_control_lock", lambda _path: nullcontext())
    stop = Mock(return_value={"stopping": True})
    monkeypatch.setattr(desktop, "_request_stop", stop)
    monkeypatch.setattr(control, "_pid_alive", lambda _pid: False)
    assert desktop.start(portable.resources, receipt, port=8767)["owned"]
    assert desktop.status(portable.resources, receipt, port=8767)["owned"]
    assert desktop.stop(portable.resources, receipt, port=8767)["running"] is False
    stop.assert_called_once_with({"pid": 5151, "server_session_id": "test-port"}, 8.0, port=8767)
    assert all(call["port"] == 8767 and call["state_path"] == canonical.with_name("server-control-8767.json") for call in status_calls)
    assert not canonical.exists(), "isolated port must not overwrite normal 8765 managed state"


def test_cli_sets_profile_cwd_before_control_and_restores_caller_directory(portable, monkeypatch, capsys):
    before = Path.cwd()
    def status(project, receipt, *, port):
        assert Path.cwd() == portable.data
        assert project == portable.resources
        assert port == 8767
        return {"ok": True, "origin": "http://127.0.0.1:8767", "state": "stopped", "owned": False, "running": False}
    monkeypatch.setattr(desktop, "status", status)
    assert desktop.main(["status", "--project-root", str(portable.resources), "--state-path", str(portable.data / "owner.json"), "--port", "8767"]) == 0
    assert Path.cwd() == before
    assert json.loads(capsys.readouterr().out)["origin"].endswith(":8767")
