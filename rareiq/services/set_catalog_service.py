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
        self._selection_mode = "auto"
        self._active_set_override: dict[str, Any] | None = None
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
                self._selection_mode = str(
                    payload.get("selection_mode", "auto")
                )
                override = payload.get("active_set_override")
                self._active_set_override = (
                    dict(override) if isinstance(override, dict) else None
                )
                self._error = None
            except Exception as exc:
                self._sets = []
                self._active_set_id = "all-loaded"
                self._selection_mode = "auto"
                self._active_set_override = None
                self._error = str(exc)

    def _save(self) -> None:
        payload = {
            "version": 1,
            "sets": self._sets,
            "active_set_id": self._active_set_id,
            "selection_mode": self._selection_mode,
            "active_set_override": self._active_set_override,
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
            if self._active_set_override is not None:
                return dict(self._active_set_override)
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
            self._selection_mode = (
                "auto" if self._active_set_id == "all-loaded" else "manual"
            )
            self._active_set_override = None
            self._save()
            return dict(found)

    def configure(
        self,
        *,
        mode: str,
        set_id: str | None = None,
        set_name: str | None = None,
        language: str | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "auto").strip().lower()
        if normalized_mode not in {"auto", "manual", "pack"}:
            raise ValueError("Set mode must be auto, manual, or pack.")
        with self._lock:
            if normalized_mode == "auto":
                self._selection_mode = "auto"
                self._active_set_id = "all-loaded"
                self._active_set_override = None
            else:
                identifier = str(set_id or "").strip()
                name = str(set_name or "").strip()
                if not identifier and not name:
                    raise ValueError("Choose a set before enabling a set lock.")
                self._selection_mode = normalized_mode
                self._active_set_id = identifier or name
                self._active_set_override = {
                    "id": identifier or name,
                    "set_id": identifier or name,
                    "name": name or identifier,
                    "language": str(language or "Any"),
                    "provider": str(provider or ""),
                    "status": "locked",
                }
            self._save()
        return self.status()

    def candidate_allowed(self, candidate: dict[str, Any]) -> bool:
        """Return whether a candidate belongs to the operator-locked set."""
        with self._lock:
            mode = self._selection_mode
            active = dict(self._active_set_override or {})
        if mode == "auto" or not active:
            return True
        wanted_ids = {
            str(active.get(key) or "").strip().casefold()
            for key in ("id", "set_id", "name")
        } - {""}
        candidate_ids = {
            str(candidate.get(key) or "").strip().casefold()
            for key in ("set_id", "set_name")
        } - {""}
        if not wanted_ids.intersection(candidate_ids):
            return False
        wanted_language = str(active.get("language") or "").strip().casefold()
        candidate_language = str(
            candidate.get("language") or candidate.get("language_code") or ""
        ).strip().casefold()
        return (
            not wanted_language
            or wanted_language in {"any", "unknown"}
            or not candidate_language
            or candidate_language == wanted_language
        )

    def status(self) -> dict[str, Any]:
        active = self.active_set()
        return {
            "ok": self._error is None,
            "active_set_id": self._active_set_id,
            "active_set": active,
            "selection_mode": self._selection_mode,
            "locked": self._selection_mode in {"manual", "pack"} and bool(active),
            "set_count": len(self._sets),
            "error": self._error,
        }
