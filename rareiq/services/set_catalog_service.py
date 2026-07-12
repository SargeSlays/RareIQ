from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


class SetCatalogService:
    def __init__(self, catalog_path: Path | None = None) -> None:
        if catalog_path is None:
            catalog_path = (
                Path(__file__).resolve().parents[1]
                / "data"
                / "set_catalog.json"
            )
        self.catalog_path = catalog_path
        self._lock = threading.Lock()
        self._sets: list[dict[str, Any]] = []
        self._active_set_id = "all-loaded"
        self._error: str | None = None
        self.load()

    def load(self) -> None:
        with self._lock:
            try:
                payload = json.loads(
                    self.catalog_path.read_text(encoding="utf-8")
                )
                sets = payload.get("sets", [])
                self._sets = [
                    item for item in sets if isinstance(item, dict)
                ]
                self._active_set_id = str(
                    payload.get("active_set_id", "all-loaded")
                )
                self._error = None
            except Exception as exc:
                self._sets = []
                self._active_set_id = "all-loaded"
                self._error = str(exc)

    def _save(self) -> None:
        payload = {
            "version": 1,
            "sets": self._sets,
            "active_set_id": self._active_set_id,
        }
        self.catalog_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_sets(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._sets]

    def active_set(self) -> dict[str, Any] | None:
        with self._lock:
            for item in self._sets:
                if str(item.get("id")) == self._active_set_id:
                    return dict(item)
        return None

    def set_active(self, set_id: str) -> dict[str, Any]:
        with self._lock:
            found = next(
                (
                    item for item in self._sets
                    if str(item.get("id")) == str(set_id)
                ),
                None,
            )
            if found is None:
                raise ValueError(f"Unknown set id: {set_id}")
            self._active_set_id = str(set_id)
            self._save()
            return dict(found)

    def status(self) -> dict[str, Any]:
        active = self.active_set()
        return {
            "ok": self._error is None,
            "active_set_id": self._active_set_id,
            "active_set": active,
            "set_count": len(self._sets),
            "error": self._error,
        }
