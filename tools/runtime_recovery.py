from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BUFFER_SIZE = 4 * 1024 * 1024
MANIFEST_NAME = "manifest.json"
MANIFEST_DIGEST_NAME = "manifest.sha256"
SNAPSHOT_VERSION = 1
DEFAULT_RETENTION = 14
DEFAULT_SCHEDULE_TIME = "03:00"
WINDOWS_TASK_NAME = "RareIQ Runtime Recovery"


class RecoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileSet:
    root: Path
    files: tuple[Path, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _safe_files(root: Path, predicate, *, recursive: bool = True) -> tuple[Path, ...]:
    root = root.resolve()
    if not root.is_dir() or _is_link(root):
        return ()
    files: list[Path] = []
    candidates = root.rglob("*") if recursive else root.iterdir()
    for path in candidates:
        if _is_link(path):
            raise RecoveryError(f"Runtime snapshots do not follow links or junctions: {path}")
        if path.is_file() and predicate(path, path.relative_to(root)):
            files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _storage_payload(project_root: Path) -> tuple[Path, dict[str, Any]]:
    config_path = project_root / "storage_config.json"
    if not config_path.is_file():
        config_path = project_root / "storage_config.example.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise RecoveryError(f"Storage configuration is invalid: {config_path}") from exc
    if not isinstance(payload, dict):
        raise RecoveryError(f"Storage configuration is not an object: {config_path}")
    return config_path, payload


def _configured_path(config_path: Path, payload: dict[str, Any], key: str) -> Path:
    raw = payload.get(key)
    if not raw and key in {"provenance_path", "replay_path", "recording_path"}:
        suffix = {"provenance_path": "provenance", "replay_path": "replays", "recording_path": "recordings"}[key]
        raw = str(Path(str(payload["capture_path"])) / suffix)
    if not isinstance(raw, str) or not raw:
        raise RecoveryError(f"Storage path is missing: {key}")
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    return (expanded if expanded.is_absolute() else config_path.parent / expanded).resolve()


def configured_file_sets(project_root: Path, profile: str = "critical") -> dict[str, FileSet]:
    if profile not in {"critical", "media"}:
        raise RecoveryError(f"Unsupported recovery profile: {profile}")
    project_root = Path(project_root).resolve()
    config_path, payload = _storage_payload(project_root)
    database_root = _configured_path(config_path, payload, "database_root")
    config_root = _configured_path(config_path, payload, "config_path")
    cache_root = _configured_path(config_path, payload, "cache_path")
    log_root = _configured_path(config_path, payload, "log_path")
    provenance_root = _configured_path(config_path, payload, "provenance_path")
    replay_root = _configured_path(config_path, payload, "replay_path")
    recording_root = _configured_path(config_path, payload, "recording_path")
    project_data = project_root / "rareiq" / "data"

    state_suffixes = {".json", ".jsonl", ".db", ".sqlite", ".sqlite3"}
    sets = {
        "database": FileSet(
            database_root,
            _safe_files(database_root, lambda path, _relative: path.suffix.lower() in state_suffixes, recursive=False),
        ),
        "config": FileSet(config_root, _safe_files(config_root, lambda _path, _relative: True)),
        "cache_state": FileSet(cache_root, _safe_files(cache_root, lambda path, _relative: path.suffix.lower() in {".json", ".jsonl"})),
        "sessions": FileSet(log_root / "sessions", _safe_files(log_root / "sessions", lambda _path, _relative: True)),
        "project_runtime": FileSet(project_data, _safe_files(project_data, lambda path, _relative: path.suffix.lower() in {".json", ".jsonl"}, recursive=False)),
        "provenance_metadata": FileSet(
            provenance_root,
            _safe_files(
                provenance_root,
                lambda _path, relative: relative.as_posix() in {"events.jsonl", "settings.json"} or relative.name == "event.json",
            ),
        ),
    }
    if profile == "media":
        sets["provenance_media"] = FileSet(
            provenance_root,
            _safe_files(provenance_root, lambda _path, relative: relative.name != "event.json" and relative.as_posix() not in {"events.jsonl", "settings.json"}),
        )
        sets["replays"] = FileSet(replay_root, _safe_files(replay_root, lambda _path, _relative: True))
        sets["recordings"] = FileSet(recording_root, _safe_files(recording_root, lambda _path, _relative: True))
    return sets


def configured_destinations(project_root: Path) -> tuple[dict[str, Path], Path]:
    project_root = Path(project_root).resolve()
    config_path, payload = _storage_payload(project_root)
    log_root = _configured_path(config_path, payload, "log_path")
    destinations = {
        "database": _configured_path(config_path, payload, "database_root"),
        "config": _configured_path(config_path, payload, "config_path"),
        "cache_state": _configured_path(config_path, payload, "cache_path"),
        "sessions": log_root / "sessions",
        "project_runtime": project_root / "rareiq" / "data",
        "provenance_metadata": _configured_path(config_path, payload, "provenance_path"),
        "provenance_media": _configured_path(config_path, payload, "provenance_path"),
        "replays": _configured_path(config_path, payload, "replay_path"),
        "recordings": _configured_path(config_path, payload, "recording_path"),
    }
    return destinations, _configured_path(config_path, payload, "backup_path")


def _source_signature(file_sets: dict[str, FileSet]) -> str:
    digest = hashlib.sha256()
    for scope, file_set in sorted(file_sets.items()):
        for path in file_set.files:
            stat = path.stat()
            relative = path.relative_to(file_set.root).as_posix()
            digest.update(f"{scope}\0{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> str:
    source_hash = _sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.rareiq-recovery-{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            while chunk := input_handle.read(BUFFER_SIZE):
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        shutil.copystat(source, temporary)
        os.replace(temporary, destination)
        if destination.stat().st_size != source.stat().st_size or _sha256(destination) != source_hash:
            raise RecoveryError(f"Snapshot verification failed: {destination}")
        return source_hash
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _volume(path: Path) -> str:
    resolved = path.resolve()
    return (resolved.drive or resolved.anchor or str(resolved)).casefold()


def create_snapshot(
    file_sets: dict[str, FileSet],
    destination_root: Path,
    *,
    profile: str = "critical",
    consistency: str = "strict",
    apply: bool = False,
) -> dict[str, Any]:
    if consistency not in {"strict", "file"}:
        raise RecoveryError(f"Unsupported snapshot consistency mode: {consistency}")
    destination_root = Path(destination_root).resolve()
    initial_signature = _source_signature(file_sets)
    total_files = sum(len(item.files) for item in file_sets.values())
    total_bytes = sum(path.stat().st_size for item in file_sets.values() for path in item.files)
    report = {
        "mode": "apply" if apply else "dry-run",
        "profile": profile,
        "consistency": consistency,
        "destination_root": str(destination_root),
        "files": total_files,
        "bytes": total_bytes,
        "scopes": {scope: len(item.files) for scope, item in file_sets.items()},
        "same_volume_scopes": sorted(
            scope for scope, item in file_sets.items() if item.files and _volume(item.root) == _volume(destination_root)
        ),
        "secrets_included": False,
    }
    if not apply:
        return report
    existing_parent = destination_root
    while not existing_parent.exists() and existing_parent != existing_parent.parent:
        existing_parent = existing_parent.parent
    if shutil.disk_usage(existing_parent).free < total_bytes + 64 * 1024 * 1024:
        raise RecoveryError("Insufficient free space for the recovery snapshot.")

    snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    partial = destination_root / f".{snapshot_id}.partial"
    final = destination_root / snapshot_id
    if partial.exists() or final.exists():
        raise RecoveryError(f"Snapshot path already exists: {snapshot_id}")
    entries: list[dict[str, Any]] = []
    try:
        partial.mkdir(parents=True)
        for scope, file_set in sorted(file_sets.items()):
            for source in file_set.files:
                relative = source.relative_to(file_set.root)
                destination = partial / "data" / scope / relative
                digest = _copy_verified(source, destination)
                entries.append({
                    "scope": scope,
                    "relative_path": relative.as_posix(),
                    "bytes": destination.stat().st_size,
                    "sha256": digest,
                })
        if consistency == "strict" and _source_signature(file_sets) != initial_signature:
            raise RecoveryError("Runtime state changed during snapshot; stop RareIQ and retry.")
        manifest = {
            "version": SNAPSHOT_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "profile": profile,
            "consistency": consistency,
            "files": entries,
            "source_signature": initial_signature,
            "secrets_included": False,
            "same_volume_scopes": report["same_volume_scopes"],
        }
        manifest_path = partial / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (partial / MANIFEST_DIGEST_NAME).write_text(_sha256(manifest_path) + "\n", encoding="ascii")
        os.replace(partial, final)
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    verification = verify_snapshot(final)
    return {**report, "snapshot_id": snapshot_id, "snapshot_path": str(final), "verification": verification}


def _load_manifest(snapshot: Path) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    manifest_path = snapshot / MANIFEST_NAME
    digest_path = snapshot / MANIFEST_DIGEST_NAME
    try:
        expected = digest_path.read_text(encoding="ascii").strip().lower()
        if len(expected) != 64 or _sha256(manifest_path) != expected:
            raise RecoveryError("Snapshot manifest checksum mismatch.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, RecoveryError):
            raise
        raise RecoveryError(f"Snapshot manifest is invalid: {snapshot}") from exc
    if manifest.get("version") != SNAPSHOT_VERSION or not isinstance(manifest.get("files"), list):
        raise RecoveryError("Unsupported snapshot manifest.")
    return manifest


def verify_snapshot(snapshot: Path) -> dict[str, Any]:
    snapshot = Path(snapshot).resolve()
    manifest = _load_manifest(snapshot)
    total_bytes = 0
    for entry in manifest["files"]:
        scope = str(entry.get("scope") or "")
        relative = Path(str(entry.get("relative_path") or ""))
        candidate = (snapshot / "data" / scope / relative).resolve()
        try:
            candidate.relative_to(snapshot / "data")
        except ValueError as exc:
            raise RecoveryError("Snapshot entry escapes the data directory.") from exc
        if not candidate.is_file() or _is_link(candidate):
            raise RecoveryError(f"Snapshot file is missing: {scope}/{relative.as_posix()}")
        if candidate.stat().st_size != int(entry.get("bytes") or -1) or _sha256(candidate) != entry.get("sha256"):
            raise RecoveryError(f"Snapshot file checksum mismatch: {scope}/{relative.as_posix()}")
        total_bytes += candidate.stat().st_size
    return {"passed": True, "files": len(manifest["files"]), "bytes": total_bytes}


def _remove_snapshot(snapshot: Path, snapshot_root: Path) -> None:
    snapshot_root = Path(snapshot_root).resolve()
    candidate = Path(snapshot)
    if _is_link(candidate):
        raise RecoveryError(f"Refusing to remove linked snapshot path: {candidate}")
    candidate = candidate.resolve()
    try:
        candidate.relative_to(snapshot_root)
    except ValueError as exc:
        raise RecoveryError(f"Snapshot path escapes the configured root: {candidate}") from exc
    if candidate.parent != snapshot_root or not candidate.is_dir():
        raise RecoveryError(f"Snapshot is not a direct child of the configured root: {candidate}")
    shutil.rmtree(candidate)


def prune_snapshots(
    snapshot_root: Path,
    *,
    keep: int = DEFAULT_RETENTION,
    apply: bool = False,
) -> dict[str, Any]:
    if keep < 1:
        raise RecoveryError("Snapshot retention must keep at least one verified snapshot.")
    snapshot_root = Path(snapshot_root).resolve()
    verified: list[tuple[str, str, Path]] = []
    untouched: list[str] = []
    if snapshot_root.is_dir() and not _is_link(snapshot_root):
        for candidate in sorted(snapshot_root.iterdir(), key=lambda item: item.name):
            if not candidate.is_dir() or _is_link(candidate) or candidate.name.startswith("."):
                untouched.append(candidate.name)
                continue
            try:
                verification = verify_snapshot(candidate)
                manifest = _load_manifest(candidate)
                if not verification.get("passed"):
                    raise RecoveryError("Snapshot verification did not pass.")
                verified.append((str(manifest.get("created_at") or ""), candidate.name, candidate))
            except (RecoveryError, OSError, ValueError, TypeError):
                untouched.append(candidate.name)
    verified.sort(key=lambda item: (item[0], item[1]), reverse=True)
    removable = verified[keep:]
    removed: list[str] = []
    if apply:
        for _created_at, name, candidate in removable:
            _remove_snapshot(candidate, snapshot_root)
            removed.append(name)
    return {
        "mode": "apply" if apply else "dry-run",
        "snapshot_root": str(snapshot_root),
        "keep": keep,
        "verified_snapshots": len(verified),
        "retained": [name for _created_at, name, _candidate in verified[:keep]],
        "eligible_for_removal": [name for _created_at, name, _candidate in removable],
        "removed": removed,
        "untouched": sorted(untouched),
    }


def scheduled_run(project_root: Path, *, keep: int = DEFAULT_RETENTION) -> dict[str, Any]:
    project_root = Path(project_root).resolve()
    _destinations, backup_root = configured_destinations(project_root)
    snapshot_root = backup_root / "runtime-snapshots"
    snapshot = create_snapshot(
        configured_file_sets(project_root, "critical"),
        snapshot_root,
        profile="critical",
        consistency="file",
        apply=True,
    )
    retention = prune_snapshots(snapshot_root, keep=keep, apply=True)
    return {"snapshot": snapshot, "retention": retention}


def windows_schedule(
    project_root: Path,
    *,
    schedule_time: str = DEFAULT_SCHEDULE_TIME,
    keep: int = DEFAULT_RETENTION,
    apply: bool = False,
    runner=subprocess.run,
) -> dict[str, Any]:
    try:
        hour_text, minute_text = schedule_time.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RecoveryError("Schedule time must use 24-hour HH:MM format.") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or schedule_time != f"{hour:02d}:{minute:02d}":
        raise RecoveryError("Schedule time must use 24-hour HH:MM format.")
    if keep < 1:
        raise RecoveryError("Snapshot retention must keep at least one verified snapshot.")
    project_root = Path(project_root).resolve()
    python = project_root / ".venv" / "Scripts" / "python.exe"
    script = project_root / "tools" / "runtime_recovery.py"
    if not python.is_file():
        raise RecoveryError(f"RareIQ virtual-environment Python was not found: {python}")
    task_command = f'"{python}" -B "{script}" scheduled-run --keep {keep}'
    command = [
        "schtasks.exe", "/Create", "/TN", WINDOWS_TASK_NAME,
        "/TR", task_command, "/SC", "DAILY", "/ST", schedule_time,
        "/RL", "LIMITED", "/F",
    ]
    report = {
        "mode": "apply" if apply else "dry-run",
        "task_name": WINDOWS_TASK_NAME,
        "schedule": "daily",
        "time": schedule_time,
        "keep": keep,
        "task_command": task_command,
    }
    if not apply:
        return report
    if os.name != "nt":
        raise RecoveryError("Windows Task Scheduler is only available on Windows.")
    completed = runner(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown scheduler error").strip()
        raise RecoveryError(f"Could not install the scheduled task: {detail}")
    return {**report, "installed": True, "scheduler_output": completed.stdout.strip()}


def _restore_file(source: Path, destination: Path) -> None:
    _copy_verified(source, destination)


def restore_snapshot(
    snapshot: Path,
    destinations: dict[str, Path],
    *,
    apply: bool = False,
    rollback_root: Path | None = None,
) -> dict[str, Any]:
    snapshot = Path(snapshot).resolve()
    verification = verify_snapshot(snapshot)
    manifest = _load_manifest(snapshot)
    plan: list[tuple[Path, Path, str, Path]] = []
    for entry in manifest["files"]:
        scope = str(entry["scope"])
        if scope not in destinations:
            raise RecoveryError(f"No restore destination is configured for scope: {scope}")
        root = Path(destinations[scope]).resolve()
        if _is_link(root):
            raise RecoveryError(f"Restore destination cannot be a link or junction: {root}")
        relative = Path(str(entry["relative_path"]))
        source = (snapshot / "data" / scope / relative).resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RecoveryError(f"Restore path escaped its scope: {scope}/{relative.as_posix()}") from exc
        plan.append((source, target, scope, relative))
    report = {
        "mode": "apply" if apply else "dry-run",
        "snapshot_id": manifest["snapshot_id"],
        "profile": manifest["profile"],
        "files": len(plan),
        "existing_targets": sum(target.exists() for _source, target, _scope, _relative in plan),
        "verification": verification,
    }
    if not apply:
        return report
    if rollback_root is None:
        raise RecoveryError("An explicit rollback root is required for restore.")
    rollback = Path(rollback_root).resolve() / (time.strftime("restore-%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    replaced: list[tuple[Path, Path | None]] = []
    try:
        for source, target, scope, relative in plan:
            previous = None
            if target.is_file():
                previous = rollback / "data" / scope / relative
                _copy_verified(target, previous)
            elif target.exists():
                raise RecoveryError(f"Restore target is not a regular file: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            replaced.append((target, previous))
            _restore_file(source, target)
    except Exception:
        for target, previous in reversed(replaced):
            if previous and previous.is_file():
                _restore_file(previous, target)
            else:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        raise
    rollback_manifest = {
        "snapshot_id": manifest["snapshot_id"],
        "restored_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "replaced_files": sum(previous is not None for _target, previous in replaced),
        "created_files": sum(previous is None for _target, previous in replaced),
    }
    rollback.mkdir(parents=True, exist_ok=True)
    (rollback / "restore.json").write_text(json.dumps(rollback_manifest, indent=2), encoding="utf-8")
    return {**report, "restored": True, "rollback_path": str(rollback), **rollback_manifest}


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create, verify, or restore RareIQ runtime recovery snapshots.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--profile", choices=("critical", "media"), default="critical")
    create.add_argument("--destination", type=Path, default=None)
    create.add_argument("--apply", action="store_true")
    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--apply", action="store_true")
    prune = subparsers.add_parser("prune")
    prune.add_argument("--keep", type=int, default=DEFAULT_RETENTION)
    prune.add_argument("--apply", action="store_true")
    scheduled = subparsers.add_parser("scheduled-run")
    scheduled.add_argument("--keep", type=int, default=DEFAULT_RETENTION)
    schedule = subparsers.add_parser("schedule")
    schedule.add_argument("--time", default=DEFAULT_SCHEDULE_TIME)
    schedule.add_argument("--keep", type=int, default=DEFAULT_RETENTION)
    schedule.add_argument("--apply", action="store_true")
    try:
        args = parser.parse_args(argv)
        destinations, backup_root = configured_destinations(project_root)
        if args.command == "create":
            result = create_snapshot(
                configured_file_sets(project_root, args.profile),
                args.destination or (backup_root / "runtime-snapshots"),
                profile=args.profile,
                apply=args.apply,
            )
        elif args.command == "verify":
            result = verify_snapshot(args.snapshot)
        elif args.command == "restore":
            result = restore_snapshot(
                args.snapshot,
                destinations,
                apply=args.apply,
                rollback_root=backup_root / "restore-rollbacks",
            )
        elif args.command == "prune":
            result = prune_snapshots(
                backup_root / "runtime-snapshots",
                keep=args.keep,
                apply=args.apply,
            )
        elif args.command == "scheduled-run":
            result = scheduled_run(project_root, keep=args.keep)
        else:
            result = windows_schedule(
                project_root,
                schedule_time=args.time,
                keep=args.keep,
                apply=args.apply,
            )
    except RecoveryError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
