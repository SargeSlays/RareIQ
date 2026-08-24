from __future__ import annotations

import json
import statistics
import time
from typing import Any

from rareiq.core.storage import storage


class BenchmarkService:
    def __init__(self, fusion_service: Any) -> None:
        self.fusion_service = fusion_service
        self.results_path = (
            storage.get_path("log_path") / "benchmarks" / "latest.json"
        )
        self.results_path.parent.mkdir(parents=True, exist_ok=True)

    def run_fusion_benchmark(self, iterations: int = 10000) -> dict[str, Any]:
        samples = {
            "visual_similarity": 0.96,
            "collector_number": 1.0,
            "ocr_name": 0.88,
            "language": 1.0,
            "layout": 0.92,
            "color_profile": 0.91,
            "rarity_hint": 0.84,
        }

        timings = []
        result = None
        for _ in range(max(1, iterations)):
            started = time.perf_counter()
            result = self.fusion_service.score(samples)
            timings.append((time.perf_counter() - started) * 1000)

        payload = {
            "ok": True,
            "iterations": iterations,
            "mean_ms": round(statistics.mean(timings), 6),
            "p95_ms": round(
                sorted(timings)[int(len(timings) * 0.95) - 1],
                6,
            ),
            "max_ms": round(max(timings), 6),
            "sample_result": result,
            "created_at": time.time(),
        }
        self.results_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return payload

    def latest(self) -> dict[str, Any]:
        if not self.results_path.exists():
            return {"ok": False, "error": "No benchmark has been run."}
        return json.loads(self.results_path.read_text(encoding="utf-8"))
