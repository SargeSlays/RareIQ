from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from rareiq.core.provider_http import download_bytes
from rareiq.core.storage import storage


class FastPipelineService:
    """
    Two-stage Pokémon ingestion:

    1. Metadata-first catalog build
    2. Resumable HD artwork backfill

    Existing files are always reused.
    """

    DEFAULT_LANGUAGES = (
        "English",
        "Japanese",
        "Traditional Chinese",
    )

    def __init__(
        self,
        master_database: Any,
        catalog_engine: Any,
        visual_index: Any,
    ) -> None:
        self.master_database = master_database
        self.catalog_engine = catalog_engine
        self.visual_index = visual_index

        self.catalog_root = storage.get_path("catalog_path") / "pokemon"
        self.sets_root = self.catalog_root / "sets"
        self.image_root = storage.get_path("image_path") / "pokemon"
        self.config_root = storage.get_path("config_path")
        self.log_root = storage.get_path("log_path") / "pipelines"

        for path in (
            self.catalog_root,
            self.sets_root,
            self.image_root,
            self.config_root,
            self.log_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        self.state_path = self.config_root / "fast_pipeline_state.json"
        self.image_queue_path = self.config_root / "hd_image_queue.json"
        self.log_path = self.log_root / "fast_pipeline.log"

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._metadata_thread: threading.Thread | None = None
        self._image_thread: threading.Thread | None = None

        self._state: dict[str, Any] = {
            "metadata": {
                "busy": False,
                "phase": "IDLE",
                "languages": list(self.DEFAULT_LANGUAGES),
                "sets_discovered": 0,
                "sets_completed": 0,
                "sets_failed": 0,
                "cards": 0,
                "current_set": None,
                "current_language": None,
                "started_at": None,
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "last_error": None,
            },
            "images": {
                "busy": False,
                "phase": "IDLE",
                "queued": 0,
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "workers": 12,
                "bytes_downloaded": 0,
                "mb_per_second": 0.0,
                "current": None,
                "started_at": None,
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "last_error": None,
            },
            "catalog_ready": False,
            "activity": [],
            "updated_at": time.time(),
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self._state.update(saved)
            self._state["metadata"]["busy"] = False
            self._state["images"]["busy"] = False
            if self._state["metadata"].get("phase") not in {"COMPLETE", "FAILED"}:
                self._state["metadata"]["phase"] = "PAUSED"
            if self._state["images"].get("phase") not in {"COMPLETE", "FAILED"}:
                self._state["images"]["phase"] = "PAUSED"
        except Exception:
            pass

    def _save(self) -> None:
        with self._lock:
            payload = dict(self._state)
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _activity(self, text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        with self._lock:
            activity = list(self._state.get("activity") or [])
            activity.append(line)
            self._state["activity"] = activity[-100:]
            self._state["updated_at"] = time.time()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self._save()

    def status(self) -> dict[str, Any]:
        self._refresh_metrics()
        with self._lock:
            return json.loads(json.dumps(self._state))

    def start_metadata(
        self,
        languages: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._metadata_thread and self._metadata_thread.is_alive():
                return {"ok": False, "error": "Metadata pipeline is already running."}
            if self._image_thread and self._image_thread.is_alive():
                return {
                    "ok": False,
                    "error": "Stop the HD artwork job before rebuilding metadata.",
                }

        selected = [
            item for item in (languages or self.DEFAULT_LANGUAGES)
            if item
        ]
        self._stop.clear()
        with self._lock:
            self._state["metadata"].update({
                "busy": True,
                "phase": "PREFLIGHT",
                "languages": selected,
                "sets_discovered": 0,
                "sets_completed": 0,
                "sets_failed": 0,
                "cards": self._count_metadata_cards(),
                "current_set": None,
                "current_language": None,
                "started_at": time.time(),
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "last_error": None,
            })
            self._state["catalog_ready"] = False

        self._activity(
            "Starting metadata-first build for: " + ", ".join(selected)
        )
        self._metadata_thread = threading.Thread(
            target=self._metadata_worker,
            args=(selected,),
            daemon=True,
            name="rareiq-fast-metadata",
        )
        self._metadata_thread.start()
        return {"ok": True, "pipeline": self.status()}

    def start_images(self, workers: int = 12) -> dict[str, Any]:
        with self._lock:
            if self._image_thread and self._image_thread.is_alive():
                return {"ok": False, "error": "HD artwork job is already running."}
            if self._metadata_thread and self._metadata_thread.is_alive():
                return {
                    "ok": False,
                    "error": "Wait for metadata to finish before starting HD artwork.",
                }

        queue_items = self._build_image_queue()
        worker_count = max(2, min(24, int(workers or 12)))
        self._stop.clear()

        with self._lock:
            self._state["images"].update({
                "busy": True,
                "phase": "DOWNLOADING",
                "queued": len(queue_items),
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "workers": worker_count,
                "bytes_downloaded": 0,
                "mb_per_second": 0.0,
                "current": None,
                "started_at": time.time(),
                "elapsed_seconds": 0.0,
                "eta_seconds": None,
                "last_error": None,
            })

        self.image_queue_path.write_text(
            json.dumps(queue_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._activity(
            f"Queued {len(queue_items)} missing HD images with "
            f"{worker_count} adaptive workers."
        )

        self._image_thread = threading.Thread(
            target=self._image_worker,
            args=(queue_items, worker_count),
            daemon=True,
            name="rareiq-hd-artwork",
        )
        self._image_thread.start()
        return {"ok": True, "pipeline": self.status()}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        with self._lock:
            if self._state["metadata"]["busy"]:
                self._state["metadata"]["phase"] = "STOPPING"
            if self._state["images"]["busy"]:
                self._state["images"]["phase"] = "STOPPING"
        self._activity("Stop requested. Current file operations will finish safely.")
        return {"ok": True}

    def shutdown(self) -> None:
        self._stop.set()
        for worker in (self._metadata_thread, self._image_thread):
            if worker and worker.is_alive():
                worker.join(timeout=3.0)

    def build_visual_index(self) -> dict[str, Any]:
        self._activity("Building visual index from available local artwork.")
        result = self.visual_index.rebuild()
        self._activity(
            f"Visual index complete: {result.get('records', 0)} records."
        )
        return result

    # --------------------------------------------------------------
    # Metadata stage
    # --------------------------------------------------------------
    def _metadata_worker(self, languages: list[str]) -> None:
        started = time.perf_counter()
        try:
            health = self.master_database.provider_health()
            online = {
                key for key, value in health.items()
                if value.get("online")
            }
            if not online:
                raise RuntimeError("No Pokémon providers passed preflight.")

            with self._lock:
                self._state["metadata"]["phase"] = "DISCOVERING"
            discovery = self.master_database.discover_all(languages)
            tasks = [
                item for item in (discovery.get("sets") or [])
                if item.get("provider") in online
            ]

            with self._lock:
                self._state["metadata"]["sets_discovered"] = len(tasks)
                self._state["metadata"]["phase"] = "METADATA"

            self._activity(
                f"Discovered {len(tasks)} supported set-language records."
            )

            for item in tasks:
                if self._stop.is_set():
                    self._pause_metadata()
                    return

                provider_id = str(item.get("provider") or "")
                language = str(item.get("language") or "")
                set_id = str(item.get("set_id") or "")
                set_name = str(item.get("set_name") or set_id)

                with self._lock:
                    self._state["metadata"]["current_set"] = set_name
                    self._state["metadata"]["current_language"] = language

                try:
                    provider = self.master_database.providers[provider_id]
                    payload = provider.fetch_set(language, set_id)
                    cards = list(payload.get("cards") or [])
                    normalized = self._normalize_metadata(
                        provider_id,
                        language,
                        set_id,
                        set_name,
                        payload,
                        cards,
                    )
                    self._write_metadata_set(
                        provider_id,
                        language,
                        set_id,
                        set_name,
                        payload,
                        normalized,
                    )
                    with self._lock:
                        self._state["metadata"]["sets_completed"] += 1
                        self._state["metadata"]["cards"] = (
                            self._count_metadata_cards()
                        )
                    self._activity(
                        f"Metadata ready: {set_name} "
                        f"({language}) — {len(normalized)} cards."
                    )
                except Exception as exc:
                    with self._lock:
                        self._state["metadata"]["sets_failed"] += 1
                        self._state["metadata"]["last_error"] = str(exc)
                    self._activity(
                        f"Metadata failed: {set_name} ({language}) — {exc}"
                    )

                self._refresh_metrics()

            with self._lock:
                self._state["metadata"].update({
                    "busy": False,
                    "phase": "COMPLETE",
                    "current_set": None,
                    "current_language": None,
                    "elapsed_seconds": round(time.perf_counter() - started, 1),
                    "eta_seconds": 0,
                })
                self._state["catalog_ready"] = True

            self._activity(
                "Metadata catalog is ready. HD artwork can now run independently."
            )
        except Exception as exc:
            with self._lock:
                self._state["metadata"].update({
                    "busy": False,
                    "phase": "FAILED",
                    "last_error": str(exc),
                })
            self._activity(f"Metadata pipeline failed: {exc}")

    def _normalize_metadata(
        self,
        provider_id: str,
        language: str,
        set_id: str,
        set_name: str,
        payload: dict[str, Any],
        cards: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        language_code = self._language_code(language)
        result: list[dict[str, Any]] = []

        for position, card in enumerate(cards, start=1):
            local_id = str(
                card.get("localId")
                or card.get("number")
                or card.get("id")
                or position
            )
            image_value = (
                card.get("image")
                or (card.get("images") or {}).get("large")
                or (card.get("images") or {}).get("small")
            )
            image_url = self._resolve_image_url(image_value)

            result.append({
                "id": card.get("id") or f"{set_id}-{local_id}",
                "name": card.get("name"),
                "printed_name": card.get("name"),
                "english_name": card.get("name") if language == "English" else None,
                "language": language,
                "language_code": language_code,
                "set_id": set_id,
                "set_name": set_name,
                "collector_number": local_id,
                "local_id": local_id,
                "rarity": card.get("rarity"),
                "hp": card.get("hp"),
                "types": card.get("types") or [],
                "illustrator": card.get("illustrator") or card.get("artist"),
                "image_url": image_url,
                "local_image": self._existing_local_image(
                    language_code,
                    set_id,
                    str(card.get("id") or f"{set_id}-{local_id}"),
                ),
                "source": provider_id,
            })

        return result

    def _write_metadata_set(
        self,
        provider_id: str,
        language: str,
        set_id: str,
        set_name: str,
        payload: dict[str, Any],
        cards: list[dict[str, Any]],
    ) -> None:
        language_code = self._language_code(language)
        set_dir = self.sets_root / self._safe(f"{language_code}_{set_id}")
        set_dir.mkdir(parents=True, exist_ok=True)

        (set_dir / "cards.json").write_text(
            json.dumps(cards, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = {
            "catalog_format": "RareIQ Metadata Catalog v2",
            "provider": provider_id,
            "language": language,
            "language_code": language_code,
            "set_id": set_id,
            "set_name": set_name,
            "cards": len(cards),
            "metadata_ready": True,
            "hd_images_ready": sum(
                1 for card in cards if card.get("local_image")
            ),
            "imported_at": time.time(),
        }
        (set_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _pause_metadata(self) -> None:
        with self._lock:
            self._state["metadata"].update({
                "busy": False,
                "phase": "PAUSED",
            })
        self._activity("Metadata pipeline paused. Completed sets were preserved.")

    # --------------------------------------------------------------
    # HD artwork stage
    # --------------------------------------------------------------
    def _build_image_queue(self) -> list[dict[str, str]]:
        queue_items: list[dict[str, str]] = []

        for cards_file in self.sets_root.glob("*/cards.json"):
            try:
                cards = json.loads(cards_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            for card in cards if isinstance(cards, list) else []:
                image_url = str(card.get("image_url") or "").strip()
                if not image_url:
                    continue

                language_code = str(card.get("language_code") or "unknown")
                set_id = str(card.get("set_id") or "unknown")
                card_id = str(card.get("id") or card.get("local_id") or "card")
                destination = (
                    self.image_root
                    / language_code
                    / self._safe(set_id)
                    / f"{self._safe(card_id)}.webp"
                )

                if destination.exists() and destination.stat().st_size > 1024:
                    continue

                queue_items.append({
                    "url": image_url,
                    "destination": str(destination),
                    "card_id": card_id,
                    "set_id": set_id,
                    "language_code": language_code,
                })

        return queue_items

    def _image_worker(
        self,
        queue_items: list[dict[str, str]],
        workers: int,
    ) -> None:
        started = time.perf_counter()
        completed = skipped = failed = bytes_downloaded = 0

        def download_one(item: dict[str, str]) -> tuple[str, int, str | None]:
            destination = Path(item["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)

            if destination.exists() and destination.stat().st_size > 1024:
                return "skipped", 0, None

            try:
                with httpx.Client(
                    timeout=httpx.Timeout(45.0, connect=10.0),
                    follow_redirects=True,
                    limits=httpx.Limits(
                        max_connections=4,
                        max_keepalive_connections=2,
                    ),
                ) as client:
                    content, _ = download_bytes(client, item["url"])
                temp = destination.with_suffix(destination.suffix + ".part")
                temp.write_bytes(content)
                temp.replace(destination)
                return "completed", len(content), None
            except Exception as exc:
                return "failed", 0, str(exc)

        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(download_one, item): item
                    for item in queue_items
                }

                for future in as_completed(futures):
                    if self._stop.is_set():
                        for pending in futures:
                            pending.cancel()
                        break

                    item = futures[future]
                    status, size, error = future.result()
                    if status == "completed":
                        completed += 1
                        bytes_downloaded += size
                    elif status == "skipped":
                        skipped += 1
                    else:
                        failed += 1

                    elapsed = max(0.001, time.perf_counter() - started)
                    processed = completed + skipped + failed
                    rate = bytes_downloaded / elapsed / (1024 * 1024)
                    remaining = max(0, len(queue_items) - processed)
                    items_per_second = processed / elapsed
                    eta = (
                        round(remaining / items_per_second, 1)
                        if items_per_second > 0 else None
                    )

                    with self._lock:
                        self._state["images"].update({
                            "completed": completed,
                            "skipped": skipped,
                            "failed": failed,
                            "bytes_downloaded": bytes_downloaded,
                            "mb_per_second": round(rate, 2),
                            "current": item.get("card_id"),
                            "elapsed_seconds": round(elapsed, 1),
                            "eta_seconds": eta,
                            "last_error": error,
                        })

                    if processed == 1 or processed % 50 == 0:
                        self._activity(
                            f"HD artwork: {processed}/{len(queue_items)} "
                            f"files at {rate:.2f} MB/s."
                        )
                    else:
                        self._save()

            phase = "PAUSED" if self._stop.is_set() else "COMPLETE"
            with self._lock:
                self._state["images"].update({
                    "busy": False,
                    "phase": phase,
                    "current": None,
                })
            self._activity(
                "HD artwork paused safely."
                if phase == "PAUSED"
                else "HD artwork backfill complete."
            )
        except Exception as exc:
            with self._lock:
                self._state["images"].update({
                    "busy": False,
                    "phase": "FAILED",
                    "last_error": str(exc),
                })
            self._activity(f"HD artwork pipeline failed: {exc}")

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    def _refresh_metrics(self) -> None:
        now = time.time()
        with self._lock:
            metadata = self._state["metadata"]
            if metadata.get("busy") and metadata.get("started_at"):
                elapsed = max(0.0, now - float(metadata["started_at"]))
                metadata["elapsed_seconds"] = round(elapsed, 1)
                done = (
                    int(metadata.get("sets_completed") or 0)
                    + int(metadata.get("sets_failed") or 0)
                )
                total = int(metadata.get("sets_discovered") or 0)
                metadata["eta_seconds"] = (
                    round((total - done) * elapsed / done, 1)
                    if done > 0 and total > done else None
                )

            images = self._state["images"]
            if images.get("busy") and images.get("started_at"):
                images["elapsed_seconds"] = round(
                    max(0.0, now - float(images["started_at"])),
                    1,
                )

            self._state["updated_at"] = now
        self._save()

    def _count_metadata_cards(self) -> int:
        total = 0
        for cards_file in self.sets_root.glob("*/cards.json"):
            try:
                payload = json.loads(cards_file.read_text(encoding="utf-8"))
                total += len(payload) if isinstance(payload, list) else 0
            except Exception:
                continue
        return total

    def _existing_local_image(
        self,
        language_code: str,
        set_id: str,
        card_id: str,
    ) -> str | None:
        path = (
            self.image_root
            / language_code
            / self._safe(set_id)
            / f"{self._safe(card_id)}.webp"
        )
        return str(path) if path.exists() else None

    @staticmethod
    def _language_code(language: str) -> str:
        return {
            "English": "en",
            "Japanese": "ja",
            "Traditional Chinese": "zh-tw",
            "Simplified Chinese": "zh-cn",
            "French": "fr",
            "German": "de",
            "Italian": "it",
            "Spanish": "es",
            "Portuguese": "pt",
        }.get(language, language.lower().replace(" ", "-"))

    @staticmethod
    def _resolve_image_url(value: Any) -> str | None:
        if not value:
            return None
        text = str(value)
        if text.startswith("http"):
            if text.endswith(".webp") or text.endswith(".png") or text.endswith(".jpg"):
                return text
            return text + "/high.webp"
        return None

    @staticmethod
    def _safe(value: str) -> str:
        return "".join(
            character if character.isalnum() or character in "-_." else "_"
            for character in value
        ).strip("._") or "item"
