"""Plan or apply a bounded legacy configuration adoption into an existing profile.

No application/service is imported, no runtime is stopped, and no original is
moved or deleted. Apply requires the caller to have stopped the backend. Public
reports contain only fixed names, counts, fingerprints and constant reasons.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Source audit: SecretsManager, SpotifyService, server legacy settings/history,
# OverlayStateService and MultiCardRecognitionService presentation defaults.
# Configured config_path/cache/database roots remain referenced, not copied.
LOOSE_CONFIGURATION_FILES = (
    "storage_config.json", "rareiq_secrets.json", "spotify_settings.json",
    "obs_settings.json", "production_scenes.json", "production_history.json",
    "rareiq/data/overlay_presentation.json", "rareiq/data/multi_card_presentation.json",
)
EXCLUDED_FILES = {
    "production_session.json": "active_runtime_state",
    "rareiq/data/temporal_multi_card_history.json": "recognition_runtime_state",
    "rareiq/data/set_catalog.json": "catalog_data",
}
REQUIRED_STORAGE_PATHS = (
    "database_root", "catalog_path", "image_path", "embedding_path", "index_path",
    "cache_path", "capture_path", "grading_path", "export_path", "backup_path", "log_path", "config_path",
)
OPTIONAL_STORAGE_PATHS = ("provenance_path", "replay_path", "recording_path")
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CARD_FILE_BYTES = 16 * 1024 * 1024
MAX_CARD_FILES = 512
MAX_CARD_TREE_BYTES = 128 * 1024 * 1024
MAX_CATALOG_REFERENCE_FILES = 4096
MAX_CATALOG_REFERENCE_BYTES = 4 * 1024 * 1024 * 1024
MAX_CATALOG_IMAGE_BYTES = 64 * 1024 * 1024
CATALOG_CORPUS = "catalog_master/recognition/pokipair_cards.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CARD_CONFIGURATION_FILES = (
    "rareiq/data/set_catalog.json", "rareiq/data/artwork_index.json",
    "rareiq/data/pack_transition_model.json", "catalog_master/pokipair_identity_overrides.json",
    "catalog_master/stream_speed_identity_overrides.json", "catalog_master/recognition/pokipair_cards.json",
)
CARD_TREES = {
    "rareiq/data/reference_cards": ("card_references", {".json", ".txt", ".jpg", ".jpeg", ".png", ".webp"}),
    "rareiq/data/pack_transition_backups": ("card_transition_backups", {".json"}),
}
SCHEMA_VERSION = 1
_CAPTURE_TARGET = object()


class AdoptionError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _fail(reason):
    raise AdoptionError(reason)


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    try:
        return json.loads(value.decode("utf-8"))
    except (UnicodeError, ValueError):
        _fail("invalid_configuration_json")


def _plain_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        _fail("absolute_explicit_path_required")
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            _fail("path_unavailable")
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("linked_path_rejected")
    if os.path.normcase(str(path.resolve())) != os.path.normcase(str(path)):
        _fail("linked_path_rejected")
    return path


def _resource_path(path):
    return any(part.casefold() == "resources" for part in path.parts)


def _within(path, root):
    return path == root or root in path.parents


def _roots(source, target, backup):
    source, target, backup = map(_plain_path, (source, target, backup))
    if not source.is_dir() or not (source / "app.py").is_file():
        _fail("source_project_required")
    if target.name != "backend" or not target.parent.is_dir() or not (target.parent / "browser").is_dir():
        _fail("existing_desktop_profile_required")
    _plain_path(target.parent / "browser")
    if _resource_path(source) or _resource_path(target) or _resource_path(backup):
        _fail("bundle_resources_rejected")
    if any(_within(a, b) or _within(b, a) for a, b in ((source, target), (source, backup), (target, backup))):
        _fail("overlapping_adoption_roots")
    if _within(backup, target.parent) or _within(target.parent, backup):
        _fail("backup_must_be_outside_desktop_profile")
    if target.exists() and not target.is_dir() or backup.exists() and not backup.is_dir():
        _fail("directory_required")
    return source, target, backup


def _read(path, *, missing=False, limit=MAX_FILE_BYTES):
    path = _plain_path(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            _fail("bounded_regular_file_required")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if identity(before) != identity(opened) or identity(opened) != identity(after) or len(data) > limit:
            _fail("configuration_changed_during_read")
        return data
    except FileNotFoundError:
        if missing:
            return None
        _fail("configuration_missing")
    except AdoptionError:
        raise
    except OSError:
        _fail("configuration_unavailable")


def _storage_configuration(raw, source):
    value = _json(raw)
    if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key] for key in REQUIRED_STORAGE_PATHS):
        _fail("complete_storage_configuration_required")
    result = dict(value)
    for key in (*REQUIRED_STORAGE_PATHS, *OPTIONAL_STORAGE_PATHS):
        if key not in result or result[key] in (None, ""):
            continue
        if not isinstance(result[key], str):
            _fail("invalid_storage_path")
        expanded = os.path.expandvars(os.path.expanduser(result[key]))
        if "$" in expanded or "%" in expanded or "\x00" in expanded:
            _fail("unresolved_storage_path")
        path = Path(expanded)
        path = _plain_path(Path(os.path.abspath(path if path.is_absolute() else source / path)))
        if _resource_path(path):
            _fail("storage_inside_bundle_resources")
        result[key] = str(path)
    return (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


@dataclass(frozen=True, repr=False)
class _Entry:
    name: str
    source_hash: str | None
    target_hash: str | None
    after_hash: str | None
    decision: str
    data: bytes | None
    before: bytes | None
    category: str = "configuration"
    size: int = 0
    streamed: bool = False


def _category(name):
    for prefix, (category, _) in CARD_TREES.items():
        if name.startswith(prefix + "/"):
            return category
    if name.startswith("catalog_master/") and Path(name).suffix.lower() in IMAGE_SUFFIXES:
        return "catalog_reference_images"
    return "card_configuration" if name in CARD_CONFIGURATION_FILES else "configuration"


def _public_name(entry):
    return entry.category + "/file-" + _digest(entry.name.encode("utf-8"))[:16] if entry.category in {"card_references", "card_transition_backups", "catalog_reference_images"} else entry.name


def _limit(name):
    if _category(name) == "catalog_reference_images":
        return MAX_CATALOG_IMAGE_BYTES
    return MAX_CARD_FILE_BYTES if _category(name) != "configuration" else MAX_FILE_BYTES


def _fingerprint(path, *, missing=False, limit=MAX_FILE_BYTES, copy_to=None):
    """Bounded streaming read with identity checks; never retain image bytes."""
    path = _plain_path(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            _fail("bounded_regular_file_required")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        digest, size = hashlib.sha256(), 0
        with os.fdopen(descriptor, "rb") as handle:
            opened = os.fstat(handle.fileno())
            while block := handle.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    _fail("bounded_regular_file_required")
                digest.update(block)
                if copy_to is not None:
                    copy_to.write(block)
            after = os.fstat(handle.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if identity(before) != identity(opened) or identity(opened) != identity(after) or size != before.st_size:
            _fail("configuration_changed_during_read")
        return digest.hexdigest(), size
    except FileNotFoundError:
        if missing:
            return None, 0
        _fail("configuration_missing")
    except AdoptionError:
        raise
    except OSError:
        _fail("configuration_unavailable")


def _catalog_inventory(source, *, max_files, max_bytes):
    raw = _read(source / CATALOG_CORPUS, missing=True, limit=MAX_CARD_FILE_BYTES)
    if raw is None:
        return ()
    value = _json(raw)
    rows = value.get("records") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        _fail("catalog_reference_schema_requires_review")
    names, total = set(), 0
    for row in rows:
        if not isinstance(row, dict):
            _fail("catalog_reference_schema_requires_review")
        for field in ("reference_image", "image_path"):
            image = row.get(field)
            if image in (None, ""):
                continue
            if not isinstance(image, str) or "\\" in image or "\x00" in image:
                _fail("catalog_reference_path_requires_review")
            relative = Path(image)
            if (relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2
                    or relative.parts[0] != "catalog_master" or relative.suffix.lower() not in IMAGE_SUFFIXES
                    or len(image.encode("utf-8")) > 512 or ":" in image):
                _fail("catalog_reference_path_requires_review")
            name = relative.as_posix()
            if name in names:
                continue
            path = _plain_path(source / relative)
            if not _within(path, source / "catalog_master"):
                _fail("catalog_reference_path_requires_review")
            try:
                info = path.stat()
            except OSError:
                _fail("catalog_reference_missing_requires_review")
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CATALOG_IMAGE_BYTES:
                _fail("bounded_regular_file_required")
            names.add(name)
            total += info.st_size
            if len(names) > max_files or total > max_bytes:
                _fail("catalog_reference_scope_limit_exceeded")
    return tuple(sorted(names))


def _inventory(root, *, max_files, max_bytes):
    names, total = [], 0
    for prefix, (_, suffixes) in CARD_TREES.items():
        base = _plain_path(root / prefix)
        if not base.exists():
            continue
        if not base.is_dir():
            _fail("card_reference_directory_required")
        pending = [base]
        while pending:
            directory = pending.pop()
            if len(directory.relative_to(base).parts) > 12:
                _fail("card_reference_depth_exceeded")
            for entry in os.scandir(directory):
                path = _plain_path(Path(entry.path))
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    if path.suffix.lower() not in suffixes:
                        _fail("unsupported_card_reference_file")
                    if info.st_size > MAX_CARD_FILE_BYTES:
                        _fail("card_reference_file_limit_exceeded")
                    names.append(path.relative_to(root).as_posix())
                    if len(names[-1].encode("utf-8")) > 512:
                        _fail("card_reference_name_limit_exceeded")
                    total += info.st_size
                    if len(names) > max_files or total > max_bytes:
                        _fail("card_reference_scope_limit_exceeded")
                else:
                    _fail("bounded_regular_file_required")
    return tuple(sorted(names))


def _index_configuration(raw, source, target, inventory):
    """Rewrite only known record image_path values under the adopted references."""
    value = _json(raw)
    reviews = {}
    def review(code):
        reviews[code] = reviews.get(code, 0) + 1
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict) and isinstance(value.get("records", value.get("references")), list):
        rows = value.get("records", value.get("references"))
    else:
        return raw, (("artwork_index_schema_requires_review", 1),), 0
    changed = 0
    reference_root = source / "rareiq/data/reference_cards"
    for row in rows:
        if not isinstance(row, dict):
            review("artwork_index_schema_requires_review")
            continue
        image = row.get("image_path")
        if not isinstance(image, str) or not image:
            if row.get("reference_image"):
                review("artwork_index_custom_reference_requires_review")
            continue
        supplied = Path(image)
        try:
            actual = _plain_path(Path(os.path.abspath(supplied if supplied.is_absolute() else source / supplied)))
        except AdoptionError:
            review("artwork_index_linked_reference_requires_review")
            continue
        if _within(actual, reference_root) and actual != reference_root:
            name = actual.relative_to(source).as_posix()
            if name not in inventory:
                review("artwork_index_missing_reference_requires_review")
                continue
            replacement = str(target / name)
            if image != replacement:
                row["image_path"] = replacement
                changed += 1
        elif not supplied.is_absolute():
            review("artwork_index_relative_external_reference_requires_review")
        elif not actual.is_file():
            review("artwork_index_missing_reference_requires_review")
        else:
            review("artwork_index_external_reference_requires_review")
    output = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8") if changed else raw
    return output, tuple(sorted(reviews.items())), changed


@dataclass(frozen=True, repr=False)
class AdoptionPlan:
    _source: Path
    _target: Path
    _backup: Path
    _entries: tuple[_Entry, ...]
    plan_id: str
    replace_existing: bool
    include_card_data: bool = False
    max_card_files: int = MAX_CARD_FILES
    max_card_bytes: int = MAX_CARD_TREE_BYTES
    acknowledge_external_references: bool = False
    _source_inventory: tuple[str, ...] = ()
    _target_inventory: tuple[str, ...] = ()
    _reviews: tuple[tuple[str, int], ...] = ()
    _rebased_references: int = 0
    include_catalog_reference_images: bool = False
    max_catalog_reference_files: int = MAX_CATALOG_REFERENCE_FILES
    max_catalog_reference_bytes: int = MAX_CATALOG_REFERENCE_BYTES
    _catalog_inventory: tuple[str, ...] = ()

    def report(self):
        return {"schema_version": SCHEMA_VERSION, "plan_id": self.plan_id,
                "replace_existing": self.replace_existing,
                "include_card_data": self.include_card_data,
                "include_catalog_reference_images": self.include_catalog_reference_images,
                "acknowledge_external_references": self.acknowledge_external_references,
                "card_limits": {"files": self.max_card_files, "bytes": self.max_card_bytes, "per_file_bytes": MAX_CARD_FILE_BYTES},
                "card_inventory": [{"category": category, "files": sum(e.category == category for e in self._entries),
                                    "bytes": sum(e.size for e in self._entries if e.category == category)}
                                   for category in ("card_references", "card_transition_backups", "catalog_reference_images")],
                "catalog_reference_limits": {"files": self.max_catalog_reference_files, "bytes": self.max_catalog_reference_bytes,
                                             "per_file_bytes": MAX_CATALOG_IMAGE_BYTES},
                "review": [{"reason": reason, "count": count} for reason, count in self._reviews],
                "rebased_reference_count": self._rebased_references,
                "files": [{"name": _public_name(e), "category": e.category, "decision": e.decision,
                           "source_sha256": e.source_hash, "before_sha256": e.target_hash,
                           "after_sha256": e.after_hash} for e in self._entries],
                "counts": {state: sum(e.decision == state for e in self._entries)
                           for state in ("create", "replace", "unchanged", "missing", "conflict")},
                "excluded": [{"name": name, "reason": reason} for name, reason in EXCLUDED_FILES.items()
                             if not (self.include_card_data and name in CARD_CONFIGURATION_FILES)]}


def plan_adoption(source_project, target_backend, backup_root, *, replace_existing=False, include_card_data=False,
                  max_card_files=MAX_CARD_FILES, max_card_bytes=MAX_CARD_TREE_BYTES, acknowledge_external_references=False,
                  include_catalog_reference_images=False, max_catalog_reference_files=MAX_CATALOG_REFERENCE_FILES,
                  max_catalog_reference_bytes=MAX_CATALOG_REFERENCE_BYTES):
    if any(type(value) is not bool for value in (replace_existing, include_card_data, acknowledge_external_references, include_catalog_reference_images)):
        _fail("invalid_replace_selection")
    if (type(max_card_files) is not int or not 1 <= max_card_files <= MAX_CARD_FILES
            or type(max_card_bytes) is not int or not 1 <= max_card_bytes <= MAX_CARD_TREE_BYTES):
        _fail("card_reference_scope_limit_exceeded")
    if (type(max_catalog_reference_files) is not int or not 1 <= max_catalog_reference_files <= MAX_CATALOG_REFERENCE_FILES
            or type(max_catalog_reference_bytes) is not int or not 1 <= max_catalog_reference_bytes <= MAX_CATALOG_REFERENCE_BYTES):
        _fail("catalog_reference_scope_limit_exceeded")
    if include_catalog_reference_images and not include_card_data:
        _fail("catalog_references_require_card_data")
    source, target, backup = _roots(source_project, target_backend, backup_root)
    source_inventory = _inventory(source, max_files=max_card_files, max_bytes=max_card_bytes) if include_card_data else ()
    target_inventory = _inventory(target, max_files=max_card_files, max_bytes=max_card_bytes) if include_card_data else ()
    if set(target_inventory) - set(source_inventory):
        _fail("target_card_inventory_requires_review")
    selected_catalog = _catalog_inventory(source, max_files=max_catalog_reference_files, max_bytes=max_catalog_reference_bytes) if include_card_data else ()
    catalog_inventory = selected_catalog if include_catalog_reference_images else ()
    names = (*LOOSE_CONFIGURATION_FILES, *(CARD_CONFIGURATION_FILES if include_card_data else ()), *source_inventory, *catalog_inventory)
    entries = []
    reviews, rebased = (), 0
    for name in names:
        category = _category(name)
        if category == "catalog_reference_images" or category == "card_references" and Path(name).suffix.lower() in IMAGE_SUFFIXES:
            source_hash, size = _fingerprint(source / name, limit=_limit(name))
            target_hash, _ = _fingerprint(target / name, missing=True, limit=_limit(name))
            decision = "unchanged" if source_hash == target_hash else "create" if target_hash is None else "replace" if replace_existing else "conflict"
            entries.append(_Entry(name, source_hash, target_hash, source_hash, decision, None, None, category, size, True))
            continue
        raw, before = _read(source / name, missing=True, limit=_limit(name)), _read(target / name, missing=True, limit=_limit(name))
        if raw is None:
            if name == "storage_config.json":
                _fail("source_storage_configuration_required")
            entries.append(_Entry(name, None, _digest(before) if before is not None else None, None, "missing", None, before, _category(name)))
            continue
        data = _storage_configuration(raw, source) if name == "storage_config.json" else raw
        if name == "rareiq/data/artwork_index.json":
            data, reviews, rebased = _index_configuration(raw, source, target, source_inventory)
        if name.endswith(".json"):
            _json(data)  # Images remain exact bytes; selected JSON is validated, not otherwise rewritten.
        decision = "unchanged" if before == data else "create" if before is None else "replace" if replace_existing else "conflict"
        entries.append(_Entry(name, _digest(raw), _digest(before) if before is not None else None, _digest(data), decision, data, before, category, len(data)))
    if selected_catalog and not include_catalog_reference_images:
        reviews = tuple(sorted((*reviews, ("catalog_reference_images_not_selected_requires_review", len(selected_catalog)))))
    options = (include_card_data, max_card_files, max_card_bytes, acknowledge_external_references, source_inventory, target_inventory, reviews, rebased,
               include_catalog_reference_images, max_catalog_reference_files, max_catalog_reference_bytes, catalog_inventory)
    plan_id = _plan_id(source, target, backup, replace_existing, entries, *options)
    return AdoptionPlan(source, target, backup, tuple(entries), plan_id, replace_existing, *options)


def _plan_id(source, target, backup, replace_existing, entries, include_card_data=False, max_card_files=MAX_CARD_FILES,
             max_card_bytes=MAX_CARD_TREE_BYTES, acknowledge_external_references=False, source_inventory=(),
             target_inventory=(), reviews=(), rebased=0, include_catalog_reference_images=False,
             max_catalog_reference_files=MAX_CATALOG_REFERENCE_FILES, max_catalog_reference_bytes=MAX_CATALOG_REFERENCE_BYTES, catalog_inventory=()):
    identity = {"roots": [str(p) for p in (source, target, backup)], "replace_existing": replace_existing,
                "files": [(e.name, e.source_hash, e.target_hash, e.after_hash, e.decision, e.size, e.streamed) for e in entries],
                "include_card_data": include_card_data, "card_limits": [max_card_files, max_card_bytes, MAX_CARD_FILE_BYTES],
                "acknowledge_external_references": acknowledge_external_references,
                "source_inventory": source_inventory, "target_inventory": target_inventory,
                "review": reviews, "rebased_reference_count": rebased,
                "include_catalog_reference_images": include_catalog_reference_images,
                "catalog_reference_limits": [max_catalog_reference_files, max_catalog_reference_bytes, MAX_CATALOG_IMAGE_BYTES],
                "catalog_inventory": catalog_inventory}
    return _digest(json.dumps(identity, sort_keys=True).encode("utf-8"))


def _private(path):
    if os.name == "nt":
        from rareiq.core.platform_credentials import _owner_only
        _owner_only(path)
    else:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def _mkdir(path):
    path = _plain_path(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        _private(directory)


def _atomic_write(path, data, *, target_hash=_CAPTURE_TARGET, limit=MAX_FILE_BYTES):
    path = _plain_path(path)
    if target_hash is _CAPTURE_TARGET:
        target_hash = _fingerprint(path, missing=True, limit=limit)[0]
    _mkdir(path.parent)
    temporary = path.parent / (".adoption-" + uuid4().hex + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            _private(temporary)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _plain_path(path)
        _plain_path(temporary)
        if _fingerprint(path, missing=True, limit=limit)[0] != target_hash:
            _fail("target_changed_since_plan")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()  # Only this invocation's generated atomic temporary.


def _atomic_copy(path, source, expected_hash, *, limit, target_hash=None):
    path = _plain_path(path)
    _mkdir(path.parent)
    temporary = path.parent / (".adoption-" + uuid4().hex + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            _private(temporary)
            digest, _ = _fingerprint(source, limit=limit, copy_to=handle)
            if digest != expected_hash:
                _fail("source_changed_since_plan")
            handle.flush()
            os.fsync(handle.fileno())
        _plain_path(path)
        _plain_path(temporary)
        if _fingerprint(path, missing=True, limit=limit)[0] != target_hash:
            _fail("target_changed_since_plan")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _journal(plan, state, applied):
    return {"schema_version": SCHEMA_VERSION, "plan_id": plan.plan_id, "state": state,
            "replace_existing": plan.replace_existing,
            "include_card_data": plan.include_card_data, "max_card_files": plan.max_card_files, "max_card_bytes": plan.max_card_bytes,
            "acknowledge_external_references": plan.acknowledge_external_references,
            "source_inventory": list(plan._source_inventory), "target_inventory": list(plan._target_inventory),
            "review": [list(item) for item in plan._reviews], "rebased_reference_count": plan._rebased_references,
            "include_catalog_reference_images": plan.include_catalog_reference_images,
            "max_catalog_reference_files": plan.max_catalog_reference_files, "max_catalog_reference_bytes": plan.max_catalog_reference_bytes,
            "catalog_inventory": list(plan._catalog_inventory),
            "files": [{"name": e.name, "before_sha256": e.target_hash, "after_sha256": e.after_hash,
                       "source_sha256": e.source_hash, "decision": e.decision, "size": e.size, "streamed": e.streamed,
                       "applied": e.name in applied} for e in plan._entries]}


def _write_journal(path, plan, state, applied):
    data = (json.dumps(_journal(plan, state, applied), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(data) > MAX_MANIFEST_BYTES:
        _fail("adoption_manifest_limit_exceeded")
    _atomic_write(path, data, limit=MAX_MANIFEST_BYTES)


def resume_plan(source_project, target_backend, backup_root, reviewed_plan_id, *, replace_existing=False, **options):
    """Reconstruct the exact reviewed bounded scope from its private journal."""
    source, target, backup = _roots(source_project, target_backend, backup_root)
    if not isinstance(reviewed_plan_id, str) or len(reviewed_plan_id) != 64 or any(c not in "0123456789abcdef" for c in reviewed_plan_id):
        _fail("reviewed_plan_required")
    saved = _json(_read(backup / reviewed_plan_id / "manifest.json", limit=MAX_MANIFEST_BYTES))
    fresh = plan_adoption(source, target, backup, replace_existing=replace_existing, **options)
    expected = _journal(fresh, "prepared", set())
    headers = ("schema_version", "replace_existing", "include_card_data", "max_card_files", "max_card_bytes",
               "acknowledge_external_references", "source_inventory", "review", "rebased_reference_count",
               "include_catalog_reference_images", "max_catalog_reference_files", "max_catalog_reference_bytes", "catalog_inventory")
    if (not isinstance(saved, dict) or saved.get("schema_version") != SCHEMA_VERSION
            or saved.get("plan_id") != reviewed_plan_id or saved.get("replace_existing") is not replace_existing
            or any(saved.get(key) != expected[key] for key in headers)
            or not isinstance(saved.get("target_inventory"), list)
            or not set(saved["target_inventory"]).issubset(fresh._source_inventory)
            or not isinstance(saved.get("files"), list) or len(saved["files"]) != len(fresh._entries)):
        _fail("adoption_manifest_conflict")
    entries = []
    for current_entry, item in zip(fresh._entries, saved["files"]):
        name = current_entry.name
        if not isinstance(item, dict) or item.get("name") != name or item.get("decision") not in {"create", "replace", "unchanged", "missing"}:
            _fail("adoption_manifest_conflict")
        if (current_entry.source_hash != item.get("source_sha256") or current_entry.after_hash != item.get("after_sha256")
                or current_entry.size != item.get("size") or current_entry.streamed is not item.get("streamed")):
            _fail("source_changed_since_plan")
        before = None
        if item.get("before_sha256") is not None:
            before_path = target / name
            if _fingerprint(before_path, missing=True, limit=_limit(name))[0] != item["before_sha256"]:
                before_path = backup / reviewed_plan_id / "before" / name
            if _fingerprint(before_path, missing=True, limit=_limit(name))[0] != item["before_sha256"]:
                _fail("adoption_backup_conflict")
            if not current_entry.streamed:
                before = _read(before_path, limit=_limit(name))
        entries.append(_Entry(name, current_entry.source_hash, item.get("before_sha256"), current_entry.after_hash,
                              item["decision"], current_entry.data, before, current_entry.category, current_entry.size, current_entry.streamed))
    plan_options = (fresh.include_card_data, fresh.max_card_files, fresh.max_card_bytes, fresh.acknowledge_external_references,
                    fresh._source_inventory, tuple(saved["target_inventory"]), fresh._reviews, fresh._rebased_references,
                    fresh.include_catalog_reference_images, fresh.max_catalog_reference_files, fresh.max_catalog_reference_bytes, fresh._catalog_inventory)
    if _plan_id(source, target, backup, replace_existing, entries, *plan_options) != reviewed_plan_id:
        _fail("adoption_manifest_conflict")
    return AdoptionPlan(source, target, backup, tuple(entries), reviewed_plan_id, replace_existing, *plan_options)


@contextmanager
def _lock(path):
    path = _plain_path(path)
    _mkdir(path.parent)
    try:
        before = path.lstat()
    except FileNotFoundError:
        before = None
    except OSError:
        _fail("adoption_lock_unavailable")
    descriptor = _open_lock_file(path, exists=before is not None)
    with os.fdopen(descriptor, "r+b") as handle:
        opened = os.fstat(handle.fileno())
        _verify_lock_file(path, opened, before)
        _private_lock_file(handle.fileno())
        _verify_lock_file(path, opened, before)
        if not os.fstat(handle.fileno()).st_size:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _fail("adoption_already_running")
        try:
            _verify_lock_file(path, opened, before)
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _verify_lock_file(path, opened, before):
    _plain_path(path)
    try:
        current = path.lstat()
    except OSError:
        _fail("adoption_lock_changed")
    identity = lambda info: (info.st_dev, info.st_ino)
    for info in (opened, current, *(() if before is None else (before,))):
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("linked_path_rejected")
        if info.st_nlink != 1:
            _fail("linked_lock_file_rejected")
        if identity(info) != identity(opened):
            _fail("adoption_lock_changed")


def _open_lock_file(path, *, exists):
    if os.name != "nt":
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | (0 if exists else os.O_CREAT | os.O_EXCL)
        try:
            return os.open(path, flags, 0o600)
        except OSError:
            _fail("adoption_lock_unavailable")
    # Deny deletion while open, open reparse points themselves, and request
    # WRITE_DAC so permissions can be set on the verified handle, not its name.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0xC0040000, 0x3, None, 3 if exists else 1, 0x00200080, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        _fail("adoption_lock_unavailable")
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDWR | getattr(os, "O_BINARY", 0))
    except Exception:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise


def _private_lock_file(descriptor):
    if os.name != "nt":
        os.fchmod(descriptor, 0o600)
        return
    import ctypes
    from ctypes import wintypes
    import msvcrt
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    apply = advapi.SetKernelObjectSecurity
    apply.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security = ctypes.c_void_p()
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(security), None):
        _fail("adoption_lock_permissions_unavailable")
    try:
        if not apply(msvcrt.get_osfhandle(descriptor), 0x80000004, security):
            _fail("adoption_lock_permissions_unavailable")
    finally:
        kernel.LocalFree(security)


def _recheck(plan, *, resumable=False):
    _roots(plan._source, plan._target, plan._backup)
    if plan.include_card_data:
        if _inventory(plan._source, max_files=plan.max_card_files, max_bytes=plan.max_card_bytes) != plan._source_inventory:
            _fail("source_card_inventory_changed_since_plan")
        target_names = _inventory(plan._target, max_files=plan.max_card_files, max_bytes=plan.max_card_bytes)
        if (not resumable and target_names != plan._target_inventory or resumable
                and (not set(plan._target_inventory).issubset(target_names) or not set(target_names).issubset(plan._source_inventory))):
            _fail("target_card_inventory_changed_since_plan")
        index = _read(plan._source / "rareiq/data/artwork_index.json", missing=True, limit=MAX_CARD_FILE_BYTES)
        reviews = _index_configuration(index, plan._source, plan._target, plan._source_inventory)[1] if index is not None else ()
        selected = _catalog_inventory(plan._source, max_files=plan.max_catalog_reference_files, max_bytes=plan.max_catalog_reference_bytes)
        if plan.include_catalog_reference_images and selected != plan._catalog_inventory:
            _fail("source_catalog_inventory_changed_since_plan")
        if selected and not plan.include_catalog_reference_images:
            reviews = tuple(sorted((*reviews, ("catalog_reference_images_not_selected_requires_review", len(selected)))))
        if reviews != plan._reviews:
            _fail("card_reference_review_changed_since_plan")
    for e in plan._entries:
        _recheck_entry(plan, e, resumable=resumable)


def _recheck_entry(plan, entry, *, resumable):
    if _fingerprint(plan._source / entry.name, missing=True, limit=_limit(entry.name))[0] != entry.source_hash:
        _fail("source_changed_since_plan")
    digest = _fingerprint(plan._target / entry.name, missing=True, limit=_limit(entry.name))[0]
    if digest != entry.target_hash and not (resumable and entry.decision in {"create", "replace"} and digest == entry.after_hash):
        _fail("target_changed_since_plan")
    return digest


def apply_adoption(plan, *, reviewed_plan_id, backend_stopped=False):
    if not isinstance(plan, AdoptionPlan) or reviewed_plan_id != plan.plan_id:
        _fail("reviewed_plan_required")
    if backend_stopped is not True:
        _fail("backend_must_be_stopped")
    if any(e.decision == "conflict" for e in plan._entries):
        _fail("target_conflict_requires_review")
    if any(reason != "artwork_index_external_reference_requires_review" or not plan.acknowledge_external_references
           for reason, _ in plan._reviews):
        _fail("card_reference_review_required")
    backup = plan._backup / plan.plan_id
    _plain_path(backup)
    journal_path = backup / "manifest.json"
    prior = _read(journal_path, missing=True, limit=MAX_MANIFEST_BYTES)
    if prior is not None:
        value = _json(prior)
        expected = _journal(plan, "prepared", set())
        if (not isinstance(value, dict) or any(value.get(key) != expected[key] for key in expected if key not in {"state", "files"})
                or not isinstance(value.get("files"), list) or len(value["files"]) != len(expected["files"])
                or any({k: item.get(k) for k in want if k != "applied"} !=
                       {k: want[k] for k in want if k != "applied"}
                       for item, want in zip(value["files"], expected["files"]) if isinstance(item, dict))
                or any(not isinstance(item, dict) for item in value["files"])):
            _fail("adoption_manifest_conflict")
    _recheck(plan, resumable=prior is not None)
    applied = set()
    with _lock(plan._backup / ".adoption.lock"):
        _recheck(plan, resumable=prior is not None)
        try:
            # Every old target is backed up and verified before any target write.
            for e in plan._entries:
                if e.decision not in {"create", "replace"} or e.target_hash is None:
                    continue
                saved = backup / "before" / e.name
                digest = _fingerprint(saved, missing=True, limit=_limit(e.name))[0]
                if digest is None:
                    if e.streamed:
                        _atomic_copy(saved, plan._target / e.name, e.target_hash, limit=_limit(e.name))
                    else:
                        _atomic_write(saved, e.before, target_hash=None, limit=_limit(e.name))
                elif digest != e.target_hash:
                    _fail("adoption_backup_conflict")
                if _fingerprint(saved, limit=_limit(e.name))[0] != e.target_hash:
                    _fail("adoption_backup_conflict")
            _write_journal(journal_path, plan, "prepared", applied)
            _recheck(plan, resumable=prior is not None)
            for e in plan._entries:
                if e.decision not in {"create", "replace"}:
                    continue
                current_hash = _recheck_entry(plan, e, resumable=True)
                if current_hash != e.after_hash:
                    if e.streamed:
                        _atomic_copy(plan._target / e.name, plan._source / e.name, e.after_hash, limit=_limit(e.name), target_hash=current_hash)
                    else:
                        _atomic_write(plan._target / e.name, e.data, target_hash=current_hash, limit=_limit(e.name))
                if _fingerprint(plan._target / e.name, limit=_limit(e.name))[0] != e.after_hash:
                    _fail("target_write_unconfirmed")
                applied.add(e.name)
                # Recovery also checks target hashes, so bounded batches avoid
                # rewriting a multi-megabyte manifest for every catalog image.
                if len(applied) <= 16 or len(applied) % 32 == 0:
                    _write_journal(journal_path, plan, "applying", applied)
            _recheck(plan, resumable=True)
            _write_journal(journal_path, plan, "complete", applied)
            return {"ok": True, "plan_id": plan.plan_id, "state": "complete", "adopted_count": len(applied),
                    "files": sorted(_public_name(e) for e in plan._entries if e.name in applied), "backup_manifest": True}
        except Exception as error:
            try:
                _write_journal(journal_path, plan, "partial", applied)
            except Exception:
                pass
            return {"ok": False, "reason": error.reason if isinstance(error, AdoptionError) else "adoption_apply_failed", "plan_id": plan.plan_id,
                    "state": "partial", "adopted_count": len(applied), "files": sorted(_public_name(e) for e in plan._entries if e.name in applied),
                    "backup_manifest": journal_path.exists()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--target-backend", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--include-card-data", action="store_true")
    parser.add_argument("--max-card-files", type=int, default=MAX_CARD_FILES)
    parser.add_argument("--max-card-bytes", type=int, default=MAX_CARD_TREE_BYTES)
    parser.add_argument("--acknowledge-external-references", action="store_true")
    parser.add_argument("--include-catalog-reference-images", action="store_true")
    parser.add_argument("--max-catalog-reference-files", type=int, default=MAX_CATALOG_REFERENCE_FILES)
    parser.add_argument("--max-catalog-reference-bytes", type=int, default=MAX_CATALOG_REFERENCE_BYTES)
    parser.add_argument("--reviewed-plan-id")
    parser.add_argument("--backend-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        options = {key: getattr(args, key) for key in ("replace_existing", "include_card_data", "max_card_files", "max_card_bytes",
                   "acknowledge_external_references", "include_catalog_reference_images", "max_catalog_reference_files", "max_catalog_reference_bytes")}
        plan = plan_adoption(args.source_project, args.target_backend, args.backup_root, **options)
        if args.action == "apply" and args.reviewed_plan_id and plan.plan_id != args.reviewed_plan_id:
            plan = resume_plan(args.source_project, args.target_backend, args.backup_root, args.reviewed_plan_id,
                               **options)
        value = plan.report() if args.action == "plan" else apply_adoption(plan, reviewed_plan_id=args.reviewed_plan_id, backend_stopped=args.backend_stopped)
    except AdoptionError as error:
        value = {"ok": False, "reason": error.reason}
    except Exception:
        value = {"ok": False, "reason": "adoption_unavailable"}
    print(json.dumps(value))
    return 1 if value.get("ok") is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
