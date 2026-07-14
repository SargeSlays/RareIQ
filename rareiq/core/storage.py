from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class StorageManager:
    REQUIRED_PATHS = (
        "database_root", "catalog_path", "image_path", "embedding_path",
        "index_path", "cache_path", "capture_path", "grading_path",
        "export_path", "backup_path", "log_path", "config_path",
    )

    def __init__(self, config_file: str | Path = "storage_config.json") -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        self.config_file = self.project_root / config_file
        self.config: dict[str, Any] = {}
        self.paths: dict[str, Path] = {}
        self.initialized = False

    def initialize(self) -> None:
        if self.initialized:
            return
        if not self.config_file.exists():
            raise FileNotFoundError(
                f"Storage configuration was not found: {self.config_file}"
            )
        self.config = json.loads(self.config_file.read_text(encoding="utf-8"))
        missing = [k for k in self.REQUIRED_PATHS if not self.config.get(k)]
        if missing:
            raise ValueError("Missing storage values: " + ", ".join(missing))
        for key in self.REQUIRED_PATHS:
            path = Path(self.config[key])
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
