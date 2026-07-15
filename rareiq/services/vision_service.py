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

        edge_score = cls._edge_support(
            edges,
            points,
        )

        approximation = cv2.approxPolyDP(
            contour,
            0.035 * perimeter,
            True,
        )

        four_corner_bonus = (
            1.0
            if (
                len(approximation) == 4
                and cv2.isContourConvex(approximation)
            )
            else 0.0
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

        height, width = frame.shape[:2]
        frame_area = float(width * height)

        gray = cv2.cvtColor(
            frame,
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

        normalized = (
            points
            / np.array(
                [width, height],
                dtype=np.float32,
            )
        ).astype(np.float32)

        destination = np.array(
            [
                [0, 0],
                [499, 0],
                [499, 699],
                [0, 699],
            ],
            dtype=np.float32,
        )

        transform = cv2.getPerspectiveTransform(
            points.astype(np.float32),
            destination,
        )

        crop = cv2.warpPerspective(
            frame,
            transform,
            (500, 700),
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

        capture.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            1280,
        )

        capture.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            720,
        )

        capture.set(
            cv2.CAP_PROP_BUFFERSIZE,
            1,
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

                with self._lock:
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

                if candidate_found and result.crop is not None:
                    quality = self._crop_quality(
                        result.crop
                    )

                    with self._lock:
                        self._latest_crop = (
                            result.crop.copy()
                        )

                    if (
                        visible
                        and quality >= self._best_lock_quality
                    ):
                        self._best_lock_crop = (
                            result.crop.copy()
                        )

                        self._best_lock_quality = quality

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
                                    2,
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
