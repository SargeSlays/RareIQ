"""Opt-in desktop resource/data separation; ordinary web/dev paths stay unchanged.

This module deliberately imports only the standard library so launch controllers
can establish writable paths before any application singleton is imported.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolved(path: Path) -> Path:
    resolved = path.resolve()
    # Windows can retain the extended-length prefix while a newly created file
    # is briefly busy. Normalize equivalent spellings before containment checks;
    # resolve still performs the junction/symlink traversal above.
    value = str(resolved)
    if os.name == "nt" and value.startswith("\\\\?\\"):
        if value.startswith("\\\\?\\UNC\\"):
            return Path("\\\\" + value[8:])
        if len(value) >= 7 and value[5:7] == ":\\":
            return Path(value[4:])
    return resolved


def _desktop_absolute(name: str) -> Path | None:
    if os.environ.get("PRODUCER_DESKTOP") != "1":
        return None
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return _resolved(path)


def desktop_data_root() -> Path | None:
    root = _desktop_absolute("PRODUCER_DESKTOP_DATA_ROOT")
    resources = _resolved(Path(__file__)).parents[2]
    if root is not None and (root == resources or resources in root.parents):
        raise ValueError("Desktop data root must be outside bundled resources")
    return root


def desktop_python() -> Path | None:
    return _desktop_absolute("PRODUCER_DESKTOP_PYTHON")


def desktop_config_path(requested: str | Path) -> Path | None:
    root = desktop_data_root()
    if root is None:
        return None
    requested = Path(requested)
    if requested.is_absolute():
        # Older services pass an absolute __file__-relative default. Never load
        # that developer/build-machine configuration in an installed runtime.
        try:
            _resolved(requested).relative_to(root)
        except ValueError:
            requested = Path(requested.name)
    candidate = _resolved(root / requested)
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("Desktop configuration must stay inside its data root") from None
    return candidate


def portable_storage_defaults() -> dict[str, str]:
    return {key: "runtime/" + directory for key, directory in {
        "database_root": "database", "catalog_path": "catalog", "image_path": "images",
        "embedding_path": "embeddings", "index_path": "indexes", "cache_path": "cache",
        "capture_path": "captures", "grading_path": "grading", "export_path": "exports",
        "backup_path": "backups", "log_path": "logs", "config_path": "config",
    }.items()}
