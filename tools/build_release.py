from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_NAME = "release-manifest.json"
MANIFEST_VERSION = 1
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
VERSION_PATTERN = re.compile(rb'^VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


class ReleaseBuildError(RuntimeError):
    pass


def _run_git(project_root: Path, *args: str, text: bool = True):
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=text,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseBuildError(f"Git command failed: {' '.join(args)}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() if text else completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReleaseBuildError(detail or f"Git command failed: {' '.join(args)}")
    return completed.stdout


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _forbidden_path(path: str) -> bool:
    normalized = PurePosixPath(path)
    lowered = path.casefold()
    parts = {part.casefold() for part in normalized.parts}
    name = normalized.name.casefold()
    if normalized.is_absolute() or ".." in normalized.parts or "\\" in path:
        return True
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo", ".log")):
        return True
    if parts & {".venv", "runtime", "captures", "backups", "artifacts", ".pytest_cache"}:
        return True
    if lowered == "storage_config.json":
        return True
    if name.startswith(".env") and name != ".env.example":
        return True
    if "rareiq_secrets" in name and name != "rareiq_secrets.example.json":
        return True
    return False


def _tracked_entries(project_root: Path) -> list[dict[str, Any]]:
    raw = _run_git(project_root, "ls-tree", "-rz", "--full-tree", "HEAD", text=False)
    entries = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseBuildError("Git tree contains an unsupported entry.") from exc
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ReleaseBuildError(f"Release tree contains unsupported object {object_type} {mode}: {path}")
        if _forbidden_path(path):
            raise ReleaseBuildError(f"Tracked runtime or sensitive path cannot enter a release: {path}")
        payload = _run_git(project_root, "cat-file", "blob", object_id, text=False)
        entries.append({
            "path": path,
            "mode": mode,
            "git_blob": object_id,
            "bytes": len(payload),
            "sha256": _sha256(payload),
            "payload": payload,
        })
    entries.sort(key=lambda entry: entry["path"])
    return entries


def _release_identity(project_root: Path, entries: list[dict[str, Any]]) -> dict[str, str]:
    version_entry = next((entry for entry in entries if entry["path"] == "rareiq/version.py"), None)
    if not version_entry:
        raise ReleaseBuildError("rareiq/version.py is missing from the release tree.")
    match = VERSION_PATTERN.search(version_entry["payload"])
    if not match:
        raise ReleaseBuildError("RareIQ version could not be read from the committed source.")
    return {
        "version": match.group(1).decode("utf-8"),
        "commit": _run_git(project_root, "rev-parse", "HEAD").strip(),
        "commit_time": _run_git(project_root, "show", "-s", "--format=%cI", "HEAD").strip(),
        "branch": _run_git(project_root, "branch", "--show-current").strip(),
    }


def _archive_info(name: str, mode: str = "100644") -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    permissions = 0o755 if mode == "100755" else 0o644
    info.external_attr = (0o100000 | permissions) << 16
    return info


def build_release(
    project_root: Path,
    *,
    output: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    dirty = _run_git(project_root, "status", "--porcelain", "--untracked-files=all").strip()
    if dirty:
        raise ReleaseBuildError("Release builds require a clean Git worktree.")
    entries = _tracked_entries(project_root)
    identity = _release_identity(project_root, entries)
    root_name = f"RareIQ-{identity['version']}"
    if output is None:
        sys.path.insert(0, str(project_root))
        try:
            from rareiq.core.storage import StorageManager

            manager = StorageManager(project_root=project_root)
            output_root = manager.get_path("export_path") / "releases"
        finally:
            try:
                sys.path.remove(str(project_root))
            except ValueError:
                pass
        output = output_root / f"{root_name}-{identity['commit'][:12]}.zip"
    output = Path(output).resolve()
    manifest = {
        "version": MANIFEST_VERSION,
        "schema": "rareiq-source-release-v1",
        "product": "RareIQ",
        "release_version": identity["version"],
        "source_commit": identity["commit"],
        "source_branch": identity["branch"],
        "source_commit_time": identity["commit_time"],
        "archive_root": root_name,
        "files": [
            {key: entry[key] for key in ("path", "mode", "git_blob", "bytes", "sha256")}
            for entry in entries
        ],
        "runtime_data_included": False,
        "secrets_included": False,
    }
    report = {
        "mode": "apply" if apply else "dry-run",
        "output": str(output),
        "archive_root": root_name,
        "release_version": identity["version"],
        "source_commit": identity["commit"],
        "files": len(entries),
        "bytes_uncompressed": sum(entry["bytes"] for entry in entries),
        "runtime_data_included": False,
        "secrets_included": False,
    }
    if not apply:
        return report
    if output.exists():
        raise ReleaseBuildError(f"Release archive already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for entry in entries:
                archive.writestr(_archive_info(f"{root_name}/{entry['path']}", entry["mode"]), entry["payload"])
            archive.writestr(_archive_info(f"{root_name}/{MANIFEST_NAME}"), manifest_payload)
        os.replace(temporary, output)
        verification = verify_release(output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {
        **report,
        "archive_sha256": _sha256(output.read_bytes()),
        "bytes_compressed": output.stat().st_size,
        "verification": verification,
    }


def verify_release(archive_path: Path) -> dict[str, Any]:
    archive_path = Path(archive_path).resolve()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ReleaseBuildError("Release archive contains duplicate entries.")
            manifest_names = [name for name in names if name.endswith(f"/{MANIFEST_NAME}")]
            if len(manifest_names) != 1:
                raise ReleaseBuildError("Release archive must contain exactly one manifest.")
            manifest_name = manifest_names[0]
            root_name = manifest_name.split("/", 1)[0]
            manifest = json.loads(archive.read(manifest_name))
            if (
                manifest.get("version") != MANIFEST_VERSION
                or manifest.get("archive_root") != root_name
                or manifest.get("runtime_data_included") is not False
                or manifest.get("secrets_included") is not False
            ):
                raise ReleaseBuildError("Release manifest is unsupported or unsafe.")
            expected = {manifest_name}
            total_bytes = 0
            for entry in manifest.get("files") or []:
                path = str(entry.get("path") or "")
                if _forbidden_path(path):
                    raise ReleaseBuildError(f"Release manifest contains a forbidden path: {path}")
                name = f"{root_name}/{path}"
                payload = archive.read(name)
                if len(payload) != int(entry.get("bytes") or -1) or _sha256(payload) != entry.get("sha256"):
                    raise ReleaseBuildError(f"Release file checksum mismatch: {path}")
                expected.add(name)
                total_bytes += len(payload)
            if set(names) != expected:
                raise ReleaseBuildError("Release archive contains unmanifested files.")
    except ReleaseBuildError:
        raise
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise ReleaseBuildError(f"Release archive is invalid: {archive_path}") from exc
    return {
        "passed": True,
        "release_version": manifest["release_version"],
        "source_commit": manifest["source_commit"],
        "files": len(expected) - 1,
        "bytes_uncompressed": total_bytes,
    }


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build or verify a deterministic RareIQ source release archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output", type=Path, default=None)
    build.add_argument("--apply", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive", type=Path)
    try:
        args = parser.parse_args(argv)
        result = build_release(project_root, output=args.output, apply=args.apply) if args.command == "build" else verify_release(args.archive)
    except ReleaseBuildError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
