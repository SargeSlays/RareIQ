"""Safety guards for real bundled acceptance; these tests start no processes."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import qa_bundled_backend as qa


def test_probe_dependencies_are_used_by_production_source_not_assumed_from_features():
    root = Path(__file__).resolve().parents[1]
    files = list((root / "rareiq").rglob("*.py")) + [root / "app.py", root / "desktop/encoder_worker.py"]
    imported = set()
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    for name in qa.PROBE_MODULES:
        if name.startswith(("tools.", "rareiq.")):
            assert (root / (name.replace(".", "/") + ".py")).is_file()
        else:
            assert name.split(".")[0] in imported, name + " is not a production dependency"


@pytest.mark.parametrize("port", [8765, 0, True, 65536])
def test_acceptance_rejects_production_and_invalid_ports(port):
    with pytest.raises(RuntimeError, match="isolated_port_required"):
        qa.LocalReads(port)


@pytest.mark.parametrize("route", ["/api/camera/discover", "/api/production/session/start",
                                  "http://127.0.0.1:8765/api/boot/ping", "/api/desktop/encoding-status"])
def test_acceptance_read_allowlist_never_requests_actions_or_foreign_origins(route):
    reader = qa.LocalReads(8767)
    reader.opener.open = Mock(side_effect=AssertionError("disallowed request escaped"))
    with pytest.raises(RuntimeError, match="read_route_not_allowed"):
        reader.get(route)
    reader.opener.open.assert_not_called()


def test_clean_environment_does_not_inherit_credentials_or_python_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PRIVATE_API_KEY", "must-not-transfer")
    monkeypatch.setenv("PYTHONPATH", "C:/machine-specific/source")
    result = qa.isolated_environment(tmp_path / "resources", tmp_path / "resources/python/python.exe", tmp_path / "profile")
    assert "SYNTHETIC_PRIVATE_API_KEY" not in result
    assert result["PYTHONPATH"].endswith("intentionally-nonexistent-python-path")
    assert "machine-specific" not in result["PATH"]
    assert result["PRODUCER_DESKTOP"] == "1"


@pytest.mark.parametrize("violation", ["reused", "active_session", "active_encoding", "connected_client", "foreign_identity"])
def test_qa_teardown_preserves_any_process_without_complete_idle_ownership(tmp_path, monkeypatch, violation):
    profile, backend, python = tmp_path / "profile", tmp_path / "resources/backend", tmp_path / "resources/python/python.exe"
    profile.mkdir()
    identity = {"pid": 4242, "server_session_id": "owned-test"}
    started = {"owned": violation != "reused", "reason": "started", "identity": identity}
    managed = profile / "managed.json"
    managed.write_text(json.dumps({**identity, "launcher_pid": 4242, "host": "127.0.0.1", "port": 8767}))
    receipt = profile / "receipt.json"
    receipt.write_text(json.dumps({"identity": identity, "port": 8767, "project_root": str(backend), "managed_state_path": str(managed)}))
    kernel = SimpleNamespace(TerminateProcess=Mock(), CloseHandle=Mock())
    monkeypatch.setattr(qa, "process_handle", lambda _pid: (kernel, "held-handle"))
    monkeypatch.setattr(qa, "image_path", lambda *_args: python)
    values = {"/api/boot/ping": identity,
              "/api/desktop/status": {**identity, "clients": int(violation == "connected_client"),
                                      "native_encoding": {"active": violation == "active_encoding"},
                                      "reason": "obs_not_confirmed_idle"},
              "/api/production/session": {"session": {"active": violation == "active_session", "recording": {"active": False}},
                                          "native_encoding": {"active": False}}}
    if violation == "foreign_identity":
        values["/api/boot/ping"] = {"pid": 9999, "server_session_id": "other"}
    with pytest.raises(RuntimeError):
        qa.guarded_qa_terminate(started=started, receipt=receipt, profile=profile, backend=backend,
                                python=python, port=8767, reads=SimpleNamespace(get=values.__getitem__))
    kernel.TerminateProcess.assert_not_called()
