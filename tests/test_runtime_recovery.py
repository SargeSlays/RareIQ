from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.runtime_recovery as recovery
from tools.runtime_recovery import (
    FileSet,
    RecoveryError,
    configured_file_sets,
    create_snapshot,
    prune_snapshots,
    restore_snapshot,
    verify_snapshot,
    windows_schedule,
)


def _sets(root: Path, names=("state.json",)) -> dict[str, FileSet]:
    source = root / "database"
    source.mkdir(parents=True)
    files = []
    for name in names:
        path = source / name
        path.write_text(f"original-{name}", encoding="utf-8")
        files.append(path)
    return {"database": FileSet(source, tuple(files))}


def test_snapshot_dry_run_is_non_mutating(tmp_path):
    file_sets = _sets(tmp_path / "source")
    destination = tmp_path / "backups"

    report = create_snapshot(file_sets, destination)

    assert report["mode"] == "dry-run"
    assert report["files"] == 1
    assert report["secrets_included"] is False
    assert destination.exists() is False


def test_snapshot_is_atomic_manifest_backed_and_verified(tmp_path):
    file_sets = _sets(tmp_path / "source", ("collection.json", "inventory.json"))

    report = create_snapshot(file_sets, tmp_path / "backups", apply=True)
    snapshot = Path(report["snapshot_path"])

    assert report["verification"] == {"passed": True, "files": 2, "bytes": 47}
    assert snapshot.is_dir()
    assert not list(snapshot.parent.glob("*.partial"))
    assert verify_snapshot(snapshot)["passed"] is True
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["secrets_included"] is False
    assert {entry["relative_path"] for entry in manifest["files"]} == {
        "collection.json", "inventory.json"
    }


def test_snapshot_tampering_is_detected(tmp_path):
    report = create_snapshot(_sets(tmp_path / "source"), tmp_path / "backups", apply=True)
    snapshot = Path(report["snapshot_path"])
    (snapshot / "data/database/state.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(RecoveryError, match="checksum mismatch"):
        verify_snapshot(snapshot)


def test_runtime_change_during_snapshot_removes_partial_output(tmp_path, monkeypatch):
    file_sets = _sets(tmp_path / "source")
    source = file_sets["database"].files[0]
    original_copy = recovery._copy_verified

    def copy_then_change(source_path, destination_path):
        digest = original_copy(source_path, destination_path)
        source.write_text("changed-during-copy", encoding="utf-8")
        return digest

    monkeypatch.setattr(recovery, "_copy_verified", copy_then_change)
    with pytest.raises(RecoveryError, match="Runtime state changed"):
        create_snapshot(file_sets, tmp_path / "backups", apply=True)

    assert not list((tmp_path / "backups").glob("*"))


def test_restore_dry_run_then_apply_retains_rollback_copy(tmp_path):
    report = create_snapshot(_sets(tmp_path / "source"), tmp_path / "backups", apply=True)
    snapshot = Path(report["snapshot_path"])
    target_root = tmp_path / "live"
    target = target_root / "state.json"
    target_root.mkdir()
    target.write_text("new-live-state", encoding="utf-8")

    dry_run = restore_snapshot(snapshot, {"database": target_root})
    assert dry_run["mode"] == "dry-run"
    assert target.read_text(encoding="utf-8") == "new-live-state"

    restored = restore_snapshot(
        snapshot,
        {"database": target_root},
        apply=True,
        rollback_root=tmp_path / "rollbacks",
    )
    rollback = Path(restored["rollback_path"])
    assert restored["restored"] is True
    assert restored["replaced_files"] == 1
    assert target.read_text(encoding="utf-8") == "original-state.json"
    assert (rollback / "data/database/state.json").read_text(encoding="utf-8") == "new-live-state"


def test_restore_failure_automatically_restores_every_original(tmp_path, monkeypatch):
    report = create_snapshot(
        _sets(tmp_path / "source", ("a.json", "b.json")),
        tmp_path / "backups",
        apply=True,
    )
    snapshot = Path(report["snapshot_path"])
    target_root = tmp_path / "live"
    target_root.mkdir()
    (target_root / "a.json").write_text("live-a", encoding="utf-8")
    (target_root / "b.json").write_text("live-b", encoding="utf-8")
    original_restore = recovery._restore_file

    def fail_second_snapshot_file(source, destination):
        if source == snapshot / "data/database/b.json":
            raise OSError("simulated restore failure")
        original_restore(source, destination)

    monkeypatch.setattr(recovery, "_restore_file", fail_second_snapshot_file)
    with pytest.raises(OSError, match="simulated restore failure"):
        restore_snapshot(
            snapshot,
            {"database": target_root},
            apply=True,
            rollback_root=tmp_path / "rollbacks",
        )

    assert (target_root / "a.json").read_text(encoding="utf-8") == "live-a"
    assert (target_root / "b.json").read_text(encoding="utf-8") == "live-b"


def test_manifest_path_escape_is_rejected_even_with_updated_digest(tmp_path):
    report = create_snapshot(_sets(tmp_path / "source"), tmp_path / "backups", apply=True)
    snapshot = Path(report["snapshot_path"])
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "../../outside.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (snapshot / "manifest.sha256").write_text(recovery._sha256(manifest_path) + "\n", encoding="ascii")

    with pytest.raises(RecoveryError, match="escapes"):
        verify_snapshot(snapshot)


def test_configured_profiles_exclude_secrets_and_keep_media_opt_in(tmp_path):
    project = tmp_path / "RareIQ"
    paths = {
        "database_root": tmp_path / "runtime/database",
        "config_path": tmp_path / "runtime/config",
        "cache_path": tmp_path / "runtime/cache",
        "log_path": tmp_path / "runtime/logs",
        "capture_path": tmp_path / "runtime/captures",
        "provenance_path": tmp_path / "runtime/captures/provenance",
        "replay_path": tmp_path / "runtime/captures/replays",
        "recording_path": tmp_path / "runtime/captures/recordings",
        "backup_path": tmp_path / "runtime/backups",
    }
    project.mkdir()
    (project / "storage_config.json").write_text(
        json.dumps({key: str(value) for key, value in paths.items()}), encoding="utf-8"
    )
    (project / "rareiq/data").mkdir(parents=True)
    (project / "rareiq/data/artwork_index.json").write_text("{}", encoding="utf-8")
    (project / "rareiq_secrets.json").write_text('{"secret":"never-copy"}', encoding="utf-8")
    for root in paths.values():
        root.mkdir(parents=True, exist_ok=True)
    (paths["database_root"] / "collection.json").write_text("{}", encoding="utf-8")
    event_dir = paths["provenance_path"] / "2026/08/23/event"
    event_dir.mkdir(parents=True)
    (event_dir / "event.json").write_text("{}", encoding="utf-8")
    (event_dir / "full-frame.png").write_bytes(b"png")

    critical = configured_file_sets(project, "critical")
    media = configured_file_sets(project, "media")

    assert all("secrets" not in str(path) for item in critical.values() for path in item.files)
    assert event_dir / "event.json" in critical["provenance_metadata"].files
    assert event_dir / "full-frame.png" not in critical["provenance_metadata"].files
    assert event_dir / "full-frame.png" in media["provenance_media"].files


def _set_snapshot_time(snapshot: Path, created_at: str) -> None:
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = created_at
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (snapshot / "manifest.sha256").write_text(recovery._sha256(manifest_path) + "\n", encoding="ascii")


def test_prune_removes_only_old_fully_verified_snapshots(tmp_path):
    snapshot_root = tmp_path / "backups"
    snapshots = []
    for index in range(3):
        report = create_snapshot(_sets(tmp_path / f"source-{index}"), snapshot_root, apply=True)
        snapshot = Path(report["snapshot_path"])
        _set_snapshot_time(snapshot, f"2026-08-{20 + index:02d}T03:00:00Z")
        snapshots.append(snapshot)
    unknown = snapshot_root / "operator-notes"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("leave me alone", encoding="utf-8")
    tampered = snapshot_root / "tampered-snapshot"
    tampered.mkdir()
    (tampered / "manifest.json").write_text("{}", encoding="utf-8")
    (tampered / "manifest.sha256").write_text("0" * 64, encoding="ascii")

    dry_run = prune_snapshots(snapshot_root, keep=2)
    assert all(snapshot.exists() for snapshot in snapshots)
    assert dry_run["eligible_for_removal"] == [snapshots[0].name]

    applied = prune_snapshots(snapshot_root, keep=2, apply=True)
    assert applied["removed"] == [snapshots[0].name]
    assert snapshots[0].exists() is False
    assert snapshots[1].exists() and snapshots[2].exists()
    assert unknown.exists() and tampered.exists()
    assert {unknown.name, tampered.name}.issubset(applied["untouched"])


def test_scheduled_run_uses_online_file_consistency_and_ignores_later_new_files(tmp_path, monkeypatch):
    project = tmp_path / "RareIQ"
    project.mkdir()
    roots = {
        "database_root": tmp_path / "runtime/database",
        "config_path": tmp_path / "runtime/config",
        "cache_path": tmp_path / "runtime/cache",
        "log_path": tmp_path / "runtime/logs",
        "capture_path": tmp_path / "runtime/captures",
        "backup_path": tmp_path / "runtime/backups",
    }
    (project / "storage_config.json").write_text(
        json.dumps({key: str(value) for key, value in roots.items()}), encoding="utf-8"
    )
    (project / "rareiq/data").mkdir(parents=True)
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    (roots["database_root"] / "state.json").write_text("{}", encoding="utf-8")
    original_create = recovery.create_snapshot

    def create_then_add(*args, **kwargs):
        result = original_create(*args, **kwargs)
        (roots["database_root"] / "new-state.json").write_text("{}", encoding="utf-8")
        return result

    monkeypatch.setattr(recovery, "create_snapshot", create_then_add)
    result = recovery.scheduled_run(project)

    snapshot_root = roots["backup_path"] / "runtime-snapshots"
    snapshot = Path(result["snapshot"]["snapshot_path"])
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert result["snapshot"]["consistency"] == "file"
    assert manifest["consistency"] == "file"
    assert verify_snapshot(snapshot)["passed"] is True
    assert not any(entry["relative_path"] == "new-state.json" for entry in manifest["files"])
    assert list(snapshot_root.glob("*")) == [snapshot]


def test_file_consistency_snapshot_tolerates_independent_source_updates(tmp_path, monkeypatch):
    file_sets = _sets(tmp_path / "source", ("a.json", "b.json"))
    source = file_sets["database"].files[0]
    original_copy = recovery._copy_verified

    def copy_then_update(source_path, destination_path):
        digest = original_copy(source_path, destination_path)
        if source_path == source:
            source.write_text("newer-independent-state", encoding="utf-8")
        return digest

    monkeypatch.setattr(recovery, "_copy_verified", copy_then_update)
    report = create_snapshot(
        file_sets,
        tmp_path / "backups",
        consistency="file",
        apply=True,
    )

    assert report["verification"]["passed"] is True
    manifest = json.loads((Path(report["snapshot_path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["consistency"] == "file"


def test_windows_schedule_is_dry_run_first_and_uses_no_shell(tmp_path):
    project = tmp_path / "RareIQ"
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    (project / "tools").mkdir()
    (project / "tools/runtime_recovery.py").write_text("", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="SUCCESS", stderr="")

    dry_run = windows_schedule(project, schedule_time="03:00", keep=14, runner=runner)
    assert dry_run["mode"] == "dry-run"
    assert calls == []

    applied = windows_schedule(project, schedule_time="03:00", keep=14, apply=True, runner=runner)
    command, kwargs = calls[0]
    assert applied["installed"] is True
    assert command[0] == "schtasks.exe"
    assert "/RL" in command and "LIMITED" in command
    assert kwargs == {"check": False, "capture_output": True, "text": True}
    assert "shell" not in kwargs


@pytest.mark.parametrize("schedule_time", ["3:00", "24:00", "03:60", "noon"])
def test_windows_schedule_rejects_invalid_time(tmp_path, schedule_time):
    project = tmp_path / "RareIQ"
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    with pytest.raises(RecoveryError, match="HH:MM"):
        windows_schedule(project, schedule_time=schedule_time)
