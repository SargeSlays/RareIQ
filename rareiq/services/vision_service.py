from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from cv2_enumerate_cameras import enumerate_cameras


@dataclass(frozen=True)
class DetectionResult:
    crop: np.ndarray | None
    polygon: np.ndarray | None
    confidence: float
    aspect_score: float = 0.0
    rectangularity_score: float = 0.0
    solidity_score: float = 0.0
    edge_score: float = 0.0
    area_score: float = 0.0


@dataclass
class AcquisitionFrame:
    crop: np.ndarray
    polygon: np.ndarray
    frame_id: int
    detection_confidence: float
    quality_score: float
    sharpness: float
    brightness: float
    contrast: float
    glare_score: float
    fingerprint: np.ndarray
    full_card_hash: int
    artwork_hash: int
    structural_image: np.ndarray
    acquisition_epoch: int
    captured_at: float
    stream_session_id: int = 0
    device_sequence_id: int = 0
    device_timestamp: float = 0.0
    content_fingerprint: str | None = None
    source_camera_index: int | None = None
    source_camera_backend: int | None = None


class MultiFrameAcquisitionBuffer:
    """Keeps and ranks several corrected views of the current physical card."""

    REPLACEMENT_WINDOW_SIZE = 8
    REPLACEMENT_REQUIRED_CHANGED = 6
    FULL_CARD_HASH_THRESHOLD = 16
    ARTWORK_HASH_THRESHOLD = 14
    STRUCTURAL_SIMILARITY_THRESHOLD = 0.72
    ARTWORK_STRONG_STRUCTURAL_SIMILARITY_THRESHOLD = 0.60
    POLYGON_IOU_MINIMUM = 0.75
    MAX_CORNER_MOVEMENT = 0.025
    REFERENCE_SAMPLE_COUNT = 5
    PROPOSED_REFERENCE_COUNT = 5
    MIN_REPLACEMENT_QUALITY_SCORE = 0.15
    MIN_REPLACEMENT_DETECTION_CONFIDENCE = 0.42
    SUSTAINED_INVALID_GEOMETRY_FRAMES = 3
    IDENTITY_COLLAPSE_MAJORITY = 6
    DIAGNOSTIC_JOURNAL_SIZE = 64

    def __init__(
        self,
        *,
        max_samples: int = 12,
        consensus_count: int = 3,
    ) -> None:
        self.max_samples = max(3, int(max_samples))
        self.consensus_count = max(2, int(consensus_count))
        self.samples: list[AcquisitionFrame] = []
        self.last_captured_fingerprint: np.ndarray | None = None
        self.replacement_frames = 0
        self.reference_samples: list[AcquisitionFrame] = []
        self.replacement_window: deque[dict[str, Any]] = deque(
            maxlen=self.REPLACEMENT_WINDOW_SIZE
        )
        self.last_replacement_evidence: dict[str, Any] = {}
        self.replacement_journal: deque[dict[str, Any]] = deque(
            maxlen=self.DIAGNOSTIC_JOURNAL_SIZE
        )
        self._replacement_latched = False

    def reset(
        self,
        *,
        reason: str = "acquisition_reset",
        clear_replacement_latch: bool = True,
    ) -> None:
        self.samples.clear()
        self.replacement_frames = 0
        self.replacement_window.clear()
        self.last_replacement_evidence = {}
        if clear_replacement_latch:
            self._replacement_latched = False
        self._record_replacement_decision(
            {"event": "replacement_window_reset", "reason": reason}
        )

    def _record_replacement_decision(self, entry: dict[str, Any]) -> None:
        self.replacement_journal.append({
            "timestamp": time.time(),
            "frame_id": entry.get("frame_id"),
            "generation": None,
            "previous_state": "captured_identity",
            "next_state": "proposed_replacement",
            **entry,
        })

    @staticmethod
    def _fingerprint(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(
            gray,
            (32, 32),
            interpolation=cv2.INTER_AREA,
        )
        normalized = cv2.equalizeHist(resized)
        return normalized.astype(np.float32).reshape(-1) / 255.0

    @staticmethod
    def _dhash(image: np.ndarray, *, artwork: bool = False) -> int:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if artwork:
            height, width = gray.shape[:2]
            gray = gray[
                int(height * 0.16):int(height * 0.62),
                int(width * 0.08):int(width * 0.92),
            ]
        resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        value = 0
        for bit in (resized[:, 1:] > resized[:, :-1]).flatten():
            value = (value << 1) | int(bool(bit))
        return value

    @staticmethod
    def _structural_image(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (64, 90), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _structural_similarity(left: np.ndarray, right: np.ndarray) -> float:
        left_f = left.astype(np.float32)
        right_f = right.astype(np.float32)
        mu_left = float(left_f.mean())
        mu_right = float(right_f.mean())
        var_left = float(left_f.var())
        var_right = float(right_f.var())
        covariance = float(
            np.mean((left_f - mu_left) * (right_f - mu_right))
        )
        c1 = (0.01 * 255.0) ** 2
        c2 = (0.03 * 255.0) ** 2
        denominator = (
            (mu_left ** 2 + mu_right ** 2 + c1)
            * (var_left + var_right + c2)
        )
        if denominator <= 0.0:
            return 1.0
        return float(np.clip(
            ((2.0 * mu_left * mu_right + c1) * (2.0 * covariance + c2))
            / denominator,
            -1.0,
            1.0,
        ))

    @staticmethod
    def _polygon_iou(left: np.ndarray, right: np.ndarray) -> float:
        left_hull = cv2.convexHull(np.asarray(left, dtype=np.float32))
        right_hull = cv2.convexHull(np.asarray(right, dtype=np.float32))
        left_area = abs(float(cv2.contourArea(left_hull)))
        right_area = abs(float(cv2.contourArea(right_hull)))
        if left_area <= 0.0 or right_area <= 0.0:
            return 0.0
        intersection, _ = cv2.intersectConvexConvex(left_hull, right_hull)
        union = left_area + right_area - float(intersection)
        return float(intersection / union) if union > 0.0 else 0.0

    @staticmethod
    def _hash_distance(left: int, right: int) -> int:
        return int(left ^ right).bit_count()

    @staticmethod
    def fingerprint_distance(
        left: np.ndarray | None,
        right: np.ndarray | None,
    ) -> float:
        if left is None or right is None:
            return 1.0

        if left.shape != right.shape:
            return 1.0

        return float(np.mean(np.abs(left - right)))

    @staticmethod
    def _quality(image: np.ndarray) -> dict[str, float]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        raw_sharpness = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F,
            ).var()
        )
        sharpness = float(
            np.clip(
                raw_sharpness / 700.0,
                0.0,
                1.0,
            )
        )

        mean = float(gray.mean())
        brightness = float(
            np.clip(
                1.0 - abs(mean - 132.0) / 132.0,
                0.0,
                1.0,
            )
        )

        contrast = float(
            np.clip(
                float(gray.std()) / 72.0,
                0.0,
                1.0,
            )
        )

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        glare_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 235], dtype=np.uint8),
            np.array([180, 52, 255], dtype=np.uint8),
        )
        glare_ratio = (
            float(np.count_nonzero(glare_mask))
            / float(max(1, glare_mask.size))
        )
        glare_score = float(
            np.clip(
                1.0 - glare_ratio / 0.16,
                0.0,
                1.0,
            )
        )

        quality_score = (
            sharpness * 0.38
            + brightness * 0.17
            + contrast * 0.18
            + glare_score * 0.27
        )

        return {
            "quality_score": round(quality_score, 5),
            "sharpness": round(sharpness, 5),
            "brightness": round(brightness, 5),
            "contrast": round(contrast, 5),
            "glare_score": round(glare_score, 5),
        }

    def add(
        self,
        *,
        crop: np.ndarray,
        polygon: np.ndarray,
        frame_id: int,
        detection_confidence: float,
        acquisition_epoch: int = 0,
        captured_at: float | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> AcquisitionFrame | None:
        if crop is None or crop.size == 0:
            return None

        quality = self._quality(crop)
        fingerprint = self._fingerprint(crop)

        provenance = dict(provenance or {})
        sample = AcquisitionFrame(
            crop=crop.copy(),
            polygon=np.asarray(
                polygon,
                dtype=np.float32,
            ).copy(),
            frame_id=int(frame_id),
            detection_confidence=float(
                np.clip(
                    detection_confidence,
                    0.0,
                    1.0,
                )
            ),
            quality_score=float(quality["quality_score"]),
            sharpness=float(quality["sharpness"]),
            brightness=float(quality["brightness"]),
            contrast=float(quality["contrast"]),
            glare_score=float(quality["glare_score"]),
            fingerprint=fingerprint,
            full_card_hash=self._dhash(crop),
            artwork_hash=self._dhash(crop, artwork=True),
            structural_image=self._structural_image(crop),
            acquisition_epoch=int(acquisition_epoch),
            captured_at=float(captured_at or time.time()),
            stream_session_id=int(provenance.get("stream_session_id") or 0),
            device_sequence_id=int(provenance.get("device_sequence_id") or 0),
            device_timestamp=float(provenance.get("device_timestamp") or 0.0),
            content_fingerprint=provenance.get("content_fingerprint"),
            source_camera_index=provenance.get("source_camera_index"),
            source_camera_backend=provenance.get("source_camera_backend"),
        )

        self.samples.append(sample)
        # Retain the newest acquisition history. Quality is applied only after
        # recency/epoch/geometry eligibility filtering at selection time.
        if len(self.samples) > self.max_samples:
            self.samples = sorted(
                self.samples, key=lambda item: item.frame_id, reverse=True
            )[:self.max_samples]

        return sample

    def _rank_consensus(
        self, candidates: list[AcquisitionFrame]
    ) -> list[AcquisitionFrame]:
        candidate_pool = list(candidates)
        ranked: list[tuple[float, int, AcquisitionFrame]] = []
        for sample in candidate_pool:
            similarities = []

            for other in candidate_pool:
                if other is sample:
                    continue

                distance = self.fingerprint_distance(
                    sample.fingerprint,
                    other.fingerprint,
                )
                similarities.append(
                    float(
                        np.clip(
                            1.0 - distance / 0.30,
                            0.0,
                            1.0,
                        )
                    )
                )

            similarities.sort(reverse=True)
            agreement = (
                sum(
                    similarities[
                        :max(
                            1,
                            self.consensus_count - 1,
                        )
                    ]
                )
                / max(
                    1,
                    min(
                        len(similarities),
                        self.consensus_count - 1,
                    ),
                )
                if similarities
                else 0.0
            )

            combined = (
                sample.quality_score * 0.60
                + sample.detection_confidence * 0.18
                + agreement * 0.22
            )

            ranked.append((combined, sample.frame_id, sample))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked]

    def eligible_samples(
        self,
        *,
        current_epoch: int,
        current_frame_id: int | None,
        current_polygon: np.ndarray | None,
        now: float | None = None,
        max_age_seconds: float = 0.40,
        minimum_polygon_iou: float = 0.80,
        quarantined_frame_ids: set[int] | None = None,
        excluded_frame_ids: set[int] | None = None,
    ) -> list[AcquisitionFrame]:
        now = time.time() if now is None else float(now)
        quarantine = set(quarantined_frame_ids or ())
        excluded = set(excluded_frame_ids or ())
        minimum_frame = max(quarantine, default=-1)
        eligible = []
        for sample in self.samples:
            if sample.acquisition_epoch != int(current_epoch):
                continue
            if sample.frame_id <= 0 or sample.frame_id in quarantine | excluded:
                continue
            if sample.frame_id <= minimum_frame:
                continue
            if current_frame_id is None or sample.frame_id > int(current_frame_id):
                continue
            if now - sample.captured_at > float(max_age_seconds):
                continue
            if current_polygon is None or self._polygon_iou(
                sample.polygon, current_polygon
            ) < float(minimum_polygon_iou):
                continue
            eligible.append(sample)
        return sorted(eligible, key=lambda item: item.frame_id, reverse=True)

    def best_recent_consensus(self, **eligibility: Any) -> AcquisitionFrame | None:
        ranked = self._rank_consensus(self.eligible_samples(**eligibility))
        return ranked[0] if ranked else None

    def next_eligible_consensus(self, **eligibility: Any) -> AcquisitionFrame | None:
        return self.best_recent_consensus(**eligibility)

    def best_consensus(self) -> AcquisitionFrame | None:
        if not self.samples:
            return None
        ranked = self._rank_consensus(self.samples)
        return ranked[0] if ranked else None

    def mark_captured(
        self,
        sample: AcquisitionFrame | None,
    ) -> None:
        if sample is not None:
            self.last_captured_fingerprint = (
                sample.fingerprint.copy()
            )
            ordered = sorted(
                self.samples,
                key=lambda item: self.fingerprint_distance(
                    item.fingerprint, sample.fingerprint
                ),
            )
            self.reference_samples = [
                item for item in ordered[:self.REFERENCE_SAMPLE_COUNT]
            ] or [sample]

            # Start the next acquisition epoch from the captured identity. This
            # prevents a high-quality pre-capture sample from becoming the next
            # card reference after exposure or autofocus changes.
            self.samples = [sample]
        self.replacement_frames = 0
        self.replacement_window.clear()
        self.last_replacement_evidence = {}
        self._replacement_latched = False
        self._record_replacement_decision({
            "event": "identity_rebased",
            "reason": "successful_capture",
            "frame_id": sample.frame_id if sample is not None else None,
        })

    def observe_replacement(
        self,
        fingerprint: np.ndarray | AcquisitionFrame | None,
        *,
        polygon: np.ndarray | None = None,
    ) -> bool:
        sample = fingerprint if isinstance(fingerprint, AcquisitionFrame) else None
        if self._replacement_latched:
            return False
        if (
            fingerprint is None
            or self.last_captured_fingerprint is None
        ):
            self.replacement_frames = 0
            self.replacement_window.clear()
            return False

        if sample is None or not self.reference_samples:
            distance = self.fingerprint_distance(
                np.asarray(fingerprint), self.last_captured_fingerprint
            )
            changed = distance >= 0.115
            self.replacement_frames = (
                self.replacement_frames + 1
                if changed else max(0, self.replacement_frames - 2)
            )
            # Backward-compatible fingerprint-only callers do not have the
            # geometry and structural evidence required by the live path.
            return self.replacement_frames >= 4

        references = self.reference_samples
        full_distance = int(np.median([
            self._hash_distance(sample.full_card_hash, ref.full_card_hash)
            for ref in references
        ]))
        artwork_distance = int(np.median([
            self._hash_distance(sample.artwork_hash, ref.artwork_hash)
            for ref in references
        ]))
        structural_similarity = float(np.median([
            self._structural_similarity(
                sample.structural_image, ref.structural_image
            )
            for ref in references
        ]))
        primary_identity_changed = (
            full_distance >= self.FULL_CARD_HASH_THRESHOLD
            and artwork_distance >= self.ARTWORK_HASH_THRESHOLD
            and structural_similarity < self.STRUCTURAL_SIMILARITY_THRESHOLD
        )
        artwork_identity_changed = (
            artwork_distance >= self.ARTWORK_HASH_THRESHOLD
            and structural_similarity
            < self.ARTWORK_STRONG_STRUCTURAL_SIMILARITY_THRESHOLD
        )
        identity_changed = bool(
            primary_identity_changed
        )
        identity_collapsed = (
            full_distance < self.FULL_CARD_HASH_THRESHOLD - 4
            and artwork_distance < self.ARTWORK_HASH_THRESHOLD - 4
            and structural_similarity >= self.STRUCTURAL_SIMILARITY_THRESHOLD + 0.06
        )

        proposed = [
            item for item in self.replacement_window
            if item.get("identity_changed") and item.get("polygon") is not None
        ][-self.PROPOSED_REFERENCE_COUNT:]
        proposed_polygons = [
            np.asarray(item["polygon"], dtype=np.float32)
            for item in proposed
        ]
        proposed_polygons.append(np.asarray(sample.polygon, dtype=np.float32))
        proposed_median = np.median(
            np.stack(proposed_polygons), axis=0
        ).astype(np.float32)
        polygon_iou = self._polygon_iou(sample.polygon, proposed_median)
        corner_movement = float(np.mean(np.linalg.norm(
            sample.polygon - proposed_median, axis=1
        )))
        valid_full_card_geometry = bool(
            sample.polygon.shape == (4, 2)
            and np.isfinite(sample.polygon).all()
            and abs(float(cv2.contourArea(sample.polygon))) > 0.001
        )
        stable_crop_quality = bool(
            sample.quality_score >= self.MIN_REPLACEMENT_QUALITY_SCORE
            and sample.detection_confidence
            >= self.MIN_REPLACEMENT_DETECTION_CONFIDENCE
        )
        geometry_valid = bool(
            valid_full_card_geometry
            and
            polygon_iou >= self.POLYGON_IOU_MINIMUM
            and corner_movement <= self.MAX_CORNER_MOVEMENT
            and stable_crop_quality
        )
        changed = identity_changed and geometry_valid
        evidence = {
            "full_card_hash_distance": full_distance,
            "artwork_hash_distance": artwork_distance,
            "structural_similarity": round(structural_similarity, 5),
            "polygon_iou": round(polygon_iou, 5),
            "corner_movement": round(corner_movement, 5),
            "geometry_valid": geometry_valid,
            "valid_full_card_geometry": valid_full_card_geometry,
            "stable_crop_quality": stable_crop_quality,
            "quality_score": round(sample.quality_score, 5),
            "detection_confidence": round(sample.detection_confidence, 5),
            "identity_changed": identity_changed,
            "primary_identity_changed": primary_identity_changed,
            "artwork_identity_changed": artwork_identity_changed,
            "identity_collapsed": identity_collapsed,
            "changed": changed,
            "frame_id": sample.frame_id,
            "timestamp": sample.captured_at,
            "full_card_fingerprint": f"{sample.full_card_hash:016x}",
            "artwork_fingerprint": f"{sample.artwork_hash:016x}",
            "polygon": sample.polygon.tolist(),
            "corners": sample.polygon.tolist(),
        }
        self.replacement_window.append(evidence)
        recent_invalid_geometry = 0
        for item in reversed(self.replacement_window):
            if item.get("geometry_valid"):
                break
            recent_invalid_geometry += 1
        collapsed_frames = sum(
            bool(item.get("identity_collapsed"))
            for item in self.replacement_window
        )
        if (
            recent_invalid_geometry
            >= self.SUSTAINED_INVALID_GEOMETRY_FRAMES
        ):
            self.replacement_window.clear()
            self.replacement_window.append(evidence)
            evidence["reason"] = "sustained_proposed_geometry_invalid"
        elif (
            len(self.replacement_window) == self.REPLACEMENT_WINDOW_SIZE
            and collapsed_frames >= self.IDENTITY_COLLAPSE_MAJORITY
        ):
            self.replacement_window.clear()
            self.replacement_window.append(evidence)
            evidence["reason"] = "identity_evidence_collapsed_majority"
        elif identity_collapsed:
            evidence["reason"] = "identity_evidence_disagrees"
        elif not geometry_valid:
            evidence["reason"] = "proposed_geometry_disagrees"
        changed_frames = sum(
            bool(item["changed"]) for item in self.replacement_window
        )
        self.replacement_frames = changed_frames
        confirmed = (
            len(self.replacement_window) == self.REPLACEMENT_WINDOW_SIZE
            and changed_frames >= self.REPLACEMENT_REQUIRED_CHANGED
        )
        evidence.update({
            "changed_frames": changed_frames,
            "window_size": len(self.replacement_window),
            "replacement_confirmed": confirmed,
            "decisive": confirmed,
        })
        self.last_replacement_evidence = evidence
        self._record_replacement_decision({
            key: value for key, value in evidence.items()
            if key not in {"polygon", "corners"}
        } | {
            "event": "replacement_window_decision",
            "reason": evidence.get("reason") or (
                "replacement_confirmed" if confirmed else "collecting_evidence"
            ),
        })
        if confirmed:
            self._replacement_latched = True
        return confirmed

    def telemetry(self) -> dict[str, Any]:
        best = self.best_consensus()

        return {
            "buffer_size": len(self.samples),
            "buffer_capacity": self.max_samples,
            "consensus_target": self.consensus_count,
            "best_quality": (
                round(best.quality_score, 4)
                if best is not None
                else 0.0
            ),
            "best_sharpness": (
                round(best.sharpness, 4)
                if best is not None
                else 0.0
            ),
            "best_brightness": (
                round(best.brightness, 4)
                if best is not None
                else 0.0
            ),
            "best_contrast": (
                round(best.contrast, 4)
                if best is not None
                else 0.0
            ),
            "best_glare_score": (
                round(best.glare_score, 4)
                if best is not None
                else 0.0
            ),
            "replacement_frames": self.replacement_frames,
            "replacement_evidence": dict(self.last_replacement_evidence),
            "replacement_journal": list(self.replacement_journal),
        }


class ConfidenceLockTracker:
    """Converts imperfect card detections into a stable temporal lock.

    Detection confidence and geometric motion are accumulated over time.
    A brief contour failure or noisy frame decays confidence instead of
    immediately destroying all lock progress.
    """

    def __init__(
        self,
        *,
        stable_target: int = 4,
        detect_threshold: float = 0.32,
        lock_threshold: float = 0.48,
        unlock_threshold: float = 0.44,
        smoothing: float = 0.28,
        missing_tolerance: int = 6,
        movement_soft_limit: float = 0.035,
        movement_hard_limit: float = 0.075,
    ) -> None:
        self.stable_target = int(stable_target)
        self.detect_threshold = float(detect_threshold)
        self.lock_threshold = float(lock_threshold)
        self.unlock_threshold = float(unlock_threshold)
        self.smoothing = float(smoothing)
        self.missing_tolerance = int(missing_tolerance)
        self.movement_soft_limit = float(movement_soft_limit)
        self.movement_hard_limit = float(movement_hard_limit)

        self.reference: np.ndarray | None = None
        self.detection_confidence = 0.0
        self.lock_confidence = 0.0
        self.movement = 1.0
        self.detected_frames = 0
        self.stable_frames = 0
        self.missing_frames = 0
        self.locked = False

    def reset(self) -> None:
        self.reference = None
        self.detection_confidence = 0.0
        self.lock_confidence = 0.0
        self.movement = 1.0
        self.detected_frames = 0
        self.stable_frames = 0
        self.missing_frames = 0
        self.locked = False

    def miss(self) -> tuple[bool, bool, np.ndarray | None]:
        self.missing_frames += 1
        self.detection_confidence *= 0.72

        if self.missing_frames <= self.missing_tolerance:
            self.lock_confidence *= 0.84
            self.detected_frames = max(0, self.detected_frames - 1)
            self.stable_frames = max(0, self.stable_frames - 1)
        else:
            self.lock_confidence *= 0.38
            self.reference = None
            self.detected_frames = 0
            self.stable_frames = 0

        if self.locked and self.lock_confidence < self.unlock_threshold:
            self.locked = False

        visible = (
            self.reference is not None
            and self.detection_confidence >= self.detect_threshold
        )

        return visible, self.locked, self.reference

    def update(
        self,
        polygon: np.ndarray,
        detection_confidence: float,
    ) -> tuple[bool, bool, np.ndarray]:
        current = np.asarray(
            polygon,
            dtype=np.float32,
        ).reshape(4, 2)

        detection_confidence = float(
            np.clip(detection_confidence, 0.0, 1.0)
        )

        self.missing_frames = 0

        if self.reference is None:
            movement = 0.0
            reference = current.copy()
        else:
            movement = float(
                np.mean(
                    np.linalg.norm(
                        current - self.reference,
                        axis=1,
                    )
                )
            )

            reference = (
                (1.0 - self.smoothing) * self.reference
                + self.smoothing * current
            ).astype(np.float32)

        self.reference = reference
        self.movement = movement
        self.detection_confidence = detection_confidence

        if movement >= self.movement_hard_limit:
            motion_score = 0.0
        else:
            motion_score = float(
                np.clip(
                    1.0 - movement / self.movement_soft_limit,
                    0.0,
                    1.0,
                )
            )

        evidence = (
            0.72 * detection_confidence
            + 0.28 * motion_score
        )

        visible = detection_confidence >= self.detect_threshold

        if visible:
            self.detected_frames += 1
        else:
            self.detected_frames = max(
                0,
                self.detected_frames - 1,
            )

        if movement >= self.movement_hard_limit:
            self.lock_confidence *= 0.28
            self.stable_frames = max(
                0,
                self.stable_frames - 3,
            )
        elif evidence >= 0.60:
            self.lock_confidence = (
                0.72 * self.lock_confidence
                + 0.28 * evidence
            )
        else:
            self.lock_confidence = (
                0.85 * self.lock_confidence
                + 0.15 * evidence
            )

        if (
            visible
            and movement < self.movement_soft_limit
            and self.lock_confidence >= 0.18
        ):
            self.stable_frames = min(
                self.stable_target,
                self.stable_frames + 1,
            )
        else:
            self.stable_frames = max(
                0,
                self.stable_frames - 1,
            )

        if (
            not self.locked
            and self.detected_frames >= 4
            and self.stable_frames >= self.stable_target
            and self.lock_confidence >= self.lock_threshold
        ):
            self.locked = True

        if (
            self.locked
            and self.lock_confidence < self.unlock_threshold
        ):
            self.locked = False

        return visible, self.locked, reference


class VisionService:
    STABLE_TARGET = 4
    MIN_CARD_AREA_FRACTION = 0.015
    MIN_ENVELOPE_ASPECT_SCORE = 0.70
    MIN_ENVELOPE_SUPPORTED_SIDES = 3
    MIN_ENVELOPE_SIDE_EDGE_SUPPORT = 0.16
    MIN_ENVELOPE_TO_INNER_AREA_RATIO = 4.0
    ENVELOPE_ROI_CONTAINMENT_TOLERANCE = 4.0

    REQUESTED_FRAME_WIDTH = 1920
    REQUESTED_FRAME_HEIGHT = 1080
    DETECTION_MAX_WIDTH = 960
    OUTPUT_CROP_WIDTH = 1000
    OUTPUT_CROP_HEIGHT = 1400
    SCAN_ZONE = {
        "left": 0.10,
        "top": 0.08,
        "right": 0.90,
        "bottom": 0.92,
    }

    DETECT_THRESHOLD = 0.42
    LOCK_THRESHOLD = 0.76
    UNLOCK_THRESHOLD = 0.44

    REARM_MISSING_FRAMES = 8
    CAPTURE_COOLDOWN_SECONDS = 1.5
    CAPTURE_MIN_LAPLACIAN_SHARPNESS = 5.0
    CAPTURE_MIN_PIXEL_STDDEV = 28.0
    CAPTURE_MIN_EDGE_DENSITY = 0.008
    CAPTURE_MIN_SIDE_EDGE_SUPPORT = 0.012
    CAPTURE_MIN_SUPPORTED_SIDES = 3
    CAPTURE_MIN_POLYGON_IOU = 0.80
    CAPTURE_MAX_FRAME_AGE_SECONDS = 0.40
    DUPLICATE_CONTENT_HASH_DISTANCE = 2
    DUPLICATE_ARTWORK_HASH_DISTANCE = 3
    DUPLICATE_STRUCTURAL_SIMILARITY = 0.94
    EMPTY_SCENE_HASH_DISTANCE = 8

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        capture_dir: Path,
    ) -> None:
        self.emit = emit
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None

        self._latest_jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_crop: np.ndarray | None = None

        self._best_lock_crop: np.ndarray | None = None
        self._best_lock_quality = 0.0
        self._acquisition = MultiFrameAcquisitionBuffer(
            max_samples=12,
            consensus_count=3,
        )

        self._frame_id = 0
        self._latest_frame_at: float | None = None
        self._selected_camera: dict[str, Any] | None = None
        self._stream_session_id = 0
        self._device_sequence_id = 0
        self._latest_provenance: dict[str, Any] = {}
        self._last_device_content_hash: int | None = None
        self._repeated_content_count = 0
        self._last_genuinely_changed_frame_at: float | None = None
        self._last_duplicate_content_frame_id: int | None = None
        self._epoch_device_sequence_baseline = 0
        self._last_accepted_provenance: dict[str, Any] | None = None
        self._last_accepted_crop: np.ndarray | None = None
        self._last_accepted_full_hash: int | None = None
        self._last_accepted_artwork_hash: int | None = None
        self._empty_content_transition_seen = False

        self._auto_capture_enabled = True
        self._auto_capture_armed = True
        self._missing_frames = 0
        self._last_auto_capture_at = 0.0
        self._removal_emitted = True
        self._acquisition_epoch = 0
        self._epoch_started_frame_id = 0
        self._tracked_polygon: np.ndarray | None = None
        self._capture_lock_revision = 0
        self._capture_was_locked = False
        self._capture_quarantined_frame_ids: set[int] = set()
        self._capture_quarantine_epoch = 0
        self._capture_telemetry: dict[str, Any] = {
            "total_capture_attempts": 0,
            "total_capture_rejections": 0,
            "rejections_by_reason": {},
            "quarantined_sample_count": 0,
            "last_rejected_frame_id": None,
            "last_accepted_frame_id": None,
            "consecutive_retry_count": 0,
            "current_eligible_sample_count": 0,
            "lock_revision": 0,
        }
        self._last_capture_validation: dict[str, Any] = {
            "accepted": False,
            "rejection_reason": "not_evaluated",
            "acquisition_epoch": 0,
        }

        self._status: dict[str, Any] = {
            "running": False,
            "frame_available": False,
            "frame_id": None,
            "frame_timestamp": None,
            "camera_provenance": {},
            "frame_shape": None,
            "requested_resolution": [
                self.REQUESTED_FRAME_WIDTH,
                self.REQUESTED_FRAME_HEIGHT,
            ],
            "actual_resolution": None,
            "resolution_fallback": None,
            "scan_zone": dict(self.SCAN_ZONE),
            "scan_zone_pixels": None,
            "camera_index": None,
            "camera_name": None,
            "camera_backend": None,
            "state": "SEARCHING",
            "visible": False,
            "stable": False,
            "stable_frames": 0,
            "stable_target": self.STABLE_TARGET,
            "detection_confidence": 0.0,
            "lock_confidence": 0.0,
            "movement": None,
            "candidate_scores": {},
            "capture_quality": 0.0,
            "acquisition": {
                "buffer_size": 0,
                "buffer_capacity": 12,
                "consensus_target": 3,
                "best_quality": 0.0,
                "best_sharpness": 0.0,
                "best_brightness": 0.0,
                "best_contrast": 0.0,
                "best_glare_score": 0.0,
                "replacement_frames": 0,
            },
            "polygon": [],
            "error": None,
            "auto_capture_enabled": True,
            "auto_capture_armed": True,
            "last_capture_path": None,
            "full_card_fingerprint": None,
            "artwork_fingerprint": None,
            "replacement_confirmed": False,
            "removal_confirmed": True,
            "capture_validation": dict(self._last_capture_validation),
            "capture_selection": dict(self._capture_telemetry),
        }

    @staticmethod
    def _content_hash(image: np.ndarray | None) -> int | None:
        if image is None or image.size == 0:
            return None
        resized = cv2.resize(image, (9, 8), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        diff = gray[:, 1:] > gray[:, :-1]
        value = 0
        for bit in diff.flatten():
            value = (value << 1) | int(bool(bit))
        return value

    @staticmethod
    def _content_hash_hex(value: int | None) -> str | None:
        return None if value is None else f"{value:016x}"

    @staticmethod
    def _hash_distance_values(left: int | None, right: int | None) -> int | None:
        if left is None or right is None:
            return None
        return int((left ^ right).bit_count())

    def _capture_provenance(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest_provenance)

    def list_cameras(self) -> list[dict[str, Any]]:
        cameras: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()

        for backend in (
            cv2.CAP_DSHOW,
            cv2.CAP_MSMF,
        ):
            try:
                for camera in enumerate_cameras(backend):
                    key = (
                        int(camera.index),
                        int(camera.backend),
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    cameras.append(
                        {
                            "index": int(camera.index),
                            "name": str(camera.name),
                            "backend": int(camera.backend),
                            "backend_name": (
                                cv2.videoio_registry.getBackendName(
                                    int(camera.backend)
                                )
                            ),
                            "path": str(camera.path or ""),
                            "vid": camera.vid,
                            "pid": camera.pid,
                        }
                    )
            except Exception:
                continue

        cameras.sort(
            key=lambda item: (
                item["name"].lower(),
                item["backend_name"],
                item["index"],
            )
        )

        return cameras

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def latest_crop(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_crop is None:
                return None

            return self._latest_crop.copy()

    def latest_frame(self) -> np.ndarray | None:
        with self._lock:
            if self._latest_frame is None:
                return None

            return self._latest_frame.copy()

    def worker_alive(self) -> bool:
        """Return whether the active Vision worker thread is still alive."""
        thread = self._thread
        return bool(self._running and thread is not None and thread.is_alive())

    def set_auto_capture(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        with self._lock:
            self._auto_capture_enabled = bool(enabled)
            self._status["auto_capture_enabled"] = bool(enabled)

        return self.status()

    def _attempt_auto_capture(
        self,
        current_polygon: np.ndarray | None,
        now: float | None = None,
    ) -> bool:
        """Try one recoverable automatic capture without killing the worker."""
        now = time.time() if now is None else float(now)
        attempted_this_cycle: set[int] = set()
        while True:
            eligible = self._acquisition.eligible_samples(
                current_epoch=self._acquisition_epoch,
                current_frame_id=self._frame_id,
                current_polygon=current_polygon,
                now=now,
                max_age_seconds=self.CAPTURE_MAX_FRAME_AGE_SECONDS,
                minimum_polygon_iou=self.CAPTURE_MIN_POLYGON_IOU,
                quarantined_frame_ids=self._capture_quarantined_frame_ids,
                excluded_frame_ids=attempted_this_cycle,
            )
            self._capture_telemetry["current_eligible_sample_count"] = len(
                eligible
            )
            ranked = self._acquisition._rank_consensus(eligible)
            captured_sample = ranked[0] if ranked else None
            if captured_sample is None:
                break
            attempted_this_cycle.add(captured_sample.frame_id)
            self._capture_telemetry["total_capture_attempts"] += 1
            try:
                saved_path = self.save_latest_crop(
                    source="auto",
                    sample=captured_sample,
                    current_polygon=current_polygon,
                )
            except Exception as exc:
                message = (
                    "Automatic capture failed and will retry: "
                    f"{type(exc).__name__}: {exc}"
                )
                with self._lock:
                    self._last_capture_validation = {
                        "accepted": False,
                        "rejection_reason": "capture_exception",
                        "detail": message,
                        "frame_id": captured_sample.frame_id,
                        "acquisition_epoch": self._acquisition_epoch,
                    }
                    self._status["capture_validation"] = dict(
                        self._last_capture_validation
                    )
                    self._status["capture_error"] = message
                self._record_capture_rejection(
                    captured_sample.frame_id, "capture_exception"
                )
                self._acquisition._record_replacement_decision({
                    "event": "capture_rejected",
                    "reason": "capture_exception",
                    "frame_id": captured_sample.frame_id,
                    "detail": message,
                    "acquisition_epoch": self._acquisition_epoch,
                })
                return False

            if not saved_path:
                reason = self._last_capture_validation.get(
                    "rejection_reason", "capture_validation_failed"
                )
                self._record_capture_rejection(captured_sample.frame_id, reason)
                self._acquisition._record_replacement_decision({
                    "event": "capture_rejected",
                    "reason": reason,
                    "frame_id": captured_sample.frame_id,
                    "acquisition_epoch": self._acquisition_epoch,
                })
                if self._is_quarantine_reason(reason):
                    self._capture_quarantined_frame_ids.add(
                        captured_sample.frame_id
                    )
                    self._capture_telemetry["quarantined_sample_count"] = len(
                        self._capture_quarantined_frame_ids
                    )
                continue

            self._acquisition.mark_captured(captured_sample)
            self._auto_capture_armed = False
            self._last_auto_capture_at = now
            self._capture_telemetry["last_accepted_frame_id"] = (
                captured_sample.frame_id
            )
            self._capture_telemetry["consecutive_retry_count"] = 0
            with self._lock:
                self._status["capture_error"] = None
            self._acquisition._record_replacement_decision({
                "event": "capture_accepted",
                "reason": "validated_auto_capture",
                "frame_id": captured_sample.frame_id,
                "acquisition_epoch": self._acquisition_epoch,
            })
            self._reset_capture_quarantine("successful_capture")
            return True

        if not attempted_this_cycle:
            with self._lock:
                self._last_capture_validation = {
                    "accepted": False,
                    "rejection_reason": "no_eligible_consensus_sample",
                    "acquisition_epoch": self._acquisition_epoch,
                }
                self._status["capture_validation"] = dict(
                    self._last_capture_validation
                )
                self._status["capture_error"] = None
            self._acquisition._record_replacement_decision({
                "event": "capture_rejected",
                "reason": "no_eligible_consensus_sample",
                "acquisition_epoch": self._acquisition_epoch,
            })
        return False

    @staticmethod
    def _is_quarantine_reason(reason: str | None) -> bool:
        values = set(str(reason or "").split(","))
        return bool(values & {
            "stale_frame", "polygon_mismatch", "wrong_acquisition_epoch",
            "invalid_epoch", "invalid_frame_id",
            "duplicate_pre_removal_content", "wrong_stream_session",
            "stale_device_sequence",
        })

    def _record_capture_rejection(
        self, frame_id: int | None, reason: str | None
    ) -> None:
        self._capture_telemetry["total_capture_rejections"] += 1
        self._capture_telemetry["last_rejected_frame_id"] = frame_id
        self._capture_telemetry["consecutive_retry_count"] += 1
        counts = self._capture_telemetry["rejections_by_reason"]
        for value in filter(None, str(reason or "unknown").split(",")):
            counts[value] = int(counts.get(value, 0)) + 1

    def _reset_capture_quarantine(
        self, reason: str, *, advance_revision: bool = False
    ) -> None:
        if advance_revision:
            self._capture_lock_revision += 1
        self._capture_quarantined_frame_ids.clear()
        self._capture_quarantine_epoch = self._acquisition_epoch
        self._capture_telemetry["quarantined_sample_count"] = 0
        self._capture_telemetry["current_eligible_sample_count"] = 0
        self._capture_telemetry["consecutive_retry_count"] = 0
        self._capture_telemetry["lock_revision"] = self._capture_lock_revision
        self._acquisition._record_replacement_decision({
            "event": "capture_quarantine_reset",
            "reason": reason,
            "acquisition_epoch": self._acquisition_epoch,
        })

    def start(
        self,
        camera_index: int,
        camera_backend: int,
    ) -> dict[str, Any]:
        self.stop()

        cameras = self.list_cameras()

        selected = next(
            (
                camera
                for camera in cameras
                if (
                    camera["index"] == int(camera_index)
                    and camera["backend"] == int(camera_backend)
                )
            ),
            None,
        )

        if selected is None:
            selected = {
                "index": int(camera_index),
                "name": f"Camera {camera_index}",
                "backend": int(camera_backend),
                "backend_name": "Unknown",
                "path": "",
                "vid": None,
                "pid": None,
            }

        self._selected_camera = selected
        self._auto_capture_armed = True
        self._missing_frames = 0
        self._best_lock_crop = None
        self._best_lock_quality = 0.0
        self._acquisition.reset(reason="camera_start")
        self._reset_capture_quarantine("camera_start", advance_revision=True)
        self._acquisition.last_captured_fingerprint = None
        self._epoch_device_sequence_baseline = 0
        self._empty_content_transition_seen = False
        self._running = True

        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "camera_index": selected["index"],
                    "camera_name": selected["name"],
                    "camera_backend": selected["backend"],
                    "state": "SEARCHING",
                    "visible": False,
                    "stable": False,
                    "stable_frames": 0,
                    "stable_target": self.STABLE_TARGET,
                    "detection_confidence": 0.0,
                    "lock_confidence": 0.0,
                    "movement": None,
                    "candidate_scores": {},
                    "capture_quality": 0.0,
                    "polygon": [],
                    "actual_resolution": None,
                    "resolution_fallback": None,
                    "scan_zone_pixels": None,
                    "error": None,
                    "auto_capture_armed": True,
                    "camera_provenance": {},
                }
            )

        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="RareIQVision",
        )

        self._thread.start()

        return self.status()

    def stop(self) -> dict[str, Any]:
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        self._thread = None

        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "state": "SEARCHING",
                    "visible": False,
                    "stable": False,
                    "stable_frames": 0,
                    "polygon": [],
                }
            )

        return self.status()

    @staticmethod
    def _order(points: np.ndarray) -> np.ndarray:
        points = np.asarray(
            points,
            dtype=np.float32,
        ).reshape(4, 2)

        ordered = np.zeros(
            (4, 2),
            dtype=np.float32,
        )

        sums = points.sum(axis=1)
        differences = np.diff(
            points,
            axis=1,
        ).reshape(-1)

        ordered[0] = points[np.argmin(sums)]
        ordered[2] = points[np.argmax(sums)]
        ordered[1] = points[np.argmin(differences)]
        ordered[3] = points[np.argmax(differences)]

        return ordered

    @staticmethod
    def _closeness_score(
        value: float,
        target: float,
        tolerance: float,
    ) -> float:
        return float(
            np.clip(
                1.0 - abs(value - target) / tolerance,
                0.0,
                1.0,
            )
        )

    @staticmethod
    def _crop_quality(
        crop: np.ndarray | None,
    ) -> float:
        if crop is None or crop.size == 0:
            return 0.0

        gray = cv2.cvtColor(
            crop,
            cv2.COLOR_BGR2GRAY,
        )

        sharpness = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F,
            ).var()
        )

        contrast = float(gray.std())
        exposure = float(gray.mean())

        exposure_score = max(
            0.0,
            1.0 - abs(exposure - 128.0) / 128.0,
        )

        return (
            sharpness
            + contrast * 1.75
            + exposure_score * 25.0
        )

    @classmethod
    def _edge_support(
        cls,
        edges: np.ndarray,
        points: np.ndarray,
    ) -> float:
        mask = np.zeros_like(edges)

        cv2.polylines(
            mask,
            [points.astype(np.int32)],
            True,
            255,
            5,
            cv2.LINE_AA,
        )

        supported = cv2.countNonZero(
            cv2.bitwise_and(
                edges,
                mask,
            )
        )

        total = max(
            1,
            cv2.countNonZero(mask),
        )

        return float(
            np.clip(
                supported / total * 3.0,
                0.0,
                1.0,
            )
        )

    @staticmethod
    def _edge_side_support(
        edges: np.ndarray,
        points: np.ndarray,
    ) -> tuple[float, float, float, float]:
        ordered = np.asarray(points, dtype=np.float32).reshape(4, 2)
        supports: list[float] = []
        for index in range(4):
            start = ordered[index]
            end = ordered[(index + 1) % 4]
            mask = np.zeros(edges.shape, dtype=np.uint8)
            cv2.line(
                mask,
                tuple(np.round(start).astype(int)),
                tuple(np.round(end).astype(int)),
                255,
                7,
                cv2.LINE_AA,
            )
            supported = cv2.countNonZero(cv2.bitwise_and(edges, mask))
            total = max(1, cv2.countNonZero(mask))
            supports.append(float(np.clip(supported / total, 0.0, 1.0)))
        return tuple(supports)  # type: ignore[return-value]

    @classmethod
    def _fragmented_outer_envelope(
        cls,
        contour: np.ndarray,
        edges: np.ndarray,
        frame_area: float,
        inner_points: np.ndarray,
    ) -> tuple[float, np.ndarray, dict[str, float]] | None:
        hull = cv2.convexHull(contour)
        rotated_rect = cv2.minAreaRect(hull)
        rect_width, rect_height = rotated_rect[1]
        envelope_area = float(rect_width * rect_height)
        if envelope_area <= 0:
            return None

        points = cls._order(cv2.boxPoints(rotated_rect))
        height, width = edges.shape[:2]
        tolerance = cls.ENVELOPE_ROI_CONTAINMENT_TOLERANCE
        if (
            float(points[:, 0].min()) < -tolerance
            or float(points[:, 1].min()) < -tolerance
            or float(points[:, 0].max()) > width - 1 + tolerance
            or float(points[:, 1].max()) > height - 1 + tolerance
        ):
            return None

        short_side = min(rect_width, rect_height)
        long_side = max(rect_width, rect_height)
        aspect_ratio = short_side / max(long_side, 1.0)
        aspect_score = cls._closeness_score(aspect_ratio, 0.714, 0.24)
        if aspect_score < cls.MIN_ENVELOPE_ASPECT_SCORE:
            return None

        inner_area = abs(float(cv2.contourArea(inner_points.astype(np.float32))))
        if (
            inner_area <= 0
            or envelope_area / inner_area
            < cls.MIN_ENVELOPE_TO_INNER_AREA_RATIO
        ):
            return None

        for point in np.asarray(inner_points, dtype=np.float32).reshape(4, 2):
            if cv2.pointPolygonTest(points, tuple(point), True) < -tolerance:
                return None

        side_support = cls._edge_side_support(edges, points)
        supported_sides = sum(
            value >= cls.MIN_ENVELOPE_SIDE_EDGE_SUPPORT
            for value in side_support
        )
        if supported_sides < cls.MIN_ENVELOPE_SUPPORTED_SIDES:
            return None

        strongest = sorted(side_support, reverse=True)[
            :cls.MIN_ENVELOPE_SUPPORTED_SIDES
        ]
        boundary_support = sum(strongest) / len(strongest)
        area_fraction = envelope_area / frame_area
        area_score = float(np.clip(
            (area_fraction - cls.MIN_CARD_AREA_FRACTION) / 0.30,
            0.0,
            1.0,
        ))
        confidence = (
            0.46 * aspect_score
            + 0.34 * boundary_support
            + 0.12 * (supported_sides / 4.0)
            + 0.08 * area_score
        )
        if confidence < cls.DETECT_THRESHOLD:
            return None

        return confidence, points, {
            "aspect": aspect_score,
            "rectangularity": 0.0,
            "solidity": 0.0,
            "edge": boundary_support,
            "area": area_score,
            "four_corner_bonus": 0.0,
            "envelope": 1.0,
            "supported_sides": float(supported_sides),
        }

    @classmethod
    def _score_contour(
        cls,
        contour: np.ndarray,
        edges: np.ndarray,
        frame_area: float,
    ) -> tuple[
        float,
        np.ndarray,
        dict[str, float],
    ] | None:
        area = float(
            cv2.contourArea(contour)
        )

        area_fraction = area / frame_area

        if (
            area_fraction < cls.MIN_CARD_AREA_FRACTION
            or area_fraction > 0.92
        ):
            return None

        perimeter = float(
            cv2.arcLength(
                contour,
                True,
            )
        )

        if perimeter <= 0:
            return None

        hull = cv2.convexHull(contour)
        hull_area = float(
            cv2.contourArea(hull)
        )

        if hull_area <= 0:
            return None

        rotated_rect = cv2.minAreaRect(hull)
        rect_width, rect_height = rotated_rect[1]

        if min(rect_width, rect_height) < 24:
            return None

        points = cls._order(
            cv2.boxPoints(rotated_rect)
        )

        rect_area = float(
            rect_width * rect_height
        )

        rectangularity = float(
            np.clip(
                area / max(rect_area, 1.0),
                0.0,
                1.0,
            )
        )

        solidity = float(
            np.clip(
                area / hull_area,
                0.0,
                1.0,
            )
        )

        short_side = min(
            rect_width,
            rect_height,
        )

        long_side = max(
            rect_width,
            rect_height,
        )

        aspect_ratio = (
            short_side / max(long_side, 1.0)
        )

        aspect_score = cls._closeness_score(
            aspect_ratio,
            0.714,
            0.24,
        )

        # A candidate must still be reasonably card-shaped.
        # Other strong features must not allow wide screens, books,
        # tables, or UI panels to overpower a bad aspect ratio.
        if aspect_score < 0.35:
            return None
            
        rectangularity_score = float(
            np.clip(
                (rectangularity - 0.52) / 0.43,
                0.0,
                1.0,
            )
        )

        solidity_score = float(
            np.clip(
                (solidity - 0.68) / 0.30,
                0.0,
                1.0,
            )
        )

        area_score = float(
            np.clip(
                (
                    area_fraction
                    - cls.MIN_CARD_AREA_FRACTION
                ) / 0.18,
                0.0,
                1.0,
            )
        )

        approximation = cv2.approxPolyDP(
            contour,
            0.025 * perimeter,
            True,
        )

        has_four_corners = (
            len(approximation) == 4
            and cv2.isContourConvex(approximation)
        )

        if has_four_corners:
            # Use the card's actual detected corners for perspective correction.
            # Do not warp from the larger rotated bounding rectangle.
            points = cls._order(
                approximation.reshape(4, 2)
            )

            four_corner_bonus = 1.0
        else:
            # A min-area rectangle around a noisy contour can include large amounts
            # of background. Reject weak blob-like candidates instead of warping them.
            if (
                rectangularity < 0.68
                or solidity < 0.78
            ):
                return None

            four_corner_bonus = 0.0

        edge_score = cls._edge_support(
            edges,
            points,
        )    

        confidence = (
            0.30 * aspect_score
            + 0.22 * rectangularity_score
            + 0.16 * solidity_score
            + 0.16 * edge_score
            + 0.10 * area_score
            + 0.06 * four_corner_bonus
        )

        scores = {
            "aspect": aspect_score,
            "rectangularity": rectangularity_score,
            "solidity": solidity_score,
            "edge": edge_score,
            "area": area_score,
            "four_corner_bonus": four_corner_bonus,
        }

        return (
            float(confidence),
            points,
            scores,
        )

    @classmethod
    def detect(
        cls,
        frame: np.ndarray,
    ) -> DetectionResult:
        if frame is None or frame.size == 0:
            return DetectionResult(
                crop=None,
                polygon=None,
                confidence=0.0,
            )

        full_height, full_width = frame.shape[:2]

        left = int(round(full_width * cls.SCAN_ZONE["left"]))
        top = int(round(full_height * cls.SCAN_ZONE["top"]))
        right = int(round(full_width * cls.SCAN_ZONE["right"]))
        bottom = int(round(full_height * cls.SCAN_ZONE["bottom"]))

        left = max(0, min(left, full_width - 1))
        top = max(0, min(top, full_height - 1))
        right = max(left + 1, min(right, full_width))
        bottom = max(top + 1, min(bottom, full_height))

        roi = frame[top:bottom, left:right]
        roi_height, roi_width = roi.shape[:2]

        detection_scale = min(
            1.0,
            cls.DETECTION_MAX_WIDTH / max(roi_width, 1),
        )

        if detection_scale < 1.0:
            detection_frame = cv2.resize(
                roi,
                (
                    max(1, int(round(roi_width * detection_scale))),
                    max(1, int(round(roi_height * detection_scale))),
                ),
                interpolation=cv2.INTER_AREA,
            )
        else:
            detection_frame = roi

        height, width = detection_frame.shape[:2]
        frame_area = float(width * height)

        gray = cv2.cvtColor(
            detection_frame,
            cv2.COLOR_BGR2GRAY,
        )

        blurred = cv2.GaussianBlur(
            gray,
            (5, 5),
            0,
        )

        median = float(
            np.median(blurred)
        )

        lower = int(
            max(
                18,
                median * 0.55,
            )
        )

        upper = int(
            min(
                235,
                max(
                    lower + 35,
                    median * 1.45,
                ),
            )
        )

        edges = cv2.Canny(
            blurred,
            lower,
            upper,
        )

        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            np.ones(
                (5, 5),
                dtype=np.uint8,
            ),
            iterations=2,
        )

        edges = cv2.dilate(
            edges,
            np.ones(
                (3, 3),
                dtype=np.uint8,
            ),
            iterations=1,
        )

        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        candidates: list[
            tuple[
                float,
                np.ndarray,
                dict[str, float],
            ]
        ] = []

        accepted_with_contours: list[
            tuple[float, np.ndarray, dict[str, float], np.ndarray]
        ] = []

        for contour in contours:
            candidate = cls._score_contour(
                contour,
                edges,
                frame_area,
            )

            if candidate is not None:
                candidates.append(candidate)
                accepted_with_contours.append((*candidate, contour))

        if not candidates:
            return DetectionResult(
                crop=None,
                polygon=None,
                confidence=0.0,
            )

        confidence, points, scores = max(
            candidates,
            key=lambda item: item[0],
        )

        envelope_candidates: list[
            tuple[float, np.ndarray, dict[str, float]]
        ] = []
        for _, inner_points, _, _ in accepted_with_contours:
            inner_area = abs(float(cv2.contourArea(inner_points)))
            for contour in contours:
                contour_area = abs(float(cv2.contourArea(contour)))
                if contour_area <= inner_area:
                    continue
                envelope = cls._fragmented_outer_envelope(
                    contour,
                    edges,
                    frame_area,
                    inner_points,
                )
                if envelope is not None:
                    envelope_candidates.append(envelope)

        if envelope_candidates:
            confidence, points, scores = max(
                envelope_candidates,
                key=lambda item: (
                    item[0],
                    abs(float(cv2.contourArea(item[1]))),
                ),
            )

        roi_points = (
            points.astype(np.float32)
            / max(detection_scale, np.finfo(np.float32).eps)
        )

        full_points = roi_points + np.array(
            [left, top],
            dtype=np.float32,
        )

        normalized = (
            full_points
            / np.array(
                [full_width, full_height],
                dtype=np.float32,
            )
        ).astype(np.float32)

        destination = np.array(
            [
                [0, 0],
                [cls.OUTPUT_CROP_WIDTH - 1, 0],
                [
                    cls.OUTPUT_CROP_WIDTH - 1,
                    cls.OUTPUT_CROP_HEIGHT - 1,
                ],
                [0, cls.OUTPUT_CROP_HEIGHT - 1],
            ],
            dtype=np.float32,
        )

        transform = cv2.getPerspectiveTransform(
            full_points.astype(np.float32),
            destination,
        )

        crop = cv2.warpPerspective(
            frame,
            transform,
            (
                cls.OUTPUT_CROP_WIDTH,
                cls.OUTPUT_CROP_HEIGHT,
            ),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

        return DetectionResult(
            crop=crop,
            polygon=normalized,
            confidence=confidence,
            aspect_score=scores["aspect"],
            rectangularity_score=scores["rectangularity"],
            solidity_score=scores["solidity"],
            edge_score=scores["edge"],
            area_score=scores["area"],
        )

    @classmethod
    def _detect(
        cls,
        frame: np.ndarray,
    ) -> tuple[
        np.ndarray | None,
        list[list[float]],
    ]:
        result = cls.detect(frame)

        polygon = (
            []
            if result.polygon is None
            else result.polygon.tolist()
        )

        return result.crop, polygon

    @classmethod
    def _validate_capture_candidate(
        cls,
        crop: np.ndarray | None,
        polygon: np.ndarray | None,
        current_polygon: np.ndarray | None,
        *,
        frame_id: int | None,
        current_frame_id: int | None,
        captured_at: float,
        acquisition_epoch: int,
        current_epoch: int,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "accepted": False,
            "rejection_reason": None,
            "sharpness": 0.0,
            "pixel_stddev": 0.0,
            "edge_density": 0.0,
            "border_support": [0.0, 0.0, 0.0, 0.0],
            "supported_sides": 0,
            "polygon_iou": 0.0,
            "frame_age_ms": round(max(0.0, time.time() - captured_at) * 1000, 2),
            "frame_id": frame_id,
            "acquisition_epoch": acquisition_epoch,
        }
        reasons: list[str] = []
        if crop is None or crop.size == 0:
            reasons.append("empty_crop")
        elif crop.shape != (cls.OUTPUT_CROP_HEIGHT, cls.OUTPUT_CROP_WIDTH, 3):
            reasons.append("invalid_dimensions")
        else:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            pixel_stddev = float(gray.std())
            edges = cv2.Canny(gray, 50, 150)
            edge_density = float(np.count_nonzero(edges)) / float(edges.size)
            height, width = gray.shape
            border_width = max(8, int(min(height, width) * 0.035))
            strips = (
                edges[:border_width, :],
                edges[:, width - border_width:],
                edges[height - border_width:, :],
                edges[:, :border_width],
            )
            support = [
                float(np.count_nonzero(side)) / float(max(1, side.size))
                for side in strips
            ]
            supported = sum(
                value >= cls.CAPTURE_MIN_SIDE_EDGE_SUPPORT for value in support
            )
            metrics.update({
                "sharpness": round(sharpness, 4),
                "pixel_stddev": round(pixel_stddev, 4),
                "edge_density": round(edge_density, 5),
                "border_support": [round(value, 5) for value in support],
                "supported_sides": supported,
            })
            if sharpness < cls.CAPTURE_MIN_LAPLACIAN_SHARPNESS:
                reasons.append("insufficient_sharpness")
            if pixel_stddev < cls.CAPTURE_MIN_PIXEL_STDDEV:
                reasons.append("insufficient_texture")
            if edge_density < cls.CAPTURE_MIN_EDGE_DENSITY:
                reasons.append("smooth_background")
            if supported < cls.CAPTURE_MIN_SUPPORTED_SIDES:
                reasons.append("insufficient_border_support")

        if acquisition_epoch != current_epoch:
            reasons.append("wrong_acquisition_epoch")
        if (
            frame_id is None
            or current_frame_id is None
            or frame_id > current_frame_id
        ):
            reasons.append("invalid_frame_id")
        if metrics["frame_age_ms"] > cls.CAPTURE_MAX_FRAME_AGE_SECONDS * 1000:
            reasons.append("stale_frame")
        if polygon is None or current_polygon is None:
            reasons.append("missing_polygon")
        else:
            polygon_iou = MultiFrameAcquisitionBuffer._polygon_iou(
                polygon, current_polygon
            )
            metrics["polygon_iou"] = round(polygon_iou, 5)
            if polygon_iou < cls.CAPTURE_MIN_POLYGON_IOU:
                reasons.append("polygon_mismatch")

        metrics["accepted"] = not reasons
        metrics["rejection_reason"] = ",".join(reasons) if reasons else None
        return metrics

    def save_latest_crop(
        self,
        source: str = "manual",
        *,
        sample: AcquisitionFrame | None = None,
        current_polygon: np.ndarray | None = None,
    ) -> str | None:
        with self._lock:
            preferred = (
                sample.crop
                if sample is not None
                else self._best_lock_crop
                if source == "auto"
                else self._latest_crop
            )

            crop = (
                None
                if preferred is None
                else preferred.copy()
            )

            camera_name = self._status.get(
                "camera_name"
            )

            frame_id = self._status.get(
                "frame_id"
            )
            tracked_polygon = (
                self._tracked_polygon.copy()
                if self._tracked_polygon is not None
                else None
            )
            epoch = self._acquisition_epoch

        candidate_polygon = (
            sample.polygon if sample is not None else current_polygon
        )
        candidate_frame_id = sample.frame_id if sample is not None else frame_id
        candidate_timestamp = (
            sample.captured_at if sample is not None else time.time()
        )
        candidate_epoch = (
            sample.acquisition_epoch if sample is not None else epoch
        )
        provenance = (
            {
                "stream_session_id": sample.stream_session_id,
                "device_sequence_id": sample.device_sequence_id,
                "device_timestamp": sample.device_timestamp,
                "application_frame_id": sample.frame_id,
                "content_fingerprint": sample.content_fingerprint,
                "source_camera_index": sample.source_camera_index,
                "source_camera_backend": sample.source_camera_backend,
            }
            if sample is not None else self._capture_provenance()
        )
        validation = self._validate_capture_candidate(
            crop,
            candidate_polygon,
            current_polygon if current_polygon is not None else tracked_polygon,
            frame_id=candidate_frame_id,
            current_frame_id=frame_id,
            captured_at=candidate_timestamp,
            acquisition_epoch=candidate_epoch,
            current_epoch=epoch,
        )
        provenance_reasons: list[str] = []
        stream_session = int(provenance.get("stream_session_id") or 0)
        device_sequence = int(provenance.get("device_sequence_id") or 0)
        if stream_session and stream_session != self._stream_session_id:
            provenance_reasons.append("wrong_stream_session")
        if device_sequence and device_sequence <= self._epoch_device_sequence_baseline:
            provenance_reasons.append("stale_device_sequence")
        if sample is not None and self._is_duplicate_pre_removal_sample(sample):
            provenance_reasons.append("duplicate_pre_removal_content")
        if provenance_reasons:
            existing = validation.get("rejection_reason")
            reasons = ([existing] if existing else []) + provenance_reasons
            validation["accepted"] = False
            validation["rejection_reason"] = ",".join(reasons)
        validation["provenance"] = dict(provenance)
        with self._lock:
            self._last_capture_validation = dict(validation)
            self._status["capture_validation"] = dict(validation)
        if not validation["accepted"]:
            return None

        if crop is None or crop.size == 0:
            return None

        path = self.capture_dir / (
            f"card_{int(time.time() * 1000)}.jpg"
        )

        if not cv2.imwrite(
            str(path),
            crop,
        ):
            with self._lock:
                self._status["error"] = (
                    f"Could not write capture: {path}"
                )

            return None

        with self._lock:
            # Trigger Manager must receive the exact crop that was saved.
            self._latest_crop = crop.copy()
            self._status["last_capture_path"] = str(path)

        event_crop = crop.copy()
        event_crop.setflags(write=False)
        self.emit(
            {
                "type": "card_captured",
                "payload": {
                    "path": str(path),
                    "source": source,
                    "camera_name": camera_name,
                    "frame_id": candidate_frame_id,
                    "timestamp": time.time(),
                    "capture_timestamp": candidate_timestamp,
                    "crop_path": str(path),
                    "crop": event_crop,
                    "polygon": np.asarray(candidate_polygon).copy(),
                    "acquisition_epoch": candidate_epoch,
                    "validation": dict(validation),
                    "provenance": dict(provenance),
                },
            }
        )

        self._last_accepted_provenance = dict(provenance)
        self._last_accepted_crop = crop.copy()
        self._last_accepted_full_hash = self._acquisition._dhash(crop)
        self._last_accepted_artwork_hash = self._acquisition._dhash(
            crop, artwork=True
        )

        return str(path)

    def _is_duplicate_pre_removal_sample(self, sample: AcquisitionFrame) -> bool:
        previous = self._last_accepted_provenance
        if (
            previous is None
            or self._last_accepted_crop is None
            or self._empty_content_transition_seen
            or int(previous.get("stream_session_id") or 0)
            != int(sample.stream_session_id)
        ):
            return False
        full_distance = self._hash_distance_values(
            self._last_accepted_full_hash, sample.full_card_hash
        )
        artwork_distance = self._hash_distance_values(
            self._last_accepted_artwork_hash, sample.artwork_hash
        )
        structural = MultiFrameAcquisitionBuffer._structural_similarity(
            MultiFrameAcquisitionBuffer._structural_image(
                self._last_accepted_crop
            ),
            sample.structural_image,
        )
        return bool(
            full_distance is not None
            and full_distance <= self.DUPLICATE_CONTENT_HASH_DISTANCE
            and artwork_distance is not None
            and artwork_distance <= self.DUPLICATE_ARTWORK_HASH_DISTANCE
            and structural >= self.DUPLICATE_STRUCTURAL_SIMILARITY
        )

    @staticmethod
    def _dhash_hex(image: np.ndarray, *, artwork: bool = False) -> str:
        sample = image
        if artwork:
            height, width = image.shape[:2]
            sample = image[
                int(height * 0.12):int(height * 0.58),
                int(width * 0.08):int(width * 0.92),
            ]
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        bits = resized[:, 1:] > resized[:, :-1]
        value = 0
        for bit in bits.flatten():
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"

    def capture_fresh(self, source: str = "manual") -> dict[str, Any]:
        """Detect and correct the newest camera frame at request time."""
        with self._lock:
            frame = (
                None
                if self._latest_frame is None
                else self._latest_frame.copy()
            )
            frame_id = self._status.get("frame_id")
        if frame is None or frame.size == 0:
            return {"ok": False, "reason": "no_current_frame"}
        result = self.detect(frame)
        if result.crop is None or result.polygon is None:
            return {"ok": False, "reason": "no_current_card"}
        captured_at = time.time()
        sample = AcquisitionFrame(
            crop=result.crop.copy(),
            polygon=result.polygon.copy(),
            frame_id=int(frame_id or 0),
            detection_confidence=result.confidence,
            quality_score=0.0,
            sharpness=0.0,
            brightness=0.0,
            contrast=0.0,
            glare_score=0.0,
            fingerprint=self._acquisition._fingerprint(result.crop),
            full_card_hash=self._acquisition._dhash(result.crop),
            artwork_hash=self._acquisition._dhash(result.crop, artwork=True),
            structural_image=self._acquisition._structural_image(result.crop),
            acquisition_epoch=self._acquisition_epoch,
            captured_at=captured_at,
            **{
                "stream_session_id": int(self._latest_provenance.get("stream_session_id") or 0),
                "device_sequence_id": int(self._latest_provenance.get("device_sequence_id") or 0),
                "device_timestamp": float(self._latest_provenance.get("device_timestamp") or 0.0),
                "content_fingerprint": self._latest_provenance.get("content_fingerprint"),
                "source_camera_index": self._latest_provenance.get("source_camera_index"),
                "source_camera_backend": self._latest_provenance.get("source_camera_backend"),
            },
        )
        with self._lock:
            self._latest_crop = result.crop.copy()
            self._tracked_polygon = result.polygon.copy()
        path = self.save_latest_crop(
            source=source,
            sample=sample,
            current_polygon=result.polygon,
        )
        validation = dict(self._last_capture_validation)
        return {
            "ok": bool(path),
            "path": path,
            "frame_id": frame_id,
            "crop": result.crop.copy(),
            "validation": validation,
            "reason": (
                None if path else validation.get("rejection_reason")
                or "capture_write_failed"
            ),
        }

    def _worker(self) -> None:
        selected = self._selected_camera or {}

        index = int(
            selected.get(
                "index",
                0,
            )
        )

        backend = int(
            selected.get(
                "backend",
                cv2.CAP_DSHOW,
            )
        )

        name = str(
            selected.get(
                "name",
                f"Camera {index}",
            )
        )

        capture = cv2.VideoCapture(
            index,
            backend,
        )

        if not capture.isOpened():
            with self._lock:
                self._status.update(
                    {
                        "running": False,
                        "error": f"Could not open {name}",
                    }
                )

            self._running = False

            self.emit(
                {
                    "type": "vision_status",
                    "payload": self.status(),
                }
            )

            return

        with self._lock:
            self._stream_session_id += 1
            self._device_sequence_id = 0
            self._last_device_content_hash = None
            self._repeated_content_count = 0
            self._last_duplicate_content_frame_id = None
            self._last_genuinely_changed_frame_at = None
            self._epoch_device_sequence_baseline = 0
            self._latest_provenance = {}

        camera_properties = (
            (
                cv2.CAP_PROP_FRAME_WIDTH,
                self.REQUESTED_FRAME_WIDTH,
                "frame width",
            ),
            (
                cv2.CAP_PROP_FRAME_HEIGHT,
                self.REQUESTED_FRAME_HEIGHT,
                "frame height",
            ),
            (
                cv2.CAP_PROP_BUFFERSIZE,
                1,
                "buffer size",
            ),
        )

        for (
            property_id,
            value,
            label,
        ) in camera_properties:
            try:
                capture.set(
                    property_id,
                    value,
                )

            except cv2.error as exc:
                print(
                    "[RareIQ Vision] "
                    f"Camera rejected {label}: "
                    f"{exc}"
                )

            except Exception as exc:
                print(
                    "[RareIQ Vision] "
                    f"Could not set {label}: "
                    f"{exc}"
                )       

        tracker = ConfidenceLockTracker(
            stable_target=self.STABLE_TARGET,
            detect_threshold=self.DETECT_THRESHOLD,
            lock_threshold=self.LOCK_THRESHOLD,
            unlock_threshold=self.UNLOCK_THRESHOLD,
        )

        last_emit = 0.0

        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "camera_name": name,
                    "error": None,
                }
            )

        try:
            while self._running:
                ok, frame = capture.read()

                if not ok or frame is None:
                    with self._lock:
                        self._status["error"] = (
                            f"Camera frame read failed: {name}"
                        )

                    break

                clean_frame = frame.copy()
                frame_timestamp = time.time()
                content_hash = self._content_hash(clean_frame)
                actual_height, actual_width = clean_frame.shape[:2]

                with self._lock:
                    self._device_sequence_id += 1
                    application_frame_id = self._frame_id + 1
                    content_distance = self._hash_distance_values(
                        content_hash, self._last_device_content_hash
                    )
                    repeated = bool(
                        content_distance is not None
                        and content_distance <= self.DUPLICATE_CONTENT_HASH_DISTANCE
                    )
                    if repeated:
                        self._repeated_content_count += 1
                        self._last_duplicate_content_frame_id = application_frame_id
                    else:
                        self._last_genuinely_changed_frame_at = frame_timestamp
                    self._last_device_content_hash = content_hash
                    self._latest_provenance = {
                        "stream_session_id": self._stream_session_id,
                        "device_sequence_id": self._device_sequence_id,
                        "device_timestamp": frame_timestamp,
                        "application_frame_id": application_frame_id,
                        "content_fingerprint": self._content_hash_hex(content_hash),
                        "source_camera_index": index,
                        "source_camera_backend": backend,
                        "repeated_content": repeated,
                        "repeated_content_count": self._repeated_content_count,
                        "last_genuinely_changed_frame_timestamp": self._last_genuinely_changed_frame_at,
                        "last_duplicate_content_frame_id": self._last_duplicate_content_frame_id,
                    }
                    actual_resolution = (
                        self._status.get("actual_resolution")
                        or [actual_width, actual_height]
                    )
                    telemetry_width, telemetry_height = actual_resolution
                    scan_zone_pixels = {
                        "left": int(round(telemetry_width * self.SCAN_ZONE["left"])),
                        "top": int(round(telemetry_height * self.SCAN_ZONE["top"])),
                        "right": int(round(telemetry_width * self.SCAN_ZONE["right"])),
                        "bottom": int(round(telemetry_height * self.SCAN_ZONE["bottom"])),
                    }
                    resolution_fallback = actual_resolution != [
                        self.REQUESTED_FRAME_WIDTH,
                        self.REQUESTED_FRAME_HEIGHT,
                    ]
                    self._latest_frame = clean_frame
                    self._frame_id += 1
                    self._latest_frame_at = frame_timestamp

                    self._status.update(
                        {
                            "frame_available": True,
                            "frame_id": self._frame_id,
                            "frame_timestamp": frame_timestamp,
                            "frame_shape": list(
                                clean_frame.shape
                            ),
                            "actual_resolution": actual_resolution,
                            "resolution_fallback": resolution_fallback,
                            "scan_zone_pixels": scan_zone_pixels,
                            "camera_provenance": dict(self._latest_provenance),
                        }
                    )

                result = self.detect(clean_frame)

                candidate_found = (
                    result.polygon is not None
                    and result.crop is not None
                )

                if candidate_found:
                    visible, locked, reference = tracker.update(
                        result.polygon,
                        result.confidence,
                    )
                else:
                    visible, locked, reference = tracker.miss()

                if locked and not self._capture_was_locked:
                    self._reset_capture_quarantine(
                        "lock_revision_changed", advance_revision=True
                    )
                self._capture_was_locked = bool(locked)

                polygon: list[list[float]] = (
                    reference.tolist()
                    if reference is not None
                    else []
                )

                current_sample = None

                if candidate_found and result.crop is not None:
                    current_sample = self._acquisition.add(
                        crop=result.crop,
                        polygon=result.polygon,
                        frame_id=self._frame_id,
                        detection_confidence=result.confidence,
                        acquisition_epoch=self._acquisition_epoch,
                        captured_at=time.time(),
                        provenance=self._capture_provenance(),
                    )

                    with self._lock:
                        self._latest_crop = (
                            result.crop.copy()
                        )

                    consensus_sample = (
                        self._acquisition.best_consensus()
                    )

                    if (
                        visible
                        and consensus_sample is not None
                    ):
                        self._best_lock_crop = (
                            consensus_sample.crop.copy()
                        )

                        self._best_lock_quality = (
                            consensus_sample.quality_score
                        )

                    if current_sample is not None:
                        full_fingerprint = self._dhash_hex(result.crop)
                        artwork_fingerprint = self._dhash_hex(
                            result.crop,
                            artwork=True,
                        )
                        replacement_confirmed = (
                            not self._auto_capture_armed
                            and self._acquisition.observe_replacement(
                                current_sample
                            )
                        )
                        if replacement_confirmed:
                            replacement_evidence = dict(
                                self._acquisition.last_replacement_evidence
                            )
                            self._acquisition_epoch += 1
                            self._epoch_started_frame_id = self._frame_id
                            self._epoch_device_sequence_baseline = self._device_sequence_id
                            self._empty_content_transition_seen = True
                            self._acquisition.reset(
                                reason="replacement_confirmed",
                                clear_replacement_latch=False,
                            )
                            self._reset_capture_quarantine(
                                "replacement_confirmed", advance_revision=True
                            )
                            current_sample = self._acquisition.add(
                                crop=result.crop,
                                polygon=result.polygon,
                                frame_id=self._frame_id,
                                detection_confidence=result.confidence,
                                acquisition_epoch=self._acquisition_epoch,
                                captured_at=time.time(),
                            )
                            self._auto_capture_armed = True
                            self._best_lock_crop = result.crop.copy()
                            self._best_lock_quality = current_sample.quality_score
                            self.emit({
                                "type": "card_changed",
                                "payload": {
                                    "frame_id": self._frame_id,
                                    "timestamp": time.time(),
                                    "full_card_fingerprint": full_fingerprint,
                                    "artwork_fingerprint": artwork_fingerprint,
                                    "geometry_quality": result.confidence,
                                    "movement": tracker.movement,
                                    "replacement_confirmed": True,
                                    "decisive": True,
                                    **replacement_evidence,
                                    "acquisition_epoch": self._acquisition_epoch,
                                    "provenance": self._capture_provenance(),
                                },
                            })
                    else:
                        full_fingerprint = None
                        artwork_fingerprint = None
                        replacement_confirmed = False
                else:
                    full_fingerprint = None
                    artwork_fingerprint = None
                    replacement_confirmed = False

                if reference is not None:
                    with self._lock:
                        self._tracked_polygon = reference.copy()
                    frame_height, frame_width = frame.shape[:2]

                    pixel_points = (
                        reference
                        * np.array(
                            [frame_width, frame_height],
                            dtype=np.float32,
                        )
                    ).astype(np.int32)

                    cv2.polylines(
                        frame,
                        [pixel_points],
                        True,
                        (
                            (90, 255, 190)
                            if locked
                            else (255, 255, 255)
                        ),
                        3,
                        cv2.LINE_AA,
                    )

                if visible:
                    self._missing_frames = 0
                    self._removal_emitted = False
                else:
                    self._missing_frames += 1

                    if (
                        self._missing_frames
                        >= self.REARM_MISSING_FRAMES
                    ):
                        self._auto_capture_armed = True
                        self._best_lock_crop = None
                        self._best_lock_quality = 0.0
                        if not self._removal_emitted:
                            with self._lock:
                                self._latest_crop = None
                                self._tracked_polygon = None
                            self._acquisition_epoch += 1
                            self._epoch_started_frame_id = self._frame_id
                            self._epoch_device_sequence_baseline = self._device_sequence_id
                            self._acquisition.reset(reason="removal_confirmed")
                            self._reset_capture_quarantine(
                                "removal_confirmed", advance_revision=True
                            )
                            self._removal_emitted = True
                            self.emit({
                                "type": "card_removed",
                                "payload": {
                                    "frame_id": self._frame_id,
                                    "timestamp": time.time(),
                                    "removal_confirmed": True,
                                    "acquisition_epoch": self._acquisition_epoch,
                                    "provenance": self._capture_provenance(),
                                },
                            })

                if (
                    not visible
                    and self._last_accepted_provenance is not None
                    and int(self._last_accepted_provenance.get("stream_session_id") or 0)
                    == self._stream_session_id
                ):
                    previous_hash_text = self._last_accepted_provenance.get(
                        "content_fingerprint"
                    )
                    try:
                        previous_hash = int(str(previous_hash_text), 16)
                    except (TypeError, ValueError):
                        previous_hash = None
                    distance = self._hash_distance_values(content_hash, previous_hash)
                    if distance is not None and distance >= self.EMPTY_SCENE_HASH_DISTANCE:
                        self._empty_content_transition_seen = True

                now = time.time()

                if (
                    locked
                    and self._auto_capture_enabled
                    and self._auto_capture_armed
                    and (
                        now - self._last_auto_capture_at
                        >= self.CAPTURE_COOLDOWN_SECONDS
                    )
                ):
                    self._attempt_auto_capture(reference, now)

                state = (
                    "CARD LOCKED"
                    if locked
                    else (
                        "CARD DETECTED"
                        if visible
                        else "SEARCHING"
                    )
                )

                cv2.putText(
                    frame,
                    f"RareIQ Vision | {name} | {state}",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.72,
                    (
                        (90, 255, 190)
                        if locked
                        else (255, 255, 255)
                    ),
                    2,
                    cv2.LINE_AA,
                )

                ok_jpeg, jpeg = cv2.imencode(
                    ".jpg",
                    frame,
                    [
                        int(cv2.IMWRITE_JPEG_QUALITY),
                        82,
                    ],
                )

                if ok_jpeg:
                    with self._lock:
                        self._latest_jpeg = jpeg.tobytes()

                        self._status.update(
                            {
                                "running": True,
                                "camera_name": name,
                                "state": state,
                                "visible": bool(visible),
                                "stable": bool(locked),
                                "stable_frames": (
                                    tracker.stable_frames
                                ),
                                "stable_target": (
                                    self.STABLE_TARGET
                                ),
                                "detection_confidence": round(
                                    tracker.detection_confidence,
                                    3,
                                ),
                                "lock_confidence": round(
                                    tracker.lock_confidence,
                                    3,
                                ),
                                "movement": round(
                                    tracker.movement,
                                    5,
                                ),
                                "candidate_scores": {
                                    "aspect": round(
                                        result.aspect_score,
                                        3,
                                    ),
                                    "rectangularity": round(
                                        result.rectangularity_score,
                                        3,
                                    ),
                                    "solidity": round(
                                        result.solidity_score,
                                        3,
                                    ),
                                    "edge": round(
                                        result.edge_score,
                                        3,
                                    ),
                                    "area": round(
                                        result.area_score,
                                        3,
                                    ),
                                },
                                "capture_quality": round(
                                    self._best_lock_quality,
                                    4,
                                ),
                                "acquisition": (
                                    self._acquisition.telemetry()
                                ),
                                "polygon": polygon,
                                "error": None,
                                "auto_capture_enabled": (
                                    self._auto_capture_enabled
                                ),
                                "auto_capture_armed": (
                                    self._auto_capture_armed
                                ),
                                "full_card_fingerprint": full_fingerprint,
                                "artwork_fingerprint": artwork_fingerprint,
                                "replacement_confirmed": replacement_confirmed,
                                "removal_confirmed": self._removal_emitted,
                                "capture_selection": dict(
                                    self._capture_telemetry
                                ),
                            }
                        )

                if now - last_emit >= 0.05:
                    self.emit(
                        {
                            "type": "card_tracking",
                            "payload": self.status(),
                        }
                    )

                    last_emit = now

        except Exception as exc:
            with self._lock:
                self._status["error"] = (
                    f"Vision worker failed: {exc}"
                )

        finally:
            capture.release()
            self._running = False

            with self._lock:
                self._status.update(
                    {
                        "running": False,
                        "state": "SEARCHING",
                        "visible": False,
                        "stable": False,
                        "stable_frames": 0,
                        "polygon": [],
                    }
                )

            self.emit(
                {
                    "type": "vision_status",
                    "payload": self.status(),
                }
            )





