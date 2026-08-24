from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


class StorageManager:
    REQUIRED_PATHS = (
        "database_root", "catalog_path", "image_path", "embedding_path",
        "index_path", "cache_path", "capture_path", "grading_path",
        "export_path", "backup_path", "log_path", "config_path",
    )

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
        }


storage = StorageManager()
