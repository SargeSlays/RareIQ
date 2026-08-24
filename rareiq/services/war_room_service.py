from __future__ import annotations

from typing import Any

from rareiq.core.plugin_manager import plugin_manager


class WarRoomService:
    def __init__(
        self,
        asset_manager: Any,
        benchmark_service: Any,
        fast_pipeline: Any,
        visual_index: Any,
    ) -> None:
        self.asset_manager = asset_manager
        self.benchmark_service = benchmark_service
        self.fast_pipeline = fast_pipeline
        self.visual_index = visual_index

    def status(self) -> dict[str, Any]:
        pipeline = self.fast_pipeline.status()
        visual = self.visual_index.status()
        assets = self.asset_manager.status()

        return {
            "mission": "Wide Architecture Rebuild",
            "plugins": plugin_manager.list_plugins(),
            "systems": {
                "storage": "ready",
                "metadata_pipeline": pipeline["metadata"].get("phase", "IDLE"),
                "hd_artwork": pipeline["images"].get("phase", "IDLE"),
                "visual_index": (
                    "ready" if visual.get("ready") else "not_ready"
                ),
                "asset_registry": (
                    "ready" if assets.get("assets", 0) >= 0 else "error"
                ),
                "recognition_fusion": "ready",
                "benchmarking": "ready",
            },
            "metrics": {
                "metadata_cards": pipeline["metadata"].get("cards", 0),
                "images_downloaded": pipeline["images"].get("completed", 0),
                "visual_records": visual.get("records", 0),
                "registered_assets": assets.get("assets", 0),
                "asset_bytes": assets.get("bytes", 0),
            },
        }
