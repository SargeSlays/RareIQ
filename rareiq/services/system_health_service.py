from __future__ import annotations

import threading
import time
from typing import Any


class SystemHealthService:
    def __init__(
        self,
        vision: Any,
        recognition: Any,
        visual_index: Any,
        asset_manager: Any,
        fast_pipeline: Any,
        provider_diagnostics: Any,
        job_queue: Any,
        storage_manager: Any,
    ) -> None:
        self.vision = vision
        self.recognition = recognition
        self.visual_index = visual_index
        self.asset_manager = asset_manager
        self.fast_pipeline = fast_pipeline
        self.provider_diagnostics = provider_diagnostics
        self.job_queue = job_queue
        self.storage_manager = storage_manager

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._auto_index_enabled = True
        self._last_auto_index_check = 0.0
        self._available_local_images: int | None = None
        self._available_local_images_checked_at: float | None = None
        self._worker = threading.Thread(
            target=self._watch,
            daemon=True,
            name="rareiq-health-monitor",
        )
        self._worker.start()

    def status(self) -> dict[str, Any]:
        visual = self.visual_index.status()
        providers = self.provider_diagnostics.status()
        pipeline = self.fast_pipeline.status()

        with self._lock:
            available_images = self._available_local_images
            available_images_checked_at = self._available_local_images_checked_at

        camera = self.vision.status()
        recognition = self.recognition.status()
        assets = self.asset_manager.status()
        jobs = self.job_queue.status()
        storage = self.storage_manager.health()

        systems = {
            "camera": self._state(
                bool(camera.get("running") or camera.get("connected")),
                "online" if camera.get("running") or camera.get("connected") else "offline",
            ),
            "recognition": self._state(True, "ready"),
            "visual_index": self._state(
                bool(visual.get("ready")),
                "ready" if visual.get("ready") else "not_ready",
            ),
            "metadata": self._state(
                bool(pipeline.get("catalog_ready")),
                pipeline.get("metadata", {}).get("phase", "IDLE"),
            ),
            "providers": self._state(
                any(
                    result.get("online")
                    for result in (providers.get("providers") or {}).values()
                ),
                "online" if providers.get("providers") else "unchecked",
            ),
            "storage": {
                "ok": bool(storage.get("healthy")),
                "status": storage.get("state") or "unknown",
                "message": storage.get("message"),
                "free_bytes": storage.get("free_bytes"),
                "recovery": storage.get("recovery"),
            },
            "asset_registry": self._state(True, "ready"),
            "job_queue": self._state(True, "ready"),
        }

        return {
            "systems": systems,
            "metrics": {
                "indexed_cards": int(visual.get("records") or 0),
                "available_local_images": available_images,
                "available_local_images_checked_at": available_images_checked_at,
                "unindexed_local_images": (
                    max(0, available_images - int(visual.get("records") or 0))
                    if available_images is not None
                    else None
                ),
                "registered_assets": int(assets.get("assets") or 0),
                "queued_jobs": int(jobs.get("queued") or 0),
                "storage_free_bytes": int(storage.get("free_bytes") or 0),
                "recovery_age_hours": (storage.get("recovery") or {}).get("age_hours"),
            },
            "auto_index_enabled": self._auto_index_enabled,
            "current_job": jobs.get("current"),
            "healthy": all(
                item["ok"]
                for name, item in systems.items()
                if name not in {"camera", "providers"}
            ),
        }

    def set_auto_index(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._auto_index_enabled = bool(enabled)
        return {
            "ok": True,
            "auto_index_enabled": self._auto_index_enabled,
        }

    def shutdown(self) -> None:
        self._stop.set()
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)

    def _watch(self) -> None:
        while not self._stop.is_set():
            try:
                self._refresh_available_images()
            except Exception:
                pass

            if self._stop.wait(60.0):
                break

    def _refresh_available_images(self) -> None:
        visual = self.visual_index.status()
        if visual.get("busy"):
            return

        available = self.visual_index.available_local_image_count()
        checked_at = time.time()
        indexed = int(visual.get("records") or 0)
        with self._lock:
            self._available_local_images = available
            self._available_local_images_checked_at = checked_at
            self._last_auto_index_check = checked_at
            auto_index_enabled = self._auto_index_enabled

        if not auto_index_enabled or available <= indexed:
            return

        queue_status = self.job_queue.status()
        if not queue_status.get("current"):
            self.job_queue.submit(
                "Incremental Recognition Index",
                self.visual_index.incremental_update,
            )

    @staticmethod
    def _state(ok: bool, status: str) -> dict[str, Any]:
        return {"ok": bool(ok), "status": status}
