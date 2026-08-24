from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StorageManager:
    RECOVERY_MAX_AGE_HOURS = 36.0
    MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
    REQUIRED_PATHS = (
        "database_root", "catalog_path", "image_path", "embedding_path",
        "index_path", "cache_path", "capture_path", "grading_path",
        "export_path", "backup_path", "log_path", "config_path",
    )
    OPTIONAL_PATH_DEFAULTS = {
        "provenance_path": ("capture_path", "provenance"),
        "replay_path": ("capture_path", "replays"),
        "recording_path": ("capture_path", "recordings"),
    }

    def __init__(
        self,
        config_file: str | Path = "storage_config.json",
        *,
        project_root: str | Path | None = None,
    ) -> None:
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
        requested_config = Path(config_file)
        self.config_file = (
            requested_config
            if requested_config.is_absolute()
            else self.project_root / requested_config
        )
        self.example_config_file = self.project_root / "storage_config.example.json"
        self.config: dict[str, Any] = {}
        self.paths: dict[str, Path] = {}
        self.initialized = False

    def initialize(self) -> None:
        if self.initialized:
            return
        if not self.config_file.exists():
            if not self.example_config_file.is_file():
                raise FileNotFoundError(
                    f"Storage configuration was not found: {self.config_file}"
                )
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.example_config_file, self.config_file)

        payload = json.loads(self.config_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Storage configuration must be a JSON object.")
        self.config = payload
        missing = [k for k in self.REQUIRED_PATHS if not self.config.get(k)]
        if missing:
            raise ValueError("Missing storage values: " + ", ".join(missing))
        for key in self.REQUIRED_PATHS:
            raw_path = self.config[key]
            if not isinstance(raw_path, str):
                raise ValueError(f"Storage value must be a path string: {key}")
            expanded = Path(os.path.expandvars(os.path.expanduser(raw_path)))
            path = expanded if expanded.is_absolute() else self.config_file.parent / expanded
            path = path.resolve()
            path.mkdir(parents=True, exist_ok=True)
            self.paths[key] = path
        for key, (parent_key, directory_name) in self.OPTIONAL_PATH_DEFAULTS.items():
            raw_path = self.config.get(key)
            if raw_path is not None and not isinstance(raw_path, str):
                raise ValueError(f"Storage value must be a path string: {key}")
            if raw_path:
                expanded = Path(os.path.expandvars(os.path.expanduser(raw_path)))
                path = expanded if expanded.is_absolute() else self.config_file.parent / expanded
                path = path.resolve()
            else:
                path = (self.paths[parent_key] / directory_name).resolve()
            path.mkdir(parents=True, exist_ok=True)
            self.paths[key] = path
        self.initialized = True

    def get_path(self, key: str) -> Path:
        if not self.initialized:
            self.initialize()
        if key not in self.paths:
            raise KeyError(f"Unknown storage path: {key}")
        return self.paths[key]

    def status(self) -> dict[str, Any]:
        root = self.get_path("database_root")
        usage = shutil.disk_usage(root)
        return {
            "ready": True,
            "root": str(root),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "paths": {k: str(v) for k, v in self.paths.items()},
            "recovery": self.recovery_status(),
        }

    def recovery_status(self) -> dict[str, Any]:
        snapshot_root = self.get_path("backup_path") / "runtime-snapshots"
        valid: list[tuple[datetime, str, Path]] = []
        invalid = 0
        if snapshot_root.is_dir() and not snapshot_root.is_symlink():
            for candidate in snapshot_root.iterdir():
                if not candidate.is_dir() or candidate.is_symlink() or candidate.name.startswith("."):
                    continue
                manifest_path = candidate / "manifest.json"
                digest_path = candidate / "manifest.sha256"
                try:
                    expected = digest_path.read_text(encoding="ascii").strip().lower()
                    actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    created = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
                    if len(expected) != 64 or actual != expected or payload.get("version") != 1:
                        raise ValueError("invalid recovery manifest")
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    valid.append((created.astimezone(timezone.utc), candidate.name, candidate))
                except (OSError, ValueError, TypeError, KeyError):
                    invalid += 1
        valid.sort(reverse=True)
        latest = valid[0] if valid else None
        age_hours = None
        state = "missing"
        if latest:
            age_hours = max(0.0, (datetime.now(timezone.utc) - latest[0]).total_seconds() / 3600.0)
            state = "healthy" if age_hours <= self.RECOVERY_MAX_AGE_HOURS else "stale"
        elif invalid:
            state = "invalid"
        database_root = self.get_path("database_root")
        return {
            "state": state,
            "snapshot_root": str(snapshot_root),
            "valid_snapshot_count": len(valid),
            "invalid_snapshot_count": invalid,
            "latest_snapshot_id": latest[1] if latest else None,
            "latest_snapshot_path": str(latest[2]) if latest else None,
            "latest_created_at": latest[0].isoformat().replace("+00:00", "Z") if latest else None,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "max_age_hours": self.RECOVERY_MAX_AGE_HOURS,
            "same_volume_as_database": (
                (snapshot_root.drive or snapshot_root.anchor).casefold()
                == (database_root.drive or database_root.anchor).casefold()
            ),
            "verification_scope": "manifest",
        }

    def health(self) -> dict[str, Any]:
        try:
            status = self.status()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return {
                "healthy": False,
                "state": "error",
                "message": f"Configured storage is unavailable: {type(exc).__name__}",
                "free_bytes": None,
                "minimum_free_bytes": self.MIN_FREE_BYTES,
                "recovery": {"state": "unknown"},
            }
        recovery = status["recovery"]
        low_space = int(status["free_bytes"]) < self.MIN_FREE_BYTES
        recovery_state = str(recovery.get("state") or "unknown")
        invalid_recovery = recovery_state == "invalid"
        healthy = not low_space and not invalid_recovery
        if low_space:
            state = "error"
            message = "Configured storage has less than 2 GiB free."
        elif invalid_recovery:
            state = "error"
            message = "No valid recovery snapshot is available; invalid snapshots were found."
        elif recovery_state == "stale":
            state = "warning"
            message = "Runtime storage is ready, but the latest recovery snapshot is stale."
        elif recovery_state == "missing":
            state = "warning"
            message = "Runtime storage is ready; no recovery snapshot exists yet."
        else:
            state = "ready"
            message = "Configured storage and recovery checkpoint are healthy."
        return {
            "healthy": healthy,
            "state": state,
            "message": message,
            "root": status["root"],
            "free_bytes": status["free_bytes"],
            "minimum_free_bytes": self.MIN_FREE_BYTES,
            "recovery": recovery,
        }


storage = StorageManager()
