from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


BUNDLE_VERSION = 1
MAX_LOG_BYTES = 256 * 1024
MAX_LOG_FILES = 6
SENSITIVE_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "authorization", "credential")
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_ -]?key|password|secret|token|authorization|client[_ -]?secret)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\"'\s,;]+)"
)
BEARER_TOKEN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
AUTHORIZATION_HEADER = re.compile(
    r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\"'\s,;]+"
)
FORBIDDEN_NAME_PARTS = ("secret", "capture", "artwork", "catalog", "database", "image")


class DiagnosticBundleError(RuntimeError):
    pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _redact_text(value: str) -> str:
    value = AUTHORIZATION_HEADER.sub(lambda match: match.group(1) + "[REDACTED]", value)
    value = SENSITIVE_ASSIGNMENT.sub(lambda match: match.group(1) + "[REDACTED]", value)
    return BEARER_TOKEN.sub(lambda match: match.group(1) + "[REDACTED]", value)


def _redact(value: Any, *, key: str = "") -> Any:
    normalized_key = key.casefold().replace("-", "_").replace(" ", "_")
    if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
        return "[REDACTED]" if value is not None and value != "" else value
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _storage_manager(project_root: Path):
    sys.path.insert(0, str(project_root))
    try:
        from rareiq.core.storage import StorageManager

        return StorageManager(project_root=project_root)
    finally:
        try:
            sys.path.remove(str(project_root))
        except ValueError:
            pass


def _git(project_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _request_health(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state:
        return None
    host = str(state.get("host") or "")
    port = int(state.get("port") or 0)
    if host not in {"127.0.0.1", "localhost", "::1"} or not 1 <= port <= 65535:
        return None
    display_host = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(f"http://{display_host}:{port}/api/system/health")
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError):
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _log_entries(log_root: Path) -> dict[str, bytes]:
    server_root = log_root / "server"
    if not server_root.is_dir() or server_root.is_symlink():
        return {}
    candidates = []
    for path in server_root.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if not (path.name.endswith(".out.log") or path.name.endswith(".err.log")):
            continue
        candidates.append(path)
    candidates.sort(key=lambda path: (path.stat().st_mtime_ns, path.name), reverse=True)
    entries: dict[str, bytes] = {}
    for index, path in enumerate(candidates[:MAX_LOG_FILES]):
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - MAX_LOG_BYTES))
                raw = handle.read(MAX_LOG_BYTES)
        except OSError:
            continue
        text = _redact_text(raw.decode("utf-8", errors="replace"))
        entries[f"logs/{index + 1:02d}-{path.name}"] = text.encode("utf-8")
    return entries


def collect_bundle_entries(project_root: Path) -> tuple[dict[str, bytes], Path, dict[str, Any]]:
    project_root = Path(project_root).resolve()
    manager = _storage_manager(project_root)
    storage_status = manager.status()
    storage_health = manager.health()
    log_root = manager.get_path("log_path")
    state_path = log_root / "server" / "server-control.json"
    server_state = _load_json(state_path)
    live_health = _request_health(server_state)
    try:
        from rareiq.version import version_payload

        release = version_payload()
    except Exception as exc:
        release = {"error": type(exc).__name__}
    git_status = (_git(project_root, "status", "--short", "--untracked-files=all") or "").splitlines()
    git_status = [
        line for line in git_status
        if not any(part in line.casefold() for part in SENSITIVE_KEY_PARTS)
    ]
    report = _redact({
        "schema": "rareiq-diagnostic-bundle-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release": release,
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "architecture": platform.machine(),
        },
        "git": {
            "branch": _git(project_root, "branch", "--show-current"),
            "commit": _git(project_root, "rev-parse", "HEAD"),
            "status": git_status,
        },
        "storage": {
            "status": storage_status,
            "health": storage_health,
        },
        "server": {
            "managed_state": server_state,
            "live_health": live_health,
        },
        "privacy": {
            "secrets_included": False,
            "environment_included": False,
            "captures_included": False,
            "databases_included": False,
            "catalogs_included": False,
            "artwork_included": False,
            "logs_are_tail_only": True,
            "maximum_log_bytes_each": MAX_LOG_BYTES,
        },
    })
    entries = _log_entries(log_root)
    entries["report.json"] = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return entries, manager.get_path("export_path") / "diagnostics", report


def create_bundle(
    project_root: Path,
    *,
    output: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    entries, default_root, report = collect_bundle_entries(project_root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path(output).resolve() if output else default_root / f"RareIQ-diagnostics-{stamp}-{uuid.uuid4().hex[:8]}.zip"
    result = {
        "mode": "apply" if apply else "dry-run",
        "output": str(output),
        "entries": sorted(entries),
        "bytes_uncompressed": sum(len(payload) for payload in entries.values()),
        "secrets_included": False,
        "captures_included": False,
        "databases_included": False,
        "release": report.get("release"),
    }
    if not apply:
        return result
    if output.exists():
        raise DiagnosticBundleError(f"Diagnostic bundle already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": BUNDLE_VERSION,
        "created_at": report["created_at"],
        "secrets_included": False,
        "entries": [
            {"path": name, "bytes": len(payload), "sha256": _sha256(payload)}
            for name, payload in sorted(entries.items())
        ],
    }
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in sorted(entries.items()):
                archive.writestr(name, payload)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        os.replace(temporary, output)
        verification = verify_bundle(output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {**result, "verification": verification, "bytes_compressed": output.stat().st_size}


def verify_bundle(bundle: Path) -> dict[str, Any]:
    bundle = Path(bundle).resolve()
    try:
        with zipfile.ZipFile(bundle, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise DiagnosticBundleError("Diagnostic bundle has duplicate entries or no manifest.")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise DiagnosticBundleError(f"Diagnostic bundle contains an unsafe path: {name}")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("version") != BUNDLE_VERSION or manifest.get("secrets_included") is not False:
                raise DiagnosticBundleError("Diagnostic bundle manifest is unsupported or unsafe.")
            expected_names = {"manifest.json"}
            total_bytes = 0
            for entry in manifest.get("entries") or []:
                name = str(entry.get("path") or "")
                lowered = name.casefold()
                if not name or any(part in lowered for part in FORBIDDEN_NAME_PARTS):
                    raise DiagnosticBundleError(f"Diagnostic bundle contains a forbidden entry: {name}")
                payload = archive.read(name)
                if len(payload) != int(entry.get("bytes") or -1) or _sha256(payload) != entry.get("sha256"):
                    raise DiagnosticBundleError(f"Diagnostic bundle checksum mismatch: {name}")
                expected_names.add(name)
                total_bytes += len(payload)
            if set(names) != expected_names:
                raise DiagnosticBundleError("Diagnostic bundle has unmanifested entries.")
    except DiagnosticBundleError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise DiagnosticBundleError(f"Diagnostic bundle is invalid: {bundle}") from exc
    return {"passed": True, "entries": len(expected_names) - 1, "bytes_uncompressed": total_bytes}


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create or verify a privacy-bounded RareIQ diagnostic bundle.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", type=Path, default=None)
    create.add_argument("--apply", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    try:
        args = parser.parse_args(argv)
        result = create_bundle(project_root, output=args.output, apply=args.apply) if args.command == "create" else verify_bundle(args.bundle)
    except DiagnosticBundleError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
