from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any

from rareiq.core.storage import storage


@dataclass
class BuildTask:
    provider: str
    language: str
    set_id: str
    set_name: str
    estimated_cards: int = 0
    attempts: int = 0


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
        self._refresh_lock = threading.Lock()

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
            "failed_tasks": [],
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
            "last_discovery_at": None,
            "new_releases_added": 0,
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
        catalog = self.catalog_engine.status()
        # Progress polling must stay small even when the worldwide catalog has
        # thousands of set manifests. The full catalog endpoint remains
        # available to screens that explicitly need per-set detail.
        result["catalog"] = {
            key: catalog.get(key)
            for key in (
                "busy", "provider", "sets", "cards", "images",
                "coverage_percent", "last_import", "error",
            )
        }
        return result

    def discover(self) -> dict[str, Any]:
        self._set_phase("DISCOVERING")
        self._activity("Discovering supported Pokémon sets from providers.")
        result = self.master_database.discover_all()
        sets = list(result.get("sets") or [])
        with self._lock:
            self._state["sets_discovered"] = len(sets)
            self._state["last_discovery_at"] = time.time()
            self._state["updated_at"] = time.time()
        self._activity(
            f"Discovery complete. {len(sets)} provider set records found."
        )
        self._save_state()
        return result

    def refresh_new_releases(self, *, start_if_idle: bool = True) -> dict[str, Any]:
        """Reconcile live providers with the resumable queue.

        Provider catalogs change while a worldwide build is running.  This
        method deliberately appends only unseen provider/language/set keys so
        a newly published expansion is picked up without resetting progress or
        interrupting the set currently being downloaded.
        """
        if not self._refresh_lock.acquire(blocking=False):
            return {"ok": False, "error": "Catalog discovery is already running."}
        try:
            discovery = self.master_database.discover_all()
            discovered = list(discovery.get("sets") or [])
            completed = self._completed_keys()
            discovered_keys = {
                "|".join(
                    str(value or "").lower()
                    for value in (
                        item.get("provider"),
                        item.get("language"),
                        item.get("set_id"),
                    )
                )
                for item in discovered
                if item.get("provider") and item.get("set_id")
            }
            with self._tasks.mutex:
                queued = {self._task_key(task) for task in self._tasks.queue}
            with self._lock:
                current = "|".join(str(value or "").lower() for value in (
                    self._state.get("current_provider"),
                    self._state.get("current_language"),
                    self._state.get("current_set_id"),
                ))
                busy = bool(self._state.get("busy"))

            additions: list[BuildTask] = []
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
                if key in completed or key in queued or key == current:
                    continue
                additions.append(task)
                queued.add(key)

            for task in additions:
                self._tasks.put(task)
            self._persist_queue()

            now = time.time()
            with self._lock:
                self._state["sets_discovered"] = len(discovered)
                # This is the total denominator, not a cumulative enqueue
                # counter. Replacing it prevents restart-time freshness scans
                # from making worldwide progress appear to move backwards.
                self._state["sets_queued"] = len(discovered)
                self._state["sets_completed"] = len(
                    completed & discovered_keys
                )
                self._state["new_releases_added"] = int(self._state.get("new_releases_added") or 0) + len(additions)
                self._state["last_discovery_at"] = now
                self._state["updated_at"] = now

            if additions:
                names = ", ".join(task.set_name for task in additions[:6])
                suffix = "…" if len(additions) > 6 else ""
                self._activity(f"Freshness scan queued {len(additions)} new release records: {names}{suffix}")
            else:
                self._activity("Freshness scan complete; catalog is current with providers.")

            if additions and start_if_idle and not busy:
                self._begin_queued_worker()
            return {
                "ok": True,
                "discovered": len(discovered),
                "added": len(additions),
                "sets": [asdict(task) for task in additions],
                "provider_errors": list(discovery.get("errors") or []),
            }
        finally:
            self._refresh_lock.release()

    def _persist_queue(self) -> None:
        with self._tasks.mutex:
            pending = [asdict(task) for task in self._tasks.queue]
        self.queue_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _begin_queued_worker(self) -> None:
        """Start processing tasks appended by a background freshness scan."""
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            now = time.time()
            self._state.update({
                "busy": True,
                "phase": "QUEUED",
                "sets_failed": 0,
                "failed_tasks": [],
                "started_at": now,
                "last_error": None,
                "updated_at": now,
            })
        self._cancel.clear()
        self._started_perf = time.perf_counter()
        self._last_sample_perf = self._started_perf
        self._last_sample_cards = int(self.catalog_engine.status().get("cards") or 0)
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="rareiq-master-database-builder",
        )
        self._worker.start()

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
        discovered_keys = set()
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
            discovered_keys.add(key)
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

        self._persist_queue()

        self._cancel.clear()
        now = time.time()
        self._started_perf = time.perf_counter()
        self._last_sample_perf = self._started_perf
        self._last_sample_cards = int(self.catalog_engine.status().get("cards") or 0)

        with self._lock:
            self._state.update({
                "busy": True,
                "phase": "QUEUED",
                # Progress remains worldwide and monotonic across resumes.
                # `tasks` is only the remaining queue, not the denominator.
                "sets_queued": len(discovered),
                # Manifests can outlive a provider discovery record or come
                # from an older provider. Count only records in this run's
                # discovery so progress can never exceed its denominator.
                "sets_completed": len(completed_keys & discovered_keys),
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

    def coverage(
        self,
        *,
        query: str = "",
        language: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return compact per-set download coverage for the operator UI."""
        needle = str(query or "").strip().casefold()
        wanted_language = str(language or "").strip().casefold()
        rows: list[dict[str, Any]] = []
        language_totals: dict[str, dict[str, int]] = {}

        for path in self.catalog_engine.sets_dir.glob("*/manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            row_language = str(manifest.get("language") or "Unknown")
            if wanted_language and row_language.casefold() != wanted_language:
                continue
            haystack = " ".join(str(manifest.get(key) or "") for key in (
                "set_name", "set_id", "provider", "language",
            )).casefold()
            if needle and needle not in haystack:
                continue
            cards = int(manifest.get("cards") or 0)
            images = int(manifest.get("images") or 0)
            errors = len(manifest.get("errors") or [])
            coverage = round(images / cards * 100, 1) if cards else 0.0
            row = {
                "provider": str(manifest.get("provider") or "unknown"),
                "language": row_language,
                "set_id": str(manifest.get("set_id") or ""),
                "set_name": str(manifest.get("set_name") or manifest.get("set_id") or "Unknown set"),
                "cards": cards,
                "images": images,
                "coverage_percent": coverage,
                "download_complete": bool(manifest.get("download_complete")),
                "errors": errors,
            }
            rows.append(row)
            totals = language_totals.setdefault(row_language, {"sets": 0, "cards": 0, "images": 0})
            totals["sets"] += 1
            totals["cards"] += cards
            totals["images"] += images

        rows.sort(key=lambda item: (
            not item["download_complete"],
            item["coverage_percent"],
            item["language"].casefold(),
            item["set_name"].casefold(),
        ))
        return {
            "ok": True,
            "sets": rows[:max(1, min(500, int(limit)))],
            "matching_sets": len(rows),
            "languages": language_totals,
        }

    def set_options(self, *, limit: int = 2500) -> list[dict[str, Any]]:
        """Return downloaded and queued sets for recognition-context controls."""
        completed = self.coverage(limit=limit).get("sets") or []
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in completed:
            key = (
                str(item.get("provider") or "").casefold(),
                str(item.get("language") or "").casefold(),
                str(item.get("set_id") or "").casefold(),
            )
            rows[key] = {**item, "references_ready": bool(item.get("images"))}
        with self._tasks.mutex:
            queued = list(self._tasks.queue)
        for task in queued:
            key = (
                str(task.provider).casefold(),
                str(task.language).casefold(),
                str(task.set_id).casefold(),
            )
            rows.setdefault(key, {
                "provider": task.provider,
                "language": task.language,
                "set_id": task.set_id,
                "set_name": task.set_name,
                "cards": 0,
                "images": 0,
                "coverage_percent": 0.0,
                "download_complete": False,
                "references_ready": False,
                "queued": True,
            })
        return sorted(rows.values(), key=lambda item: (
            str(item.get("set_name") or "").casefold(),
            str(item.get("language") or "").casefold(),
        ))[:max(1, int(limit))]

    def prioritize(self, query: str) -> dict[str, Any]:
        """Move matching queued sets ahead without disturbing the active set."""
        needle = str(query or "").strip().casefold()
        if not needle:
            return {"ok": False, "error": "Enter a set name or set ID."}
        with self._tasks.mutex:
            pending = list(self._tasks.queue)
            matches = [task for task in pending if needle in f"{task.set_id} {task.set_name} {task.language}".casefold()]
            if not matches:
                return {"ok": False, "error": "No queued sets matched that search."}
            others = [task for task in pending if task not in matches]
            self._tasks.queue.clear()
            self._tasks.queue.extend(matches + others)
            self._tasks.not_empty.notify_all()
        self._activity(f"Prioritized {len(matches)} queued set records matching '{query}'.")
        return {
            "ok": True,
            "query": query,
            "matches": len(matches),
            "sets": [asdict(task) for task in matches[:25]],
        }


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
                    elif task.provider == "simplifiedtcg":
                        result = self.master_database._import_simplifiedtcg_set(
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
                            failed = [
                                item for item in self._state.get("failed_tasks") or []
                                if item.get("task_key") != self._task_key(task)
                            ]
                            self._state["failed_tasks"] = failed
                            self._state["sets_failed"] = len(failed)
                        self._activity(
                            f"Completed {task.set_name}: "
                            f"{result.get('cards', 0)} cards, "
                            f"{result.get('images', 0)} images."
                        )
                    elif self._requeue_transient_failure(
                        task, str(result.get("error") or "")
                    ):
                        pass
                    else:
                        self._record_task_failure(
                            task, str(result.get("error") or "Unknown provider error")
                        )
                        self._activity(
                            f"Failed {task.set_name}: {result.get('error')}"
                        )
                except Exception as exc:
                    if not self._requeue_transient_failure(task, str(exc)):
                        self._record_task_failure(task, str(exc))
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
                # Older metadata-only imports wrote a manifest even when no
                # reference artwork had been attempted.  Those records are
                # useful for lookup, but must not make a resumable world build
                # skip the images required by visual recognition.
                if not manifest.get("download_complete"):
                    continue
                if int(manifest.get("cards") or 0) <= 0:
                    continue
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

    def _requeue_transient_failure(self, task: BuildTask, error: str) -> bool:
        """Retry short-lived provider failures without losing the set.

        Permanent catalog misses still fail immediately. Retries go to the
        back of the queue so a struggling provider cannot block healthy ones.
        """
        transient_markers = (
            "429", "500", "502", "503", "504", "bad gateway",
            "internal server error", "service unavailable", "timed out",
            "timeout", "connection reset", "connection aborted",
        )
        if task.attempts >= 3 or not any(
            marker in error.lower() for marker in transient_markers
        ):
            return False

        retry = BuildTask(
            provider=task.provider,
            language=task.language,
            set_id=task.set_id,
            set_name=task.set_name,
            estimated_cards=task.estimated_cards,
            attempts=task.attempts + 1,
        )
        self._tasks.put(retry)
        self._persist_queue()
        with self._lock:
            self._state["last_error"] = error
        self._activity(
            f"Retrying {task.set_name} later after transient provider error "
            f"({retry.attempts}/3): {error}"
        )
        return True

    def _record_task_failure(self, task: BuildTask, error: str) -> None:
        """Persist the exact missing provider record for targeted retries."""
        task_key = self._task_key(task)
        failure = {
            **asdict(task),
            "task_key": task_key,
            "error": error,
            "failed_at": time.time(),
        }
        with self._lock:
            failed = [
                item for item in self._state.get("failed_tasks") or []
                if item.get("task_key") != task_key
            ]
            failed.append(failure)
            self._state["failed_tasks"] = failed[-250:]
            self._state["sets_failed"] = len(self._state["failed_tasks"])
            self._state["last_error"] = error

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
