from __future__ import annotations

import threading
import time
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


class MultiFrameAcquisitionBuffer:
    """Keeps and ranks several corrected views of the current physical card."""

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

    def reset(self) -> None:
        self.samples.clear()
        self.replacement_frames = 0

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
    ) -> AcquisitionFrame | None:
        if crop is None or crop.size == 0:
            return None

        quality = self._quality(crop)
        fingerprint = self._fingerprint(crop)

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
        )

        self.samples.append(sample)
        self.samples.sort(
            key=lambda item: (
                item.quality_score * 0.72
                + item.detection_confidence * 0.28
            ),
            reverse=True,
        )

        if len(self.samples) > self.max_samples:
            self.samples = self.samples[:self.max_samples]

        return sample

    def best_consensus(self) -> AcquisitionFrame | None:
        if not self.samples:
            return None

        candidate_pool = self.samples[
            :min(
                len(self.samples),
                max(self.consensus_count * 2, 6),
            )
        ]

        best_sample = candidate_pool[0]
        best_score = -1.0

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

            if combined > best_score:
                best_score = combined
                best_sample = sample

        return best_sample

    def mark_captured(
        self,
        sample: AcquisitionFrame | None,
    ) -> None:
        if sample is not None:
            self.last_captured_fingerprint = (
                sample.fingerprint.copy()
            )

        self.replacement_frames = 0

    def observe_replacement(
        self,
        fingerprint: np.ndarray | None,
        *,
        distance_threshold: float = 0.115,
        required_frames: int = 4,
    ) -> bool:
        if (
            fingerprint is None
            or self.last_captured_fingerprint is None
        ):
            self.replacement_frames = 0
            return False

        distance = self.fingerprint_distance(
            fingerprint,
            self.last_captured_fingerprint,
        )

        if distance >= distance_threshold:
            self.replacement_frames += 1
        else:
            self.replacement_frames = max(
                0,
                self.replacement_frames - 1,
            )

        return self.replacement_frames >= required_frames

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
        stable_target: int = 8,
        detect_threshold: float = 0.42,
        lock_threshold: float = 0.76,
        unlock_threshold: float = 0.44,
        smoothing: float = 0.28,
        missing_tolerance: int = 3,
        movement_soft_limit: float = 0.016,
        movement_hard_limit: float = 0.050,
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
            and self.lock_confidence >= 0.48
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
    STABLE_TARGET = 8

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

        self._auto_capture_enabled = True
        self._auto_capture_armed = True
        self._missing_frames = 0
        self._last_auto_capture_at = 0.0

        self._status: dict[str, Any] = {
            "running": False,
            "frame_available": False,
            "frame_id": None,
            "frame_timestamp": None,
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
        }

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

    def set_auto_capture(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        with self._lock:
            self._auto_capture_enabled = bool(enabled)
            self._status["auto_capture_enabled"] = bool(enabled)

        return self.status()

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
        self._acquisition.reset()
        self._acquisition.last_captured_fingerprint = None
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
            area_fraction < 0.025
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
                (area_fraction - 0.025) / 0.18,
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

        for contour in contours:
            candidate = cls._score_contour(
                contour,
                edges,
                frame_area,
            )

            if candidate is not None:
                candidates.append(candidate)

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

    def save_latest_crop(
        self,
        source: str = "manual",
    ) -> str | None:
        with self._lock:
            preferred = (
                self._best_lock_crop
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

        self.emit(
            {
                "type": "card_captured",
                "payload": {
                    "path": str(path),
                    "source": source,
                    "camera_name": camera_name,
                    "frame_id": frame_id,
                    "timestamp": time.time(),
                },
            }
        )

        return str(path)

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
                actual_height, actual_width = clean_frame.shape[:2]

                with self._lock:
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

                if reference is not None:
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
                else:
                    self._missing_frames += 1

                    if (
                        self._missing_frames
                        >= self.REARM_MISSING_FRAMES
                    ):
                        self._auto_capture_armed = True
                        self._best_lock_crop = None
                        self._best_lock_quality = 0.0

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
                    saved_path = self.save_latest_crop(
                        source="auto"
                    )

                    if saved_path:
                        captured_sample = (
                            self._acquisition.best_consensus()
                        )

                        self._acquisition.mark_captured(
                            captured_sample
                        )

                        self._auto_capture_armed = False
                        self._last_auto_capture_at = now

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
