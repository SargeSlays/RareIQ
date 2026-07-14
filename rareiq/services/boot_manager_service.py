from __future__ import annotations

import threading
import time
from typing import Any


class BootManagerService:
    """Deterministic startup coordinator for RareIQ."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator
        self._lock = threading.RLock()
        self._state = "idle"
        self._message = "Boot Manager idle."
        self._progress = 0
        self._started_at: float | None = None
        self._completed_at: float | None = None
        self._last_error: str | None = None
        self._steps: list[dict[str, Any]] = []
        self._generation = 0

    def _set(self, state: str, message: str, progress: int, error: str | None = None) -> None:
        self._state = state
        self._message = message
        self._progress = max(0, min(100, int(progress)))
        self._last_error = error
        self._generation += 1

    def _step(self, key: str, label: str, status: str, detail: str) -> None:
        payload = {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "timestamp": time.time(),
        }
        existing = next((item for item in self._steps if item["key"] == key), None)
        if existing is None:
            self._steps.append(payload)
        else:
            existing.update(payload)

    def status(self) -> dict[str, Any]:
        return {
            "ok": self._state in {"ready", "degraded"},
            "state": self._state,
            "message": self._message,
            "progress": self._progress,
            "generation": self._generation,
            "started_at": self._started_at,
            "completed_at": self._completed_at,
            "last_error": self._last_error,
            "steps": [dict(item) for item in self._steps],
        }

    def run(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if self._state == "ready" and not force:
                return self.status()

            self._started_at = time.time()
            self._completed_at = None
            self._steps = []
            self._set("booting", "Initializing RareIQ.", 5)

            try:
                self._step("config", "Load Configuration", "working", "Loading runtime configuration.")
                self._step("config", "Load Configuration", "complete", "Configuration loaded.")

                self._set("discovering_camera", "Discovering cameras.", 18)
                self._step("discover", "Discover Cameras", "working", "Scanning Windows video devices.")
                cameras = self.orchestrator.camera_manager.discover(force=True)

                if cameras:
                    self._step("discover", "Discover Cameras", "complete", f"{len(cameras)} camera option(s) detected.")
                else:
                    self._step("discover", "Discover Cameras", "warning", "No camera detected.")

                self._set("restoring_camera", "Restoring saved camera.", 32)
                self._step("restore", "Restore Camera", "working", "Loading the saved device selection.")
                selected = self.orchestrator.camera_manager.selected_camera()

                if selected is None and cameras:
                    selected = self.orchestrator.camera_manager.select(
                        int(cameras[0]["index"]),
                        int(cameras[0]["backend"]),
                    )

                if selected:
                    self._step("restore", "Restore Camera", "complete", str(selected.get("name") or "Saved camera restored."))
                else:
                    self._step("restore", "Restore Camera", "warning", "No saved camera available.")

                camera_ready = False
                if selected:
                    self._set("starting_camera", "Starting camera.", 46)
                    self._step("camera", "Start Camera", "working", f"Opening {selected.get('name')}.")
                    camera_status = self.orchestrator.camera_manager.start(
                        int(selected["index"]),
                        int(selected["backend"]),
                        True,
                    )
                    camera_ready = (
                        camera_status.get("manager", {}).get("state") == "running"
                        and bool(camera_status.get("vision", {}).get("running"))
                        and bool(camera_status.get("vision", {}).get("frame_available", True))
                    )

                    if camera_ready:
                        self._step("camera", "Start Camera", "complete", "First live frame received.")
                    else:
                        self._step(
                            "camera",
                            "Start Camera",
                            "warning",
                            camera_status.get("manager", {}).get("last_error")
                            or camera_status.get("manager", {}).get("message")
                            or "Camera did not become ready.",
                        )
                else:
                    self._step("camera", "Start Camera", "warning", "Skipped because no camera is available.")

                self._set("verifying_services", "Verifying core services.", 72)
                checks = [
                    ("recognition", "Recognition Engine", self.orchestrator.recognition.status()),
                    ("catalog", "Catalog Service", self.orchestrator.catalog.status()),
                    ("index", "Visual Index", self.orchestrator.index_activation.status()),
                ]

                unhealthy: list[str] = []
                for key, label, result in checks:
                    error = result.get("error") if isinstance(result, dict) else None
                    if error:
                        unhealthy.append(label)
                        self._step(key, label, "warning", str(error))
                    else:
                        self._step(key, label, "complete", f"{label} available.")

                self._set("verifying_services", "Finalizing Studio.", 92)
                self._step("studio", "Enter Studio", "working", "Preparing the operator workspace.")

                degraded = bool(unhealthy or not camera_ready)
                self._completed_at = time.time()

                if degraded:
                    details: list[str] = []
                    if not camera_ready:
                        details.append("camera unavailable")
                    details.extend(unhealthy)
                    self._set("degraded", "RareIQ is ready with limited functionality: " + ", ".join(details), 100)
                    self._step("studio", "Enter Studio", "complete", "Studio entered in degraded mode.")
                else:
                    self._set("ready", "RareIQ is ready.", 100)
                    self._step("studio", "Enter Studio", "complete", "All core services are ready.")

                return self.status()

            except Exception as exc:
                self._completed_at = time.time()
                self._set("error", "Boot sequence failed.", self._progress, str(exc))
                self._step("studio", "Enter Studio", "error", str(exc))
                return self.status()
