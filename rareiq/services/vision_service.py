from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from cv2_enumerate_cameras import enumerate_cameras


class VisionService:
    STABLE_TARGET = 8

    def __init__(self, emit: Callable[[dict[str, Any]], None], capture_dir: Path) -> None:
        self.emit = emit
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_crop: np.ndarray | None = None
        self._selected_camera: dict[str, Any] | None = None

        self._auto_capture_enabled = True
        self._auto_capture_armed = True
        self._missing_frames = 0
        self._last_auto_capture_at = 0.0

        self._status: dict[str, Any] = {
            "running": False,
            "camera_index": None,
            "camera_name": None,
            "camera_backend": None,
            "visible": False,
            "stable": False,
            "stable_frames": 0,
            "stable_target": self.STABLE_TARGET,
            "polygon": [],
            "error": None,
            "auto_capture_enabled": True,
            "auto_capture_armed": True,
            "last_capture_path": None,
        }

    def list_cameras(self) -> list[dict[str, Any]]:
        cameras: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()

        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            try:
                for camera in enumerate_cameras(backend):
                    key = (int(camera.index), int(camera.backend))
                    if key in seen:
                        continue
                    seen.add(key)
                    cameras.append(
                        {
                            "index": int(camera.index),
                            "name": str(camera.name),
                            "backend": int(camera.backend),
                            "backend_name": cv2.videoio_registry.getBackendName(
                                int(camera.backend)
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
            return None if self._latest_crop is None else self._latest_crop.copy()

    def latest_frame(self) -> np.ndarray | None:
        with self._lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def set_auto_capture(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._auto_capture_enabled = bool(enabled)
            self._status["auto_capture_enabled"] = bool(enabled)
        return self.status()

    def start(self, camera_index: int, camera_backend: int) -> dict[str, Any]:
        self.stop()

        cameras = self.list_cameras()
        selected = next(
            (
                camera
                for camera in cameras
                if camera["index"] == int(camera_index)
                and camera["backend"] == int(camera_backend)
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
        self._running = True

        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "camera_index": selected["index"],
                    "camera_name": selected["name"],
                    "camera_backend": selected["backend"],
                    "visible": False,
                    "stable": False,
                    "stable_frames": 0,
                    "polygon": [],
                    "error": None,
                    "auto_capture_armed": True,
                }
            )

        self._thread = threading.Thread(target=self._worker, daemon=True)
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
                    "visible": False,
                    "stable": False,
                    "stable_frames": 0,
                    "polygon": [],
                }
            )
        return self.status()

    def save_latest_crop(self, source: str = "manual") -> str | None:
        with self._lock:
            crop = None if self._latest_crop is None else self._latest_crop.copy()
            camera_name = self._status.get("camera_name")

        if crop is None:
            return None

        path = self.capture_dir / f"card_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(str(path), crop)

        with self._lock:
            self._status["last_capture_path"] = str(path)

        self.emit(
            {
                "type": "card_captured",
                "payload": {
                    "path": str(path),
                    "source": source,
                    "camera_name": camera_name,
                    "timestamp": time.time(),
                },
            }
        )
        return str(path)

    @staticmethod
    def _order(points: np.ndarray) -> np.ndarray:
        out = np.zeros((4, 2), dtype=np.float32)
        sums = points.sum(axis=1)
        diffs = np.diff(points, axis=1).reshape(-1)
        out[0] = points[np.argmin(sums)]
        out[2] = points[np.argmax(sums)]
        out[1] = points[np.argmin(diffs)]
        out[3] = points[np.argmax(diffs)]
        return out

    @classmethod
    def _detect(cls, frame: np.ndarray) -> tuple[np.ndarray | None, list[list[float]]]:
        height, width = frame.shape[:2]
        gray = cv2.GaussianBlur(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
            (5, 5),
            0,
        )
        edges = cv2.dilate(
            cv2.Canny(gray, 55, 155),
            np.ones((3, 3), np.uint8),
            iterations=1,
        )
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        frame_area = width * height
        candidates: list[tuple[float, np.ndarray]] = []

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < frame_area * 0.035 or area > frame_area * 0.9:
                continue

            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)

            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue

            points = cls._order(approx.reshape(4, 2).astype(np.float32))
            card_width = max(
                np.linalg.norm(points[1] - points[0]),
                np.linalg.norm(points[2] - points[3]),
            )
            card_height = max(
                np.linalg.norm(points[3] - points[0]),
                np.linalg.norm(points[2] - points[1]),
            )

            if min(card_width, card_height) <= 0:
                continue

            ratio = min(card_width, card_height) / max(card_width, card_height)
            score = 1 - abs(ratio - 0.714)

            if score >= 0.73:
                candidates.append((area * score, points))

        if not candidates:
            return None, []

        _, points = max(candidates, key=lambda item: item[0])
        normalized = [
            [float(x / width), float(y / height)]
            for x, y in points
        ]

        destination = np.array(
            [[0, 0], [499, 0], [499, 699], [0, 699]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(points, destination)
        crop = cv2.warpPerspective(frame, matrix, (500, 700))
        return crop, normalized

    def _worker(self) -> None:
        selected = self._selected_camera or {}
        index = int(selected.get("index", 0))
        backend = int(selected.get("backend", cv2.CAP_DSHOW))
        name = str(selected.get("name", f"Camera {index}"))

        capture = cv2.VideoCapture(index, backend)
        if not capture.isOpened():
            with self._lock:
                self._status.update(
                    {
                        "running": False,
                        "error": f"Could not open {name}",
                    }
                )
            self._running = False
            self.emit({"type": "vision_status", "payload": self.status()})
            return

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        smoothed: np.ndarray | None = None
        previous: np.ndarray | None = None
        stable_frames = 0
        last_emit = 0.0

        with self._lock:
            self._status.update(
                {
                    "running": True,
                    "camera_name": name,
                    "error": None,
                }
            )

        while self._running:
            ok, frame = capture.read()
            if not ok:
                break

            clean_frame = frame.copy()
            with self._lock:
                self._latest_frame = clean_frame

            crop, polygon = self._detect(frame)
            visible = bool(polygon)
            stable = False

            if visible:
                current = np.array(polygon, dtype=np.float32)
                smoothed = (
                    current
                    if smoothed is None
                    else 0.76 * smoothed + 0.24 * current
                )
                movement = (
                    1.0
                    if previous is None
                    else float(np.mean(np.abs(smoothed - previous)))
                )
                previous = smoothed.copy()
                stable_frames = stable_frames + 1 if movement < 0.0028 else 0
                stable = stable_frames >= self.STABLE_TARGET
                polygon = smoothed.tolist()

                frame_height, frame_width = frame.shape[:2]
                pixel_points = (
                    smoothed
                    * np.array([frame_width, frame_height], dtype=np.float32)
                ).astype(np.int32)

                cv2.polylines(
                    frame,
                    [pixel_points],
                    True,
                    (90, 255, 190) if stable else (255, 255, 255),
                    3,
                )

                with self._lock:
                    self._latest_crop = crop
            else:
                smoothed = None
                previous = None
                stable_frames = 0

            if visible:
                self._missing_frames = 0
            else:
                self._missing_frames += 1
                if self._missing_frames >= 10:
                    self._auto_capture_armed = True

            now = time.time()
            if (
                stable
                and self._auto_capture_enabled
                and self._auto_capture_armed
                and now - self._last_auto_capture_at >= 1.5
            ):
                saved_path = self.save_latest_crop(source="auto")
                if saved_path:
                    self._auto_capture_armed = False
                    self._last_auto_capture_at = now

            label = (
                "CARD LOCKED"
                if stable
                else ("CARD DETECTED" if visible else "SEARCHING")
            )

            cv2.putText(
                frame,
                f"RareIQ Vision | {name} | {label}",
                (24, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (90, 255, 190) if stable else (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            ok_jpeg, jpeg = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), 82],
            )

            if ok_jpeg:
                with self._lock:
                    self._latest_jpeg = jpeg.tobytes()
                    self._status.update(
                        {
                            "running": True,
                            "camera_name": name,
                            "visible": visible,
                            "stable": stable,
                            "stable_frames": stable_frames,
                            "stable_target": self.STABLE_TARGET,
                            "polygon": polygon,
                            "error": None,
                            "auto_capture_enabled": self._auto_capture_enabled,
                            "auto_capture_armed": self._auto_capture_armed,
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

        capture.release()
        self._running = False

        with self._lock:
            self._status.update(
                {
                    "running": False,
                    "visible": False,
                    "stable": False,
                    "stable_frames": 0,
                    "polygon": [],
                }
            )

        self.emit({"type": "vision_status", "payload": self.status()})
