from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any


BUFFER_SIZE = 4 * 1024 * 1024
MINIMUM_FREE_MARGIN_BYTES = 256 * 1024 * 1024
INDEX_NAME = "events.jsonl"
SETTINGS_NAME = "settings.json"


class MigrationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise MigrationError(f"Symbolic links are not allowed in provenance storage: {path}")
        if path.is_file():
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _source_signature(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _regular_files(root):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _event_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    events: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            event_id = str(event["event_id"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise MigrationError(f"Invalid provenance index line {line_number}: {path}") from exc
        previous = events.get(event_id)
        if previous is not None and previous != event:
            raise MigrationError(f"Conflicting duplicate event ID {event_id}: {path}")
        events[event_id] = event
    return events


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        raise MigrationError(f"No existing destination parent is available: {path}")
    return candidate


def _validate_roots(source: Path, destination: Path) -> tuple[Path, Path]:
    requested_source = Path(source)
    is_junction = getattr(requested_source, "is_junction", lambda: False)
    if requested_source.is_symlink() or is_junction():
        raise MigrationError("The provenance source cannot be a symbolic link or junction.")
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise MigrationError(f"Provenance source does not exist: {source}")
    if source == destination or source in destination.parents or destination in source.parents:
        raise MigrationError("Source and destination must be separate, non-nested directories.")
    return source, destination


def _copy_verified(source: Path, destination: Path) -> tuple[str, bool]:
    source_hash = _sha256(source)
    if destination.is_file():
        if destination.stat().st_size == source.stat().st_size and _sha256(destination) == source_hash:
            return source_hash, False
        raise MigrationError(f"Destination conflict: {destination}")
    if destination.exists():
        raise MigrationError(f"Destination is not a regular file: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.rareiq-migrate-{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as input_handle, temporary.open("xb") as output_handle:
            while chunk := input_handle.read(BUFFER_SIZE):
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        shutil.copystat(source, temporary)
        os.replace(temporary, destination)
        if destination.stat().st_size != source.stat().st_size or _sha256(destination) != source_hash:
            raise MigrationError(f"Post-copy verification failed: {destination}")
        return source_hash, True
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_event_index(path: Path, events: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.rareiq-migrate-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            for event in events.values():
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _settings_destination(source: Path, destination: Path) -> Path:
    normal = destination / SETTINGS_NAME
    if not normal.exists() or _sha256(normal) == _sha256(source):
        return normal
    return destination / f"settings.legacy-{_sha256(source)[:12]}.json"


def migrate(
    source: Path,
    destination: Path,
    *,
    apply: bool = False,
    remove_source: bool = False,
    expected_removable_source: Path | None = None,
) -> dict[str, Any]:
    if remove_source and not apply:
        raise MigrationError("--remove-source requires --apply.")
    source, destination = _validate_roots(Path(source), Path(destination))
    if remove_source and (
        expected_removable_source is None
        or source != Path(expected_removable_source).resolve()
    ):
        raise MigrationError("Source removal is allowed only for the expected legacy provenance directory.")

    initial_signature = _source_signature(source)
    source_files = _regular_files(source)
    source_events = _event_index(source / INDEX_NAME)
    destination_events = _event_index(destination / INDEX_NAME)
    merged_events = dict(destination_events)
    for event_id, event in source_events.items():
        previous = merged_events.get(event_id)
        if previous is not None and previous != event:
            raise MigrationError(f"Destination has conflicting event ID: {event_id}")
        merged_events.setdefault(event_id, event)

    mappings: list[tuple[Path, Path]] = []
    conflicts: list[str] = []
    already_present = 0
    bytes_to_copy = 0
    for source_file in source_files:
        relative = source_file.relative_to(source)
        if relative.as_posix() == INDEX_NAME:
            continue
        destination_file = (
            _settings_destination(source_file, destination)
            if relative.as_posix() == SETTINGS_NAME
            else destination / relative
        )
        resolved_destination = destination_file.resolve()
        try:
            resolved_destination.relative_to(destination)
        except ValueError as exc:
            raise MigrationError(f"Destination path escaped the configured root: {destination_file}") from exc
        if destination_file.is_file():
            if destination_file.stat().st_size == source_file.stat().st_size and _sha256(destination_file) == _sha256(source_file):
                already_present += 1
            else:
                conflicts.append(relative.as_posix())
        elif destination_file.exists():
            conflicts.append(relative.as_posix())
        else:
            bytes_to_copy += source_file.stat().st_size
        mappings.append((source_file, destination_file))
    if conflicts:
        raise MigrationError("Destination file conflicts: " + ", ".join(conflicts[:10]))

    free_bytes = shutil.disk_usage(_nearest_existing_parent(destination)).free
    free_margin = max(MINIMUM_FREE_MARGIN_BYTES, int(bytes_to_copy * 0.05))
    if bytes_to_copy + free_margin > free_bytes:
        raise MigrationError(
            f"Insufficient destination space: need {bytes_to_copy + free_margin} bytes, have {free_bytes}."
        )

    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "source": str(source),
        "destination": str(destination),
        "source_files": len(source_files),
        "source_bytes": sum(path.stat().st_size for path in source_files),
        "source_events": len(source_events),
        "destination_events_before": len(destination_events),
        "destination_events_after": len(merged_events),
        "files_already_present": already_present,
        "files_to_copy": len(mappings) - already_present,
        "bytes_to_copy": bytes_to_copy,
        "free_bytes": free_bytes,
        "verified_files": 0,
        "copied_files": 0,
        "source_removed": False,
    }
    if not apply:
        return report

    destination.mkdir(parents=True, exist_ok=True)
    for source_file, destination_file in mappings:
        _digest, copied = _copy_verified(source_file, destination_file)
        report["verified_files"] += 1
        if copied:
            report["copied_files"] += 1
    _write_event_index(destination / INDEX_NAME, merged_events)
    verified_events = _event_index(destination / INDEX_NAME)
    for event_id, event in source_events.items():
        if verified_events.get(event_id) != event:
            raise MigrationError(f"Event verification failed: {event_id}")
    if _source_signature(source) != initial_signature:
        raise MigrationError("Source changed during migration; source was preserved. Stop RareIQ and rerun.")
    report["verified_events"] = len(source_events)
    report["verification"] = "passed"

    if remove_source:
        shutil.rmtree(source)
        if source.exists():
            raise MigrationError(f"Verified source removal failed: {source}")
        report["source_removed"] = True
    return report


def _configured_destination(project_root: Path) -> Path:
    config_path = project_root / "storage_config.json"
    if not config_path.is_file():
        config_path = project_root / "storage_config.example.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        raw = payload.get("provenance_path")
        if not raw:
            raw = str(Path(str(payload["capture_path"])) / "provenance")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MigrationError(f"Unable to resolve provenance storage from {config_path}") from exc
    expanded = Path(os.path.expandvars(os.path.expanduser(str(raw))))
    return (expanded if expanded.is_absolute() else config_path.parent / expanded).resolve()


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    default_source = project_root / "rareiq" / "data" / "provenance"
    parser = argparse.ArgumentParser(description="Safely migrate legacy RareIQ provenance media.")
    parser.add_argument("--source", type=Path, default=default_source)
    parser.add_argument("--destination", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="Copy and verify data. Default is dry-run.")
    parser.add_argument(
        "--remove-source",
        action="store_true",
        help="After successful verification, remove only the expected legacy source.",
    )
    args = parser.parse_args(argv)
    try:
        report = migrate(
            args.source,
            args.destination or _configured_destination(project_root),
            apply=args.apply,
            remove_source=args.remove_source,
            expected_removable_source=default_source,
        )
    except MigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
