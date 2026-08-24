from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.migrate_provenance_storage as migration
from tools.migrate_provenance_storage import (
    MigrationError,
    _configured_destination,
    migrate,
)


def _event(event_id: str, relative_path: str) -> dict:
    return {
        "event_id": event_id,
        "event_version": 1,
        "event_type": "screenshot",
        "created_at": "2026-08-23T12:00:00Z",
        "assets": [
            {
                "asset_id": f"{event_id}-full_frame",
                "type": "full_frame",
                "relative_path": relative_path,
                "sha256": "fixture",
                "bytes": 8,
            }
        ],
    }


def _write_index(root: Path, *events: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )


def _source(root: Path, event_id: str = "legacy-event") -> tuple[dict, Path]:
    relative = Path("2026/08/23") / event_id / "full-frame.png"
    asset = root / relative
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"png-data")
    event = _event(event_id, relative.as_posix())
    _write_index(root, event)
    (root / "settings.json").write_text('{"enabled": false}', encoding="utf-8")
    return event, asset


def test_dry_run_reports_without_creating_destination(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    _source(source)

    report = migrate(source, destination)

    assert report["mode"] == "dry-run"
    assert report["source_events"] == 1
    assert report["files_to_copy"] == 2
    assert destination.exists() is False
    assert source.is_dir()


def test_apply_merges_events_preserves_settings_and_verifies_assets(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    source_event, source_asset = _source(source)
    destination_event = _event("current-event", "2026/08/24/current-event/full-frame.png")
    destination_asset = destination / destination_event["assets"][0]["relative_path"]
    destination_asset.parent.mkdir(parents=True, exist_ok=True)
    destination_asset.write_bytes(b"new-data")
    _write_index(destination, destination_event)
    (destination / "settings.json").write_text('{"enabled": true}', encoding="utf-8")

    report = migrate(source, destination, apply=True)

    assert report["verification"] == "passed"
    assert report["copied_files"] == 2
    assert report["verified_events"] == 1
    assert report["destination_events_after"] == 2
    assert source.is_dir()
    assert (destination / source_event["assets"][0]["relative_path"]).read_bytes() == source_asset.read_bytes()
    assert json.loads((destination / "settings.json").read_text(encoding="utf-8"))["enabled"] is True
    legacy_settings = list(destination.glob("settings.legacy-*.json"))
    assert len(legacy_settings) == 1
    assert json.loads(legacy_settings[0].read_text(encoding="utf-8"))["enabled"] is False
    merged_ids = {
        json.loads(line)["event_id"]
        for line in (destination / "events.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert merged_ids == {"legacy-event", "current-event"}


def test_apply_is_resumable_and_reuses_verified_files(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    _source(source)
    first = migrate(source, destination, apply=True)

    second = migrate(source, destination, apply=True)

    assert first["copied_files"] == 2
    assert second["copied_files"] == 0
    assert second["files_already_present"] == 2
    assert second["verification"] == "passed"


def test_conflict_aborts_before_copying_any_new_file(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    event, _asset = _source(source)
    conflict = destination / event["assets"][0]["relative_path"]
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_bytes(b"different")

    with pytest.raises(MigrationError, match="Destination file conflicts"):
        migrate(source, destination, apply=True)

    assert conflict.read_bytes() == b"different"
    assert not list(destination.glob("settings*.json"))


def test_verified_copy_can_remove_only_the_expected_source(tmp_path):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    _source(source)

    with pytest.raises(MigrationError, match="expected legacy"):
        migrate(source, destination, apply=True, remove_source=True)
    with pytest.raises(MigrationError, match="expected legacy"):
        migrate(
            source,
            destination,
            apply=True,
            remove_source=True,
            expected_removable_source=tmp_path / "different-source",
        )
    assert source.is_dir()

    report = migrate(
        source,
        destination,
        apply=True,
        remove_source=True,
        expected_removable_source=source,
    )
    assert report["source_removed"] is True
    assert source.exists() is False
    assert (destination / "events.jsonl").is_file()


def test_source_change_during_copy_preserves_source_for_safe_rerun(tmp_path, monkeypatch):
    source = tmp_path / "legacy"
    destination = tmp_path / "external" / "provenance"
    _source(source)
    original_copy = migration._copy_verified
    changed = False

    def copy_then_change(source_file, destination_file):
        nonlocal changed
        result = original_copy(source_file, destination_file)
        if not changed:
            changed = True
            (source / "arrived-during-copy.txt").write_text("new event", encoding="utf-8")
        return result

    monkeypatch.setattr(migration, "_copy_verified", copy_then_change)
    with pytest.raises(MigrationError, match="Source changed during migration"):
        migrate(source, destination, apply=True)

    assert source.is_dir()
    assert (source / "arrived-during-copy.txt").is_file()
    assert destination.is_dir()


def test_malformed_event_index_and_nested_paths_are_rejected(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "events.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="Invalid provenance index"):
        migrate(source, tmp_path / "destination")
    with pytest.raises(MigrationError, match="non-nested"):
        migrate(source, source / "destination")


def test_configured_destination_uses_explicit_or_capture_fallback(tmp_path):
    (tmp_path / "storage_config.json").write_text(
        json.dumps({"capture_path": "runtime/captures", "provenance_path": "F:/RareIQ/evidence"}),
        encoding="utf-8",
    )
    assert _configured_destination(tmp_path) == Path("F:/RareIQ/evidence").resolve()

    (tmp_path / "storage_config.json").write_text(
        json.dumps({"capture_path": "runtime/captures"}), encoding="utf-8"
    )
    assert _configured_destination(tmp_path) == (tmp_path / "runtime/captures/provenance").resolve()
