from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from rareiq.services.vision_service import VisionService


class CameraManagerService:
    """Single owner for the camera lifecycle.

    All discovery, selection, start, stop, readiness, and recovery operations
    are serialized here so competing frontend requests cannot open the same
    device simultaneously.
    """

    DISCOVERY_TTL_SECONDS = 8.0
    FIRST_FRAME_TIMEOUT_SECONDS = 12.0

    def __init__(self, vision: VisionService, state_path: Path) -> None:
        self.vision = vision
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self._operation_lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._devices: list[dict[str, Any]] = []
        self._devices_scanned_at = 0.0
        self._generation = 0
        self._state = "boot"
        self._message = "Camera manager initialized."
        self._last_error: str | None = None
        self._last_frame_at: float | None = None
        self._selected = self._load_selected()
        self._recovery_count = 0

    def _load_selected(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            selected = payload.get("selected_camera")
            return selected if isinstance(selected, dict) else None
        except Exception:
            return None

    def _save_selected(self, camera: dict[str, Any]) -> None:
        self._selected = {
            "index": int(camera["index"]),
            "backend": int(camera["backend"]),
            "name": str(camera.get("name") or f"Camera {camera['index']}"),
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"selected_camera": self._selected}, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.state_path)

    def _set_state(
        self,
        state: str,
        message: str,
        error: str | None = None,
    ) -> None:
        self._state = state
        self._message = message
        self._last_error = error
        self._generation += 1

    def discover(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._cache_lock:
            fresh = (
                self._devices
                and now - self._devices_scanned_at < self.DISCOVERY_TTL_SECONDS
            )
            if fresh and not force:
                return [dict(item) for item in self._devices]

        with self._operation_lock:
            self._set_state("discovering", "Scanning Windows camera devices.")
            devices = self.vision.list_cameras()

            with self._cache_lock:
                self._devices = [dict(item) for item in devices]
                self._devices_scanned_at = time.monotonic()

            if devices:
                self._set_state(
                    "ready",
                    f"{len(devices)} camera option(s) available.",
                )
            else:
                self._set_state(
                    "waiting_for_device",
                    "No camera devices are currently available.",
                )

            return [dict(item) for item in devices]

    def selected_camera(self) -> dict[str, Any] | None:
        return None if self._selected is None else dict(self._selected)

    def select(
        self,
        camera_index: int,
        camera_backend: int,
    ) -> dict[str, Any]:
        devices = self.discover(force=False)
        selected = next(
            (
                item
                for item in devices
                if int(item["index"]) == int(camera_index)
                and int(item["backend"]) == int(camera_backend)
            ),
            {
                "index": int(camera_index),
                "backend": int(camera_backend),
                "name": f"Camera {camera_index}",
            },
        )
        self._save_selected(selected)
        self._set_state("selected", f"Selected {selected['name']}.")
        return dict(selected)

    def start(
        self,
        camera_index: int | None = None,
        camera_backend: int | None = None,
        wait_for_frame: bool = True,
    ) -> dict[str, Any]:
        with self._operation_lock:
            if camera_index is not None and camera_backend is not None:
                selected = self.select(camera_index, camera_backend)
            else:
                selected = self.selected_camera()

            if selected is None:
                devices = self.discover(force=True)
                if not devices:
                    self._set_state(
                        "error",
                        "No camera is available to start.",
                        "No cameras detected.",
                    )
                    return self.status()
                selected = self.select(
                    int(devices[0]["index"]),
                    int(devices[0]["backend"]),
                )

            current = self.vision.status()
            same_camera = (
                current.get("camera_index") == int(selected["index"])
                and current.get("camera_backend") == int(selected["backend"])
            )

            if current.get("visible") and same_camera:
                self._set_state(
                    "running",
                    f"{selected['name']} is already streaming.",
                )
                return self.status()

            self._set_state(
                "starting",
                f"Opening {selected['name']}.",
            )
            result = self.vision.start(
                int(selected["index"]),
                int(selected["backend"]),
            )

            if result.get("error"):
                self._set_state(
                    "error",
                    f"Could not open {selected['name']}.",
                    str(result["error"]),
                )
                return self.status()

            if not wait_for_frame:
                self._set_state(
                    "waiting_for_frame",
                    f"Waiting for the first frame from {selected['name']}.",
                )
                return self.status()

            self._set_state(
                "waiting_for_frame",
                f"Waiting for the first frame from {selected['name']}.",
            )
            deadline = time.monotonic() + self.FIRST_FRAME_TIMEOUT_SECONDS

            while time.monotonic() < deadline:
                status = self.vision.status()
                frame = self.vision.latest_jpeg()

                if frame:
                    self._last_frame_at = time.time()
                    self._recovery_count = 0
                    self._set_state(
                        "running",
                        f"{selected['name']} is streaming.",
                    )
                    return self.status()

                if status.get("error"):
                    self._set_state(
                        "error",
                        f"{selected['name']} failed during startup.",
                        str(status["error"]),
                    )
                    return self.status()

                time.sleep(0.1)

            self._set_state(
                "error",
                f"{selected['name']} opened but produced no frames.",
                "First-frame timeout.",
            )
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._operation_lock:
            self._set_state("stopping", "Stopping camera.")
            self.vision.stop()
            self._set_state("stopped", "Camera stopped.")
            return self.status()

    def recover(self) -> dict[str, Any]:
        with self._operation_lock:
            self._recovery_count += 1
            self._set_state(
                "recovering",
                f"Recovering camera, attempt {self._recovery_count}.",
            )
            self.vision.stop()
            time.sleep(0.25)
            return self.start(wait_for_frame=True)

    def status(self) -> dict[str, Any]:
        vision = self.vision.status()
        if self.vision.latest_jpeg():
            self._last_frame_at = time.time()
            if self._state in {
                "starting",
                "waiting_for_frame",
                "recovering",
                "ready",
                "selected",
            }:
                self._set_state(
                    "running",
                    f"{vision.get('camera_name') or 'Camera'} is streaming.",
                )

        return {
            "ok": self._state != "error",
            "manager": {
                "state": self._state,
                "message": self._message,
                "generation": self._generation,
                "last_error": self._last_error,
                "last_frame_at": self._last_frame_at,
                "recovery_count": self._recovery_count,
                "selected_camera": self.selected_camera(),
                "cached_devices": len(self._devices),
                "devices_scanned_at": self._devices_scanned_at,
            },
            "vision": vision,
            # Compatibility fields for existing frontends.
            **vision,
        }

    def health(self) -> dict[str, Any]:
        status = self.status()
        vision = status["vision"]
        healthy = bool(vision.get("visible") and self._state == "running")
        return {
            "healthy": healthy,
            "state": self._state,
            "message": self._message,
            "camera_name": vision.get("camera_name"),
            "visible": bool(vision.get("visible")),
            "running": bool(vision.get("running")),
            "last_frame_at": self._last_frame_at,
            "last_error": self._last_error,
        }

    # Vision compatibility/proxy methods.
    def latest_jpeg(self) -> bytes | None:
        return self.vision.latest_jpeg()

    def latest_crop(self):
        return self.vision.latest_crop()

    def latest_frame(self):
        return self.vision.latest_frame()

    def set_auto_capture(self, enabled: bool) -> dict[str, Any]:
        return self.vision.set_auto_capture(enabled)

    def save_latest_crop(self, source: str = "manual") -> str | None:
        return self.vision.save_latest_crop(source=source)
