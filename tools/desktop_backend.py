"""One desktop session's conservative ownership of the managed loopback backend.

The receipt is private application state, never a source/configuration file. A
new launch may replace an old receipt but never inherits its shutdown authority.
This controller never imports the application, scans devices, or force-kills.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import ctypes
import io
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import server_control as control
from rareiq.core.runtime_paths import desktop_data_root

ORIGIN = "http://127.0.0.1:8765"
RECEIPT_VERSION = 1


def _origin(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_desktop_port")
    return f"http://127.0.0.1:{port}"


def _managed_path(project, port):
    _origin(port)
    path, _ = control._resolved_paths(project, None)
    return path if port == 8765 else path.with_name(f"server-control-{port}.json")


def _identity(status):
    pid, session = status.get("pid"), status.get("server_session_id")
    if type(pid) is int and pid > 0 and isinstance(session, str) and session:
        return {"pid": pid, "server_session_id": session}
    return None


def _result(status, *, owned=False, ok=True, reason=None, port=8765):
    running = (status.get("state") == "running" or status.get("healthy") is True
               or status.get("pid_alive") is True)
    result = {"ok": ok, "origin": _origin(port), "running": running if status.get("state") != "unknown" else None,
              "owned": owned, "state": status.get("state", "unknown")}
    if identity := _identity(status):
        result["identity"] = identity
    if reason:
        result["reason"] = reason
    return result


def _read_receipt(path):
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        return receipt if isinstance(receipt, dict) and receipt.get("version") == RECEIPT_VERSION else {}
    except (OSError, ValueError):
        return {}


def _write_receipt(path, receipt):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(receipt, handle)
        if os.name == "nt":
            _restrict_windows_receipt(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restrict_windows_receipt(path):
    """Protect the receipt with an owner-only DACL, independent of folder ACLs."""
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    apply = advapi.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # OW is the owner-rights SID. P disables inherited access for this file.
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not apply(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def _valid_running(status, port=8765):
    return (status.get("state") == "running" and status.get("managed") is True
            and status.get("url") == _origin(port) and status.get("bind_host") == "127.0.0.1"
            and not status.get("remote_access") and _identity(status) is not None)


def _owned(receipt, project, status, port=8765):
    return (receipt.get("owned") is True and receipt.get("consumed") is False
            and receipt.get("project_root") == str(project)
            and receipt.get("port", 8765) == port
            and receipt.get("identity") == _identity(status) and _valid_running(status, port))


def start(project_root, state_path, *, timeout=90.0, port=8765):
    project, receipt_path = Path(project_root).resolve(), Path(state_path).resolve()
    # Resolve the existing canonical state so a browser-launched managed backend
    # is reused rather than mistaken for an unmanaged server on the same port.
    managed_path = _managed_path(project, port)
    if managed_path == receipt_path:
        raise ValueError("desktop_receipt_is_server_state")
    with control._control_lock(managed_path):
        current = control.server_status(project, state_path=managed_path, port=port)
        if current.get("state") == "running":
            if not _valid_running(current, port):
                return _result(current, ok=False, reason="loopback_managed_server_required", port=port)
            owned = False
        else:
            if current.get("state") not in {"stopped", "stale"}:
                reasons = {"unmanaged": "unmanaged_server", "conflict": "server_identity_conflict",
                           "unhealthy": "managed_server_unhealthy"}
                return _result(current, ok=False, reason=reasons.get(current.get("state"), "server_state_unknown"), port=port)
            previous = os.environ.get("PRODUCER_DESKTOP")
            os.environ["PRODUCER_DESKTOP"] = "1"
            try:
                current = control.start_server(project, host="127.0.0.1", port=port,
                    timeout=timeout, open_browser=False, remote_access=False,
                    state_path=managed_path, _lock_held=True)
            finally:
                if previous is None:
                    os.environ.pop("PRODUCER_DESKTOP", None)
                else:
                    os.environ["PRODUCER_DESKTOP"] = previous
            if not _valid_running(current, port):
                return _result(current, ok=False, reason="startup_identity_unverified", port=port)
            owned = current.get("started") is True
        _write_receipt(receipt_path, {"version": RECEIPT_VERSION, "project_root": str(project),
            "managed_state_path": str(managed_path), "identity": _identity(current),
            "owned": owned, "consumed": False, "port": port})
        return _result(current, owned=owned, reason="started" if owned else "reused", port=port)


def status(project_root, state_path, *, port=8765):
    project = Path(project_root).resolve()
    receipt = _read_receipt(Path(state_path).resolve())
    current = control.server_status(project, state_path=_managed_path(project, port), port=port)
    return _result(current, owned=_owned(receipt, project, current, port), port=port)


def _request_stop(identity, timeout, *, port=8765):
    request = urllib.request.Request(_origin(port) + "/api/desktop/stop", method="POST",
        data=json.dumps(identity).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def stop(project_root, state_path, *, timeout=20.0, port=8765):
    project, receipt_path = Path(project_root).resolve(), Path(state_path).resolve()
    managed_path = _managed_path(project, port)
    if managed_path == receipt_path:
        raise ValueError("desktop_receipt_is_server_state")
    with control._control_lock(managed_path):
        receipt = _read_receipt(receipt_path)
        current = control.server_status(project, state_path=managed_path, port=port)
        if not _owned(receipt, project, current, port):
            return _result(current, reason="not_owned", port=port)
        # Consume before contacting the server: a timeout must not leave reusable
        # authority that could affect a later show or a new desktop session.
        receipt.update(owned=False, consumed=True)
        _write_receipt(receipt_path, receipt)
        deadline = time.monotonic() + timeout
        response = _request_stop(_identity(current), min(8.0, timeout), port=port)
        if not response or response.get("stopping") is not True:
            reason = response.get("reason") if response else None
            allowed = {"clients_connected", "operation_in_progress", "session_not_idle",
                       "native_encoding_active",
                       "recording_not_idle", "obs_not_confirmed_idle", "idle_state_unknown",
                       "desktop_mode_required", "identity_mismatch"}
            return _result(current, reason=reason if reason in allowed else "shutdown_not_confirmed", port=port)
        while time.monotonic() < deadline and control._pid_alive(current["pid"]):
            time.sleep(0.1)
        if control._pid_alive(current["pid"]):
            return _result(current, reason="shutdown_pending", port=port)
        control._remove_state(managed_path)
        return _result({**current, "state": "stopped", "healthy": False, "pid_alive": False}, reason="stopped", port=port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop"))
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    args.project_root = args.project_root.resolve()
    initial_cwd = Path.cwd()
    try:
        _origin(args.port)
        if not args.state_path.is_absolute():
            raise ValueError("absolute_receipt_path_required")
        # Existing storage initialization writes human-readable startup messages.
        # The desktop IPC channel carries exactly one sanitized JSON object.
        with redirect_stdout(io.StringIO()):
            root = desktop_data_root()
            if root is not None:
                root.mkdir(parents=True, exist_ok=True)
                os.chdir(root)
            kwargs = {"port": args.port}
            if args.timeout is not None and args.command != "status":
                kwargs["timeout"] = max(1.0, min(args.timeout, 120.0))
            result = globals()[args.command](args.project_root, args.state_path, **kwargs)
    except Exception:
        result = {"ok": False, "origin": _origin(args.port) if 1 <= args.port <= 65535 else None, "running": None, "owned": False,
                  "state": "unknown", "reason": "backend_control_failed"}
    finally:
        os.chdir(initial_cwd)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
