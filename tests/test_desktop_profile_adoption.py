"""Synthetic file adoption only; never inspect a workstation profile or runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import desktop_profile_adoption as adoption


@pytest.fixture
def fixture(tmp_path):
    source, profile, backup = tmp_path / "source", tmp_path / "profile", tmp_path / "private-backup"
    source.mkdir()
    (source / "app.py").write_text("# synthetic project marker", encoding="utf-8")
    (profile / "browser").mkdir(parents=True)
    (profile / "destinations.json").write_bytes(b"synthetic-outer-native-state")
    (profile / "guest-ingress.json").write_bytes(b"synthetic-outer-private-ingress")
    paths = {key: "data/" + key for key in adoption.REQUIRED_STORAGE_PATHS}
    paths["capture_path"] = "../existing-captures"
    (source / "storage_config.json").write_text(json.dumps(paths), encoding="utf-8")
    secrets = b'{ "private_value": "synthetic-secret-retained-exactly" }\n'
    (source / "rareiq_secrets.json").write_bytes(secrets)
    (source / "obs_settings.json").write_bytes(b'{"host":"synthetic-local-obs"}\n')
    return SimpleNamespace(source=source, profile=profile, target=profile / "backend", backup=backup,
                           original={p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}, secrets=secrets)


def plan(f, **kwargs):
    return adoption.plan_adoption(f.source, f.target, f.backup, **kwargs)


def apply(p):
    return adoption.apply_adoption(p, reviewed_plan_id=p.plan_id, backend_stopped=True)


def test_plan_is_read_only_redacted_and_path_normalization_preserves_existing_data(fixture):
    f = fixture
    p = plan(f)
    report = p.report()
    assert not f.target.exists() and not f.backup.exists()
    assert report["counts"]["create"] == 3
    assert str(f.source) not in str(report) and "synthetic-secret" not in str(report)
    assert str(f.source) not in repr(p) and "synthetic-secret" not in repr(p)
    assert {e["name"] for e in report["files"]} == set(adoption.LOOSE_CONFIGURATION_FILES)
    assert apply(p)["ok"]
    configured = json.loads((f.target / "storage_config.json").read_text(encoding="utf-8"))
    assert configured["capture_path"] == str((f.source.parent / "existing-captures").resolve())
    assert configured["config_path"] == str(f.source / "data/config_path")
    assert (f.target / "rareiq_secrets.json").read_bytes() == f.secrets
    assert {p.name: p.read_bytes() for p in f.source.iterdir() if p.is_file()} == f.original
    assert (f.profile / "destinations.json").read_bytes() == b"synthetic-outer-native-state"
    assert (f.profile / "guest-ingress.json").read_bytes() == b"synthetic-outer-private-ingress"


def test_original_plan_and_cli_resume_are_idempotent_without_replacing_target_bytes(fixture):
    f = fixture
    p = plan(f)
    assert apply(p)["ok"]
    before = (f.target / "rareiq_secrets.json").stat().st_mtime_ns
    assert apply(p)["ok"]
    resumed = adoption.resume_plan(f.source, f.target, f.backup, p.plan_id)
    assert apply(resumed)["ok"]
    assert (f.target / "rareiq_secrets.json").stat().st_mtime_ns == before
    assert plan(f).report()["counts"]["unchanged"] == 3


def test_conflicts_need_a_new_concretely_reviewed_replace_plan_and_all_backups_precede_writes(fixture, monkeypatch):
    f = fixture
    f.target.mkdir()
    old = {"storage_config.json": b'{"old":"settings"}', "rareiq_secrets.json": b'{"old":"synthetic-private"}'}
    for name, data in old.items():
        (f.target / name).write_bytes(data)
    p = plan(f)
    assert p.report()["counts"]["conflict"] == 2
    with pytest.raises(adoption.AdoptionError, match="target_conflict_requires_review"):
        apply(p)
    assert not f.backup.exists()
    p = plan(f, replace_existing=True)
    original = adoption._atomic_write
    def checked_write(path, data, **kwargs):
        if f.target in path.parents:
            for name, expected in old.items():
                assert (f.backup / p.plan_id / "before" / name).read_bytes() == expected
        original(path, data, **kwargs)
    monkeypatch.setattr(adoption, "_atomic_write", checked_write)
    assert apply(p)["ok"]
    assert (f.backup / p.plan_id / "before/rareiq_secrets.json").read_bytes() == old["rareiq_secrets.json"]


def test_partial_failure_retains_backups_and_can_resume_after_a_process_restart(fixture, monkeypatch):
    f = fixture
    f.target.mkdir()
    old = b'{"before":"synthetic-original"}'
    (f.target / "obs_settings.json").write_bytes(old)
    p = plan(f, replace_existing=True)
    original = adoption._atomic_write
    def failed_write(path, data, **kwargs):
        if path == f.target / "obs_settings.json":
            raise OSError("private filename must not leak")
        original(path, data, **kwargs)
    monkeypatch.setattr(adoption, "_atomic_write", failed_write)
    result = apply(p)
    assert not result["ok"] and result["state"] == "partial" and result["adopted_count"] == 2
    assert "private filename" not in str(result)
    assert (f.backup / p.plan_id / "before/obs_settings.json").read_bytes() == old
    assert (f.target / "obs_settings.json").read_bytes() == old
    monkeypatch.setattr(adoption, "_atomic_write", original)
    resumed = adoption.resume_plan(f.source, f.target, f.backup, p.plan_id, replace_existing=True)
    assert apply(resumed)["ok"]
    assert (f.target / "obs_settings.json").read_bytes() == f.original["obs_settings.json"]


@pytest.mark.parametrize("side", ["source", "target"])
def test_changes_after_review_are_rejected_before_creating_backups(fixture, side):
    f = fixture
    p = plan(f)
    root = f.source if side == "source" else f.target
    root.mkdir(exist_ok=True)
    (root / "obs_settings.json").write_bytes(b'{"changed":"synthetic"}')
    with pytest.raises(adoption.AdoptionError, match=side + "_changed_since_plan"):
        apply(p)
    assert not f.backup.exists()


def test_target_change_during_backup_is_preserved_and_prevents_any_configuration_replacement(fixture, monkeypatch):
    f = fixture
    f.target.mkdir()
    old = b'{"old":"synthetic"}'
    (f.target / "obs_settings.json").write_bytes(old)
    p = plan(f, replace_existing=True)
    original = adoption._atomic_write
    changed = False
    def changed_write(path, data, **kwargs):
        nonlocal changed
        original(path, data, **kwargs)
        if path.name == "manifest.json" and not changed:
            changed = True
            (f.target / "obs_settings.json").write_bytes(b'{"concurrent":"synthetic-preserve"}')
    monkeypatch.setattr(adoption, "_atomic_write", changed_write)
    result = apply(p)
    assert not result["ok"] and result["adopted_count"] == 0
    assert not (f.target / "storage_config.json").exists()
    assert (f.target / "obs_settings.json").read_bytes() == b'{"concurrent":"synthetic-preserve"}'


def test_linked_source_and_reparse_targets_are_rejected(fixture, monkeypatch):
    f = fixture
    original = Path.lstat
    def marked_link(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == f.source / "obs_settings.json":
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value
    monkeypatch.setattr(Path, "lstat", marked_link)
    with pytest.raises(adoption.AdoptionError, match="linked_path_rejected"):
        plan(f)
    assert not f.target.exists()


def test_root_containment_profile_marker_resource_and_storage_resource_guards(fixture):
    f = fixture
    with pytest.raises(adoption.AdoptionError, match="backup_must_be_outside_desktop_profile"):
        adoption.plan_adoption(f.source, f.target, f.profile / "backup")
    nested = f.source / "nested-profile"
    (nested / "browser").mkdir(parents=True)
    with pytest.raises(adoption.AdoptionError, match="overlapping_adoption_roots"):
        adoption.plan_adoption(f.source, nested / "backend", f.backup)
    outside = f.source.parent / "unknown-profile"
    outside.mkdir()
    with pytest.raises(adoption.AdoptionError, match="existing_desktop_profile_required"):
        adoption.plan_adoption(f.source, outside / "backend", f.backup)
    resource_profile = f.source.parent / "resources/profile"
    (resource_profile / "browser").mkdir(parents=True)
    with pytest.raises(adoption.AdoptionError, match="bundle_resources_rejected"):
        adoption.plan_adoption(f.source, resource_profile / "backend", f.backup)
    configured = json.loads((f.source / "storage_config.json").read_text())
    configured["image_path"] = str(f.source.parent / "resources/images")
    (f.source / "storage_config.json").write_text(json.dumps(configured))
    with pytest.raises(adoption.AdoptionError, match="storage_inside_bundle_resources"):
        plan(f)


def test_no_process_receipts_runtime_state_database_media_or_catalog_is_copied(fixture):
    f = fixture
    for name in ["server-control.json", "backend-owner.json", "production_session.json", "guest-ingress.json",
                 "config/platform_accounts.enc.json", "config/greenroom.sqlite3", "captures/private.bin",
                 "rareiq/data/set_catalog.json", "rareiq/data/temporal_multi_card_history.json"]:
        path = f.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"must_not_copy":"synthetic-private"}')
    p = plan(f)
    assert apply(p)["ok"]
    assert sorted(path.relative_to(f.target).as_posix() for path in f.target.rglob("*") if path.is_file()) == ["obs_settings.json", "rareiq_secrets.json", "storage_config.json"]


def test_explicit_idle_and_review_are_required_and_manifest_tampering_fails_closed(fixture):
    f = fixture
    p = plan(f)
    with pytest.raises(adoption.AdoptionError, match="reviewed_plan_required"):
        adoption.apply_adoption(p, reviewed_plan_id="wrong", backend_stopped=True)
    with pytest.raises(adoption.AdoptionError, match="backend_must_be_stopped"):
        adoption.apply_adoption(p, reviewed_plan_id=p.plan_id)
    assert not f.backup.exists()
    assert apply(p)["ok"]
    manifest = f.backup / p.plan_id / "manifest.json"
    data = json.loads(manifest.read_text())
    data["files"][0]["name"] = "../outside.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(adoption.AdoptionError, match="adoption_manifest_conflict"):
        adoption.resume_plan(f.source, f.target, f.backup, p.plan_id)


def test_reports_cli_errors_and_private_backups_never_print_paths_or_values(fixture, capsys):
    f = fixture
    args = ["--source-project", str(f.source), "--target-backend", str(f.target), "--backup-root", str(f.backup)]
    assert adoption.main(["plan", *args]) == 0
    output = capsys.readouterr().out
    assert str(f.source) not in output and "synthetic-secret" not in output
    assert adoption.main(["apply", *args]) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "reviewed_plan_required"
    p = plan(f)
    assert adoption.main(["apply", *args, "--backend-stopped", "--reviewed-plan-id", p.plan_id]) == 0
    assert "synthetic-secret" not in capsys.readouterr().out
    if os.name != "nt":
        assert (f.target / "rareiq_secrets.json").stat().st_mode & 0o777 == 0o600
        assert (f.backup / p.plan_id / "manifest.json").stat().st_mode & 0o777 == 0o600


def test_storage_path_contract_covers_current_storage_manager(fixture):
    from rareiq.core.storage import StorageManager
    assert set(adoption.REQUIRED_STORAGE_PATHS) == set(StorageManager.REQUIRED_PATHS)
    assert set(adoption.OPTIONAL_STORAGE_PATHS) == set(StorageManager.OPTIONAL_PATH_DEFAULTS)


def write_file(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def card_data(f, *, catalog=True):
    reference = "rareiq/data/reference_cards/private-card-name.png"
    write_file(f.source, reference, b"synthetic-reference-image")
    write_file(f.source, "rareiq/data/reference_cards/private-card-name.json", b'{ "private_label": "kept" }\n')
    write_file(f.source, "rareiq/data/pack_transition_backups/private-learning-backup.json", b'{"disabled_scopes":["synthetic"]}')
    raw = b'{ "preserve_format": true }\n'
    for name in adoption.CARD_CONFIGURATION_FILES:
        write_file(f.source, name, raw)
    write_file(f.source, "rareiq/data/artwork_index.json", json.dumps({"records": [{"image_path": str(f.source / reference), "other": "untouched"}], "private_metadata": 17}).encode())
    images = ["catalog_master/pokipair/private-corpus-1.png", "catalog_master/pokipair/private-corpus-2.webp"] if catalog else []
    for name in images:
        write_file(f.source, name, b"synthetic-catalog-image:" + name.encode())
    write_file(f.source, adoption.CATALOG_CORPUS, json.dumps({"records": [{"reference_image": name, "image_path": name} for name in images]}).encode())
    return reference, images


def test_explicit_card_scope_preserves_known_json_and_rebases_only_index_image_paths(fixture):
    f = fixture
    reference, _ = card_data(f, catalog=False)
    assert not plan(f).include_card_data
    p = plan(f, include_card_data=True)
    report = p.report()
    assert report["rebased_reference_count"] == 1 and report["review"] == []
    assert "private-card-name" not in str(report) and "private-learning-backup" not in str(report)
    result = apply(p)
    assert result["ok"] and "private-card-name" not in str(result)
    index = json.loads((f.target / "rareiq/data/artwork_index.json").read_text())
    assert index == {"records": [{"image_path": str(f.target / reference), "other": "untouched"}], "private_metadata": 17}
    for name in adoption.CARD_CONFIGURATION_FILES:
        if name != "rareiq/data/artwork_index.json":
            assert (f.target / name).read_bytes() == (f.source / name).read_bytes()
    assert (f.target / reference).read_bytes() == (f.source / reference).read_bytes()
    assert apply(adoption.resume_plan(f.source, f.target, f.backup, p.plan_id, include_card_data=True))["ok"]


def test_catalog_closure_is_explicit_bounded_streamed_and_public_names_are_redacted(fixture, monkeypatch):
    f = fixture
    _, images = card_data(f)
    p = plan(f, include_card_data=True)
    assert p.report()["review"] == [{"reason": "catalog_reference_images_not_selected_requires_review", "count": 2}]
    with pytest.raises(adoption.AdoptionError, match="card_reference_review_required"):
        apply(p)
    original = adoption._read
    def no_image_buffer(path, **kwargs):
        assert Path(path).suffix.lower() not in adoption.IMAGE_SUFFIXES
        return original(path, **kwargs)
    monkeypatch.setattr(adoption, "_read", no_image_buffer)
    p = plan(f, include_card_data=True, include_catalog_reference_images=True)
    assert all(e.data is None and e.before is None and e.streamed for e in p._entries if e.category == "catalog_reference_images")
    report = p.report()
    inventory = next(item for item in report["card_inventory"] if item["category"] == "catalog_reference_images")
    assert inventory["files"] == 2 and inventory["bytes"] > 0
    assert "private-corpus" not in str(report)
    assert apply(p)["ok"]
    for name in images:
        assert (f.target / name).read_bytes() == (f.source / name).read_bytes()
    resumed = adoption.resume_plan(f.source, f.target, f.backup, p.plan_id, include_card_data=True, include_catalog_reference_images=True)
    assert apply(resumed)["ok"]
    assert "private-corpus" in (f.backup / p.plan_id / "manifest.json").read_text()


def test_card_json_has_its_own_sixteen_megabyte_bound(fixture):
    f = fixture
    card_data(f, catalog=False)
    large = b'{"records":[],"padding":"' + b"x" * (5 * 1024 * 1024) + b'"}'
    write_file(f.source, adoption.CATALOG_CORPUS, large)
    assert apply(plan(f, include_card_data=True))["ok"]
    assert (f.target / adoption.CATALOG_CORPUS).read_bytes() == large
    write_file(f.source, adoption.CATALOG_CORPUS, b" " * (adoption.MAX_CARD_FILE_BYTES + 1))
    with pytest.raises(adoption.AdoptionError, match="bounded_regular_file_required"):
        plan(f, include_card_data=True)


@pytest.mark.parametrize("change", ["add", "remove", "target_extra"])
def test_reference_inventory_changes_are_rejected_before_any_backup(fixture, change):
    f = fixture
    reference, _ = card_data(f, catalog=False)
    p = plan(f, include_card_data=True)
    if change == "remove":
        (f.source / reference).unlink()
    elif change == "add":
        write_file(f.source, "rareiq/data/reference_cards/unreviewed.png", b"new")
    else:
        write_file(f.target, "rareiq/data/reference_cards/unreviewed.png", b"new")
    with pytest.raises(adoption.AdoptionError, match="card_inventory_changed_since_plan"):
        apply(p)
    assert not f.backup.exists()


def test_reference_scope_limits_and_exact_catalog_path_containment(fixture):
    f = fixture
    _, images = card_data(f)
    with pytest.raises(adoption.AdoptionError, match="card_reference_scope_limit_exceeded"):
        plan(f, include_card_data=True, max_card_files=1)
    with pytest.raises(adoption.AdoptionError, match="card_reference_scope_limit_exceeded"):
        plan(f, include_card_data=True, max_card_bytes=1)
    with pytest.raises(adoption.AdoptionError, match="catalog_reference_scope_limit_exceeded"):
        plan(f, include_card_data=True, include_catalog_reference_images=True, max_catalog_reference_files=1)
    with pytest.raises(adoption.AdoptionError, match="catalog_reference_scope_limit_exceeded"):
        plan(f, include_card_data=True, include_catalog_reference_images=True, max_catalog_reference_bytes=1)
    for bad in ["catalog_master/../outside.png", str(f.source.parent / "outside.png"), "catalog_master/private.txt"]:
        write_file(f.source, adoption.CATALOG_CORPUS, json.dumps({"records": [{"reference_image": bad}]}).encode())
        with pytest.raises(adoption.AdoptionError, match="catalog_reference_path_requires_review"):
            plan(f, include_card_data=True, include_catalog_reference_images=True)
    assert not f.backup.exists() and all((f.source / name).exists() for name in images)


def test_existing_external_index_references_need_explicit_ack_and_missing_ones_still_block(fixture):
    f = fixture
    card_data(f, catalog=False)
    external = write_file(f.source.parent, "external-private.png", b"existing-custom-image")
    write_file(f.source, "rareiq/data/artwork_index.json", json.dumps([{"image_path": str(external), "learned": 42}]).encode())
    p = plan(f, include_card_data=True)
    assert p.report()["review"] == [{"reason": "artwork_index_external_reference_requires_review", "count": 1}]
    with pytest.raises(adoption.AdoptionError, match="card_reference_review_required"):
        apply(p)
    acknowledged = plan(f, include_card_data=True, acknowledge_external_references=True)
    assert p.plan_id != acknowledged.plan_id and apply(acknowledged)["ok"]
    assert (f.target / "rareiq/data/artwork_index.json").read_bytes() == (f.source / "rareiq/data/artwork_index.json").read_bytes()
    external.unlink()
    p = plan(f, include_card_data=True, acknowledge_external_references=True)
    with pytest.raises(adoption.AdoptionError, match="card_reference_review_required"):
        apply(p)


def test_streamed_catalog_replacements_back_up_first_and_resume_without_buffering(fixture, monkeypatch):
    f = fixture
    _, images = card_data(f)
    old = b"previous-private-image"
    write_file(f.target, images[0], old)
    options = {"include_card_data": True, "include_catalog_reference_images": True, "replace_existing": True}
    p = plan(f, **options)
    original = adoption._atomic_copy
    def failed_copy(path, source, expected_hash, **kwargs):
        if path == f.target / images[1]:
            assert (f.backup / p.plan_id / "before" / images[0]).read_bytes() == old
            raise OSError("do-not-print-private-image-path")
        original(path, source, expected_hash, **kwargs)
    monkeypatch.setattr(adoption, "_atomic_copy", failed_copy)
    result = apply(p)
    assert not result["ok"] and result["state"] == "partial" and "private-" not in str(result)
    monkeypatch.setattr(adoption, "_atomic_copy", original)
    resumed = adoption.resume_plan(f.source, f.target, f.backup, p.plan_id, **options)
    assert apply(resumed)["ok"] and (f.backup / p.plan_id / "before" / images[0]).read_bytes() == old
    assert (f.source / images[0]).read_bytes() != old
    with pytest.raises(adoption.AdoptionError, match="adoption_manifest_conflict"):
        adoption.resume_plan(f.source, f.target, f.backup, p.plan_id, include_card_data=True, replace_existing=True)


def test_stream_copy_rechecks_target_before_atomic_replace(fixture, monkeypatch):
    f = fixture
    _, images = card_data(f)
    p = plan(f, include_card_data=True, include_catalog_reference_images=True)
    original = adoption._fingerprint
    def concurrent_change(path, **kwargs):
        result = original(path, **kwargs)
        if path == f.source / images[0] and kwargs.get("copy_to") is not None:
            write_file(f.target, images[0], b"concurrent-owner-change")
        return result
    monkeypatch.setattr(adoption, "_fingerprint", concurrent_change)
    result = apply(p)
    assert not result["ok"] and result["reason"] == "target_changed_since_plan"
    assert (f.target / images[0]).read_bytes() == b"concurrent-owner-change"


def test_fixed_json_rechecks_target_after_temporary_file_fsync(fixture, monkeypatch):
    f = fixture
    target = write_file(f.target, "storage_config.json", b'{"old":"reviewed"}')
    p = plan(f, replace_existing=True)
    original_private, original_sync = adoption._private, os.fsync
    preparing, changed = False, False
    def private(path):
        nonlocal preparing
        original_private(path)
        if path.parent == f.target and path.name.startswith(".adoption-"):
            preparing = True
    def fsync(descriptor):
        nonlocal changed
        if preparing and not changed:
            changed = True
            target.write_bytes(b'{"owner":"concurrent-unbacked-edit"}')
        original_sync(descriptor)
    monkeypatch.setattr(adoption, "_private", private)
    monkeypatch.setattr(os, "fsync", fsync)
    result = apply(p)
    assert changed and not result["ok"] and result["reason"] == "target_changed_since_plan"
    assert target.read_bytes() == b'{"owner":"concurrent-unbacked-edit"}'
    assert (f.backup / p.plan_id / "before/storage_config.json").read_bytes() == b'{"old":"reviewed"}'
    assert result["adopted_count"] == 0


def test_existing_reparse_lock_is_rejected_before_permissions_or_writes(fixture, monkeypatch):
    f = fixture
    lock = write_file(f.backup, ".adoption.lock", b"foreign-file-unchanged")
    original = Path.lstat
    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == lock:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info
    monkeypatch.setattr(Path, "lstat", reparse)
    monkeypatch.setattr(adoption, "_private_lock_file", lambda descriptor: pytest.fail("permissions must not change"))
    with pytest.raises(adoption.AdoptionError, match="linked_path_rejected"):
        with adoption._lock(lock):
            pytest.fail("linked lock must not be acquired")
    assert lock.read_bytes() == b"foreign-file-unchanged"


def test_hard_linked_lock_preserves_foreign_file_bytes_and_mode(fixture, monkeypatch):
    f = fixture
    foreign = write_file(f.source.parent, "foreign-lock-target", b"")
    f.backup.mkdir()
    lock = f.backup / ".adoption.lock"
    os.link(foreign, lock)
    mode = foreign.stat().st_mode
    monkeypatch.setattr(adoption, "_private_lock_file", lambda descriptor: pytest.fail("permissions must not change"))
    with pytest.raises(adoption.AdoptionError, match="linked_lock_file_rejected"):
        with adoption._lock(lock):
            pytest.fail("hard-linked lock must not be acquired")
    assert foreign.read_bytes() == b"" and foreign.stat().st_mode == mode


@pytest.mark.parametrize("replace_path", [False, True])
def test_lock_path_replacement_or_opened_file_redirection_cannot_modify_foreign_file(fixture, monkeypatch, replace_path):
    f = fixture
    lock = write_file(f.backup, ".adoption.lock", b"original-lock")
    foreign = write_file(f.source.parent, "foreign-opened-file", b"")
    original_foreign_mode = foreign.stat().st_mode
    def redirected_open(path, *, exists):
        assert exists and path == lock
        if replace_path:
            os.replace(foreign, lock)
            return os.open(lock, os.O_RDWR)
        return os.open(foreign, os.O_RDWR)
    monkeypatch.setattr(adoption, "_open_lock_file", redirected_open)
    monkeypatch.setattr(adoption, "_private_lock_file", lambda descriptor: pytest.fail("permissions must not change"))
    with pytest.raises(adoption.AdoptionError, match="adoption_lock_changed"):
        with adoption._lock(lock):
            pytest.fail("changed lock must not be acquired")
    current_foreign = lock if replace_path else foreign
    assert current_foreign.read_bytes() == b"" and current_foreign.stat().st_mode == original_foreign_mode


def test_reference_library_text_notes_are_preserved_as_passive_bytes_and_redacted(fixture):
    f = fixture
    path = f.source / "rareiq/data/reference_cards/private-library-note.txt"
    path.parent.mkdir(parents=True)
    raw = b"Synthetic reference-library instructions; data only.\r\n"
    path.write_bytes(raw)
    reviewed = plan(f, include_card_data=True)
    assert "private-library-note" not in json.dumps(reviewed.report())
    result = adoption.apply_adoption(reviewed, reviewed_plan_id=reviewed.plan_id, backend_stopped=True)
    assert result["ok"]
    assert (f.target / "rareiq/data/reference_cards/private-library-note.txt").read_bytes() == raw
    assert path.read_bytes() == raw
