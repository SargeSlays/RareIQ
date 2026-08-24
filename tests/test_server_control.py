from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.server_control as control
from tools.server_control import ServerControlError


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "RareIQ"
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    (python.parent / "pythonw.exe").write_bytes(b"")
    (project / "app.py").write_text("", encoding="utf-8")
    return project


def _state(path: Path, *, pid: int = 4242, session: str = "session-a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "version": 1,
            "pid": pid,
            "host": "127.0.0.1",
            "port": 8765,
            "server_session_id": session,
            "started_at": "2026-08-23T00:00:00Z",
            "stdout_log": "out.log",
            "stderr_log": "err.log",
        }),
        encoding="utf-8",
    )


def test_status_distinguishes_stopped_running_and_session_conflict(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    monkeypatch.setattr(control, "_ping", lambda *_args, **_kwargs: None)
    assert control.server_status(project, state_path=state_path)["state"] == "stopped"

    _state(state_path)
    monkeypatch.setattr(control, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(
        control,
        "_ping",
        lambda *_args, **_kwargs: {"ok": True, "pid": 4242, "server_session_id": "session-a"},
    )
    running = control.server_status(project, state_path=state_path)
    assert running["state"] == "running"
    assert running["healthy"] is True

    monkeypatch.setattr(
        control,
        "_ping",
        lambda *_args, **_kwargs: {"ok": True, "pid": 9999, "server_session_id": "other"},
    )
    assert control.server_status(project, state_path=state_path)["state"] == "conflict"


def test_start_is_health_gated_and_persists_exact_process_identity(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    calls = []

    class FakeProcess:
        pid = 5151

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("healthy process should not terminate")

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    responses = iter([
        None,
        None,
        {"ok": True, "pid": 5151, "server_session_id": "new-session"},
        {"ok": True, "pid": 5151, "server_session_id": "new-session"},
    ])
    monkeypatch.setattr(control, "_ping", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(control, "_pid_alive", lambda pid: pid == 5151)
    monkeypatch.setattr(control.subprocess, "Popen", fake_popen)

    result = control.start_server(project, state_path=state_path, timeout=1)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["state"] == "running"
    assert result["started"] is True
    assert persisted["pid"] == 5151
    assert persisted["launcher_pid"] == 5151
    assert persisted["server_session_id"] == "new-session"
    command, kwargs = calls[0]
    assert command == [str(project / ".venv/Scripts/python.exe"), "-B", str(project / "app.py")]
    assert kwargs["cwd"] == str(project)
    assert kwargs["env"]["RAREIQ_HOST"] == "127.0.0.1"
    assert kwargs["env"]["RAREIQ_PORT"] == "8765"
    assert kwargs["stdin"] is control.subprocess.DEVNULL
    if control.os.name == "nt":
        assert kwargs["creationflags"] & control.subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert persisted["windows_job_breakaway"] is (control.os.name == "nt")


def test_start_refuses_duplicate_or_unmanaged_server(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    monkeypatch.setattr(
        control,
        "_ping",
        lambda *_args, **_kwargs: {"ok": True, "pid": 7000, "server_session_id": "unmanaged"},
    )

    with pytest.raises(ServerControlError, match="unmanaged"):
        control.start_server(project, state_path=state_path)


def test_graceful_stop_requires_matching_session_and_removes_state(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    _state(state_path)
    alive = iter([True, False, False])
    monkeypatch.setattr(control, "_pid_alive", lambda _pid: next(alive, False))
    monkeypatch.setattr(
        control,
        "_ping",
        lambda *_args, **_kwargs: {"ok": True, "pid": 4242, "server_session_id": "session-a"},
    )
    requests = []

    def request(url, **kwargs):
        requests.append((url, kwargs))
        return {"ok": True}

    monkeypatch.setattr(control, "_request_json", request)

    result = control.stop_server(project, state_path=state_path, timeout=1)

    assert result["stopped"] is True
    assert state_path.exists() is False
    assert requests == [("http://127.0.0.1:8765/api/system/shutdown", {"method": "POST", "timeout": 3.0})]


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.4", "example.com"])
def test_remote_bindings_are_rejected(host):
    with pytest.raises(ServerControlError, match="loopback"):
        control._validate_binding(host, 8765)


def test_server_run_binding_is_loopback_and_environment_configurable(monkeypatch):
    from rareiq.web import server

    calls = []
    monkeypatch.setenv("RAREIQ_HOST", "127.0.0.1")
    monkeypatch.setenv("RAREIQ_PORT", "9055")
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.run()

    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 9055


def test_ensure_is_idempotent_for_running_server(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    _state(state_path)
    monkeypatch.setattr(
        control,
        "server_status",
        lambda *_args, **_kwargs: {"state": "running", "healthy": True, "pid": 4242},
    )
    monkeypatch.setattr(
        control,
        "start_server",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    result = control.ensure_server(project, state_path=state_path)

    assert result["action"] == "none"
    assert result["already_running"] is True


def test_ensure_recovers_stale_state_with_last_binding(tmp_path, monkeypatch):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    _state(state_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["port"] = 9040
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(control, "server_status", lambda *_args, **_kwargs: {"state": "stale"})
    starts = []

    def start(*_args, **kwargs):
        starts.append(kwargs)
        return {"state": "running", "healthy": True}

    monkeypatch.setattr(control, "start_server", start)

    result = control.ensure_server(project, state_path=state_path)

    assert result["action"] == "started"
    assert starts[0]["host"] == "127.0.0.1"
    assert starts[0]["port"] == 9040


@pytest.mark.parametrize("state", ["unhealthy", "conflict", "unmanaged"])
def test_ensure_never_replaces_ambiguous_or_unhealthy_process(tmp_path, monkeypatch, state):
    project = _project(tmp_path)
    state_path = tmp_path / "state/server.json"
    _state(state_path)
    monkeypatch.setattr(control, "server_status", lambda *_args, **_kwargs: {"state": state})

    with pytest.raises(ServerControlError, match="operator review"):
        control.ensure_server(project, state_path=state_path)


def test_watchdog_schedule_is_dry_run_first_and_uses_shell_free_tasks(tmp_path):
    project = _project(tmp_path)
    (project / "tools").mkdir()
    (project / "tools/server_control.py").write_text("", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="SUCCESS", stderr="")

    dry_run = control.windows_watchdog_schedule(project, interval_minutes=5, runner=runner)
    assert dry_run["mode"] == "dry-run"
    assert calls == []

    applied = control.windows_watchdog_schedule(project, interval_minutes=5, apply=True, runner=runner)
    assert applied["installed"] is True
    assert len(calls) == 2
    assert calls[0][0][0] == "reg.exe" and control.WINDOWS_RUN_KEY in calls[0][0]
    assert "pythonw.exe" in calls[0][0][8]
    assert calls[1][0][0] == "schtasks.exe" and "MINUTE" in calls[1][0]
    assert all("shell" not in kwargs for _command, kwargs in calls)
    assert " ensure" in calls[0][0][8]
    assert " ensure" in calls[1][0][5]


def test_watchdog_failure_rolls_back_new_logon_entry(tmp_path):
    project = _project(tmp_path)
    (project / "tools").mkdir()
    (project / "tools/server_control.py").write_text("", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=1 if command[0] == "schtasks.exe" else 0,
            stdout="",
            stderr="watchdog denied" if command[0] == "schtasks.exe" else "",
        )

    with pytest.raises(ServerControlError, match="watchdog denied"):
        control.windows_watchdog_schedule(project, apply=True, runner=runner)

    assert [command[:2] for command, _kwargs in calls] == [
        ["reg.exe", "ADD"],
        ["schtasks.exe", "/Create"],
        ["reg.exe", "DELETE"],
    ]


@pytest.mark.parametrize("interval", [0, 61, -1])
def test_watchdog_schedule_rejects_unsafe_intervals(tmp_path, interval):
    with pytest.raises(ServerControlError, match="between 1 and 60"):
        control.windows_watchdog_schedule(tmp_path, interval_minutes=interval)
