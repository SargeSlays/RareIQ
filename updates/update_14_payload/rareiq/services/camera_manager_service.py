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
    FRAME_STALL_TIMEOUT_SECONDS = 2.0

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
        self._last_observed_frame_id: int | None = None
        self._last_observed_frame_timestamp: float | None = None
        self._last_progress_at: float | None = None
        self._selected = self._load_selected()
        self._recovery_count = 0
        self._last_stream_session_id: int | None = None
        self._last_device_sequence_id: int | None = None
        self._last_content_fingerprint: str | None = None
        self._repeated_content_count = 0
        self._last_genuinely_changed_frame_timestamp: float | None = None
        self._last_duplicate_content_frame_id: int | None = None
        self._last_observed_stream_session_id: int | None = None
        self._last_observed_device_sequence_id: int | None = None

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

    def _set_state_if_changed(
        self,
        state: str,
        message: str,
        error: str | None = None,
    ) -> None:
        if (state, message, error) != (
            self._state,
            self._message,
            self._last_error,
        ):
            self._set_state(state, message, error)

    def _observe_frame_progress(
        self,
        vision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        vision = self.vision.status() if vision is None else vision
        frame_id = vision.get("frame_id")
        frame_timestamp = vision.get("frame_timestamp")
        provenance = dict(vision.get("camera_provenance") or {})
        self._last_stream_session_id = provenance.get("stream_session_id")
        self._last_device_sequence_id = provenance.get("device_sequence_id")
        self._last_content_fingerprint = provenance.get("content_fingerprint")
        self._repeated_content_count = int(
            provenance.get("repeated_content_count") or 0
        )
        self._last_genuinely_changed_frame_timestamp = provenance.get(
            "last_genuinely_changed_frame_timestamp"
        )
        self._last_duplicate_content_frame_id = provenance.get(
            "last_duplicate_content_frame_id"
        )
        stream_session = provenance.get("stream_session_id")
        device_sequence = provenance.get("device_sequence_id")
        if stream_session is not None and device_sequence is not None:
            progressed = bool(
                stream_session != self._last_observed_stream_session_id
                or device_sequence != self._last_observed_device_sequence_id
            )
        else:
            progressed = bool(
                (frame_id is not None and frame_id != self._last_observed_frame_id)
                or (
                    frame_timestamp is not None
                    and frame_timestamp != self._last_observed_frame_timestamp
                )
            )
        now = time.monotonic()
        if progressed:
            self._last_observed_frame_id = frame_id
            self._last_observed_frame_timestamp = frame_timestamp
            self._last_observed_stream_session_id = stream_session
            self._last_observed_device_sequence_id = device_sequence
            self._last_progress_at = now
            self._last_frame_at = time.time()

        worker_alive = bool(self.vision.worker_alive())
        frame_age = (
            None
            if self._last_progress_at is None
            else max(0.0, now - self._last_progress_at)
        )
        frame_fresh = bool(
            vision.get("running")
            and worker_alive
            and frame_age is not None
            and frame_age <= self.FRAME_STALL_TIMEOUT_SECONDS
        )
        stalled = bool(
            vision.get("running")
            and worker_alive
            and frame_age is not None
            and frame_age > self.FRAME_STALL_TIMEOUT_SECONDS
        )
        if vision.get("error"):
            reason = "camera_error"
        elif not worker_alive:
            reason = "dead_worker"
        elif stalled:
            reason = "frame_progress_stalled"
        elif not frame_fresh:
            reason = "waiting_for_frame_progress"
        else:
            reason = "healthy"
        return {
            "progressed": progressed,
            "worker_alive": worker_alive,
            "frame_fresh": frame_fresh,
            "stalled": stalled,
            "frame_age_seconds": frame_age,
            "health_reason": reason,
        }

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
            health = self._observe_frame_progress(current)
            same_camera = (
                current.get("camera_index") == int(selected["index"])
                and current.get("camera_backend") == int(selected["backend"])
            )

            if same_camera and health["frame_fresh"] and not current.get("error"):
                self._set_state_if_changed(
                    "running",
                    f"{selected['name']} is already streaming.",
                )
                result = self.status()
                result["already_running"] = True
                result["manager"]["start_result"] = "already_running"
                return result

            self._set_state(
                "starting",
                f"Opening {selected['name']}.",
            )
            result = self.vision.start(
                int(selected["index"]),
                int(selected["backend"]),
            )
            self._last_progress_at = None
            self._last_observed_frame_id = result.get("frame_id")
            self._last_observed_frame_timestamp = result.get("frame_timestamp")

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
                health = self._observe_frame_progress(status)

                if health["frame_fresh"]:
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
        health = self._observe_frame_progress(vision)
        with self._operation_lock:
            if health["frame_fresh"] and self._state in {
                "starting",
                "waiting_for_frame",
                "recovering",
                "ready",
                "selected",
            }:
                self._set_state_if_changed(
                    "running",
                    f"{vision.get('camera_name') or 'Camera'} is streaming.",
                )
            elif self._state not in {"stopped", "stopping", "boot"}:
                if vision.get("error") or not health["worker_alive"]:
                    detail = str(vision.get("error") or "Vision worker exited.")
                    self._set_state_if_changed(
                        "error",
                        "Camera worker is not running.",
                        detail,
                    )
                elif health["stalled"]:
                    self._set_state_if_changed(
                        "stalled",
                        "Camera frames stopped advancing.",
                        "Frame progression stalled.",
                    )
                elif health["frame_fresh"] and self._state == "stalled":
                    self._set_state_if_changed(
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
                "last_observed_frame_id": self._last_observed_frame_id,
                "last_observed_frame_timestamp": self._last_observed_frame_timestamp,
                "frame_age_seconds": health["frame_age_seconds"],
                "frame_fresh": health["frame_fresh"],
                "worker_alive": health["worker_alive"],
                "stalled": health["stalled"],
                "health_reason": health["health_reason"],
                "freshness_timeout_seconds": self.FRAME_STALL_TIMEOUT_SECONDS,
                "recovery_count": self._recovery_count,
                "selected_camera": self.selected_camera(),
                "cached_devices": len(self._devices),
                "devices_scanned_at": self._devices_scanned_at,
                "stream_session_id": self._last_stream_session_id,
                "device_sequence_id": self._last_device_sequence_id,
                "content_fingerprint": self._last_content_fingerprint,
                "repeated_content_count": self._repeated_content_count,
                "last_genuinely_changed_frame_timestamp": (
                    self._last_genuinely_changed_frame_timestamp
                ),
                "last_duplicate_content_frame_id": (
                    self._last_duplicate_content_frame_id
                ),
            },
            "vision": vision,
            # Compatibility fields for existing frontends.
            **vision,
        }

    def health(self) -> dict[str, Any]:
        status = self.status()
        vision = status["vision"]
        manager = status["manager"]
        healthy = bool(
            self._state == "running"
            and vision.get("running")
            and manager["worker_alive"]
            and manager["frame_fresh"]
            and not vision.get("error")
        )
        return {
            "healthy": healthy,
            "state": self._state,
            "message": self._message,
            "camera_name": vision.get("camera_name"),
            "visible": bool(vision.get("visible")),
            "running": bool(vision.get("running")),
            "last_frame_at": self._last_frame_at,
            "last_error": self._last_error,
            "worker_alive": manager["worker_alive"],
            "frame_fresh": manager["frame_fresh"],
            "stalled": manager["stalled"],
            "frame_age_seconds": manager["frame_age_seconds"],
            "health_reason": manager["health_reason"],
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

    def capture_fresh(self, source: str = "manual") -> dict[str, Any]:
        return self.vision.capture_fresh(source=source)
