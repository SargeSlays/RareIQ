from __future__ import annotations

import statistics
import time
from typing import Any

import cv2
import numpy as np


class X7BenchmarkService:
    def __init__(self, optimizer: Any, ranker: Any) -> None:
        self.optimizer = optimizer
        self.ranker = ranker

    def run(self, iterations: int = 100) -> dict[str, Any]:
        image = np.zeros((900, 640, 3), dtype=np.uint8)
        cv2.rectangle(image, (70, 60), (570, 840), (205, 205, 205), -1)
        cv2.putText(
            image,
            "RareIQ Benchmark Card",
            (105, 170),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )

        candidates = [
            {
                "id": "benchmark-1",
                "name": "RareIQ Benchmark Card",
                "score": 0.97,
                "collector_number": "001",
                "language": "English",
            },
            {
                "id": "benchmark-2",
                "name": "Different Card",
                "score": 0.72,
                "collector_number": "002",
                "language": "English",
            },
        ]
        ocr = {
            "text": "RareIQ Benchmark Card",
            "collector_number": "001",
            "language": "English",
        }

        optimize_times = []
        rank_times = []
        last_result = None

        for _ in range(max(1, iterations)):
            started = time.perf_counter()
            optimized = self.optimizer.optimize(image)
            optimize_times.append((time.perf_counter() - started) * 1000)

            started = time.perf_counter()
            last_result = self.ranker.rank(
                visual_candidates=candidates,
                ocr_payload=ocr,
                quality=optimized["quality"],
            )
            rank_times.append((time.perf_counter() - started) * 1000)

        return {
            "ok": True,
            "iterations": iterations,
            "vision_mean_ms": round(statistics.mean(optimize_times), 4),
            "vision_p95_ms": round(
                sorted(optimize_times)[int(len(optimize_times) * 0.95) - 1],
                4,
            ),
            "ranking_mean_ms": round(statistics.mean(rank_times), 4),
            "ranking_p95_ms": round(
                sorted(rank_times)[int(len(rank_times) * 0.95) - 1],
                4,
            ),
            "top_candidate": last_result[0] if last_result else None,
        }
