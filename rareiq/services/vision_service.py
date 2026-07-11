from __future__ import annotations
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np


class VisionService:
    def __init__(self, emit: Callable[[dict[str, Any]], None], capture_dir: Path) -> None:
        self.emit = emit
        self.capture_dir = capture_dir
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_crop: np.ndarray | None = None
        self._status = {
            "running": False, "camera_index": 0, "visible": False,
            "stable": False, "polygon": [], "error": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def start(self, camera_index: int) -> dict[str, Any]:
        self.stop()
        self._running = True
        self._status["camera_index"] = int(camera_index)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.2)
        self._thread = None
        with self._lock:
            self._status.update({"running": False, "visible": False, "stable": False, "polygon": []})
        return self.status()

    def save_latest_crop(self) -> str | None:
        with self._lock:
            crop = None if self._latest_crop is None else self._latest_crop.copy()
        if crop is None:
            return None
        path = self.capture_dir / f"card_{int(time.time()*1000)}.jpg"
        cv2.imwrite(str(path), crop)
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
    def _detect(cls, frame: np.ndarray):
        h, w = frame.shape[:2]
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        edges = cv2.dilate(cv2.Canny(gray, 55, 155), np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        frame_area = w * h

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < frame_area * 0.035 or area > frame_area * 0.9:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            pts = cls._order(approx.reshape(4, 2).astype(np.float32))
            cw = max(np.linalg.norm(pts[1]-pts[0]), np.linalg.norm(pts[2]-pts[3]))
            ch = max(np.linalg.norm(pts[3]-pts[0]), np.linalg.norm(pts[2]-pts[1]))
            if min(cw, ch) <= 0:
                continue
            ratio = min(cw, ch) / max(cw, ch)
            score = 1 - abs(ratio - 0.714)
            if score >= 0.73:
                candidates.append((area * score, pts))

        if not candidates:
            return None, []

        _, pts = max(candidates, key=lambda x: x[0])
        normalized = [[float(x/w), float(y/h)] for x, y in pts]
        dst = np.array([[0,0],[499,0],[499,699],[0,699]], dtype=np.float32)
        crop = cv2.warpPerspective(frame, cv2.getPerspectiveTransform(pts, dst), (500,700))
        return crop, normalized

    def _worker(self) -> None:
        index = int(self._status["camera_index"])
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            with self._lock:
                self._status.update({"running": False, "error": f"Could not open camera index {index}"})
            self._running = False
            self.emit({"type": "vision_status", "payload": self.status()})
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        smoothed = previous = None
        stable_frames = 0
        last_emit = 0.0

        with self._lock:
            self._status.update({"running": True, "error": None})

        while self._running:
            ok, frame = cap.read()
            if not ok:
                break

            crop, polygon = self._detect(frame)
            visible = bool(polygon)
            stable = False

            if visible:
                current = np.array(polygon, dtype=np.float32)
                smoothed = current if smoothed is None else 0.76 * smoothed + 0.24 * current
                movement = 1.0 if previous is None else float(np.mean(np.abs(smoothed - previous)))
                previous = smoothed.copy()
                stable_frames = stable_frames + 1 if movement < 0.0028 else 0
                stable = stable_frames >= 8
                polygon = smoothed.tolist()
                ph, pw = frame.shape[:2]
                px = (smoothed * np.array([pw, ph], dtype=np.float32)).astype(np.int32)
                cv2.polylines(frame, [px], True, (90,255,190) if stable else (255,255,255), 3)
                with self._lock:
                    self._latest_crop = crop
            else:
                smoothed = previous = None
                stable_frames = 0

            text = "CARD LOCKED" if stable else ("CARD DETECTED" if visible else "SEARCHING")
            cv2.putText(frame, f"RareIQ Vision | {text}", (24,40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                        (90,255,190) if stable else (255,255,255), 2, cv2.LINE_AA)

            ok_jpg, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok_jpg:
                with self._lock:
                    self._latest_jpeg = jpg.tobytes()
                    self._status.update({
                        "running": True, "visible": visible, "stable": stable,
                        "polygon": polygon, "error": None,
                    })

            now = time.time()
            if now - last_emit >= 0.05:
                self.emit({"type": "card_tracking", "payload": self.status()})
                last_emit = now

        cap.release()
        self._running = False
        with self._lock:
            self._status.update({"running": False, "visible": False, "stable": False, "polygon": []})
