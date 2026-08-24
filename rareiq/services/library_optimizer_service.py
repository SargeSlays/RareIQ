from __future__ import annotations

from typing import Any


class LibraryOptimizerService:
    def __init__(
        self,
        asset_manager: Any,
        visual_index: Any,
        recognition: Any,
    ) -> None:
        self.asset_manager = asset_manager
        self.visual_index = visual_index
        self.recognition = recognition

    def run(self) -> dict[str, Any]:
        asset_result = self.asset_manager.scan_images()
        index_result = self.visual_index.incremental_update()
        self.recognition.set_global_visual_index(self.visual_index)

        return {
            "ok": True,
            "assets": asset_result,
            "index": index_result,
        }
