"""Run real bundled-backend acceptance on an isolated loopback port/profile.

Never uses port 8765, opens a device, starts media, or supplies account credentials.
The only mutation requested is the desktop controller's guarded stop. If OBS is
unknown, teardown may terminate only this run's identity-verified idle process.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import urllib.request


PROBE_MODULES = ('fastapi', 'uvicorn', 'numpy', 'cv2', 'PIL', 'av', 'httpx',
                 'tools.desktop_backend', 'rareiq.core.storage', 'rareiq.core.secrets')
PROBE = 'modules = ' + repr(PROBE_MODULES) + r'''
import importlib, importlib.util, json, os, sys
for name in modules:
    importlib.import_module(name)
files = {name:str(module.__file__) for name,module in list(sys.modules.items())
         if getattr(module,'__file__',None) and not str(module.__file__).startswith('<')}
print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'path':sys.path,
 'isolated':sys.flags.isolated,'ignore_environment':sys.flags.ignore_environment,
 'cwd':os.getcwd(),'module_files':files,
 'entrypoints':{name:importlib.util.find_spec(name).origin
                for name in ['app','rareiq.web.server','tools.desktop_backend']}}))
'''


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def digest_tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def isolated_environment(resources, python, profile):
    env = {name: value for name, value in os.environ.items()
           if name.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT",
                               "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS"}}
    windows = Path(env.get("SYSTEMROOT", "C:/Windows"))
    for directory in ("temp", "home", "home/AppData/Roaming", "home/AppData/Local", "cache"):
        (profile / directory).mkdir(parents=True, exist_ok=True)
    env.update(PRODUCER_DESKTOP="1", PRODUCER_DESKTOP_DATA_ROOT=str(profile / "backend"),
               PRODUCER_DESKTOP_PYTHON=str(python), PYTHONDONTWRITEBYTECODE="1",
               PYTHONHOME=str(profile / "intentionally-nonexistent-python-home"),
               PYTHONPATH=str(profile / "intentionally-nonexistent-python-path"),
               TEMP=str(profile / "temp"), TMP=str(profile / "temp"),
               HOME=str(profile / "home"), USERPROFILE=str(profile / "home"),
               APPDATA=str(profile / "home/AppData/Roaming"), LOCALAPPDATA=str(profile / "home/AppData/Local"),
               XDG_CACHE_HOME=str(profile / "cache"), HF_HOME=str(profile / "cache/huggingface"),
               TORCH_HOME=str(profile / "cache/torch"), NUMBA_CACHE_DIR=str(profile / "cache/numba"),
               PATH=os.pathsep.join(map(str, [python.parent, resources / "bin", windows / "System32", windows])),
               RAREIQ_REMOTE_ACCESS="0", PRODUCER_GUEST_INGRESS_PORT="")
    return env


def run_json(command, *, env, cwd, output, label, timeout):
    with (output / f"{label}.stdout.log").open("w", encoding="utf-8") as stdout, \
         (output / f"{label}.stderr.log").open("w", encoding="utf-8") as stderr:
        result = subprocess.run(command, env=env, cwd=cwd, stdout=stdout, stderr=stderr,
                                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = (output / f"{label}.stdout.log").read_text(encoding="utf-8").splitlines()
    require(bool(lines), label + "_returned_no_json")
    payload = json.loads(lines[-1])
    require(result.returncode == 0 and payload.get("ok", True) is True, label + "_failed")
    return payload


class LocalReads:
    ALLOWED = {"/api/boot/ping", "/api/desktop/status", "/api/production/native-preflight",
               "/api/production/session", "/control"}

    def __init__(self, port):
        require(type(port) is int and 1024 <= port <= 65535 and port != 8765, "isolated_port_required")
        self.origin = f"http://127.0.0.1:{port}"
        class NoRedirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                raise RuntimeError("acceptance_redirect_refused")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())

    def get(self, path):
        require(path in self.ALLOWED, "read_route_not_allowed")
        with self.opener.open(self.origin + path, timeout=12) as response:
            raw = response.read(4 * 1024 * 1024)
            require(response.status == 200, "read_failed")
        return raw.decode("utf-8") if path == "/control" else json.loads(raw)


def process_handle(pid):
    require(os.name == "nt" and type(pid) is int and pid > 0, "windows_process_identity_required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
    require(bool(handle), "cannot_verify_owned_process")
    return kernel, handle


def image_path(kernel, handle):
    buffer, size, code = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768), wintypes.DWORD()
    require(kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)), "process_image_unknown")
    require(kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259, "owned_process_not_alive")
    return Path(buffer.value).resolve()


def guarded_qa_terminate(*, started, receipt, profile, backend, python, port, reads):
    """Never terminate reused/unmanaged processes or a process with active work."""
    require(started.get("owned") is True and started.get("reason") == "started", "qa_does_not_own_process")
    identity = started["identity"]
    recorded = json.loads(receipt.read_text(encoding="utf-8"))
    require(recorded.get("identity") == identity and recorded.get("port") == port
            and Path(recorded["project_root"]).resolve() == backend, "receipt_identity_changed")
    managed_path = Path(recorded["managed_state_path"]).resolve()
    require(managed_path.is_relative_to(profile), "managed_state_outside_test_profile")
    managed = json.loads(managed_path.read_text(encoding="utf-8"))
    require(managed.get("pid") == identity["pid"] == managed.get("launcher_pid")
            and managed.get("server_session_id") == identity["server_session_id"]
            and managed.get("host") == "127.0.0.1" and managed.get("port") == port,
            "managed_process_identity_changed")
    kernel, handle = process_handle(identity["pid"])
    try:
        require(image_path(kernel, handle) == python, "process_is_not_bundled_python")
        ping, desktop, session = reads.get("/api/boot/ping"), reads.get("/api/desktop/status"), reads.get("/api/production/session")
        require(all(value.get("pid") == identity["pid"] and value.get("server_session_id") == identity["server_session_id"]
                    for value in (ping, desktop)), "http_identity_changed")
        require(desktop.get("clients") == 0 and desktop.get("native_encoding", {}).get("active") is False
                and desktop.get("reason") in {None, "obs_not_confirmed_idle"}, "qa_teardown_not_idle")
        state = session.get("session", {})
        require(state.get("active") is False and state.get("recording", {}).get("active") is False
                and session.get("native_encoding", {}).get("active") is False, "production_not_idle")
        require(kernel.TerminateProcess(handle, 0), "owned_test_teardown_failed")
        require(kernel.WaitForSingleObject(handle, 10000) == 0, "owned_test_teardown_pending")
        return {"kind": "identity_verified_idle_qa_termination", "pid": identity["pid"]}
    finally:
        kernel.CloseHandle(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-receipt", type=Path, default=Path("F:/Apps/ProducerPlease/latest-bundled-build.json"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args(argv)
    output = args.output_root.resolve()
    require(output.is_absolute() and output.drive.casefold() == "f:", "new_F_evidence_directory_required")
    reads = LocalReads(args.port)
    output.mkdir(parents=True, exist_ok=False)
    build = json.loads(args.build_receipt.read_text(encoding="utf-8"))
    resources = (Path(build["executable"]).resolve().parent / "resources").resolve()
    runtime = json.loads((resources / "runtime.json").read_text(encoding="utf-8"))
    require(runtime.get("buildKind") == "bundled-runtime", "bundled_build_required")
    backend, python = (resources / runtime["projectRoot"]).resolve(), (resources / runtime["python"]).resolve()
    require(backend.is_relative_to(resources) and python.is_relative_to(resources), "runtime_outside_resources")
    profile = output / "profile"
    env = isolated_environment(resources, python, profile)
    receipt = profile / "backend-owner.json"
    command = [str(python), "-B", str(backend / "tools/desktop_backend.py")]
    common = ["--project-root", str(backend), "--state-path", str(receipt), "--port", str(args.port)]
    result = {"ok": False, "origin": reads.origin, "resources": str(resources), "profile": str(profile),
              "real_platform_tested": False, "hardware_tested": False, "port_8765_contacted": False}
    started = None
    before = digest_tree(resources)
    write_json(output / "resource-hashes-before.json", before)
    try:
        probe = run_json([str(python), "-B", "-c", PROBE], env=env, cwd=profile, output=output, label="import-probe", timeout=45)
        write_json(output / "import-paths.json", probe)
        require(Path(probe["executable"]).resolve() == python and probe["isolated"] == 1 and probe["ignore_environment"] == 1,
                "embedded_isolation_not_active")
        all_paths = list(probe["module_files"].values()) + list(probe["entrypoints"].values()) + probe["path"]
        require(all(Path(path).resolve().is_relative_to(resources) for path in all_paths), "import_outside_bundle")
        started = run_json(command + ["start"] + common, env=env, cwd=profile, output=output, label="start", timeout=115)
        require(started.get("owned") is True and started.get("origin") == reads.origin, "fresh_owned_server_required")
        result["started"] = started
        kernel, handle = process_handle(started["identity"]["pid"])
        try:
            require(image_path(kernel, handle) == python, "server_not_using_bundled_python")
        finally:
            kernel.CloseHandle(handle)
        ping = reads.get("/api/boot/ping")
        require({key: ping.get(key) for key in started["identity"]} == started["identity"], "ping_identity_mismatch")
        initial = reads.get("/api/desktop/status")
        preflight = reads.get("/api/production/native-preflight")
        control_html = reads.get("/control")
        require("<!doctype html" in control_html.lower() and "studio" in control_html.lower(), "control_document_unavailable")
        final = reads.get("/api/desktop/status")
        require(initial.get("native_encoding", {}).get("active") is False
                and final.get("native_encoding", {}).get("active") is False, "unexpected_native_encoding")
        require(preflight.get("platform_live_verified") is False and preflight.get("preflight", {}).get("ready") is False,
                "empty_profile_claimed_native_output_ready")
        result.update(initial=initial, preflight=preflight, final=final,
                      control_document_bytes=len(control_html.encode("utf-8")), imports_inside_bundle=True)
        write_json(output / "readiness.json", {key: result[key] for key in ("initial", "preflight", "final")})
        result["ok"] = True
    except Exception as exc:
        result["failure"] = str(exc)
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if started and started.get("owned") is True:
            try:
                stopped = run_json(command + ["stop"] + common + ["--timeout", "10"], env=env, cwd=profile,
                                   output=output, label="stop", timeout=25)
                result["guarded_stop"] = stopped
                if stopped.get("running") is False:
                    result["cleanup"] = {"kind": "guarded_stop"}
                else:
                    result["cleanup"] = guarded_qa_terminate(started=started, receipt=receipt, profile=profile,
                        backend=backend, python=python, port=args.port, reads=reads)
            except Exception as exc:
                result.update(ok=False, cleanup={"kind": "left_running_for_review", "reason": str(exc)})
        after = digest_tree(resources)
        changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        write_json(output / "resource-hashes-after.json", after)
        result["resource_changes"] = changed
        result["profile_files"] = sorted(path.relative_to(profile).as_posix() for path in profile.rglob("*") if path.is_file())
        if changed:
            result.update(ok=False, failure="bundled_resources_changed")
        write_json(output / "results.json", result)
    print(json.dumps({key: result.get(key) for key in ("ok", "origin", "failure", "cleanup", "resource_changes")}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
