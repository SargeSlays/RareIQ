from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any

from PIL import Image

from rareiq.core.storage import storage


class UniversalAssetManagerService:
    """Tracks, validates, and repairs local collectible assets."""

    def __init__(self) -> None:
        self.root = storage.get_path("database_root")
        self.registry_path = (
            storage.get_path("config_path") / "asset_registry.sqlite3"
        )
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.registry_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plugin_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    external_id TEXT,
                    path TEXT NOT NULL UNIQUE,
                    source_url TEXT,
                    sha256 TEXT,
                    size_bytes INTEGER DEFAULT 0,
                    width INTEGER,
                    height INTEGER,
                    status TEXT NOT NULL DEFAULT 'unknown',
                    checked_at REAL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_assets_plugin_type
                ON assets(plugin_id, asset_type);

                CREATE INDEX IF NOT EXISTS idx_assets_status
                ON assets(status);
                """
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def register(
        self,
        *,
        plugin_id: str,
        asset_type: str,
        path: str | Path,
        external_id: str | None = None,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        asset_path = Path(path)
        size = asset_path.stat().st_size if asset_path.exists() else 0
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO assets (
                    plugin_id, asset_type, external_id, path,
                    source_url, size_bytes, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    plugin_id=excluded.plugin_id,
                    asset_type=excluded.asset_type,
                    external_id=excluded.external_id,
                    source_url=COALESCE(excluded.source_url, assets.source_url),
                    size_bytes=excluded.size_bytes
                """,
                (
                    plugin_id,
                    asset_type,
                    external_id,
                    str(asset_path),
                    source_url,
                    size,
                    "present" if asset_path.exists() else "missing",
                    time.time(),
                ),
            )
        return {"ok": True, "path": str(asset_path)}

    def scan_images(self, limit: int | None = None) -> dict[str, Any]:
        image_root = storage.get_path("image_path")
        candidates = []
        for suffix in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            candidates.extend(image_root.rglob(suffix))

        if limit:
            candidates = candidates[:limit]

        checked = valid = corrupt = too_small = 0
        for path in candidates:
            checked += 1
            status = "valid"
            width = height = None
            sha256 = None

            try:
                if path.stat().st_size < 1024:
                    status = "too_small"
                    too_small += 1
                else:
                    with Image.open(path) as image:
                        image.verify()
                    with Image.open(path) as image:
                        width, height = image.size
                    sha256 = self._sha256(path)
                    valid += 1
            except Exception:
                status = "corrupt"
                corrupt += 1

            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO assets (
                        plugin_id, asset_type, path, sha256,
                        size_bytes, width, height, status,
                        checked_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        sha256=excluded.sha256,
                        size_bytes=excluded.size_bytes,
                        width=excluded.width,
                        height=excluded.height,
                        status=excluded.status,
                        checked_at=excluded.checked_at
                    """,
                    (
                        "pokemon",
                        "card_image",
                        str(path),
                        sha256,
                        path.stat().st_size if path.exists() else 0,
                        width,
                        height,
                        status,
                        time.time(),
                        time.time(),
                    ),
                )

        return {
            "ok": True,
            "checked": checked,
            "valid": valid,
            "corrupt": corrupt,
            "too_small": too_small,
        }

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM assets"
            ).fetchone()[0]
            by_status = {
                row["status"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM assets
                    GROUP BY status
                    """
                )
            }
            total_bytes = connection.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM assets"
            ).fetchone()[0]

        return {
            "registry": str(self.registry_path),
            "assets": total,
            "bytes": total_bytes,
            "status_counts": by_status,
        }
