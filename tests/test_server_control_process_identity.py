"""Launcher ownership checks; the real-process probe runs only an inert script."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import server_control as control


@pytest.mark.skipif(os.name != "nt", reason="Windows process ancestry API")
def test_native_process_check_verifies_benign_python_child_and_rejects_unrelated_pid():
    script = "import json,os,sys; print(json.dumps({'pid':os.getpid(),'ppid':os.getppid()}),flush=True); sys.stdin.readline()"
    process = subprocess.Popen([sys.executable, "-B", "-c", script],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        identity = json.loads(process.stdout.readline())
        if identity["pid"] != process.pid:
            # CPython's Windows venv redirector is the parent of the interpreter.
            assert identity["ppid"] == process.pid
            assert control._windows_child_of(identity["pid"], process.pid)
        else:
            # A non-redirector interpreter itself is a child of this test.
            assert control._windows_child_of(process.pid, os.getpid())
        assert not control._windows_child_of(os.getpid(), process.pid)
        assert not control._windows_child_of(identity["pid"], 0)
    finally:
        process.communicate("\n", timeout=5)
    assert process.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows venv redirector startup")
@pytest.mark.parametrize("verified_child", [True, False])
def test_legacy_start_accepts_only_verified_redirector_child(tmp_path, monkeypatch, verified_child):
    for name in ("PRODUCER_DESKTOP", "PRODUCER_DESKTOP_DATA_ROOT", "PRODUCER_DESKTOP_PYTHON"):
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "project"
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    (project / "app.py").write_text("# inert fixture", encoding="utf-8")
    state = tmp_path / "managed/server.json"
    process = SimpleNamespace(pid=5151, poll=Mock(return_value=None), terminate=Mock(), wait=Mock(), kill=Mock())
    monkeypatch.setattr(control.subprocess, "Popen", Mock(return_value=process))
    healthy = {"ok": True, "pid": 6161, "server_session_id": "child-session"}
    monkeypatch.setattr(control, "_ping", Mock(side_effect=[None, None, healthy, healthy]))
    monkeypatch.setattr(control, "_pid_alive", lambda pid: pid in {5151, 6161})
    relation = Mock(return_value=verified_child)
    monkeypatch.setattr(control, "_windows_child_of", relation)
    if verified_child:
        result = control.start_server(project, state_path=state, timeout=1)
        assert result["state"] == "running"
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert saved["pid"] == 6161 and saved["launcher_pid"] == 5151
        assert saved["server_session_id"] == "child-session"
        process.terminate.assert_not_called()
    else:
        with pytest.raises(control.ServerControlError, match="did not become ready"):
            control.start_server(project, state_path=state, timeout=1)
        process.terminate.assert_called_once()
        assert not state.exists()
    relation.assert_called_once_with(6161, 5151)


def test_embedded_identity_never_accepts_even_a_verified_child(monkeypatch):
    relation = Mock(return_value=True)
    monkeypatch.setattr(control, "_windows_child_of", relation)
    assert not control._matches_started_process({"pid": 6161, "server_session_id": "child"}, 5151)
    relation.assert_not_called()


@pytest.mark.parametrize("payload", [{"pid": True, "server_session_id": "invalid"},
                                     {"pid": 6161, "server_session_id": ""},
                                     {"pid": "6161", "server_session_id": "invalid"}])
def test_redirector_check_does_not_relax_health_identity_shape(monkeypatch, payload):
    relation = Mock(return_value=True)
    monkeypatch.setattr(control, "_windows_child_of", relation)
    assert not control._matches_started_process(payload, 5151, allow_redirector_child=True)
    relation.assert_not_called()
