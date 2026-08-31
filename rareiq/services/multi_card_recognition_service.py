from __future__ import annotations

import threading
import time
from copy import deepcopy
from collections import Counter
from difflib import SequenceMatcher
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

import cv2
import numpy as np

from rareiq.services.recognition_service import RecognitionService
from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.vision_service import VisionService

LOGGER = logging.getLogger(__name__)


class SixCardGridDetector:
    """Detect a configurable tabletop grid of up to twelve cards."""

    ROWS = 2
    COLUMNS = 3
    DEFAULT_CARDS = 6
    MAX_CARDS = 12

    @staticmethod
    def _card_structure_score(crop: np.ndarray | None) -> tuple[float, dict[str, float]]:
        """Cheaply reject skin/tabletop rectangles before catalog recognition.

        A real trading card has repeated long horizontal rules (name, artwork,
        text and footer) plus several vertical border segments.  A tattooed arm
        can have plenty of edges, but very few edges spanning a meaningful part
        of the rectified crop.  Keeping this gate before OCR is both safer and
        considerably cheaper than recognizing a false region.
        """
        if crop is None or not getattr(crop, "size", 0):
            return 0.0, {"edge_density": 0.0, "horizontal_rules": 0.0, "vertical_rules": 0.0}
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (250, 350), interpolation=cv2.INTER_AREA)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 45, 135)
        edge_density = float(np.count_nonzero(edges)) / float(edges.size)
        horizontal_rules = int(np.count_nonzero(np.mean(edges > 0, axis=1) >= 0.16))
        vertical_rules = int(np.count_nonzero(np.mean(edges > 0, axis=0) >= 0.12))
        density_score = float(np.clip((edge_density - 0.010) / 0.055, 0.0, 1.0))
        horizontal_score = float(np.clip(horizontal_rules / 9.0, 0.0, 1.0))
        vertical_score = float(np.clip(vertical_rules / 5.0, 0.0, 1.0))
        score = density_score * 0.30 + horizontal_score * 0.45 + vertical_score * 0.25
        return score, {
            "edge_density": round(edge_density, 5),
            "horizontal_rules": float(horizontal_rules),
            "vertical_rules": float(vertical_rules),
        }

    @classmethod
    def _contour_candidates(cls, frame: np.ndarray) -> list[dict[str, Any]]:
        """Find every card-shaped tabletop contour before recognition ranking.

        The single-card detector intentionally returns only its strongest contour.
        That behavior is correct for live single-card recognition, but it caused a
        neighboring card to win several overlapping grid windows.  Multi-card mode
        instead proposes isolated full-frame rectangles and recognizes each crop.
        """
        height, width = frame.shape[:2]
        frame_area = float(height * width)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        median = float(np.median(blurred))
        lower = int(max(18, median * 0.55))
        upper = int(min(235, max(lower + 35, median * 1.45)))
        edges = cv2.Canny(blurred, lower, upper)
        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            np.ones((5, 5), dtype=np.uint8),
            iterations=2,
        )
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        # Texture, glare and thin edges can break a card's perimeter while its
        # bright border still forms a complete silhouette. Opening removes thin
        # bridges before closing small gaps; external contours cannot select an
        # artwork/text rectangle inside the card. Keep edges as a dark-card fallback.
        _, silhouette = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel_size = max(3, int(round(min(width, height) / 120)) | 1)
        silhouette = cv2.morphologyEx(
            silhouette, cv2.MORPH_OPEN, np.ones((kernel_size, kernel_size), dtype=np.uint8)
        )
        silhouette = cv2.morphologyEx(
            silhouette, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
        )
        outer_contours, _ = cv2.findContours(silhouette, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        proposals: list[dict[str, Any]] = []
        for contour, external in [(item, True) for item in outer_contours] + [(item, False) for item in contours]:
            contour_area = abs(float(cv2.contourArea(contour)))
            rotated = cv2.minAreaRect(contour)
            rect_width, rect_height = rotated[1]
            rect_area = float(rect_width * rect_height)
            if rect_area <= 0.0 or min(rect_width, rect_height) < 55.0:
                continue
            area_fraction = rect_area / frame_area
            long_side = max(rect_width, rect_height)
            short_side = min(rect_width, rect_height)
            aspect = long_side / max(short_side, 1.0)
            fill = contour_area / rect_area
            # Three normal cards can each occupy ~10% of a tabletop frame.
            # The old 8.5% ceiling rejected their outer borders but retained
            # smaller artwork/text rectangles inside them.
            if not (0.012 <= area_fraction <= 0.35):
                continue
            if not ((1.08 if external else 1.18) <= aspect <= 1.82) or fill < 0.52:
                continue
            outline = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
            is_quad = len(outline) == 4 and cv2.isContourConvex(outline)
            if area_fraction > 0.085 and (not is_quad or fill < 0.70):
                continue
            points = VisionService._order(outline.reshape(4, 2) if is_quad else cv2.boxPoints(rotated))
            centroid = np.mean(points, axis=0) / np.array([width, height], dtype=np.float32)
            proposals.append({
                "points": points,
                "centroid": centroid,
                "area_fraction": area_fraction,
                "external": external,
                "foreshortened": aspect < 1.18,
                "confidence": float(np.clip(fill * 0.55 + (1.0 - abs(aspect - 1.40) / 0.40) * 0.45, 0.0, 1.0)),
            })

        isolated: list[dict[str, Any]] = []
        for proposal in sorted(
            proposals,
            key=lambda item: (item["external"], item["area_fraction"], item["confidence"]),
            reverse=True,
        ):
            proposal_polygon = proposal["points"].astype(np.float32)
            if any(
                float(np.linalg.norm(proposal["centroid"] - item["centroid"])) < 0.075
                or cls._polygon_iou(proposal_polygon, item["points"]) > 0.30
                or cls._polygon_containment(proposal_polygon, item["points"]) > 0.85
                for item in isolated
            ):
                continue
            points = proposal_polygon
            destination = np.array([
                [0, 0],
                [VisionService.OUTPUT_CROP_WIDTH - 1, 0],
                [VisionService.OUTPUT_CROP_WIDTH - 1, VisionService.OUTPUT_CROP_HEIGHT - 1],
                [0, VisionService.OUTPUT_CROP_HEIGHT - 1],
            ], dtype=np.float32)
            transform = cv2.getPerspectiveTransform(points, destination)
            crop = cv2.warpPerspective(
                frame,
                transform,
                (VisionService.OUTPUT_CROP_WIDTH, VisionService.OUTPUT_CROP_HEIGHT),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            if (proposal["area_fraction"] > 0.085 or proposal["foreshortened"]) and cls._card_structure_score(crop)[0] < 0.44:
                continue
            isolated.append({
                "row": -1,
                "column": -1,
                "confidence": round(float(proposal["confidence"]), 5),
                "polygon": (points / np.array([width, height], dtype=np.float32)).tolist(),
                "centroid": proposal["centroid"].tolist(),
                "crop": crop,
                "ocr_crop": crop,
                "boundary_source": "silhouette" if proposal["external"] else "edges",
                "points": points,
            })
        for item in isolated:
            item.pop("points", None)
        return isolated

    @staticmethod
    def _polygon_iou(left: np.ndarray, right: np.ndarray) -> float:
        left_hull = cv2.convexHull(np.asarray(left, dtype=np.float32))
        right_hull = cv2.convexHull(np.asarray(right, dtype=np.float32))
        left_area = abs(float(cv2.contourArea(left_hull)))
        right_area = abs(float(cv2.contourArea(right_hull)))
        intersection, _ = cv2.intersectConvexConvex(left_hull, right_hull)
        union = left_area + right_area - float(intersection)
        return float(intersection / union) if union > 0.0 else 0.0

    @staticmethod
    def _polygon_containment(left: np.ndarray, right: np.ndarray) -> float:
        """Suppress inner artwork/text regions even when their full-card IoU is small."""
        left_hull = cv2.convexHull(np.asarray(left, dtype=np.float32))
        right_hull = cv2.convexHull(np.asarray(right, dtype=np.float32))
        smaller = min(abs(float(cv2.contourArea(left_hull))), abs(float(cv2.contourArea(right_hull))))
        intersection, _ = cv2.intersectConvexConvex(left_hull, right_hull)
        return float(intersection / smaller) if smaller > 0.0 else 0.0

    @classmethod
    def detect(cls, frame: np.ndarray, max_cards: int = DEFAULT_CARDS) -> list[dict[str, Any]]:
        if frame is None or not getattr(frame, "size", 0):
            return []
        height, width = frame.shape[:2]
        candidates: list[dict[str, Any]] = cls._contour_candidates(frame)
        window_width = 0.28
        x_centers = (0.18, 0.34, 0.50, 0.66, 0.82)
        limit = max(2, min(cls.MAX_CARDS, int(max_cards or cls.DEFAULT_CARDS)))
        y_bounds = (
            ((0.0, 0.50), (0.25, 0.75), (0.50, 1.0))
            if limit > 8
            else ((0.0, 0.56), (0.48, 1.0))
        )
        for row, (top_fraction, bottom_fraction) in enumerate(y_bounds):
            for column, center_x in enumerate(x_centers):
                x1 = int(round(width * max(0.0, center_x - window_width / 2)))
                x2 = int(round(width * min(1.0, center_x + window_width / 2)))
                y1 = int(round(height * top_fraction))
                y2 = int(round(height * bottom_fraction))
                cell = frame[y1:y2, x1:x2]
                detected = VisionService.detect(cell)
                if detected.crop is None or detected.polygon is None:
                    continue
                structure_score, structure = cls._card_structure_score(detected.crop)
                if structure_score < 0.44:
                    continue
                polygon = detected.polygon.copy()
                polygon[:, 0] = (polygon[:, 0] * (x2 - x1) + x1) / width
                polygon[:, 1] = (polygon[:, 1] * (y2 - y1) + y1) / height
                centroid = np.mean(polygon, axis=0)
                candidates.append({
                    "row": row, "column": column,
                    "confidence": round(float(detected.confidence), 5),
                    "polygon": polygon.tolist(),
                    "centroid": centroid.tolist(),
                    "crop": detected.crop,
                    "ocr_crop": detected.ocr_crop,
                    "structure_score": round(structure_score, 5),
                    "structure": structure,
                })

        unique: list[dict[str, Any]] = []
        for candidate in sorted(candidates, key=lambda item: (
            abs(float(cv2.contourArea(np.asarray(item["polygon"], dtype=np.float32)))), item["confidence"]
        ), reverse=True):
            center = np.asarray(candidate["centroid"], dtype=np.float32)
            if any(
                # Twelve-card layouts commonly place adjacent centers only
                # 0.09-0.12 frame widths apart.  The previous 0.125 radius
                # collapsed neighboring cards into one detection.
                float(np.linalg.norm(center - np.asarray(item["centroid"], dtype=np.float32))) < 0.060
                or cls._polygon_iou(
                    np.asarray(candidate["polygon"], dtype=np.float32),
                    np.asarray(item["polygon"], dtype=np.float32),
                ) > 0.30
                or cls._polygon_containment(
                    np.asarray(candidate["polygon"], dtype=np.float32),
                    np.asarray(item["polygon"], dtype=np.float32),
                ) > 0.85
                for item in unique
            ):
                continue
            unique.append(candidate)
        if len(unique) >= 4:
            areas = [
                abs(float(cv2.contourArea(np.asarray(item["polygon"], dtype=np.float32))))
                for item in unique
            ]
            median_area = float(np.median(areas))
            if median_area > 0.0:
                unique = [
                    item for item, area in zip(unique, areas)
                    if 0.45 * median_area <= area <= 2.10 * median_area
                ]
        # Build adaptive visual rows before sorting left-to-right. Quantizing Y
        # against a fixed origin made slightly tilted top rows cross a bucket
        # boundary and reshuffled physical slot numbers between captures.
        heights = [
            float(np.ptp(np.asarray(item["polygon"], dtype=np.float32)[:, 1]))
            for item in unique
        ]
        row_tolerance = max(0.055, (float(np.median(heights)) if heights else 0.20) * 0.38)
        rows: list[list[dict[str, Any]]] = []
        for item in sorted(unique, key=lambda candidate: candidate["centroid"][1]):
            center_y = float(item["centroid"][1])
            target = next((
                row for row in rows
                if abs(center_y - float(np.mean([entry["centroid"][1] for entry in row]))) <= row_tolerance
            ), None)
            (target if target is not None else rows.append([]) or rows[-1]).append(item)
        unique = [
            item
            for row in sorted(rows, key=lambda entries: np.mean([entry["centroid"][1] for entry in entries]))
            for item in sorted(row, key=lambda candidate: candidate["centroid"][0])
        ]
        results = unique[:limit]
        for slot, item in enumerate(results, start=1):
            item["slot"] = slot
        return results


class MultiCardRecognitionService:
    """Run up to twelve independent recognition workers without touching live state."""

    TEMPORAL_HISTORY_VERSION = 1
    TEMPORAL_HISTORY_MAX_AGE_SECONDS = 6 * 60 * 60
    RECOGNITION_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        prototype: RecognitionService,
        history_path: Path | None = None,
        presentation_path: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._capture_lock = threading.Lock()
        self._artwork_index = getattr(prototype, "artwork_index", None)
        self._job_id = 0
        self._recognition_deadline: float | None = None
        self._workers: dict[int, RecognitionService] = {}
        self._candidate_cache: dict[int, list[dict[str, Any]]] = {}
        self._batch_hint_cache: dict[int, list[dict[str, Any]]] = {}
        self._crop_cache: dict[int, np.ndarray] = {}
        self._family_delegates: dict[int, list[int]] = {}
        self._temporal_history_path = history_path or (
            Path(__file__).resolve().parents[1] / "data" / "temporal_multi_card_history.json"
        )
        self._temporal_history: dict[int, dict[str, Any]] = self._load_temporal_history()
        self._reference_cards = self._load_reference_cards()
        self._reference_feature_cache: dict[str, dict[str, Any]] = {}
        self._reference_feature_cache_lock = threading.RLock()
        self._presentation_path = presentation_path or (
            Path(__file__).resolve().parents[1] / "data" / "multi_card_presentation.json"
        )
        self._selected_slots: set[int] = self._load_selected_slots()
        self._single_exact_history: dict[str, Any] = {}
        self._state: dict[str, Any] = self._load_completed_state() or self._empty_state()
        for slot in range(1, SixCardGridDetector.MAX_CARDS + 1):
            self._workers[slot] = prototype.isolated_copy(
                lambda event, current_slot=slot: self._on_event(current_slot, event)
            )

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "mode": "six-card-grid",
            "job_id": 0,
            "status": "idle",
            "detected_count": 0,
            "completed_count": 0,
            "started_at": None,
            "updated_at": time.time(),
            "slots": [
                {"slot": slot, "status": "empty", "card": None}
                for slot in range(1, SixCardGridDetector.DEFAULT_CARDS + 1)
            ],
        }

    def capture(self, frame: np.ndarray | None, *, unique_variants: bool = False, max_cards: int = SixCardGridDetector.DEFAULT_CARDS, detections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if not self._capture_lock.acquire(blocking=False):
            return {"ok": False, "reason": "capture_in_progress", **self.status()}
        try:
            with self._lock:
                self._expire_stalled_capture()
                if self._state.get("status") == "recognizing":
                    return {"ok": False, "reason": "recognition_in_progress", **self.status()}
            return self._capture(frame, unique_variants=unique_variants, max_cards=max_cards, detections=detections)
        except Exception:
            LOGGER.exception("multi_card_capture_failed job_id=%s", self._job_id)
            self._fail_capture("recognition_failed", "The scan failed. Choose Scan Cards to try again.")
            return self.status()
        finally:
            self._capture_lock.release()

    def _fail_capture(self, reason: str, message: str) -> None:
        """Fail closed and release a wedged grid without publishing partial identities."""
        with self._lock:
            self._recognition_deadline = None
            self._selected_slots.clear()
            for item in self._state["slots"]:
                if item.get("status") not in {"empty", "waiting", "not-detected"}:
                    item.update(status="error", verified=False, error=reason)
            self._state.update(status="error", ok=False, reason=reason, message=message,
                               completed_count=self._state.get("detected_count", 0),
                               selected_slots=[], updated_at=time.time())
            self._persist_presentation()

    def _expire_stalled_capture(self) -> None:
        # Called while holding _lock by status/capture; no background thread or
        # second camera owner is needed for the recovery deadline.
        if (self._state.get("status") == "recognizing" and self._recognition_deadline is not None
                and time.monotonic() >= self._recognition_deadline):
            self._fail_capture("recognition_timeout", "Recognition timed out. Keep the cards still and choose Scan Cards to retry.")

    def _capture(self, frame: np.ndarray | None, *, unique_variants: bool = False, max_cards: int = SixCardGridDetector.DEFAULT_CARDS, detections: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if frame is None or not getattr(frame, "size", 0):
            return {"ok": False, "reason": "no_current_frame", **self.status()}
        limit = max(2, min(SixCardGridDetector.MAX_CARDS, int(max_cards or SixCardGridDetector.DEFAULT_CARDS)))
        detections = detections if detections is not None else SixCardGridDetector.detect(frame, max_cards=limit)
        delegates = self._family_first_delegates(detections)
        with self._lock:
            detected_slots = {int(item["slot"]) for item in detections}
            self._selected_slots.intersection_update(detected_slots)
            self._job_id += 1
            self._candidate_cache = {}
            self._batch_hint_cache = {}
            self._crop_cache = {
                int(item["slot"]): item["crop"]
                for item in detections
            }
            self._family_delegates = delegates
            job_id = self._job_id
            slots = [
                {"slot": slot, "status": "not-detected", "card": None}
                for slot in range(1, limit + 1)
            ]
            for item in detections:
                slots[item["slot"] - 1] = {
                    "slot": item["slot"],
                    "status": "recognizing",
                    "card": None,
                    "confidence": None,
                    "detection_confidence": item["confidence"],
                    "polygon": item["polygon"],
                }
            self._state = {
                "mode": "six-card-grid",
                "job_id": job_id,
                "status": "recognizing" if detections else "no-cards-detected",
                "detected_count": len(detections),
                "completed_count": 0,
                "started_at": time.time(),
                "updated_at": time.time(),
                "unique_variants": bool(unique_variants),
                "max_cards": limit,
                "selected_slots": sorted(self._selected_slots),
                "slots": slots,
                "family_first": {
                    "full_worker_count": len(detections) - sum(len(items) for items in delegates.values()),
                    "delegated_slot_count": sum(len(items) for items in delegates.values()),
                    "families": {str(key): list(value) for key, value in delegates.items()},
                },
            }
            self._recognition_deadline = time.monotonic() + self.RECOGNITION_TIMEOUT_SECONDS if detections else None
            # A new/empty scan invalidates the previous completed presentation.
            # Restarting during analysis must not bring an old card back on air.
            self._persist_presentation()
        batch_started = time.perf_counter()
        batch = None
        if detections and self._artwork_index is not None and hasattr(
            self._artwork_index, "batch_shortlists"
        ):
            # Every worker receives its own shortlist, but the catalog is traversed
            # only once for the full frame.
            batch = self._artwork_index.batch_shortlists({
                int(item["slot"]): item["crop"] for item in detections
            })
            with self._lock:
                self._expire_stalled_capture()
                if self._state.get("status") == "error":
                    return self.status()
            for slot, shortlist in (batch.get("slots") or {}).items():
                hints = list(shortlist.get("artwork_candidates") or [])
                hints.extend(shortlist.get("hash_candidates") or [])
                self._batch_hint_cache[int(slot)] = [dict(item) for item in hints]
                family, family_votes, family_margin = self._batch_candidate_family(int(slot))
                if family and family_votes >= 3 and family_margin >= 2:
                    with self._lock:
                        live_slot = self._state["slots"][int(slot) - 1]
                        live_slot.update({
                            "card": {
                                "name": family,
                                "display_name": family,
                                "canonical_name": family,
                                "english_name": family,
                                "exact_version_unresolved": True,
                                "recognition_source": "batch-family-interim",
                            },
                            "status": "recognizing",
                            "verified": False,
                            "exact_version_unresolved": True,
                            "batch_family_interim": True,
                            "batch_family_votes": family_votes,
                            "batch_family_margin": family_margin,
                            "fast_candidate_latency_ms": round(
                                (time.perf_counter() - batch_started) * 1000,
                                1,
                            ),
                        })
                worker = self._workers[int(slot)]
                if hasattr(worker, "seed_batch_artwork_hints"):
                    worker.seed_batch_artwork_hints(job_id, int(slot), hints)
            with self._lock:
                self._state["batch_artwork"] = {
                    "latency_ms": round((time.perf_counter() - batch_started) * 1000, 1),
                    "catalog_records_visited": int(batch.get("catalog_records_visited") or 0),
                    "live_card_count": int(batch.get("live_card_count") or 0),
                }
        for item in detections:
            with self._lock:
                if self._state.get("status") == "error":
                    break
            if any(item["slot"] in siblings for siblings in delegates.values()):
                continue
            worker = self._workers[item["slot"]]
            worker.invalidate_before(job_id)
            result = worker.submit_frame(
                item["crop"],
                generation=job_id,
                frame_id=item["slot"],
                source="six-card-grid",
                ocr_frame=item.get("ocr_crop"),
            )
            if result != "accepted":
                self._update_slot(item["slot"], {"status": result})
                for sibling in delegates.get(item["slot"], []):
                    self._update_slot(sibling, {"status": result, "verified": False})
        return {"ok": bool(detections), **self.status()}

    def _family_first_delegates(self, detections: list[dict[str, Any]]) -> dict[int, list[int]]:
        """Return representative-to-sibling mappings for repeated artwork groups."""
        descriptors = {
            int(item["slot"]): self._sift_descriptors(item.get("crop"), treatment=False)
            for item in detections
        }
        remaining = set(descriptors)
        delegates: dict[int, list[int]] = {}
        while remaining:
            seed = remaining.pop()
            group = {seed}
            changed = True
            while changed:
                changed = False
                for slot in list(remaining):
                    if any(
                        self._descriptor_score(descriptors[slot], descriptors[member]) >= 45.0
                        for member in group
                    ):
                        remaining.remove(slot)
                        group.add(slot)
                        changed = True
            if len(group) >= 2:
                representative = max(
                    group,
                    key=lambda slot: float(detections[slot - 1].get("confidence") or 0.0),
                )
                delegates[representative] = sorted(group - {representative})
        return delegates

    def _on_event(self, slot: int, event: dict[str, Any]) -> None:
        if event.get("type") != "recognition_update":
            return
        payload = dict(event.get("payload") or {})
        with self._lock:
            self._expire_stalled_capture()
            if int(payload.get("generation") or 0) != self._job_id or self._state.get("status") == "error":
                return
            # Generation validation and writes share one lock. A new capture
            # cannot begin between the check and an old worker's slot update.
            try:
                if payload.get("recognition_path") == "worker-error":
                    self._fail_capture("recognition_failed", "Card analysis failed. Choose Scan Cards to try again.")
                    return
                self._apply_worker_payload(slot, payload)
                for sibling in self._family_delegates.get(slot, []):
                    delegated = dict(payload)
                    delegated["frame_id"] = sibling
                    self._apply_worker_payload(sibling, delegated, delegated_from=slot)
            except Exception:
                LOGGER.exception("multi_card_result_failed job_id=%s slot=%s", self._job_id, slot)
                self._fail_capture("result_processing_failed", "Card analysis failed. Choose Scan Cards to try again.")

    def _apply_worker_payload(
        self,
        slot: int,
        payload: dict[str, Any],
        *,
        delegated_from: int | None = None,
    ) -> None:
        is_visual_interim = payload.get("recognition_path") == "visual-interim"
        if is_visual_interim:
            with self._lock:
                current = self._state["slots"][slot - 1]
                if current.get("status") != "recognizing":
                    return
        candidates = list(payload.get("candidates") or [])
        with self._lock:
            self._candidate_cache[slot] = [dict(candidate) for candidate in candidates]
        card = payload.get("interim_candidate") if is_visual_interim else payload.get("database_match")
        if card and card.get("retrieval_only"):
            card = None
        if not is_visual_interim and not card:
            card = next((candidate for candidate in candidates
                         if not candidate.get("retrieval_only")
                         and not candidate.get("provisional")
                         and (candidate.get("verification_strong")
                              or candidate.get("printed_code_match")
                              or candidate.get("source") == "pokipair")), None)
        delegated_family_card = None
        if delegated_from is not None and card:
            canonical = str(
                card.get("canonical_name")
                or card.get("english_name")
                or card.get("name")
                or ""
            ).strip()
            if canonical:
                delegated_family_card = {
                    "name": canonical,
                    "display_name": canonical,
                    "canonical_name": canonical,
                    "english_name": canonical,
                    "printed_name": card.get("printed_name"),
                    "language": card.get("language") or payload.get("language"),
                    "set_id": card.get("set_id"),
                    "set_name": card.get("set_name"),
                    "exact_version_unresolved": True,
                    "recognition_source": "shared-family-fast-path",
                }
        if delegated_family_card is not None:
            card = delegated_family_card
        delegated_family_name = ""
        delegated_family_set_id = ""
        delegated_family_set_name = ""
        if delegated_from is not None:
            card = card or {}
            delegated_family_name = str(
                card.get("canonical_name")
                or card.get("english_name")
                or card.get("name")
                or ""
            ).strip()
            delegated_family_set_id = str(card.get("set_id") or "").strip()
            delegated_family_set_name = str(card.get("set_name") or "").strip()
        self._update_slot(slot, {
            "status": (
                "recognizing" if is_visual_interim
                else "review-needed" if delegated_from is not None
                else "verified" if card and payload.get("recognition_locked")
                else "review-needed"
            ),
            "verified": False if delegated_from is not None else bool(card and payload.get("recognition_locked")),
            "confidence": (None if not card else
                           float(payload.get("overall_confidence") if payload.get("overall_confidence") is not None
                                 else payload.get("confidence") or 0.0)),
            "card": card,
            "collector_number": None if delegated_from is not None else payload.get("ocr_collector_number") or payload.get("collector_number"),
            "printed_code": None if delegated_from is not None else payload.get("ocr_printed_code"),
            "name_candidate": payload.get("name_candidate"),
            "raw_text": list(payload.get("raw_text") or []),
            "language": payload.get("language"),
            "candidate_count": len(candidates),
            "candidate_preview": [dict(candidate) for candidate in candidates[:8]],
            "recognition_path": payload.get("recognition_path"),
            "stage_timings": dict(payload.get("stage_timings") or {}),
            "worker_total_ms": float(
                payload.get("last_latency_ms")
                or (payload.get("stage_timings") or {}).get("total_ms")
                or 0.0
            ),
            "family_first_delegated": delegated_from is not None,
            "delegated_from_slot": delegated_from,
            "delegated_family_name": delegated_family_name or None,
            "delegated_family_set_id": delegated_family_set_id or None,
            "delegated_family_set_name": delegated_family_set_name or None,
            "exact_version_unresolved": delegated_from is not None,
            "background_enrichment": bool(payload.get("background_enrichment")),
        })

    def _update_slot(self, slot: int, update: dict[str, Any]) -> None:
        with self._lock:
            current = self._state["slots"][slot - 1]
            was_pending = current.get("status") == "recognizing"
            current.update(update)
            if was_pending and current.get("status") != "recognizing":
                self._state["completed_count"] += 1
            if (
                self._state["detected_count"] > 0
                and self._state["completed_count"] >= self._state["detected_count"]
            ):
                reconciliation_started = time.perf_counter()
                phase_timings: dict[str, float] = {}
                phase_started = time.perf_counter()
                self._reconcile_dominant_family()
                phase_timings["dominant_family_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                detected_items = [
                    item for item in self._state["slots"]
                    if item.get("status") != "not-detected"
                ]
                trusted_family_fast_path = bool(
                    detected_items
                    and not self._state.get("unique_variants")
                    and all(
                        (item.get("stage_timings") or {}).get("family_shortlist_verified")
                        for item in detected_items
                    )
                )
                if trusted_family_fast_path:
                    phase_timings["visual_variants_ms"] = 0.0
                    phase_timings["visual_variants_skipped"] = True
                else:
                    phase_started = time.perf_counter()
                    self._resolve_visual_variant_families()
                    phase_timings["visual_variants_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                phase_started = time.perf_counter()
                self._reconcile_candidate_consensus()
                phase_timings["candidate_consensus_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                phase_started = time.perf_counter()
                self._reconcile_missing_artwork_families()
                phase_timings["artwork_family_safety_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                phase_started = time.perf_counter()
                self._reconcile_printed_codes()
                phase_timings["printed_codes_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                if trusted_family_fast_path:
                    phase_timings["unresolved_references_ms"] = 0.0
                    phase_timings["unresolved_references_skipped"] = True
                else:
                    phase_started = time.perf_counter()
                    self._reconcile_unresolved_references()
                    phase_timings["unresolved_references_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                phase_started = time.perf_counter()
                self._reconcile_ocr_identity()
                phase_timings["ocr_identity_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                phase_started = time.perf_counter()
                self._apply_temporal_confirmation()
                self._record_temporal_evidence()
                phase_timings["temporal_confirmation_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                if self._state.get("unique_variants"):
                    phase_started = time.perf_counter()
                    self._assign_unique_variants()
                    phase_timings["unique_variants_ms"] = round((time.perf_counter() - phase_started) * 1000, 1)
                self._synchronize_delegated_families()
                self._enforce_delegated_version_safety()
                self._enforce_exact_identity_safety()
                phase_timings["total_ms"] = round((time.perf_counter() - reconciliation_started) * 1000, 1)
                self._state["reconciliation_timings"] = phase_timings
                worker_totals = [float(item.get("worker_total_ms") or 0.0) for item in self._state["slots"] if item.get("worker_total_ms")]
                if worker_totals:
                    self._state["worker_latency_summary"] = {
                        "min_ms": round(min(worker_totals), 1),
                        "max_ms": round(max(worker_totals), 1),
                        "mean_ms": round(sum(worker_totals) / len(worker_totals), 1),
                    }
                self._state["status"] = "complete"
                self._recognition_deadline = None
                self._persist_presentation()
            self._state["updated_at"] = time.time()

    @staticmethod
    def _family_key(card: dict[str, Any] | None) -> tuple[str, str] | None:
        if not card:
            return None
        name = str(card.get("canonical_name") or card.get("name") or "").strip().casefold()
        set_id = str(card.get("set_id") or "").strip().casefold()
        return (name, set_id) if name and set_id else None

    def _enforce_delegated_version_safety(self) -> None:
        """Keep family-first delegates versionless until independently resolved."""
        for item in self._state["slots"]:
            if not item.get("family_first_delegated") or item.get("batch_variant_resolved"):
                continue
            source = dict(item.get("card") or {})
            canonical = str(item.get("delegated_family_name") or "").strip()
            if not canonical:
                canonical = str(
                    source.get("canonical_name")
                    or source.get("english_name")
                    or source.get("name")
                    or ""
                ).strip()
            item["card"] = {
                "name": canonical,
                "display_name": canonical,
                "canonical_name": canonical,
                "english_name": canonical,
                "printed_name": source.get("printed_name"),
                "language": source.get("language") or item.get("language"),
                "set_id": item.get("delegated_family_set_id") or source.get("set_id"),
                "set_name": item.get("delegated_family_set_name") or source.get("set_name"),
                "exact_version_unresolved": True,
                "recognition_source": "shared-family-fast-path",
            }
            item.update({
                "collector_number": None,
                "printed_code": None,
                "status": "review-needed",
                "verified": False,
                "exact_version_unresolved": True,
            })

    def _synchronize_delegated_families(self) -> None:
        """Propagate each representative's final guarded family to siblings."""
        slots = self._state.get("slots") or []
        for representative_slot, sibling_slots in self._family_delegates.items():
            if not (1 <= representative_slot <= len(slots)):
                continue
            representative = slots[representative_slot - 1]
            card = representative.get("card") or {}
            family = str(
                card.get("canonical_name")
                or card.get("english_name")
                or card.get("name")
                or ""
            ).strip()
            if not family:
                continue
            for sibling_slot in sibling_slots:
                if not (1 <= sibling_slot <= len(slots)):
                    continue
                sibling = slots[sibling_slot - 1]
                sibling["delegated_family_name"] = family
                sibling["delegated_family_set_id"] = card.get("set_id")
                sibling["delegated_family_set_name"] = card.get("set_name")
                sibling["delegated_family_synchronized"] = True

    def _enforce_exact_identity_safety(self) -> None:
        """Never publish an unresolved print as a verified exact identity."""
        for item in self._state["slots"]:
            card = item.get("card") or {}
            if card.get("retrieval_only"):
                # Reconciliation can inspect raw search hits, but they remain
                # in the review shortlist until independent evidence supports one.
                item.update(card=None, status="review-needed", verified=False,
                            confidence=None, exact_version_unresolved=True,
                            version_safety_reason="unsupported_retrieval_candidate")
                continue
            canonical_code = self._normalized_printed_code(card.get("printed_code"))
            observed_code = self._normalized_printed_code(item.get("printed_code"))
            if item.get("verified") and canonical_code:
                if observed_code and observed_code != canonical_code:
                    item["ocr_printed_code_observed"] = item.get("printed_code")
                item["printed_code"] = card.get("printed_code")
            unresolved = bool(
                item.get("exact_version_unresolved")
                or card.get("exact_version_unresolved")
            )
            slot = int(item.get("slot") or 0)
            canonical = str(
                card.get("canonical_name") or card.get("english_name") or card.get("name") or ""
            ).casefold()
            family_versions = {
                self._version_key(candidate)
                for candidate in self._candidate_cache.get(slot, [])
                if str(
                    candidate.get("canonical_name")
                    or candidate.get("english_name")
                    or candidate.get("name")
                    or ""
                ).casefold() == canonical
                and self._version_key(candidate)
            }
            weak_version_only = bool(
                item.get("verified")
                and not item.get("printed_code")
                and len(family_versions) >= 2
                and float(item.get("confidence") or 0.0) < 0.60
            )
            if not unresolved and not weak_version_only:
                continue
            item.update({
                "status": "review-needed",
                "verified": False,
                "exact_version_unresolved": True,
            })
            if weak_version_only:
                item["version_safety_reason"] = "weak_visual_variant_without_footer"
            # A family-level candidate may carry a borrowed catalog number.
            # Keep independently read footer evidence, but do not expose that
            # borrowed number as the selected version.
            if not item.get("printed_code") and not item.get("collector_number"):
                continue
            source = dict(card)
            source.pop("collector_number", None)
            source.pop("official_collector_number", None)
            source.pop("reference_image", None)
            source["exact_version_unresolved"] = True
            item["card"] = source
            item["collector_number"] = None

    def _reconcile_dominant_family(self) -> None:
        """Repair a lone global-index escape without homogenizing mixed scans."""
        populated = [item for item in self._state["slots"] if item.get("card")]
        families = [key for item in populated if (key := self._family_key(item.get("card")))]
        if len(families) < 4:
            return
        dominant, count = Counter(families).most_common(1)[0]
        if count < 4 or count / len(families) < 0.75:
            return
        for item in populated:
            if self._family_key(item.get("card")) == dominant:
                continue
            matching = [
                candidate for candidate in self._candidate_cache.get(int(item["slot"]), [])
                if self._family_key(candidate) == dominant
            ]
            if not matching:
                continue
            replacement = max(
                matching,
                key=lambda candidate: float(candidate.get("fused_score") or candidate.get("score") or 0.0),
            )
            item["card"] = replacement
            item["confidence"] = float(
                replacement.get("fused_score") or replacement.get("score") or item.get("confidence") or 0.0
            )
            item["family_reconciled"] = True

    def _reconcile_missing_artwork_families(self) -> None:
        """Replace generic catalog escapes with a strong local artwork family."""
        for item in self._state["slots"]:
            card = item.get("card") or {}
            canonical = str(
                card.get("canonical_name") or card.get("english_name") or card.get("name") or ""
            ).strip()
            needs_family_guard = bool(
                not item.get("verified")
                or item.get("exact_version_unresolved")
                or item.get("family_first_delegated")
                or card.get("retrieval_only")
                or card.get("source") == "global_visual_index"
            )
            if canonical and (not needs_family_guard or self._has_crop_verified_fraction(item)):
                continue
            slot = int(item.get("slot") or 0)
            worker_family = self._worker_local_candidate_family(slot)
            batch_family, batch_votes, batch_margin = self._batch_candidate_family(slot)
            evidence_conflict = bool(
                worker_family
                and batch_family
                and worker_family.casefold() != batch_family.casefold()
            )
            family = ""
            fast_family = False
            if evidence_conflict:
                family = self._best_artwork_family(slot)
                item["family_evidence_conflict"] = {
                    "worker": worker_family,
                    "batch": batch_family,
                    "batch_votes": batch_votes,
                    "batch_margin": batch_margin,
                }
                item["family_conflict_resolved_by_artwork"] = bool(family)
            else:
                family = worker_family or batch_family
                fast_family = bool(family)
            if not family:
                family = self._best_artwork_family(slot)
            if not family:
                continue
            # A worker-local verified catalog candidate is enough to protect the
            # species family, but not enough to certify one of several prints.
            # Footer reconciliation immediately follows and owns exact-version
            # resolution.  Only the exhaustive fallback may resolve here.
            resolved = None if fast_family else self._best_named_reference(family, slot)
            item.update({
                "card": resolved or {
                    "name": family,
                    "display_name": family,
                    "canonical_name": family,
                    "english_name": family,
                    "exact_version_unresolved": True,
                    "recognition_source": "artwork-family-safety",
                },
                "collector_number": resolved.get("collector_number") if resolved else None,
                "printed_code": resolved.get("printed_code") if resolved else None,
                "status": "verified" if resolved else "review-needed",
                "verified": bool(resolved),
                "exact_version_unresolved": not bool(resolved),
                "artwork_family_recovered": True,
                "artwork_family_fast_path": fast_family,
            })

    @staticmethod
    def _has_crop_verified_fraction(item: dict[str, Any]) -> bool:
        """Skip family retrieval already settled by this crop's direct verifier.

        This only avoids an exhaustive family search. It never promotes a
        candidate, waives temporal confirmation, or changes the output gate.
        """
        card = item.get("card") or {}
        if (
            item.get("status") == "recognizing"
            or item.get("family_first_delegated") or item.get("exact_version_unresolved")
            or card.get("exact_version_unresolved") or card.get("provisional")
            or card.get("provisional_reference") or card.get("retrieval_only")
            or not card.get("verification_strong") or not card.get("artwork_verification_strong")
            or not (card.get("image_path") or card.get("reference_image") or card.get("local_image"))
            or not RecognitionService._exact_collector_fraction_match(
                item.get("collector_number"), card.get("collector_number"),
            )
        ):
            return False
        observed_name = str(item.get("name_candidate") or "").strip().casefold()
        names = {str(card.get(key) or "").strip().casefold()
                 for key in ("name", "canonical_name", "english_name", "printed_name")}
        observed_language = RecognitionService._canonical_identity_language(item.get("language"))
        reference_language = RecognitionService._canonical_identity_language(card.get("language_code") or card.get("language"))
        return not (
            (observed_name and observed_name not in names)
            or (observed_language and reference_language and observed_language != reference_language)
        )

    def _worker_local_candidate_family(self, slot: int) -> str:
        """Return a strong worker-local family without rescanning references."""
        for candidate in self._candidate_cache.get(slot, [])[:5]:
            name = str(
                candidate.get("canonical_name")
                or candidate.get("english_name")
                or ""
            ).strip()
            score = float(
                candidate.get("visual_similarity")
                or candidate.get("score")
                or 0.0
            )
            if (
                name
                and candidate.get("source") == "pokipair"
                and candidate.get("verification_strong")
                and candidate.get("artwork_verification_strong")
                and not candidate.get("retrieval_only")
                and score >= 0.45
            ):
                return name
        return ""

    def _batch_candidate_family(self, slot: int) -> tuple[str, int, int]:
        """Return repeated batch family, vote count, and runner-up margin."""
        # Batch candidates are already ordered by crop-local artwork distance
        # during the one-pass catalog traversal.  Prefer the first identified
        # local record over unrelated global-index escape candidates.
        batch_names: list[str] = []
        for candidate in self._batch_hint_cache.get(slot, [])[:16]:
            name = str(
                candidate.get("canonical_name")
                or candidate.get("english_name")
                or candidate.get("pokemon_name")
                or ""
            ).strip()
            if (
                name
                and candidate.get("source") == "pokipair"
                and not candidate.get("retrieval_only")
                and (
                    candidate.get("image_path")
                    or candidate.get("reference_image")
                    or candidate.get("local_image")
                )
            ):
                batch_names.append(name)
        if batch_names:
            candidates = self._batch_hint_cache.get(slot, [])[:16]
            distance_groups: dict[str, list[int]] = {}
            original_names: dict[str, str] = {}
            for candidate in candidates:
                name = str(
                    candidate.get("canonical_name")
                    or candidate.get("english_name")
                    or candidate.get("pokemon_name")
                    or ""
                ).strip()
                if name and candidate.get("source") == "pokipair" and candidate.get("batch_distance") is not None:
                    key = name.casefold()
                    original_names.setdefault(key, name)
                    distance_groups.setdefault(key, []).append(int(candidate["batch_distance"]))
            if distance_groups:
                # Catalogs contain unequal numbers of prints per species. Pick
                # the family with the closest crop-local artwork, then use
                # repeated variants only as supporting evidence.
                ordered = sorted(
                    distance_groups,
                    key=lambda key: (min(distance_groups[key]), -len(distance_groups[key]), key),
                )
                winner = ordered[0]
                count = len(distance_groups[winner])
                runner_count = len(distance_groups[ordered[1]]) if len(ordered) > 1 else 0
                return original_names[winner], count, max(0, count - runner_count)
            ranked = Counter(name.casefold() for name in batch_names).most_common(2)
            normalized, count = ranked[0]
            runner_up = ranked[1][1] if len(ranked) > 1 else 0
            if count >= 2:
                return (
                    next(name for name in batch_names if name.casefold() == normalized),
                    count,
                    count - runner_up,
                )
        return "", 0, 0

    def _trusted_local_candidate_family(self, slot: int) -> str:
        """Compatibility helper returning the strongest cheap family signal."""
        worker = self._worker_local_candidate_family(slot)
        if worker:
            return worker
        return self._batch_candidate_family(slot)[0]

    @staticmethod
    def _normalized_ocr_name(value: Any) -> str:
        return re.sub(r"[^\w\u3400-\u9fff]+", "", str(value or "")).casefold()

    @classmethod
    def _ocr_tokens(cls, item: dict[str, Any]) -> set[str]:
        values = [item.get("name_candidate")]
        values.extend(
            entry.get("text") if isinstance(entry, dict) else entry
            for entry in (item.get("raw_text") or [])
        )
        tokens: set[str] = set()
        for value in values:
            token = cls._normalized_ocr_name(value)
            if 2 <= len(token) <= 16 and not token.isnumeric() and any(char.isalpha() for char in token):
                tokens.add(token)
        return tokens

    def _reconcile_ocr_identity(self) -> None:
        """Preserve a strong shared OCR identity when the exact print is absent.

        A mixed-set card can share a Pokemon name with a dominant artwork family
        while having no corresponding reference image in the local index.  In
        that case the global visual shortlist may contain only unrelated cards.
        Reusing a versioned family record would be equally misleading, so expose
        a deliberately versionless provisional identity instead.
        """
        populated = [item for item in self._state["slots"] if item.get("card")]
        families = [key for item in populated if (key := self._family_key(item.get("card")))]
        if len(families) < 4:
            return
        dominant, family_count = Counter(families).most_common(1)[0]
        if family_count < 4:
            return
        family_items = [item for item in populated if self._family_key(item.get("card")) == dominant]
        names = [
            self._normalized_ocr_name(item.get("name_candidate"))
            for item in family_items
            if self._normalized_ocr_name(item.get("name_candidate"))
        ]
        shared_name = ""
        if names:
            candidate_name, shared_count = Counter(names).most_common(1)[0]
            if shared_count >= 3:
                shared_name = candidate_name
        token_counts = Counter(token for item in family_items for token in self._ocr_tokens(item))
        shared_tokens = {token for token, count in token_counts.items() if count >= 2}
        family_token_sets = [self._ocr_tokens(item) for item in family_items]
        anchor = family_items[0]["card"]
        canonical = str(
            anchor.get("canonical_name")
            or anchor.get("english_name")
            or anchor.get("name")
            or ""
        ).strip()
        if not canonical:
            return
        for item in populated:
            if self._family_key(item.get("card")) == dominant:
                continue
            slot = int(item.get("slot") or 0)
            candidates = self._candidate_cache.get(slot, [])
            candidate_names = [
                str(candidate.get("canonical_name") or candidate.get("english_name") or "").strip()
                for candidate in candidates[:5]
                if candidate.get("canonical_name") or candidate.get("english_name")
            ]
            agreed_candidate = ""
            if candidate_names:
                candidate_counts = Counter(name.casefold() for name in candidate_names)
                candidate_key, candidate_count = candidate_counts.most_common(1)[0]
                if candidate_count >= 2:
                    agreed_candidate = next(
                        name for name in candidate_names if name.casefold() == candidate_key
                    )
            # A same-name neighbor cluster must never overwrite a slot whose
            # own visual candidates repeatedly agree on another Pokemon.
            if agreed_candidate and agreed_candidate.casefold() != canonical.casefold():
                replacement = next(
                    candidate for candidate in candidates
                    if str(candidate.get("canonical_name") or candidate.get("english_name") or "").casefold()
                    == agreed_candidate.casefold()
                )
                item.update({
                    "card": dict(replacement),
                    "confidence": self._candidate_score(replacement),
                    "status": "review-needed",
                    "verified": False,
                    "shared_family_override_blocked": True,
                })
                continue
            name_matches = bool(
                shared_name
                and self._normalized_ocr_name(item.get("name_candidate")) == shared_name
            )
            item_tokens = self._ocr_tokens(item)
            token_matches = bool(shared_tokens & item_tokens)
            fuzzy_token = ""
            if not token_matches:
                fuzzy_candidates: list[tuple[int, float, str]] = []
                for token in item_tokens:
                    if len(token) < 3 or not any("\u3400" <= char <= "\u9fff" for char in token):
                        continue
                    supporting_slots = 0
                    best_similarity = 0.0
                    for family_tokens in family_token_sets:
                        similarity = max(
                            (SequenceMatcher(None, token, other).ratio() for other in family_tokens),
                            default=0.0,
                        )
                        if similarity >= 0.65:
                            supporting_slots += 1
                            best_similarity += similarity
                    if supporting_slots >= 2:
                        fuzzy_candidates.append((supporting_slots, best_similarity, token))
                if fuzzy_candidates:
                    fuzzy_token = max(fuzzy_candidates)[2]
                    token_matches = True
            if not name_matches and not token_matches:
                continue
            matched_tokens = shared_tokens & self._ocr_tokens(item)
            printed_name = (
                max(matched_tokens, key=len)
                if matched_tokens
                else fuzzy_token
                if fuzzy_token
                else str(item.get("name_candidate") or "").strip()
            )
            exact_reference = self._best_named_reference(canonical, int(item["slot"]))
            if exact_reference is not None:
                item.update({
                    "card": exact_reference,
                    "collector_number": exact_reference.get("collector_number"),
                    "status": "verified",
                    "verified": True,
                    "ocr_identity_reconciled": True,
                    "ocr_reference_resolved": True,
                    "exact_version_unresolved": False,
                })
                continue
            item.update({
                "card": {
                    "name": canonical,
                    "display_name": canonical,
                    "canonical_name": canonical,
                    "english_name": canonical,
                    "printed_name": printed_name,
                    "language": item.get("language") or anchor.get("language"),
                    "exact_version_unresolved": True,
                    "recognition_source": "shared-ocr-identity",
                },
                "status": "review-needed",
                "verified": False,
                "ocr_identity_reconciled": True,
                "exact_version_unresolved": True,
            })

    def _best_named_reference(self, canonical_name: str, slot: int) -> dict[str, Any] | None:
        matches = self._named_reference_matches(canonical_name, slot)
        if not matches:
            return None
        if matches[0][0] < 28.0:
            return None
        if len(matches) > 1 and matches[0][0] - matches[1][0] < 8.0:
            return None
        return dict(matches[0][1])

    def resolve_exact_reference(
        self,
        crop: np.ndarray | None,
        canonical_name: str,
    ) -> dict[str, Any]:
        """Resolve one crop and explain the strict score/margin decision."""
        if crop is None or not getattr(crop, "size", 0) or not canonical_name:
            return {
                "card": None,
                "diagnostics": {
                    "status": "unavailable",
                    "reason": "No usable card crop or canonical identity.",
                    "candidates": [],
                },
            }
        # Never route concurrent workers through a shared synthetic crop slot.
        # Doing so allowed one worker to overwrite another worker's image while
        # SIFT matching was still in progress, producing intermittent cross-card
        # identities in multi-card mode.
        matches = self._named_reference_matches_crop(canonical_name, crop)
        preview = [
            {
                "set_id": record.get("set_id"),
                "collector_number": record.get("collector_number"),
                "display_name": record.get("display_name") or record.get("canonical_name"),
                "score": round(float(score), 3),
            }
            for score, record in matches[:5]
        ]
        top_score = float(matches[0][0]) if matches else 0.0
        runner_up = float(matches[1][0]) if len(matches) > 1 else None
        margin = top_score - runner_up if runner_up is not None else top_score
        score_ready = top_score >= 28.0
        margin_ready = runner_up is None or margin >= 8.0
        resolved = bool(matches and score_ready and margin_ready)
        consensus_resolved = False
        confirmation_progress = 0
        leader_key = self._version_key(matches[0][1]) if matches else ""
        live_fingerprint = ArtworkIndexService.variant_marker_fingerprint(crop)
        live_response = self.treatment_response(crop)
        prior = self._single_exact_history
        response_distance = 0.0
        if matches and score_ready and leader_key:
            same_identity = (
                str(prior.get("canonical_name") or "").casefold()
                == canonical_name.casefold()
                and str(prior.get("leader_key") or "") == leader_key
            )
            prior_fingerprint = str(prior.get("fingerprint") or "")
            distance = (
                ArtworkIndexService.hamming(live_fingerprint, prior_fingerprint)
                if live_fingerprint and prior_fingerprint
                else 64
            )
            response_distance = self.treatment_response_distance(
                live_response,
                prior.get("treatment_response") or (0.0, 0.0, 0.0),
            )
            distinct_capture = (
                1 <= distance <= 10
                or (distance <= 10 and response_distance >= 1.25)
            )
            current_usable = margin >= 4.0
            prior_usable = float(prior.get("score_gap") or 0.0) >= 4.0
            confirmation_progress = 2 if (
                same_identity and distinct_capture and current_usable and prior_usable
            ) else 1
            consensus_resolved = confirmation_progress >= 2
            if not same_identity or distinct_capture:
                self._single_exact_history = {
                    "canonical_name": canonical_name,
                    "leader_key": leader_key,
                    "fingerprint": live_fingerprint,
                    "score_gap": margin,
                    "treatment_response": live_response,
                    "updated_at": time.time(),
                }
        resolved = resolved or consensus_resolved
        if consensus_resolved:
            reason = "Leading reference confirmed across two distinct stable captures."
        elif resolved:
            reason = "Leading reference cleared the score and separation gates."
        elif not matches:
            reason = "No local references matched this identity."
        elif not score_ready:
            reason = "Leading reference score is below the 28-point lock gate."
        else:
            reason = "Top references are too close; an 8-point separation is required."
        return {
            "card": dict(matches[0][1]) if resolved else None,
            "diagnostics": {
                "status": "resolved" if resolved else "ambiguous",
                "reason": reason,
                "canonical_name": canonical_name,
                "top_score": round(top_score, 3),
                "runner_up_score": round(runner_up, 3) if runner_up is not None else None,
                "score_gap": round(margin, 3),
                "minimum_score": 28.0,
                "minimum_gap": 8.0,
                "multi_frame_confirmation": consensus_resolved,
                "confirmation_progress": confirmation_progress,
                "confirmation_required": 2,
                "treatment_response_distance": round(response_distance if prior else 0.0, 3),
                "candidates": preview,
            },
        }

    def _named_reference_matches(
        self,
        canonical_name: str,
        slot: int,
    ) -> list[tuple[float, dict[str, Any]]]:
        crop = self._crop_cache.get(slot)
        if crop is None:
            return []
        return self._named_reference_matches_crop(canonical_name, crop)

    def _named_reference_matches_crop(
        self,
        canonical_name: str,
        crop: np.ndarray,
    ) -> list[tuple[float, dict[str, Any]]]:
        live = self._sift_descriptors(crop, treatment=False)
        live_treatment = self._sift_descriptors(crop, treatment=True)
        live_marker = ArtworkIndexService.variant_marker_fingerprint(crop)
        project_root = Path(__file__).resolve().parents[2]
        matches: list[tuple[float, dict[str, Any]]] = []
        for record in self._reference_cards:
            record_name = str(record.get("canonical_name") or record.get("english_name") or "")
            if record_name.casefold() != canonical_name.casefold():
                continue
            features = self._reference_features(record, project_root)
            if not features:
                continue
            artwork_score = self._descriptor_score(live, features["artwork"])
            treatment_score = self._descriptor_score(
                live_treatment,
                features["treatment"],
            )
            marker_score = self._variant_marker_score(
                live_marker,
                features["marker"],
            )
            score = artwork_score + treatment_score * 0.35 + marker_score
            matches.append((score, record))
        matches.sort(key=lambda entry: entry[0], reverse=True)
        return matches

    def _reference_features(
        self,
        record: dict[str, Any],
        project_root: Path | None = None,
    ) -> dict[str, Any] | None:
        relative = record.get("reference_image") or record.get("image_path")
        path = Path(str(relative or ""))
        if not path.is_absolute():
            path = (project_root or Path(__file__).resolve().parents[2]) / path
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None
        key = str(path.resolve()).casefold()
        with self._reference_feature_cache_lock:
            cached = self._reference_feature_cache.get(key)
            if cached and cached.get("mtime_ns") == stamp:
                return cached
        image = cv2.imread(str(path))
        if image is None:
            return None
        features = {
            "mtime_ns": stamp,
            "image": image,
            "artwork": self._sift_descriptors(image, treatment=False),
            "treatment": self._sift_descriptors(image, treatment=True),
            "marker": ArtworkIndexService.variant_marker_fingerprint(image),
        }
        with self._reference_feature_cache_lock:
            self._reference_feature_cache[key] = features
        return features

    def _reconcile_unresolved_references(self) -> None:
        """Resolve exception cards against all local references of their name."""
        verified_families = [
            self._family_key(item.get("card"))
            for item in self._state["slots"]
            if item.get("verified") and self._family_key(item.get("card"))
        ]
        dominant_name = ""
        if verified_families:
            dominant, count = Counter(verified_families).most_common(1)[0]
            if count >= 4:
                dominant_name = dominant[0]
        for item in self._state["slots"]:
            if item.get("verified"):
                continue
            if item.get("artwork_family_fast_path"):
                # Printed-code reconciliation has already had the opportunity
                # to resolve this card.  Without footer evidence, keep the safe
                # family provisional instead of running an expensive visual
                # version guess that cannot establish exact identity.
                item["exact_version_unresolved"] = True
                continue
            candidates = self._candidate_cache.get(int(item.get("slot") or 0), [])
            canonical = next(
                (
                    str(candidate.get("canonical_name") or candidate.get("english_name") or "").strip()
                    for candidate in candidates
                    if candidate.get("canonical_name") or candidate.get("english_name")
                ),
                "",
            )
            reference = (
                self._best_named_reference(canonical, int(item["slot"]))
                if canonical
                else None
            )
            ocr_name = self._normalized_ocr_name(item.get("name_candidate"))
            reference_printed_name = self._normalized_ocr_name(
                (reference or {}).get("printed_name")
            )
            reference_canonical = str(
                (reference or {}).get("canonical_name")
                or (reference or {}).get("english_name")
                or ""
            ).casefold()
            candidate_family_names = {
                str(candidate.get("canonical_name") or candidate.get("english_name") or "").casefold()
                for candidate in candidates[:5]
                if candidate.get("canonical_name") or candidate.get("english_name")
            }
            ocr_family_conflict = bool(
                reference
                and ocr_name
                and reference_printed_name
                and ocr_name != reference_printed_name
                and reference_canonical
                and any(name and name != reference_canonical for name in candidate_family_names)
            )
            if ocr_family_conflict:
                item.update({
                    "status": "review-needed",
                    "verified": False,
                    "ocr_family_conflict": True,
                    "reference_score_preview": [
                        {
                            "set_id": record.get("set_id"),
                            "collector_number": record.get("collector_number"),
                            "score": round(float(score), 3),
                        }
                        for score, record in self._named_reference_matches(canonical, int(item["slot"]))[:5]
                    ],
                })
                continue
            dominant_recovery = False
            if reference is None and dominant_name:
                reference = self._best_named_reference(dominant_name, int(item["slot"]))
                dominant_recovery = reference is not None
            if reference is None:
                if canonical:
                    measured = self._named_reference_matches(canonical, int(item["slot"]))
                    item["reference_score_preview"] = [
                        {
                            "set_id": record.get("set_id"),
                            "collector_number": record.get("collector_number"),
                            "score": round(float(score), 3),
                        }
                        for score, record in measured[:5]
                    ]
                continue
            item.update({
                "card": reference,
                "collector_number": reference.get("collector_number"),
                "status": "verified",
                "verified": True,
                "exception_reference_resolved": True,
                "dominant_family_reference_recovery": dominant_recovery,
                "exact_version_unresolved": False,
            })

    def _reconcile_candidate_consensus(self) -> None:
        """Prefer repeated canonical evidence over one weak filename artifact."""
        for item in self._state["slots"]:
            if item.get("verified"):
                continue
            candidates = self._candidate_cache.get(int(item.get("slot") or 0), [])
            if len(candidates) < 3:
                continue
            top_score = self._candidate_score(candidates[0])
            grouped: dict[str, list[dict[str, Any]]] = {}
            for candidate in candidates[:8]:
                canonical = str(
                    candidate.get("canonical_name")
                    or candidate.get("english_name")
                    or candidate.get("pokemon_name")
                    or ""
                ).strip()
                if canonical:
                    grouped.setdefault(canonical.casefold(), []).append(candidate)
            eligible = [group for group in grouped.values() if len(group) >= 2]
            if not eligible:
                continue
            group = max(
                eligible,
                key=lambda values: (len(values), max(self._candidate_score(value) for value in values)),
            )
            replacement = max(group, key=self._candidate_score)
            replacement_score = self._candidate_score(replacement)
            if replacement_score + 0.04 < top_score:
                continue
            item.update({
                "card": dict(replacement),
                "confidence": replacement_score,
                "status": "review-needed",
                "verified": False,
                "candidate_family_consensus": True,
            })

    @staticmethod
    def _version_key(card: dict[str, Any] | None) -> str:
        if not card:
            return ""
        return "|".join((
            str(card.get("set_id") or "").upper(),
            str(card.get("collector_number") or ""),
            str(card.get("printed_code") or ""),
        ))

    def _apply_temporal_confirmation(self) -> None:
        """Restore an exact version only after two matching prior observations."""
        for item in self._state["slots"]:
            if item.get("verified"):
                continue
            slot = int(item.get("slot") or 0)
            history = self._temporal_history.get(slot)
            crop = self._crop_cache.get(slot)
            confirmations = int((history or {}).get("confirmations") or 0)
            item["temporal_confirmation_progress"] = min(2, confirmations)
            item["temporal_confirmation_required"] = 2
            if not history or confirmations < 2 or crop is None:
                continue
            current_fingerprint = ArtworkIndexService.variant_marker_fingerprint(crop)
            stored_fingerprint = str(history.get("fingerprint") or "")
            fingerprint_distance = (
                ArtworkIndexService.hamming(current_fingerprint, stored_fingerprint)
                if stored_fingerprint else 65
            )
            descriptor = history.get("descriptor")
            similarity = (
                self._descriptor_score(self._sift_descriptors(crop, treatment=True), descriptor)
                if descriptor else 0.0
            )
            response_distance = self.treatment_response_distance(
                self.treatment_response(crop),
                history.get("treatment_response"),
            )
            if fingerprint_distance > 10 and not (
                similarity >= 50.0 and response_distance <= 18.0
            ):
                self._temporal_history.pop(slot, None)
                self._persist_temporal_history()
                continue
            current_center = self._slot_center(item)
            stored_center = history.get("center")
            if current_center and stored_center and float(np.linalg.norm(
                np.asarray(current_center) - np.asarray(stored_center)
            )) > 0.08:
                self._temporal_history.pop(slot, None)
                self._persist_temporal_history()
                continue
            canonical = str(
                (item.get("card") or {}).get("canonical_name")
                or next((candidate.get("canonical_name") for candidate in self._candidate_cache.get(slot, []) if candidate.get("canonical_name")), "")
            ).casefold()
            expected = str((history.get("card") or {}).get("canonical_name") or "").casefold()
            if canonical and expected and canonical != expected:
                continue
            item.update({
                "card": dict(history["card"]),
                "collector_number": history["card"].get("collector_number"),
                "status": "verified",
                "verified": True,
                "temporal_confirmation": True,
                "temporal_confirmation_count": int(history["confirmations"]),
                "temporal_confirmation_progress": 2,
                "temporal_similarity": round(float(similarity), 3),
                "temporal_fingerprint_distance": int(fingerprint_distance),
                "temporal_treatment_response_distance": round(response_distance, 3),
            })

    def _record_temporal_evidence(self) -> None:
        for item in self._state["slots"]:
            card = item.get("card") or {}
            canonical = str(
                card.get("canonical_name")
                or card.get("english_name")
                or card.get("pokemon_name")
                or ""
            ).strip()
            if (
                not item.get("verified")
                or not canonical
                or not self._version_key(card)
            ):
                continue
            slot = int(item.get("slot") or 0)
            crop = self._crop_cache.get(slot)
            if crop is None:
                continue
            descriptor = self._sift_descriptors(crop, treatment=True)
            fingerprint = ArtworkIndexService.variant_marker_fingerprint(crop)
            previous = self._temporal_history.get(slot)
            confirmations = 1
            if previous and self._version_key(previous.get("card")) == self._version_key(item.get("card")):
                current_center = self._slot_center(item)
                previous_center = previous.get("center")
                position_stable = bool(
                    current_center
                    and previous_center
                    and float(np.linalg.norm(
                        np.asarray(current_center) - np.asarray(previous_center)
                    )) <= 0.08
                )
                previous_descriptor = previous.get("descriptor")
                similarity = (
                    self._descriptor_score(descriptor, previous_descriptor)
                    if previous_descriptor else 0.0
                )
                previous_fingerprint = str(previous.get("fingerprint") or "")
                fingerprint_distance = (
                    ArtworkIndexService.hamming(fingerprint, previous_fingerprint)
                    if previous_fingerprint else 65
                )
                # A fresh exact recognition already establishes identity. Preserve
                # its durable streak when the same version remains in the same
                # position, even if glare changes the compact fingerprint.
                # This method records an independently verified fresh result;
                # position may preserve its streak. Restoration of an unverified
                # result remains subject to the stricter treatment gate above.
                if position_stable or similarity >= 40.0 or fingerprint_distance <= 10:
                    confirmations = min(8, int(previous.get("confirmations") or 0) + 1)
            self._temporal_history[slot] = {
                "card": dict(item["card"]),
                "descriptor": descriptor,
                "fingerprint": fingerprint,
                "treatment_response": self.treatment_response(crop),
                "center": self._slot_center(item),
                "confirmations": confirmations,
                "updated_at": time.time(),
            }
        self._persist_temporal_history()

    @staticmethod
    def _slot_center(item: dict[str, Any]) -> list[float] | None:
        polygon = item.get("polygon")
        if not isinstance(polygon, list) or len(polygon) != 4:
            return None
        return np.asarray(polygon, dtype=np.float32).mean(axis=0).round(5).tolist()

    def _load_temporal_history(self) -> dict[int, dict[str, Any]]:
        try:
            payload = json.loads(self._temporal_history_path.read_text(encoding="utf-8"))
            if int(payload.get("version") or 0) != self.TEMPORAL_HISTORY_VERSION:
                return {}
            now = time.time()
            loaded: dict[int, dict[str, Any]] = {}
            for raw_slot, entry in (payload.get("slots") or {}).items():
                if now - float(entry.get("updated_at") or 0.0) > self.TEMPORAL_HISTORY_MAX_AGE_SECONDS:
                    continue
                card = entry.get("card") or {}
                canonical = str(
                    card.get("canonical_name")
                    or card.get("english_name")
                    or card.get("pokemon_name")
                    or ""
                ).strip()
                if (
                    not entry.get("fingerprint")
                    or entry.get("fingerprint") == "0000000000000000"
                    or not canonical
                    or not self._version_key(card)
                ):
                    continue
                loaded[int(raw_slot)] = dict(entry)
            return loaded
        except Exception:
            return {}

    def _persist_temporal_history(self) -> None:
        try:
            self._temporal_history_path.parent.mkdir(parents=True, exist_ok=True)
            slots = {}
            for slot, entry in self._temporal_history.items():
                slots[str(slot)] = {
                    key: value for key, value in entry.items()
                    if key != "descriptor"
                }
            payload = {
                "version": self.TEMPORAL_HISTORY_VERSION,
                "updated_at": time.time(),
                "slots": slots,
            }
            temporary = self._temporal_history_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self._temporal_history_path)
        except Exception:
            return

    @staticmethod
    def _normalized_printed_code(value: Any) -> str:
        return re.sub(r"[^0-9/]", "", str(value or ""))

    @classmethod
    def _observed_printed_codes(cls, item: dict[str, Any]) -> set[str]:
        """Return unambiguous Gem Pack footer codes seen in OCR evidence."""
        values = [item.get("printed_code")]
        values.extend(
            entry.get("text") if isinstance(entry, dict) else entry
            for entry in (item.get("raw_text") or [])
        )
        codes: set[str] = set()
        for value in values:
            for match in re.findall(r"(?<!\d)(\d{4}/\d{2})(?!\d)", str(value or "")):
                # Gem Pack Vol 5 codes use a seven-print denominator. OCR often
                # reads the tiny zero as six; only normalize that known suffix.
                if match.endswith("/67"):
                    match = f"{match[:5]}07"
                if match.endswith("/07"):
                    codes.add(match)
        return codes

    def _reconcile_printed_codes(self) -> None:
        """Use a readable bottom-edge code to break same-artwork ties."""
        for item in self._state["slots"]:
            if item.get("batch_variant_resolved"):
                continue
            observed_codes = self._observed_printed_codes(item)
            if len(observed_codes) != 1:
                continue
            observed = next(iter(observed_codes))
            current_card = item.get("card") or {}
            visual_family = ""
            if item.get("artwork_family_fast_path"):
                visual_family = str(
                    current_card.get("canonical_name")
                    or current_card.get("english_name")
                    or current_card.get("name")
                    or ""
                ).strip()
            if not visual_family:
                visual_family = self._candidate_family_consensus(
                    self._candidate_cache.get(int(item.get("slot") or 0), [])
                )
            if not visual_family:
                visual_family = self._best_artwork_family(int(item.get("slot") or 0))
            candidates = list(self._candidate_cache.get(int(item.get("slot") or 0), []))
            candidates.extend(self._reference_cards)
            matches: dict[str, dict[str, Any]] = {}
            for candidate in candidates:
                if self._normalized_printed_code(candidate.get("printed_code")) != observed:
                    continue
                key = self._version_key(candidate)
                if key and (key not in matches or self._candidate_score(candidate) > self._candidate_score(matches[key])):
                    matches[key] = candidate
            if len(matches) != 1:
                continue
            replacement = next(iter(matches.values()))
            replacement_family = str(
                replacement.get("canonical_name")
                or replacement.get("english_name")
                or replacement.get("name")
                or ""
            )
            if visual_family and replacement_family.casefold() != visual_family.casefold():
                resolved = (
                    None
                    if item.get("artwork_family_fast_path")
                    else self._best_named_reference(visual_family, int(item.get("slot") or 0))
                )
                item.update({
                    "card": resolved or {
                        "name": visual_family,
                        "display_name": visual_family,
                        "canonical_name": visual_family,
                        "english_name": visual_family,
                        "exact_version_unresolved": True,
                        "recognition_source": "artwork-family-code-conflict",
                    },
                    "collector_number": resolved.get("collector_number") if resolved else None,
                    "printed_code": resolved.get("printed_code") if resolved else None,
                    "confidence": max(float(item.get("confidence") or 0.0), 0.60 if resolved else 0.0),
                    "status": "verified" if resolved else "review-needed",
                    "verified": bool(resolved),
                    "exact_version_unresolved": not bool(resolved),
                    "printed_code_conflict": observed,
                    "artwork_family_preserved": True,
                })
                continue
            resolved_card = dict(replacement)
            resolved_card["exact_version_unresolved"] = False
            item.update({
                "card": resolved_card,
                "collector_number": replacement.get("collector_number"),
                "printed_code": observed,
                "confidence": max(
                    float(item.get("confidence") or 0.0),
                    self._candidate_score(replacement),
                ),
                "status": "verified",
                "verified": True,
                "exact_version_unresolved": False,
                "printed_code_resolved": True,
            })

    @staticmethod
    def _candidate_family_consensus(candidates: list[dict[str, Any]]) -> str:
        names = [
            str(
                candidate.get("canonical_name")
                or candidate.get("english_name")
                or candidate.get("name")
                or ""
            ).strip()
            for candidate in candidates[:8]
        ]
        names = [name for name in names if name]
        if not names:
            return ""
        counts = Counter(name.casefold() for name in names)
        key, count = counts.most_common(1)[0]
        if count < 2:
            return ""
        return next(name for name in names if name.casefold() == key)

    def _best_artwork_family(self, slot: int) -> str:
        """Identify a family from one local artwork reference per species."""
        crop = self._crop_cache.get(slot)
        if crop is None:
            return ""
        live = self._sift_descriptors(crop, treatment=False)
        project_root = Path(__file__).resolve().parents[2]
        representatives: dict[str, dict[str, Any]] = {}
        for record in self._reference_cards:
            name = str(record.get("canonical_name") or record.get("english_name") or "").strip()
            if name:
                representatives.setdefault(name.casefold(), record)
        ranked: list[tuple[float, str]] = []
        for record in representatives.values():
            features = self._reference_features(record, project_root)
            if not features:
                continue
            ranked.append((
                self._descriptor_score(live, features["artwork"]),
                str(record.get("canonical_name") or record.get("english_name")),
            ))
        ranked.sort(reverse=True)
        if not ranked:
            return ""
        top_score, top_name = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        return top_name if top_score >= 40.0 and top_score - runner_up >= 12.0 else ""

    @staticmethod
    def _load_reference_cards() -> list[dict[str, Any]]:
        path = (
            Path(__file__).resolve().parents[2]
            / "catalog_master"
            / "recognition"
            / "pokipair_cards.json"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("records", []) if isinstance(payload, dict) else payload
            cards = [dict(item) for item in records if isinstance(item, dict)]
            override_path = path.parents[1] / "pokipair_identity_overrides.json"
            overrides = json.loads(override_path.read_text(encoding="utf-8"))
            for card in cards:
                key = f'{str(card.get("set_id") or "").upper()}:{card.get("collector_number")}'
                if isinstance(overrides.get(key), dict):
                    card.update(overrides[key])
                    card["identity_override_key"] = key
                if (
                    str(card.get("set_id") or "").upper() == "GEM_PACK_VOL_5"
                    and card.get("species_slot")
                    and card.get("variation_slot")
                ):
                    card["printed_code"] = (
                        f'{int(card["species_slot"]):02d}'
                        f'{int(card["variation_slot"]):02d}/07'
                    )
            return cards
        except Exception:
            return []

    @staticmethod
    def _sift_descriptors(
        image: np.ndarray | None,
        *,
        treatment: bool,
    ) -> tuple[list[Any], np.ndarray | None]:
        if image is None or not getattr(image, "size", 0):
            return [], None
        resized = cv2.resize(image, (350, 490), interpolation=cv2.INTER_AREA)
        region = (
            resized[215:455, 10:340]
            if treatment
            else resized[60:235, 20:330]
        )
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        return cv2.SIFT_create(nfeatures=900).detectAndCompute(gray, None)

    @staticmethod
    def _descriptor_score(
        left: tuple[list[Any], np.ndarray | None],
        right: tuple[list[Any], np.ndarray | None],
    ) -> float:
        left_points, left_descriptors = left
        right_points, right_descriptors = right
        if left_descriptors is None or right_descriptors is None:
            return 0.0
        pairs = cv2.BFMatcher().knnMatch(left_descriptors, right_descriptors, k=2)
        good = [match for match, runner_up in pairs if match.distance < 0.75 * runner_up.distance]
        if len(good) < 4:
            return float(len(good))
        source = np.float32([left_points[item.queryIdx].pt for item in good])
        target = np.float32([right_points[item.trainIdx].pt for item in good])
        _, mask = cv2.findHomography(source, target, cv2.RANSAC, 4.0)
        inliers = int(mask.sum()) if mask is not None else 0
        return float(inliers + len(good) * 0.08)

    @staticmethod
    def _treatment_texture_score(image: np.ndarray | None) -> float:
        if image is None or not getattr(image, "size", 0):
            return 0.0
        resized = cv2.resize(image, (350, 490), interpolation=cv2.INTER_AREA)
        region = resized[215:420, 15:335]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        saturation = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[:, :, 1]
        edge_density = float(np.count_nonzero(cv2.Canny(gray, 45, 140)) / gray.size)
        return float(saturation.mean() * edge_density)

    @staticmethod
    def treatment_response(image: np.ndarray | None) -> tuple[float, float, float]:
        """Summarize lighting-sensitive foil response outside shared artwork."""
        if image is None or not getattr(image, "size", 0):
            return (0.0, 0.0, 0.0)
        resized = cv2.resize(image, (350, 490), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized[215:455, 10:340], cv2.COLOR_BGR2HSV)
        value = hsv[:, :, 2].astype(np.float32)
        saturation = hsv[:, :, 1].astype(np.float32)
        return (round(float(value.mean()), 3), round(float(value.std()), 3), round(float(saturation.mean()), 3))

    @staticmethod
    def treatment_response_distance(left: Any, right: Any) -> float:
        if not left or not right or len(left) != 3 or len(right) != 3:
            return 0.0
        return float(sum(abs(float(a) - float(b)) * weight for a, b, weight in zip(left, right, (0.45, 0.30, 0.25))))

    @staticmethod
    def _variant_marker_score(
        live_fingerprint: str,
        reference_fingerprint: str,
    ) -> float:
        """Return bounded treatment evidence without overpowering geometry."""
        if not live_fingerprint or not reference_fingerprint:
            return 0.0
        distance = ArtworkIndexService.hamming(
            live_fingerprint,
            reference_fingerprint,
        )
        return max(0.0, 32.0 - float(distance)) * 0.45

    @staticmethod
    def _maximum_assignment(scores: list[list[float]]) -> list[int] | None:
        if not scores or not scores[0] or len(scores[0]) > 12:
            return None
        states: dict[int, tuple[float, list[int]]] = {0: (0.0, [])}
        for row in scores:
            next_states: dict[int, tuple[float, list[int]]] = {}
            for mask, (total, chosen) in states.items():
                for index, score in enumerate(row):
                    if mask & (1 << index):
                        continue
                    next_mask = mask | (1 << index)
                    candidate = (total + float(score), chosen + [index])
                    if next_mask not in next_states or candidate[0] > next_states[next_mask][0]:
                        next_states[next_mask] = candidate
            states = next_states
            if not states:
                return None
        return max(states.values(), key=lambda item: item[0])[1]

    def _resolve_visual_variant_families(self) -> None:
        """Resolve a mixed tabletop scan by artwork cluster, then card treatment.

        Shared artwork establishes the Pokemon family without trusting noisy OCR.
        A one-to-one treatment assignment is only applied when the local catalog
        supplies exactly one artwork-compatible reference per live card, making
        the correction safe for known variant sets while preserving duplicates.
        """
        live = {
            int(item["slot"]): self._sift_descriptors(
                self._crop_cache.get(int(item["slot"])), treatment=False
            )
            for item in self._state["slots"]
            if item.get("card") and int(item["slot"]) in self._crop_cache
        }
        remaining = set(live)
        groups: list[list[int]] = []
        while remaining:
            seed = remaining.pop()
            group = {seed}
            changed = True
            while changed:
                changed = False
                for slot in list(remaining):
                    if any(
                        self._descriptor_score(live[slot], live[member]) >= 45.0
                        for member in group
                    ):
                        remaining.remove(slot)
                        group.add(slot)
                        changed = True
            groups.append(sorted(group))

        project_root = Path(__file__).resolve().parents[2]
        for slots in groups:
            if len(slots) < 2:
                continue
            items = [self._state["slots"][slot - 1] for slot in slots]
            families = [key for item in items if (key := self._family_key(item.get("card")))]
            if not families:
                continue
            family, count = Counter(families).most_common(1)[0]
            if count < max(2, int(np.ceil(len(slots) * 0.67))):
                continue
            references: list[tuple[dict[str, Any], np.ndarray, tuple[list[Any], np.ndarray | None]]] = []
            anchor = live[slots[0]]
            for record in self._reference_cards:
                if self._family_key(record) != family:
                    continue
                relative = record.get("reference_image") or record.get("image_path")
                path = Path(str(relative or ""))
                if not path.is_absolute():
                    path = project_root / path
                image = cv2.imread(str(path)) if path.exists() else None
                if image is None:
                    continue
                artwork = self._sift_descriptors(image, treatment=False)
                if self._descriptor_score(anchor, artwork) < 45.0:
                    continue
                references.append((record, image, artwork))
            # A partial family scan may contain fewer live cards than known
            # references.  Keep enough candidates for one-to-one assignment,
            # then require every chosen treatment to clear strict score and
            # separation gates below; weak subsets and likely duplicates remain
            # review-needed instead of being forced into unique versions.
            if len(references) < len(slots):
                continue
            live_treatments = [
                self._sift_descriptors(self._crop_cache[slot], treatment=True)
                for slot in slots
            ]
            reference_treatments = [
                self._sift_descriptors(image, treatment=True)
                for _, image, _ in references
            ]
            scores = [
                [self._descriptor_score(live_item, reference_item) for reference_item in reference_treatments]
                for live_item in live_treatments
            ]
            self._apply_temporal_variant_priors(slots, references, scores)
            if str(family[1]).upper().startswith("GEM_PACK"):
                ordered_references = sorted(
                    range(len(references)),
                    key=lambda index: int(references[index][0].get("collector_number") or 0),
                )
                for row_index, item in enumerate(items):
                    printed_code = str(item.get("printed_code") or "")
                    suffix_match = re.search(r"(\d{2})/\d{2}$", printed_code)
                    if not suffix_match:
                        continue
                    variation = int(suffix_match.group(1))
                    if 1 <= variation <= len(ordered_references):
                        scores[row_index][ordered_references[variation - 1]] += 1000.0
                # The final Gem Pack treatment carries a distinctive artwork
                # badge.  Lock it only when its artwork match has a clear margin;
                # this keeps rainbow glare from masquerading as the printed stamp.
                badge_reference = ordered_references[-1]
                badge_scores = [
                    self._descriptor_score(live[slot], references[badge_reference][2])
                    for slot in slots
                ]
                ranked_badges = sorted(
                    enumerate(badge_scores),
                    key=lambda item: item[1],
                    reverse=True,
                )
                if (
                    len(ranked_badges) >= 2
                    and ranked_badges[0][1] - ranked_badges[1][1] >= 20.0
                ):
                    scores[ranked_badges[0][0]][badge_reference] += 2200.0
                # Star and shard treatments are the two high-frequency foils.
                # Their edge-density separation is much stronger under glare than
                # OCR or global color histograms, so reserve those references when
                # the live texture ordering has decisive margins.
                if len(ordered_references) >= 4:
                    texture_ranking = sorted(
                        enumerate(
                            self._treatment_texture_score(self._crop_cache[slot])
                            for slot in slots
                        ),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                    star_locked = (
                        len(texture_ranking) >= 3
                        and texture_ranking[0][1] >= 12.0
                        and texture_ranking[0][1] - texture_ranking[1][1] >= 1.5
                    )
                    if star_locked:
                        scores[texture_ranking[0][0]][ordered_references[2]] += 2600.0
                    if (
                        star_locked
                        and len(texture_ranking) >= 3
                        and texture_ranking[1][1] >= 10.0
                        and texture_ranking[1][1] - texture_ranking[2][1] >= 3.0
                    ):
                        scores[texture_ranking[1][0]][ordered_references[3]] += 2400.0
            assignment = self._maximum_assignment(scores)
            if assignment is None:
                continue
            assignment_ready = True
            for slot, reference_index, row in zip(slots, assignment, scores):
                chosen_score = float(row[reference_index])
                alternatives = [float(score) for index, score in enumerate(row) if index != reference_index]
                runner_up = max(alternatives, default=0.0)
                item = self._state["slots"][slot - 1]
                item["batch_variant_diagnostics"] = {
                    "candidate_collector_number": references[reference_index][0].get("collector_number"),
                    "top_score": round(chosen_score, 3),
                    "runner_up_score": round(runner_up, 3),
                    "score_gap": round(chosen_score - runner_up, 3),
                    "score_ready": chosen_score >= 28.0,
                    "margin_ready": chosen_score - runner_up >= 8.0,
                    "reference_count": len(references),
                }
                if chosen_score < 28.0 or chosen_score - runner_up < 8.0:
                    assignment_ready = False
            if not assignment_ready:
                continue
            for slot, reference_index, row in zip(slots, assignment, scores):
                item = self._state["slots"][slot - 1]
                reference = dict(references[reference_index][0])
                item.update({
                    "card": reference,
                    "collector_number": reference.get("collector_number"),
                    "status": "verified",
                    "verified": True,
                    "batch_variant_resolved": True,
                    "batch_variant_score": round(float(row[reference_index]), 3),
                })
            # A card outside the shared-artwork cluster cannot safely borrow this
            # family's identity. Keep its candidate visible, but never present the
            # conflicting version as verified catalog truth.
            for item in self._state["slots"]:
                outside_slot = int(item.get("slot") or 0)
                if outside_slot in slots or self._family_key(item.get("card")) != family:
                    continue
                item.update({
                    "status": "review-needed",
                    "verified": False,
                    "family_artwork_conflict": True,
                })

    def _apply_temporal_variant_priors(
        self,
        slots: list[int],
        references: list[tuple[dict[str, Any], np.ndarray, tuple[list[Any], np.ndarray | None]]],
        scores: list[list[float]],
    ) -> None:
        """Break close treatment ties with a fingerprint-confirmed exact prior."""
        for row_index, slot in enumerate(slots):
            history = self._temporal_history.get(slot) or {}
            confirmations = int(history.get("confirmations") or 0)
            if confirmations < 1:
                continue
            stored_fingerprint = str(history.get("fingerprint") or "")
            if not stored_fingerprint:
                continue
            current_fingerprint = ArtworkIndexService.variant_marker_fingerprint(
                self._crop_cache[slot]
            )
            fingerprint_distance = ArtworkIndexService.hamming(
                current_fingerprint, stored_fingerprint
            )
            # One observation is enough only for a near-identical treatment
            # marker. Ordinary matches still require the normal two-pass streak.
            maximum_distance = 4 if confirmations == 1 else 10
            if fingerprint_distance > maximum_distance:
                continue
            prior_key = self._version_key(history.get("card"))
            for reference_index, (reference, _, _) in enumerate(references):
                if self._version_key(reference) == prior_key:
                    scores[row_index][reference_index] += 350.0
                    break

    @staticmethod
    def _variant_key(card: dict[str, Any]) -> str:
        return str(
            card.get("identity_override_key")
            or card.get("id")
            or f'{card.get("set_id", "")}:{card.get("collector_number", "")}:{card.get("printed_code", "")}'
        )

    @staticmethod
    def _candidate_score(card: dict[str, Any]) -> float:
        return float(card.get("fused_score") or card.get("score") or card.get("visual_score") or 0.0)

    def _assign_unique_variants(self) -> None:
        """Find the strongest one-to-one assignment for an explicit variant-set scan."""
        populated = [item for item in self._state["slots"] if item.get("card")]
        expected = int(self._state.get("max_cards") or SixCardGridDetector.DEFAULT_CARDS)
        if len(populated) != expected:
            return
        families = [self._family_key(item.get("card")) for item in populated]
        if not families or not families[0] or any(family != families[0] for family in families):
            return
        family = families[0]
        per_slot: list[dict[str, dict[str, Any]]] = []
        pool: dict[str, dict[str, Any]] = {}
        for item in populated:
            candidates = list(self._candidate_cache.get(int(item["slot"]), [])) + [dict(item["card"])]
            matching: dict[str, dict[str, Any]] = {}
            for candidate in candidates:
                if self._family_key(candidate) != family:
                    continue
                key = self._variant_key(candidate)
                if key not in matching or self._candidate_score(candidate) > self._candidate_score(matching[key]):
                    matching[key] = candidate
                    pool[key] = candidate
            per_slot.append(matching)
        if len(pool) < expected or any(not candidates for candidates in per_slot):
            return
        keys = sorted(pool, key=lambda key: max(
            (self._candidate_score(candidates[key]) for candidates in per_slot if key in candidates),
            default=0.0,
        ), reverse=True)[:12]
        states: dict[int, tuple[float, list[str]]] = {0: (0.0, [])}
        for candidates in per_slot:
            next_states: dict[int, tuple[float, list[str]]] = {}
            for mask, (total, assigned) in states.items():
                for index, key in enumerate(keys):
                    if mask & (1 << index) or key not in candidates:
                        continue
                    score = total + self._candidate_score(candidates[key])
                    next_mask = mask | (1 << index)
                    if next_mask not in next_states or score > next_states[next_mask][0]:
                        next_states[next_mask] = (score, assigned + [key])
            states = next_states
            if not states:
                return
        _, assignment = max(states.values(), key=lambda result: result[0])
        for item, candidates, key in zip(populated, per_slot, assignment):
            card = candidates[key]
            item["card"] = card
            item["confidence"] = self._candidate_score(card)
            item["unique_variant_assigned"] = True

    @staticmethod
    def output_ready(item: dict[str, Any]) -> bool:
        """A processed region or species-only guess is not a publishable identity."""
        card = item.get("card") or {}
        return bool(
            item.get("verified") is True
            and item.get("status") == "verified"
            and isinstance(card, dict)
            and any(card.get(key) for key in ("english_name", "printed_name", "canonical_name", "name", "display_name"))
            and not item.get("exact_version_unresolved")
            and not card.get("exact_version_unresolved")
            and not card.get("provisional")
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._expire_stalled_capture()
            slots = deepcopy(self._state["slots"])
            for item in slots:
                item["output_ready"] = self.output_ready(item)
            detected = [item for item in slots if item.get("status") not in {"empty", "waiting", "not-detected"}]
            pending = sum(item.get("status") == "recognizing" for item in detected)
            verified = sum(item["output_ready"] for item in detected)
            return {
                **self._state,
                # completed_count is worker completion, not identity verification.
                "verified_count": verified,
                "review_count": len(detected) - pending - verified,
                "pending_count": pending,
                "selected_slots": sorted(self._selected_slots),
                "slots": slots,
            }

    @staticmethod
    def detect_regions(frame: np.ndarray | None, max_cards: int = 12) -> dict[str, Any]:
        if frame is None or not getattr(frame, "size", 0):
            return {"detected_count": 0, "slots": []}
        detections = SixCardGridDetector.detect(frame, max_cards=max_cards)
        return {
            "detected_count": len(detections),
            "slots": [{
                "slot": int(item["slot"]),
                "confidence": item["confidence"],
                "polygon": item["polygon"],
            } for item in detections],
        }

    @staticmethod
    def detect_candidates(frame: np.ndarray | None, max_cards: int = 12) -> list[dict[str, Any]]:
        if frame is None or not getattr(frame, "size", 0):
            return []
        return SixCardGridDetector.detect(frame, max_cards=max_cards)

    @staticmethod
    def crop_region(frame: np.ndarray | None, slot: int, max_cards: int = 12) -> dict[str, Any] | None:
        if frame is None or not getattr(frame, "size", 0):
            return None
        return next(
            (
                item for item in SixCardGridDetector.detect(frame, max_cards=max_cards)
                if int(item["slot"]) == int(slot)
            ),
            None,
        )

    @staticmethod
    def track_region(
        frame: np.ndarray | None,
        polygon: list[list[float]] | np.ndarray,
        max_cards: int = 12,
    ) -> dict[str, Any] | None:
        """Track one selected card by overlap, independent of slot reordering."""
        if frame is None or not getattr(frame, "size", 0) or polygon is None:
            return None
        target = np.asarray(polygon, dtype=np.float32)
        if target.shape != (4, 2):
            return None
        target_center = np.mean(target, axis=0)
        ranked: list[tuple[float, float, dict[str, Any]]] = []
        for item in SixCardGridDetector.detect(frame, max_cards=max_cards):
            candidate = np.asarray(item.get("polygon"), dtype=np.float32)
            if candidate.shape != (4, 2):
                continue
            overlap = SixCardGridDetector._polygon_iou(target, candidate)
            center_distance = float(np.linalg.norm(target_center - np.mean(candidate, axis=0)))
            ranked.append((overlap, center_distance, item))
        if not ranked:
            return None
        overlap, center_distance, match = max(ranked, key=lambda row: (row[0], -row[1]))
        if overlap < 0.35 or center_distance > 0.16:
            return None
        return {
            **match,
            "tracking_iou": round(overlap, 4),
            "tracking_center_distance": round(center_distance, 4),
        }

    def select_slots(self, slots: list[int] | tuple[int, ...]) -> dict[str, Any]:
        if not isinstance(slots, (list, tuple)) or any(
            isinstance(slot, bool) or not isinstance(slot, int)
            or not 1 <= slot <= SixCardGridDetector.MAX_CARDS for slot in slots
        ):
            return {**self.status(), "ok": False, "reason": "invalid_slots"}
        selected = set(slots)
        with self._lock:
            ready = {item["slot"] for item in self._state["slots"] if self.output_ready(item)}
            # Existing selections may always be removed, including after a rescan.
            blocked = selected - self._selected_slots - ready
            if blocked:
                return {**self.status(), "ok": False, "reason": "cards_need_verification", "blocked_slots": sorted(blocked)}
            self._selected_slots = selected
            self._state["selected_slots"] = sorted(selected)
            self._state["updated_at"] = time.time()
            self._persist_presentation()
        return {**self.status(), "ok": True}

    def _load_selected_slots(self) -> set[int]:
        try:
            payload = json.loads(self._presentation_path.read_text(encoding="utf-8"))
            return {
                int(slot) for slot in payload.get("selected_slots", [])
                if 1 <= int(slot) <= SixCardGridDetector.MAX_CARDS
            }
        except Exception:
            return set()

    def _load_completed_state(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._presentation_path.read_text(encoding="utf-8"))
            state = payload.get("completed_state")
            if not isinstance(state, dict) or state.get("status") != "complete":
                return None
            slots = state.get("slots")
            if not isinstance(slots, list) or not slots:
                return None
            detected = int(state.get("detected_count") or 0)
            completed = int(state.get("completed_count") or 0)
            terminal = sum(
                1 for item in slots
                if isinstance(item, dict)
                and item.get("status") not in {"recognizing", "not-detected", "empty"}
            )
            if detected < 0 or completed < 0 or completed > detected or terminal != completed:
                return None
            state["selected_slots"] = sorted(self._selected_slots)
            state["restored"] = True
            return state
        except Exception:
            return None

    @staticmethod
    def _presentation_slot(item: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "slot", "status", "card", "confidence", "polygon", "verified",
            "collector_number", "printed_code", "temporal_confirmation",
            "temporal_confirmation_count", "temporal_confirmation_progress",
            "temporal_confirmation_required", "batch_variant_resolved",
            "batch_variant_score", "family_artwork_conflict",
            "name_candidate", "language", "exact_version_unresolved", "version_safety_reason",
        )
        return {field: item.get(field) for field in fields if field in item}

    def _persist_presentation(self) -> None:
        try:
            self._presentation_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._presentation_path.with_suffix(self._presentation_path.suffix + ".tmp")
            completed_state = None
            if self._state.get("status") == "complete":
                completed_state = {
                    "mode": "six-card-grid",
                    "job_id": int(self._state.get("job_id") or 0),
                    "status": "complete",
                    "detected_count": int(self._state.get("detected_count") or 0),
                    "completed_count": int(self._state.get("completed_count") or 0),
                    "started_at": self._state.get("started_at"),
                    "updated_at": self._state.get("updated_at"),
                    "unique_variants": bool(self._state.get("unique_variants")),
                    "max_cards": int(self._state.get("max_cards") or SixCardGridDetector.DEFAULT_CARDS),
                    "slots": [self._presentation_slot(item) for item in self._state.get("slots", [])],
                }
            temporary.write_text(json.dumps({
                "version": 1,
                "selected_slots": sorted(self._selected_slots),
                "completed_state": completed_state,
                "updated_at": time.time(),
            }, indent=2), encoding="utf-8")
            os.replace(temporary, self._presentation_path)
        except Exception:
            return

    def shutdown(self) -> None:
        for worker in self._workers.values():
            worker.shutdown()
