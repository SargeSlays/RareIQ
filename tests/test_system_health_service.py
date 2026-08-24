from __future__ import annotations

import threading

from rareiq.services.system_health_service import SystemHealthService


class _StatusDouble:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {}

    def status(self) -> dict:
        return dict(self.payload)


class _StorageDouble:
    def health(self) -> dict:
        return {
            "healthy": True,
            "state": "ready",
            "message": "Storage healthy.",
            "free_bytes": 1024,
            "recovery": {},
        }


class _VisualIndexDouble(_StatusDouble):
    def __init__(self, available: int = 12) -> None:
        super().__init__({"ready": True, "records": 10, "busy": False})
        self.available = available
        self.inventory_calls = 0

    def available_local_image_count(self) -> int:
        self.inventory_calls += 1
        return self.available

    def incremental_update(self) -> None:
        return None


class _QueueDouble(_StatusDouble):
    def __init__(self) -> None:
        super().__init__({"queued": 0, "current": None})
        self.submissions: list[tuple[str, object]] = []

    def submit(self, name: str, callback: object) -> None:
        self.submissions.append((name, callback))


def _service() -> tuple[SystemHealthService, _VisualIndexDouble, _QueueDouble]:
    visual = _VisualIndexDouble()
    queue = _QueueDouble()
    service = SystemHealthService.__new__(SystemHealthService)
    service.vision = _StatusDouble({"running": True})
    service.recognition = _StatusDouble()
    service.visual_index = visual
    service.asset_manager = _StatusDouble({"assets": 3})
    service.fast_pipeline = _StatusDouble({"catalog_ready": True, "metadata": {}})
    service.provider_diagnostics = _StatusDouble({"providers": {}})
    service.job_queue = queue
    service.storage_manager = _StorageDouble()
    service._lock = threading.RLock()
    service._stop = threading.Event()
    service._auto_index_enabled = True
    service._last_auto_index_check = 0.0
    service._available_local_images = None
    service._available_local_images_checked_at = None
    return service, visual, queue


def test_status_never_walks_the_local_image_catalog() -> None:
    service, visual, _ = _service()

    health = service.status()

    assert visual.inventory_calls == 0
    assert health["metrics"]["indexed_cards"] == 10
    assert health["metrics"]["available_local_images"] is None
    assert health["metrics"]["unindexed_local_images"] is None
    assert health["metrics"]["available_local_images_checked_at"] is None


def test_background_refresh_caches_inventory_and_preserves_auto_index() -> None:
    service, visual, queue = _service()

    service._refresh_available_images()
    health = service.status()

    assert visual.inventory_calls == 1
    assert health["metrics"]["available_local_images"] == 12
    assert health["metrics"]["unindexed_local_images"] == 2
    assert health["metrics"]["available_local_images_checked_at"] is not None
    assert len(queue.submissions) == 1
    assert queue.submissions[0][0] == "Incremental Recognition Index"
