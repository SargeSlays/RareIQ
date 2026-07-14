from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class PokemonAutoSyncService:
    """Starts and maintains the Pokémon database without operator set IDs."""

    def __init__(
        self,
        project_root: Path,
        master_database: Any,
        visual_index: Any,
    ) -> None:
        self.project_root = project_root
        self.master_database = master_database
        self.visual_index = visual_index
        self.config_path = (
            project_root / "pokemon_master_database" / "auto_sync.json"
        )
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._status = {
            "enabled": False,
            "phase": "IDLE",
            "last_sync": None,
            "next_sync": None,
            "error": None,
        }

        if not self.config_path.exists():
            self.config_path.write_text(
                json.dumps({
                    "enabled": False,
                    "interval_hours": 24,
                    "resume": True,
                }, indent=2),
                encoding="utf-8",
            )

    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "enabled": False,
                "interval_hours": 24,
                "resume": True,
            }

    def configure(
        self,
        enabled: bool | None = None,
        interval_hours: int | None = None,
    ) -> dict[str, Any]:
        config = self.config()
        if enabled is not None:
            config["enabled"] = bool(enabled)
        if interval_hours is not None:
            config["interval_hours"] = max(1, int(interval_hours))

        self.config_path.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
        self._status["enabled"] = bool(config.get("enabled"))
        return {"ok": True, "config": config}

    def status(self) -> dict[str, Any]:
        payload = dict(self._status)
        payload["config"] = self.config()
        return payload

    def start(self, force: bool = False) -> dict[str, Any]:
        config = self.config()
        if not force and not config.get("enabled"):
            return {
                "ok": False,
                "error": "Automatic Pokémon database sync is disabled.",
            }

        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"ok": True, "status": self.status()}

            self._stop.clear()
            self._worker = threading.Thread(
                target=self._run_once,
                daemon=True,
                name="rareiq-pokemon-auto-sync",
            )
            self._worker.start()

        return {"ok": True, "status": self.status()}

    def _run_once(self) -> None:
        self._status.update({
            "phase": "DISCOVERING",
            "error": None,
        })

        try:
            discovery = self.master_database.discover_all()
            if not discovery.get("ok"):
                raise RuntimeError(discovery.get("error") or "Discovery failed")

            self._status["phase"] = "BUILDING"
            build_result = self.master_database.start_world_build(
                languages=None,
                provider_ids=None,
                resume=True,
                max_sets=None,
            )
            if not build_result.get("ok"):
                raise RuntimeError(
                    build_result.get("error") or "Database build failed"
                )

            while self.master_database.status().get("busy"):
                if self._stop.wait(2.0):
                    self.master_database.cancel()
                    return

            self._status["phase"] = "INDEXING"
            self.visual_index.rebuild()

            interval = int(self.config().get("interval_hours", 24))
            now = time.time()
            self._status.update({
                "phase": "COMPLETE",
                "last_sync": now,
                "next_sync": now + interval * 3600,
                "error": None,
            })
        except Exception as exc:
            self._status.update({
                "phase": "FAILED",
                "error": str(exc),
            })

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        self.master_database.cancel()
        self._status["phase"] = "STOPPING"
        return {"ok": True}
