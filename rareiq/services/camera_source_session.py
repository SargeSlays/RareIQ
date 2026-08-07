"""Source-owned camera preview sessions.

Sessions are created lazily by ``CameraManagerService``; importing this module
never opens hardware. Physical-camera validation should run uvicorn without
``--reload`` because a reload parent and child can briefly contend for devices.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any, Callable

import cv2
import numpy as np


VIRTUAL_CAMERA_TERMS = (
    "virtual", "obs", "streamlabs", "manycam", "snap camera", "ndi",
    "bytecast", "xsplit", "iriun", "epoccam", "droidcam",
)


def camera_source_id(camera: dict[str, Any]) -> str:
    """Return the most stable deterministic identity exposed by this stack.

    Windows device path/VID/PID are preferred when available. Index and backend
    remain part of the composite because OpenCV does not expose a hardware GUID
    consistently across every backend.
    """
    parts = (
        str(camera.get("path") or "").strip().lower(),
        str(camera.get("vid") or "").strip().lower(),
        str(camera.get("pid") or "").strip().lower(),
        str(int(camera.get("backend") or 0)),
        str(int(camera.get("index") or 0)),
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"camera-{digest}"


def camera_device_key(camera: dict[str, Any]) -> str:
    """Identify physical ownership independently of the selected backend."""
    hardware = (
        str(camera.get("path") or "").strip().lower(),
        str(camera.get("vid") or "").strip().lower(),
        str(camera.get("pid") or "").strip().lower(),
    )
    if not any(hardware):
        hardware = (
            str(camera.get("display_name") or camera.get("name") or "camera").strip().lower(),
            str(int(camera.get("index") or 0)),
            "",
        )
    digest = hashlib.sha256("|".join(hardware).encode("utf-8")).hexdigest()[:20]
    return f"device-{digest}"


def enrich_camera_source(camera: dict[str, Any]) -> dict[str, Any]:
    item = dict(camera)
    name = str(item.get("display_name") or item.get("name") or "Camera")
    virtual = any(term in name.lower() for term in VIRTUAL_CAMERA_TERMS)
    item.update({
        "source_id": str(item.get("source_id") or camera_source_id(item)),
        "device_key": str(item.get("device_key") or camera_device_key(item)),
        "display_name": name,
        "name": name,
        "classification": "virtual" if virtual else "physical",
        "physical": not virtual,
        "virtual": virtual,
        "availability": "available",
        "available": True,
    })
    return item


class CameraSourceSession:
    """Single capture owner and latest-frame pump for one preview source."""

    FRAME_STALE_SECONDS = 2.0
    PREVIEW_WIDTH = 1280
    PREVIEW_HEIGHT = 720
    PREVIEW_FPS = 15

    def __init__(
        self,
        source: dict[str, Any],
        capture_factory: Callable[[int, int], Any] | None = None,
    ) -> None:
        self.source = enrich_camera_source(source)
        self.source_id = self.source["source_id"]
        self._capture_factory = capture_factory or cv2.VideoCapture
        self._lifecycle_lock = threading.RLock()
        self._frame_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture: Any | None = None
        self._latest_frame: np.ndarray | None = None
        self._latest_jpeg: bytes | None = None
        self._last_frame_at: float | None = None
        self._frame_id = 0
        self._state = "unavailable"
        self._error: str | None = None
        self._subscribers = 0
        self._open_count = 0
        self._release_count = 0

    def start(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._state = "connecting"
            self._error = None
            self._thread = threading.Thread(
                target=self._pump,
                daemon=True,
                name=f"RareIQPreview-{self.source_id[-8:]}",
            )
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
            capture = self._capture
            self._capture = None
        self._release_capture(capture)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lifecycle_lock:
            if thread is not None and thread.is_alive():
                self._state = "error"
                self._error = "Camera worker did not stop within 2 seconds."
            else:
                self._thread = None
                self._state = "disconnected"
        return self.status()

    def restart(self) -> dict[str, Any]:
        self.stop()
        return self.start()

    reconnect = restart

    def subscribe(self) -> None:
        with self._frame_lock:
            self._subscribers += 1

    def unsubscribe(self) -> None:
        with self._frame_lock:
            self._subscribers = max(0, self._subscribers - 1)

    def latest_frame(self) -> np.ndarray | None:
        with self._frame_lock:
            return None if self._latest_frame is None else self._latest_frame.copy()

    def latest_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_jpeg

    def status(self) -> dict[str, Any]:
        with self._frame_lock:
            last_frame_at = self._last_frame_at
            frame_id = self._frame_id
            subscribers = self._subscribers
        age = None if last_frame_at is None else max(0.0, time.time() - last_frame_at)
        alive = bool(self._thread is not None and self._thread.is_alive())
        connected = bool(
            alive and self._state == "connected" and age is not None
            and age <= self.FRAME_STALE_SECONDS and self._error is None
        )
        state = self._state
        if alive and state == "connected" and not connected:
            state = "degraded"
        return {
            "source_id": self.source_id,
            "display_name": self.source["display_name"],
            "connected": connected,
            "state": state,
            "last_frame_at": last_frame_at,
            "frame_age_seconds": age,
            "frame_id": frame_id,
            "error": self._error,
            "worker_alive": alive,
            "subscribers": subscribers,
            "open_count": self._open_count,
            "release_count": self._release_count,
            "requested_preview_resolution": [self.PREVIEW_WIDTH, self.PREVIEW_HEIGHT],
            "requested_preview_fps": self.PREVIEW_FPS,
        }

    def _pump(self) -> None:
        capture = None
        try:
            capture = self._capture_factory(
                int(self.source["index"]), int(self.source["backend"])
            )
            with self._lifecycle_lock:
                self._capture = capture
                self._open_count += 1
            if capture is None or not capture.isOpened():
                self._state = "unavailable"
                self._error = f"Could not open {self.source['display_name']}"
                return
            for prop, value in (
                (cv2.CAP_PROP_BUFFERSIZE, 1),
                (cv2.CAP_PROP_FRAME_WIDTH, self.PREVIEW_WIDTH),
                (cv2.CAP_PROP_FRAME_HEIGHT, self.PREVIEW_HEIGHT),
                (cv2.CAP_PROP_FPS, self.PREVIEW_FPS),
            ):
                try:
                    capture.set(prop, value)
                except Exception:
                    pass
            self._state = "connected"
            while not self._stop_event.is_set():
                ok, frame = capture.read()
                if not ok or frame is None:
                    self._state = "disconnected"
                    self._error = "Camera frame read failed."
                    break
                ok_jpeg, encoded = cv2.imencode(".jpg", frame)
                now = time.time()
                with self._frame_lock:
                    self._latest_frame = frame.copy()
                    self._latest_jpeg = encoded.tobytes() if ok_jpeg else None
                    self._last_frame_at = now
                    self._frame_id += 1
        except Exception as exc:
            self._state = "error"
            self._error = str(exc)
        finally:
            with self._lifecycle_lock:
                owned_capture = self._capture is capture
                if owned_capture:
                    self._capture = None
            if owned_capture:
                self._release_capture(capture)

    def _release_capture(self, capture: Any | None) -> None:
        if capture is None:
            return
        try:
            capture.release()
        finally:
            with self._lifecycle_lock:
                self._release_count += 1
