from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_START_TIMEOUT = 90.0
DEFAULT_STOP_TIMEOUT = 30.0
DEFAULT_WATCHDOG_MINUTES = 5
AUTOSTART_VALUE_NAME = "RareIQ Server Auto Start"
WATCHDOG_TASK_NAME = "RareIQ Server Watchdog"
WINDOWS_RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"


class ServerControlError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_binding(
    host: str,
    port: int,
    *,
    remote_access: bool = False,
) -> tuple[str, int]:
    host = str(host).strip().lower()
    allowed = {"127.0.0.1", "localhost", "::1"}
    if remote_access:
        allowed.update({"0.0.0.0", "::"})
    if host not in allowed:
        raise ServerControlError(
            "RareIQ permits loopback hosts or an explicit authenticated wildcard LAN binding."
        )
    if not 1 <= int(port) <= 65535:
        raise ServerControlError("Server port must be between 1 and 65535.")
    return host, int(port)


def _runtime_paths(project_root: Path) -> tuple[Path, Path]:
    project_root = Path(project_root).resolve()
    sys.path.insert(0, str(project_root))
    try:
        from rareiq.core.storage import StorageManager

        manager = StorageManager(project_root=project_root)
        log_root = manager.get_path("log_path") / "server"
    finally:
        try:
            sys.path.remove(str(project_root))
        except ValueError:
            pass
    log_root.mkdir(parents=True, exist_ok=True)
    return log_root / "server-control.json", log_root


def _load_state(state_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise ServerControlError(f"Server state is unreadable: {state_path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
        raise ServerControlError(f"Server state has an unsupported format: {state_path}")
    return payload


def _write_state(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, state_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _remove_state(state_path: Path) -> None:
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _request_json(url: str, *, method: str = "GET", timeout: float = 1.0) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
        return None


def _base_url(host: str, port: int) -> str:
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    display_host = f"[{host}]" if ":" in host else host
    return f"http://{display_host}:{port}"


def _ping(host: str, port: int, *, timeout: float = 1.0) -> dict[str, Any] | None:
    return _request_json(f"{_base_url(host, port)}/api/boot/ping", timeout=timeout)


def _resolved_paths(project_root: Path, state_path: Path | None) -> tuple[Path, Path]:
    if state_path is None:
        return _runtime_paths(project_root)
    state_path = Path(state_path).resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return state_path, state_path.parent


def _remote_access_token_configured(project_root: Path) -> bool:
    token = os.environ.get("RAREIQ_REMOTE_ACCESS_TOKEN", "").strip()
    if token:
        return len(token) >= 24
    try:
        payload = json.loads((project_root / "rareiq_secrets.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return False
    return isinstance(payload, dict) and len(str(payload.get("remote_access_token") or "").strip()) >= 24


@contextmanager
def _control_lock(state_path: Path, *, timeout: float = 15.0):
    lock_path = state_path.with_name("server-control.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while time.monotonic() < deadline:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                time.sleep(0.05)
        if not locked:
            raise ServerControlError("Another RareIQ server-control operation is already in progress.")
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def server_status(project_root: Path, *, state_path: Path | None = None) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    state_path, _log_root = _resolved_paths(project_root, state_path)
    state = _load_state(state_path)
    if state:
        host, port = _validate_binding(
            state.get("host", DEFAULT_HOST),
            int(state.get("port", DEFAULT_PORT)),
            remote_access=bool(state.get("remote_access")),
        )
    else:
        host, port = DEFAULT_HOST, DEFAULT_PORT
    ping = _ping(host, port)
    if not state:
        return {
            "state": "unmanaged" if ping else "stopped",
            "managed": False,
            "healthy": bool(ping),
            "url": _base_url(host, port),
            "server": ping,
            "state_path": str(state_path),
        }
    pid = int(state.get("pid") or 0)
    launcher_pid = int(state.get("launcher_pid") or pid)
    pid_alive = _pid_alive(pid)
    launcher_alive = _pid_alive(launcher_pid)
    session_matches = bool(
        ping
        and state.get("server_session_id")
        and ping.get("server_session_id") == state.get("server_session_id")
        and int(ping.get("pid") or 0) == pid
    )
    if session_matches and pid_alive:
        status = "running"
    elif ping:
        status = "conflict"
    elif pid_alive:
        status = "unhealthy"
    else:
        status = "stale"
    return {
        "state": status,
        "managed": True,
        "healthy": status == "running",
        "pid": pid,
        "pid_alive": pid_alive,
        "launcher_pid": launcher_pid,
        "launcher_alive": launcher_alive,
        "server_session_id": state.get("server_session_id"),
        "bind_host": host,
        "remote_access": bool(state.get("remote_access")),
        "url": _base_url(host, port),
        "control_url": f"{_base_url(host, port)}/control",
        "server": ping,
        "stdout_log": state.get("stdout_log"),
        "stderr_log": state.get("stderr_log"),
        "started_at": state.get("started_at"),
        "state_path": str(state_path),
    }


def start_server(
    project_root: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_START_TIMEOUT,
    open_browser: bool = False,
    remote_access: bool = False,
    state_path: Path | None = None,
    _lock_held: bool = False,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    host, port = _validate_binding(host, port, remote_access=remote_access)
    if remote_access and not _remote_access_token_configured(project_root):
        raise ServerControlError(
            "LAN access requires remote_access_token in rareiq_secrets.json "
            "or RAREIQ_REMOTE_ACCESS_TOKEN with at least 24 characters."
        )
    state_path, log_root = _resolved_paths(project_root, state_path)
    if not _lock_held:
        with _control_lock(state_path):
            return start_server(
                project_root,
                host=host,
                port=port,
                timeout=timeout,
                open_browser=open_browser,
                remote_access=remote_access,
                state_path=state_path,
                _lock_held=True,
            )
    existing = server_status(project_root, state_path=state_path)
    if existing["state"] == "running":
        return {**existing, "already_running": True}
    if existing["state"] in {"unmanaged", "conflict", "unhealthy"}:
        raise ServerControlError(
            f"Refusing to start another RareIQ instance while server state is {existing['state']}. "
            "Inspect status or use a verified managed restart."
        )
    if existing["state"] == "stale":
        _remove_state(state_path)
    if _ping(host, port):
        raise ServerControlError(f"A RareIQ server already responds at {_base_url(host, port)} but is not managed by this state file.")
    python = project_root / ".venv" / "Scripts" / "python.exe"
    app = project_root / "app.py"
    if not python.is_file() or not app.is_file():
        raise ServerControlError("RareIQ runtime is incomplete; expected .venv\\Scripts\\python.exe and app.py.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stdout_path = log_root / f"server-{stamp}.out.log"
    stderr_path = log_root / f"server-{stamp}.err.log"
    environment = os.environ.copy()
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "RAREIQ_HOST": host,
        "RAREIQ_PORT": str(port),
        "RAREIQ_REMOTE_ACCESS": "1" if remote_access else "0",
    })
    popen_kwargs: dict[str, Any] = {
        "cwd": str(project_root),
        "env": environment,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
            | subprocess.CREATE_BREAKAWAY_FROM_JOB
        )
    else:
        popen_kwargs["start_new_session"] = True
    with stdout_path.open("ab", buffering=0) as stdout_handle, stderr_path.open("ab", buffering=0) as stderr_handle:
        process = subprocess.Popen(
            [str(python), "-B", str(app)],
            stdout=stdout_handle,
            stderr=stderr_handle,
            **popen_kwargs,
        )
    pending = {
        "version": STATE_VERSION,
        "pid": None,
        "launcher_pid": process.pid,
        "host": host,
        "port": port,
        "remote_access": remote_access,
        "server_session_id": None,
        "started_at": _utc_now(),
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "windows_job_breakaway": os.name == "nt",
    }
    _write_state(state_path, pending)
    deadline = time.monotonic() + timeout
    ping = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        ping = _ping(host, port)
        if ping and int(ping.get("pid") or 0) > 0 and ping.get("server_session_id"):
            break
        time.sleep(0.25)
    if not ping or int(ping.get("pid") or 0) <= 0 or not ping.get("server_session_id"):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        _remove_state(state_path)
        try:
            error_tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:].strip()
        except OSError:
            error_tail = ""
        raise ServerControlError(f"RareIQ did not become ready within {timeout:.0f}s. {error_tail}".strip())
    ready = {
        **pending,
        "pid": int(ping["pid"]),
        "server_session_id": ping["server_session_id"],
        "ready_at": _utc_now(),
    }
    _write_state(state_path, ready)
    result = server_status(project_root, state_path=state_path)
    if open_browser:
        webbrowser.open(result["control_url"])
    return {**result, "started": True}


def _force_stop(pid: int) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode not in {0, 128}:
            raise ServerControlError((completed.stderr or completed.stdout or "taskkill failed").strip())
    else:
        os.kill(pid, 15)


def stop_server(
    project_root: Path,
    *,
    timeout: float = DEFAULT_STOP_TIMEOUT,
    force: bool = False,
    state_path: Path | None = None,
    _lock_held: bool = False,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    state_path, _log_root = _resolved_paths(project_root, state_path)
    if not _lock_held:
        with _control_lock(state_path):
            return stop_server(
                project_root,
                timeout=timeout,
                force=force,
                state_path=state_path,
                _lock_held=True,
            )
    current = server_status(project_root, state_path=state_path)
    if current["state"] == "stopped":
        return {**current, "already_stopped": True}
    if current["state"] == "stale":
        _remove_state(state_path)
        return {**current, "stopped": True, "stale_state_removed": True}
    if current["state"] in {"unmanaged", "conflict"}:
        raise ServerControlError(f"Refusing to stop a {current['state']} server without matching managed provenance.")
    pid = int(current.get("pid") or 0)
    if current["state"] == "running":
        response = _request_json(f"{current['url']}/api/system/shutdown", method="POST", timeout=3.0)
        if not response or response.get("ok") is not True:
            if not force:
                raise ServerControlError("RareIQ did not acknowledge graceful shutdown.")
    elif not force:
        raise ServerControlError("The managed process is unhealthy; use --force only after confirming its PID.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid) and force:
        _force_stop(pid)
        force_deadline = time.monotonic() + 5.0
        while time.monotonic() < force_deadline and _pid_alive(pid):
            time.sleep(0.1)
    if _pid_alive(pid):
        raise ServerControlError(f"RareIQ PID {pid} did not stop within {timeout:.0f}s.")
    _remove_state(state_path)
    return {
        **current,
        "state": "stopped",
        "healthy": False,
        "pid_alive": False,
        "launcher_alive": _pid_alive(int(current.get("launcher_pid") or 0)),
        "stopped": True,
    }


def restart_server(
    project_root: Path,
    *,
    host: str | None = None,
    port: int | None = None,
    timeout: float = DEFAULT_START_TIMEOUT,
    force: bool = False,
    open_browser: bool = False,
    remote_access: bool | None = None,
    state_path: Path | None = None,
    _lock_held: bool = False,
) -> dict[str, Any]:
    state_path, _log_root = _resolved_paths(Path(project_root).resolve(), state_path)
    if not _lock_held:
        with _control_lock(state_path):
            return restart_server(
                project_root,
                host=host,
                port=port,
                timeout=timeout,
                force=force,
                open_browser=open_browser,
                remote_access=remote_access,
                state_path=state_path,
                _lock_held=True,
            )
    state = _load_state(state_path)
    selected_host = host or (str(state.get("host")) if state else DEFAULT_HOST)
    selected_port = port or (int(state.get("port")) if state else DEFAULT_PORT)
    selected_remote_access = (
        bool(remote_access)
        if remote_access is not None
        else bool(state.get("remote_access")) if state else False
    )
    stopped = stop_server(
        project_root,
        timeout=DEFAULT_STOP_TIMEOUT,
        force=force,
        state_path=state_path,
        _lock_held=True,
    )
    started = start_server(
        project_root,
        host=selected_host,
        port=selected_port,
        timeout=timeout,
        open_browser=open_browser,
        remote_access=selected_remote_access,
        state_path=state_path,
        _lock_held=True,
    )
    return {"stopped": stopped, "started": started}


def ensure_server(
    project_root: Path,
    *,
    timeout: float = DEFAULT_START_TIMEOUT,
    state_path: Path | None = None,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    state_path, _log_root = _resolved_paths(project_root, state_path)
    state = _load_state(state_path)
    current = server_status(project_root, state_path=state_path)
    if current["state"] == "running":
        return {**current, "action": "none", "already_running": True}
    if current["state"] not in {"stopped", "stale"}:
        raise ServerControlError(
            f"Automatic recovery is blocked while server state is {current['state']}; operator review is required."
        )
    host = str(state.get("host")) if state else DEFAULT_HOST
    port = int(state.get("port")) if state else DEFAULT_PORT
    remote_access = bool(state.get("remote_access")) if state else False
    started = start_server(
        project_root,
        host=host,
        port=port,
        timeout=timeout,
        remote_access=remote_access,
        state_path=state_path,
    )
    return {**started, "action": "started"}


def windows_watchdog_schedule(
    project_root: Path,
    *,
    interval_minutes: int = DEFAULT_WATCHDOG_MINUTES,
    apply: bool = False,
    runner=subprocess.run,
) -> dict[str, Any]:
    if not 1 <= int(interval_minutes) <= 60:
        raise ServerControlError("Watchdog interval must be between 1 and 60 minutes.")
    project_root = Path(project_root).resolve()
    python = project_root / ".venv" / "Scripts" / "python.exe"
    pythonw = project_root / ".venv" / "Scripts" / "pythonw.exe"
    script = project_root / "tools" / "server_control.py"
    if not python.is_file() or not pythonw.is_file() or not script.is_file():
        raise ServerControlError("RareIQ runtime or server-control script is missing.")
    task_command = f'"{python}" -B "{script}" ensure'
    logon_command = f'"{pythonw}" -B "{script}" ensure'
    commands = [
        [
            "reg.exe", "ADD", WINDOWS_RUN_KEY, "/v", AUTOSTART_VALUE_NAME,
            "/t", "REG_SZ", "/d", logon_command, "/f",
        ],
        [
            "schtasks.exe", "/Create", "/TN", WATCHDOG_TASK_NAME,
            "/TR", task_command, "/SC", "MINUTE", "/MO", str(interval_minutes),
            "/RL", "LIMITED", "/F",
        ],
    ]
    report = {
        "mode": "apply" if apply else "dry-run",
        "logon_command": logon_command,
        "task_command": task_command,
        "interval_minutes": interval_minutes,
        "autostart": {"mechanism": "current-user-run", "name": AUTOSTART_VALUE_NAME},
        "watchdog_task": WATCHDOG_TASK_NAME,
    }
    if not apply:
        return report
    if os.name != "nt":
        raise ServerControlError("Windows Task Scheduler is only available on Windows.")
    outputs = []
    for index, command in enumerate(commands):
        completed = runner(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            if index == 1:
                runner(
                    ["reg.exe", "DELETE", WINDOWS_RUN_KEY, "/v", AUTOSTART_VALUE_NAME, "/f"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            detail = (completed.stderr or completed.stdout or "unknown scheduler error").strip()
            component = AUTOSTART_VALUE_NAME if index == 0 else WATCHDOG_TASK_NAME
            raise ServerControlError(f"Could not install {component}: {detail}")
        outputs.append(completed.stdout.strip())
    return {**report, "installed": True, "scheduler_output": outputs}


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Reliably manage one local RareIQ server process.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--timeout", type=float, default=DEFAULT_START_TIMEOUT)
    start.add_argument("--open", action="store_true", dest="open_browser")
    start.add_argument("--lan", action="store_true", help="Enable authenticated LAN access.")
    subparsers.add_parser("status")
    ensure = subparsers.add_parser("ensure")
    ensure.add_argument("--timeout", type=float, default=DEFAULT_START_TIMEOUT)
    stop = subparsers.add_parser("stop")
    stop.add_argument("--timeout", type=float, default=DEFAULT_STOP_TIMEOUT)
    stop.add_argument("--force", action="store_true")
    restart = subparsers.add_parser("restart")
    restart.add_argument("--host", default=None)
    restart.add_argument("--port", type=int, default=None)
    restart.add_argument("--timeout", type=float, default=DEFAULT_START_TIMEOUT)
    restart.add_argument("--force", action="store_true")
    restart.add_argument("--open", action="store_true", dest="open_browser")
    restart_access = restart.add_mutually_exclusive_group()
    restart_access.add_argument(
        "--lan",
        action="store_const",
        const=True,
        default=None,
        dest="remote_access",
        help="Enable authenticated LAN access.",
    )
    restart_access.add_argument(
        "--local",
        action="store_const",
        const=False,
        dest="remote_access",
        help="Return to loopback-only access.",
    )
    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--interval", type=int, default=DEFAULT_WATCHDOG_MINUTES)
    schedule.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_server(
                project_root,
                host="0.0.0.0" if args.lan else args.host,
                port=args.port,
                timeout=args.timeout,
                open_browser=args.open_browser,
                remote_access=args.lan,
            )
        elif args.command == "status":
            result = server_status(project_root)
        elif args.command == "ensure":
            result = ensure_server(project_root, timeout=args.timeout)
        elif args.command == "stop":
            result = stop_server(project_root, timeout=args.timeout, force=args.force)
        elif args.command == "restart":
            result = restart_server(
                project_root,
                host=(
                    "0.0.0.0"
                    if args.remote_access is True
                    else "127.0.0.1"
                    if args.remote_access is False
                    else args.host
                ),
                port=args.port,
                timeout=args.timeout,
                force=args.force,
                open_browser=args.open_browser,
                remote_access=args.remote_access,
            )
        else:
            result = windows_watchdog_schedule(
                project_root,
                interval_minutes=args.interval,
                apply=args.apply,
            )
    except ServerControlError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
