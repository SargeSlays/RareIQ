from __future__ import annotations

import json
import time
import uuid
from typing import Any

from rareiq.core.storage import storage


class LearningQueueService:
    def __init__(self) -> None:
        self.root = storage.get_path("grading_path") / "learning_queue"
        self.root.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        *,
        scan_payload: dict[str, Any],
        reason: str,
        correct_card_id: str | None = None,
    ) -> dict[str, Any]:
        item_id = uuid.uuid4().hex
        payload = {
            "id": item_id,
            "created_at": time.time(),
            "reason": reason,
            "correct_card_id": correct_card_id,
            "scan": scan_payload,
        }
        path = self.root / f"{item_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "id": item_id, "path": str(path)}

    def status(self) -> dict[str, Any]:
        return {
            "queued": len(list(self.root.glob("*.json"))),
            "root": str(self.root),
        }
