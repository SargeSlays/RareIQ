from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from rareiq.core.storage import storage


@dataclass
class BuildTask:
    provider: str
    language: str
    set_id: str
    set_name: str
    estimated_cards: int = 0


class MasterDatabaseBuilderService:
    """Resumable worldwide Pokémon build coordinator."""

    def __init__(
        self,
        pokemon_master_database: Any,
        catalog_engine: Any,
        visual_index: Any,
    ) -> None:
        self.master_database = pokemon_master_database
        self.catalog_engine = catalog_engine
        self.visual_index = visual_index

        self.catalog_root = storage.get_path("catalog_path") / "pokemon"
        self.image_root = storage.get_path("image_path") / "pokemon"
        self.index_root = storage.get_path("index_path") / "pokemon"
        self.log_root = storage.get_path("log_path") / "builders"
        self.config_root = storage.get_path("config_path")

        for path in (
            self.catalog_root,
            self.image_root,
            self.index_root,
            self.log_root,
            self.config_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self.state_path = self.config_root / "pokemon_master_builder_state.json"
        self.queue_path = self.config_root / "pokemon_master_builder_queue.json"
        self.log_path = self.log_root / "pokemon_master_builder.log"

        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._tasks: queue.Queue[BuildTask] = queue.Queue()
        self._started_perf = 0.0
        self._last_sample_perf = 0.0
        self._last_sample_cards = 0

        self._state: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "current_provider": None,
            "current_language": None,
            "current_set_id": None,
            "current_set_name": None,
            "sets_discovered": 0,
            "sets_queued": 0,
            "sets_completed": 0,
            "sets_failed": 0,
            "current_set_processed": 0,
            "current_set_total": 0,
            "provider_health": {},
            "preflight_ok": False,
            "cards": 0,
            "images": 0,
            "indexed_images": 0,
            "cards_per_second": 0.0,
            "elapsed_seconds": 0.0,
            "eta_seconds": None,
            "last_completed": None,
            "last_error": None,
            "started_at": None,
            "updated_at": time.time(),
            "storage": {
                "catalog_root": str(self.catalog_root),
                "image_root": str(self.image_root),
                "index_root": str(self.index_root),
            },
            "activity": [],
        }
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            saved["busy"] = False
            if saved.get("phase") not in {"COMPLETE", "FAILED"}:
                saved["phase"] = "PAUSED"
            self._state.update(saved)
        except Exception:
            pass

    def _save_state(self) -> None:
        with self._lock:
            payload = dict(self._state)
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _activity(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"{timestamp} {message}"
        with self._lock:
            activity = list(self._state.get("activity") or [])
            activity.append(line)
            self._state["activity"] = activity[-80:]
            self._state["updated_at"] = time.time()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self._save_state()

    def status(self) -> dict[str, Any]:
        self._update_metrics()
        with self._lock:
            result = dict(self._state)
        result["queue_remaining"] = self._tasks.qsize()
        result["visual_index"] = self.visual_index.status()
        result["catalog"] = self.catalog_engine.status()
        return result

    def discover(self) -> dict[str, Any]:
        self._set_phase("DISCOVERING")
        self._activity("Discovering supported Pokémon sets from providers.")
        result = self.master_database.discover_all()
        sets = list(result.get("sets") or [])
        with self._lock:
            self._state["sets_discovered"] = len(sets)
            self._state["updated_at"] = time.time()
        self._activity(
            f"Discovery complete. {len(sets)} provider set records found."
        )
        self._save_state()
        return result

    def start(self, resume: bool = True) -> dict[str, Any]:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {
                    "ok": False,
                    "error": "Master database build is already running.",
                }

        self._set_phase("PREFLIGHT")
        self._activity("Running provider health checks before discovery.")
        provider_health = self.master_database.provider_health()
        online = [
            provider_id
            for provider_id, result in provider_health.items()
            if result.get("online")
        ]
        with self._lock:
            self._state["provider_health"] = provider_health
            self._state["preflight_ok"] = bool(online)
        self._save_state()

        if not online:
            error = "No Pokémon data providers are online."
            self._set_failed(error)
            return {"ok": False, "error": error, "providers": provider_health}

        self._activity(
            "Provider preflight complete: " + ", ".join(online)
        )

        discovery = self.discover()
        if not discovery.get("ok"):
            self._set_failed(discovery.get("error") or "Discovery failed.")
            return discovery

        discovered = list(discovery.get("sets") or [])
        completed_keys = self._completed_keys() if resume else set()
        tasks = []

        for item in discovered:
            task = BuildTask(
                provider=str(item.get("provider") or ""),
                language=str(item.get("language") or ""),
                set_id=str(item.get("set_id") or ""),
                set_name=str(item.get("set_name") or item.get("set_id") or ""),
                estimated_cards=int(item.get("card_count") or 0),
            )
            key = self._task_key(task)
            if not task.provider or not task.set_id:
                continue
            if resume and key in completed_keys:
                continue
            tasks.append(task)

        while not self._tasks.empty():
            try:
                self._tasks.get_nowait()
            except queue.Empty:
                break

        for task in tasks:
            self._tasks.put(task)

        self.queue_path.write_text(
            json.dumps([asdict(task) for task in tasks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._cancel.clear()
        now = time.time()
        self._started_perf = time.perf_counter()
        self._last_sample_perf = self._started_perf
        self._last_sample_cards = int(self.catalog_engine.status().get("cards") or 0)

        with self._lock:
            self._state.update({
                "busy": True,
                "phase": "QUEUED",
                "sets_queued": len(tasks),
                "sets_completed": 0,
                "sets_failed": 0,
                "current_set_processed": 0,
                "current_set_total": 0,
                "cards": int(self.catalog_engine.status().get("cards") or 0),
                "images": int(self.catalog_engine.status().get("images") or 0),
                "cards_per_second": 0.0,
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "started_at": now,
                "last_error": None,
                "updated_at": now,
                "activity": [],
            })

        self._activity(f"Queued {len(tasks)} sets for import.")
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="rareiq-master-database-builder",
        )
        self._worker.start()
        return {"ok": True, "status": self.status()}

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        self._set_phase("CANCELING")
        self._activity("Stop requested. Finishing the active provider call.")
        return {"ok": True}

    def rebuild_visual_index(self) -> dict[str, Any]:
        self._set_phase("INDEXING")
        self._activity("Rebuilding the global visual index.")
        result = self.visual_index.rebuild()
        with self._lock:
            self._state["indexed_images"] = int(result.get("records") or 0)
        self._activity(
            f"Visual index complete with {result.get('records', 0)} images."
        )
        self._set_phase("COMPLETE")
        return result


    def _set_progress(self, payload: dict[str, Any]) -> None:
        processed = int(payload.get("processed") or 0)
        total = int(payload.get("total") or 0)
        cards = int(payload.get("cards") or 0)
        images = int(payload.get("images") or 0)

        with self._lock:
            self._state.update({
                "current_set_processed": processed,
                "current_set_total": total,
                "cards": max(int(self._state.get("cards") or 0), cards),
                "images": max(int(self._state.get("images") or 0), images),
                "updated_at": time.time(),
            })

        if processed == 1 or processed == total or processed % 10 == 0:
            self._activity(
                f"{payload.get('set_name')}: "
                f"{processed}/{total} cards, {images} images."
            )
        else:
            self._save_state()

    def _run(self) -> None:
        self._set_phase("IMPORTING")
        try:
            while not self._cancel.is_set():
                try:
                    task = self._tasks.get_nowait()
                except queue.Empty:
                    break

                with self._lock:
                    self._state.update({
                        "current_provider": task.provider,
                        "current_language": task.language,
                        "current_set_id": task.set_id,
                        "current_set_name": task.set_name,
                        "current_set_processed": 0,
                        "current_set_total": task.estimated_cards,
                    })

                self._activity(
                    f"Importing {task.set_name} "
                    f"({task.provider}/{task.language}/{task.set_id})."
                )

                try:
                    if task.provider == "tcgdex":
                        result = self.catalog_engine.import_tcgdex_set(
                            task.set_id,
                            task.language,
                            None,
                            progress_callback=self._set_progress,
                            defer_indexes=True,
                            max_workers=8,
                        )
                    elif task.provider == "pokemontcg":
                        result = self.master_database._import_pokemontcg_set(
                            task.set_id,
                            task.language,
                            progress_callback=self._set_progress,
                            defer_indexes=True,
                            max_workers=8,
                        )
                    else:
                        result = {
                            "ok": False,
                            "error": f"Unsupported provider: {task.provider}",
                        }

                    if result.get("ok"):
                        with self._lock:
                            self._state["sets_completed"] += 1
                            self._state["last_completed"] = task.set_name
                        self._activity(
                            f"Completed {task.set_name}: "
                            f"{result.get('cards', 0)} cards, "
                            f"{result.get('images', 0)} images."
                        )
                    else:
                        with self._lock:
                            self._state["sets_failed"] += 1
                            self._state["last_error"] = result.get("error")
                        self._activity(
                            f"Failed {task.set_name}: {result.get('error')}"
                        )
                except Exception as exc:
                    with self._lock:
                        self._state["sets_failed"] += 1
                        self._state["last_error"] = str(exc)
                    self._activity(f"Failed {task.set_name}: {exc}")

                self._update_metrics()
                self._save_state()

            if self._cancel.is_set():
                with self._lock:
                    self._state.update({
                        "busy": False,
                        "phase": "PAUSED",
                    })
                self._activity("Build paused. Progress was saved.")
                return

            self._set_phase("CATALOG_INDEX")
            self._activity(
                "All queued sets processed. Rebuilding master catalog once."
            )
            self.catalog_engine.rebuild_master_index()
            self.catalog_engine.artwork_index.rebuild()

            self._set_phase("INDEXING")
            self._activity("Building global visual index.")
            index_result = self.visual_index.rebuild()

            with self._lock:
                self._state.update({
                    "indexed_images": int(index_result.get("records") or 0),
                    "busy": False,
                    "phase": "COMPLETE",
                    "current_provider": None,
                    "current_language": None,
                    "current_set_id": None,
                    "current_set_name": None,
                })
            self._update_metrics()
            self._activity("Pokémon Master Database build complete.")
        except Exception as exc:
            self._set_failed(str(exc))

    def _completed_keys(self) -> set[str]:
        completed = set()
        for path in self.catalog_engine.sets_dir.glob("*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                completed.add(
                    "|".join(
                        str(value or "").lower()
                        for value in (
                            manifest.get("provider"),
                            manifest.get("language"),
                            manifest.get("set_id"),
                        )
                    )
                )
            except Exception:
                continue
        return completed

    @staticmethod
    def _task_key(task: BuildTask) -> str:
        return "|".join(
            value.lower()
            for value in (task.provider, task.language, task.set_id)
        )

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self._state["phase"] = phase
            self._state["updated_at"] = time.time()
        self._save_state()

    def _set_failed(self, error: str) -> None:
        with self._lock:
            self._state.update({
                "busy": False,
                "phase": "FAILED",
                "last_error": error,
                "updated_at": time.time(),
            })
        self._activity(f"Builder failed: {error}")

    def _update_metrics(self) -> None:
        catalog = self.catalog_engine.status()
        cards = int(catalog.get("cards") or 0)
        images = int(catalog.get("images") or 0)

        now_perf = time.perf_counter()
        if self._started_perf:
            elapsed = max(0.0, now_perf - self._started_perf)
        else:
            elapsed = 0.0

        sample_elapsed = max(0.001, now_perf - self._last_sample_perf)
        card_delta = max(0, cards - self._last_sample_cards)
        instant_rate = card_delta / sample_elapsed

        discovered = int(self._state.get("sets_discovered") or 0)
        completed = (
            int(self._state.get("sets_completed") or 0)
            + int(self._state.get("sets_failed") or 0)
        )
        eta = None
        if completed > 0 and discovered > completed and elapsed > 0:
            seconds_per_set = elapsed / completed
            eta = round((discovered - completed) * seconds_per_set, 1)

        with self._lock:
            previous = float(self._state.get("cards_per_second") or 0.0)
            blended = (
                instant_rate
                if previous <= 0
                else previous * 0.7 + instant_rate * 0.3
            )
            self._state.update({
                "cards": cards,
                "images": images,
                "cards_per_second": round(blended, 2),
                "elapsed_seconds": round(elapsed, 1),
                "eta_seconds": eta,
                "updated_at": time.time(),
            })

        self._last_sample_perf = now_perf
        self._last_sample_cards = cards
