from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import cv2

from rareiq.services.recognition_service import RecognitionService


class StreamSpeedBenchmarkService:
    """Replay captured cards through the visual fast-path decision gate."""

    def __init__(self, global_visual_index: Any, artwork_index: Any) -> None:
        self.global_visual_index = global_visual_index
        self.artwork_index = artwork_index

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[int((len(ordered) - 1) * fraction)], 2)

    @staticmethod
    def _candidate_summary(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
        if not candidate:
            return None
        return {
            key: candidate.get(key)
            for key in (
                "id", "name", "english_name", "set_id", "collector_number",
                "identity_override_key", "score", "source", "image_path",
                "verification_strong",
            )
            if candidate.get(key) not in (None, "")
        }

    @staticmethod
    def _matches_expected(candidate: dict[str, Any], expected: dict[str, Any]) -> bool:
        comparable = {
            key: str(value).strip().casefold()
            for key, value in expected.items()
            if value not in (None, "")
        }
        return bool(comparable) and all(
            str(candidate.get(key) or "").strip().casefold() == value
            for key, value in comparable.items()
        )

    def run(
        self,
        samples: list[dict[str, Any]],
        *,
        target_p95_ms: float = 250.0,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        global_times: list[float] = []
        artwork_times: list[float] = []
        preflight_times: list[float] = []
        total_times: list[float] = []

        for sample in samples:
            path = Path(str(sample.get("path") or ""))
            image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
            if image is None or not image.size:
                rows.append({"path": str(path), "ok": False, "error": "unreadable_image"})
                continue

            replay_started = time.perf_counter()
            started = time.perf_counter()
            global_result = self.global_visual_index.search_image(image, limit=15)
            global_ms = (time.perf_counter() - started) * 1000
            global_candidates = list(global_result.get("matches") or [])
            preflight_started = time.perf_counter()
            hinted_result = (
                self.artwork_index.search_hinted(
                    image, global_candidates[:15], limit=4
                )
                if hasattr(self.artwork_index, "search_hinted")
                else {"matches": [], "hint_hits": 0}
            )
            preflight_ms = (time.perf_counter() - preflight_started) * 1000
            hinted_evidence = RecognitionService._fast_path_evidence(
                global_candidates, list(hinted_result.get("matches") or [])
            )
            if hinted_evidence:
                artwork_result = hinted_result
                artwork_ms = preflight_ms
            else:
                started = time.perf_counter()
                artwork_result = self.artwork_index.search(image, limit=10)
                artwork_ms = preflight_ms + (time.perf_counter() - started) * 1000
            total_ms = (time.perf_counter() - replay_started) * 1000
            artwork_candidates = list(artwork_result.get("matches") or [])
            cached_artwork_evidence = (
                RecognitionService._cached_artwork_fast_path_evidence(
                    artwork_result
                )
            )
            evidence = (
                hinted_evidence
                or cached_artwork_evidence
                or RecognitionService._fast_path_evidence(
                    global_candidates, artwork_candidates
                )
            )
            expected = sample.get("expected") if isinstance(sample.get("expected"), dict) else None
            correct = (
                self._matches_expected(artwork_candidates[0], expected)
                if evidence and expected and artwork_candidates else None
            )
            rows.append({
                "path": str(path),
                "ok": bool(global_result.get("ok")) and bool(artwork_result.get("ok", True)),
                "expected": expected,
                "fast_path_eligible": bool(evidence),
                "artwork_fallback": not bool(
                    hinted_evidence or cached_artwork_evidence
                ),
                "recognition_path": "fast" if evidence else "full",
                "fast_path_reason": evidence.get("reason") if evidence else None,
                "hint_hits": int(hinted_result.get("hint_hits", 0) or 0),
                "fast_path_correct": correct,
                "evidence": evidence,
                "global_top": self._candidate_summary(global_candidates[0] if global_candidates else None),
                "artwork_top": self._candidate_summary(artwork_candidates[0] if artwork_candidates else None),
                "timings_ms": {
                    "global_visual": round(global_ms, 2),
                    "artwork_search": round(artwork_ms, 2),
                    "artwork_preflight": round(preflight_ms, 2),
                    "visual_total": round(total_ms, 2),
                },
            })
            global_times.append(global_ms)
            artwork_times.append(artwork_ms)
            preflight_times.append(preflight_ms)
            total_times.append(total_ms)

        successful = [row for row in rows if row.get("ok")]
        labeled = [row for row in successful if row.get("expected")]
        eligible = [row for row in successful if row.get("fast_path_eligible")]
        labeled_eligible = [row for row in eligible if row.get("fast_path_correct") is not None]
        false_locks = sum(row.get("fast_path_correct") is False for row in labeled_eligible)
        latency_p95 = self._percentile(total_times, 0.95)
        fast_path_times = [
            float(row["timings_ms"]["visual_total"]) for row in eligible
        ]
        fast_path_p95 = self._percentile(fast_path_times, 0.95)
        accuracy_gate = (
            "pass" if labeled_eligible and false_locks == 0
            else "fail" if false_locks
            else "not_evaluated"
        )
        latency_gate = (
            "pass" if fast_path_p95 is not None and fast_path_p95 <= target_p95_ms
            else "fail"
        )
        return {
            "ok": bool(successful),
            "created_at": time.time(),
            "sample_count": len(samples),
            "successful_count": len(successful),
            "labeled_sample_count": len(labeled),
            "unlabeled_sample_count": len(successful) - len(labeled),
            "label_coverage_rate": round(len(labeled) / len(successful), 4) if successful else 0.0,
            "fast_path_eligible_count": len(eligible),
            "fast_path_eligible_rate": round(len(eligible) / len(successful), 4) if successful else 0.0,
            "labeled_fast_path_count": len(labeled_eligible),
            "false_lock_count": false_locks,
            "latency_ms": {
                "global_visual_mean": round(statistics.mean(global_times), 2) if global_times else None,
                "artwork_search_mean": round(statistics.mean(artwork_times), 2) if artwork_times else None,
                "artwork_preflight_mean": round(statistics.mean(preflight_times), 2) if preflight_times else None,
                "visual_total_p50": self._percentile(total_times, 0.50),
                "visual_total_p95": latency_p95,
                "fast_path_p50": self._percentile(fast_path_times, 0.50),
                "fast_path_p95": fast_path_p95,
            },
            "gates": {
                "fast_path_p95_under_target": latency_gate,
                "zero_false_locks": accuracy_gate,
                "target_p95_ms": float(target_p95_ms),
                "ready": latency_gate == "pass" and accuracy_gate == "pass",
            },
            "samples": rows,
        }
