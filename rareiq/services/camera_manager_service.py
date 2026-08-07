from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from rareiq.services.camera_source_session import (
    CameraSourceSession,
    enrich_camera_source,
)
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

    def __init__(
        self,
        vision: VisionService,
        state_path: Path,
        session_factory: Callable[[dict[str, Any]], CameraSourceSession] | None = None,
    ) -> None:
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
        self._slots = self._load_slots()
        self._sessions: dict[str, CameraSourceSession] = {}
        self._sources: dict[str, dict[str, Any]] = {}
        self._session_factory = session_factory or CameraSourceSession
        self._active_change_hook: Callable[[dict[str, Any]], None] | None = None
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

    def _load_slots(self) -> dict[int, dict[str, Any]]:
        slots = {
            slot: {
                "slot_id": slot,
                "source_id": None,
                "role": "active" if slot == 1 else "staging",
                "side": "unassigned",
            }
            for slot in range(1, 5)
        }
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            saved = payload.get("camera_slots") or {}
            for slot in range(1, 5):
                item = saved.get(str(slot)) or saved.get(slot) or {}
                if isinstance(item, dict):
                    slots[slot]["source_id"] = item.get("source_id") or None
                    side = str(item.get("side") or "unassigned")
                    slots[slot]["side"] = (
                        side if side in {"unassigned", "player-1", "player-2"}
                        else "unassigned"
                    )
                    if item.get("role") == "active":
                        for other in slots.values():
                            other["role"] = "staging"
                        slots[slot]["role"] = "active"
        except Exception:
            pass
        return slots

    def _save_state(self) -> None:
        payload = {
            "selected_camera": self._selected,
            "camera_slots": {
                str(slot): dict(value) for slot, value in self._slots.items()
            },
        }
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.state_path)

    def _save_selected(self, camera: dict[str, Any]) -> None:
        self._selected = {
            "index": int(camera["index"]),
            "backend": int(camera["backend"]),
            "name": str(camera.get("name") or f"Camera {camera['index']}"),
        }
        if camera.get("source_id"):
            self._selected["source_id"] = str(camera["source_id"])
        self._save_state()

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
            raw_devices = self.vision.list_cameras()
            devices = [enrich_camera_source(item) for item in raw_devices]
            previous_sources = dict(self._sources)
            self._sources = {item["source_id"]: dict(item) for item in devices}
            for source_id, previous in previous_sources.items():
                if source_id not in self._sources:
                    missing = dict(previous)
                    missing.update({
                        "available": False,
                        "availability": "missing",
                    })
                    self._sources[source_id] = missing

            if self._selected and not self._selected.get("source_id"):
                match = next((
                    item for item in devices
                    if int(item["index"]) == int(self._selected["index"])
                    and int(item["backend"]) == int(self._selected["backend"])
                ), None)
                if match:
                    self._selected = {
                        **self._selected, "source_id": match["source_id"]
                    }
                    active = self.active_slot_id()
                    if self._slots[active]["source_id"] is None:
                        self._slots[active]["source_id"] = match["source_id"]
                    self._save_state()

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
        active = self.active_slot_id()
        self._slots[active]["source_id"] = self._selected.get("source_id")
        self._save_state()
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

            source_id = selected.get("source_id")
            if source_id:
                self._stop_preview_session(str(source_id))

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

    def set_active_change_hook(
        self, hook: Callable[[dict[str, Any]], None] | None
    ) -> None:
        self._active_change_hook = hook

    def active_slot_id(self) -> int:
        return next(
            (slot for slot, value in self._slots.items() if value["role"] == "active"),
            1,
        )

    def camera_slots(self) -> list[dict[str, Any]]:
        with self._operation_lock:
            active_slot = self.active_slot_id()
            output = []
            for slot in range(1, 5):
                assignment = dict(self._slots[slot])
                source_id = assignment.get("source_id")
                source = self._sources.get(str(source_id)) if source_id else None
                if slot == active_slot:
                    vision = self.vision.status()
                    session_state = {
                        "connected": bool(vision.get("running") and not vision.get("error")),
                        "state": "connected" if vision.get("running") and not vision.get("error") else "disconnected",
                        "last_frame_at": vision.get("frame_timestamp"),
                        "error": vision.get("error"),
                    }
                elif source_id and source_id in self._sessions:
                    session_state = self._sessions[source_id].status()
                elif source_id:
                    session_state = {
                        "connected": False,
                        "state": "unavailable" if not source or not source.get("available", True) else "disconnected",
                        "last_frame_at": None,
                        "error": None,
                    }
                else:
                    session_state = {
                        "connected": False,
                        "state": "unassigned",
                        "last_frame_at": None,
                        "error": None,
                    }
                output.append({
                    **assignment,
                    "source": None if source is None else dict(source),
                    "display_name": None if source is None else source["display_name"],
                    "connection_state": session_state["state"],
                    "connected": session_state["connected"],
                    "preview_capability": bool(source_id),
                    "last_frame_at": session_state.get("last_frame_at"),
                    "error": session_state.get("error"),
                })
            return output

    def assign_slot(
        self, slot_id: int, source_id: str | None, side: str | None = None
    ) -> dict[str, Any]:
        slot_id = self._validate_slot(slot_id)
        with self._operation_lock:
            if source_id:
                source_id = str(source_id)
                source = self._sources.get(source_id)
                if source is None:
                    self.discover(force=True)
                    source = self._sources.get(source_id)
                if source is None or not source.get("available", True):
                    raise ValueError("Unknown camera source.")
                owner = next((
                    slot for slot, value in self._slots.items()
                    if slot != slot_id
                    and value.get("source_id")
                    and self._sources.get(str(value["source_id"]), {}).get("device_key")
                    == source.get("device_key")
                ), None)
                if owner is not None:
                    raise ValueError(f"Camera device is already assigned to slot {owner}.")
            previous = self._slots[slot_id].get("source_id")
            active_slot = self.active_slot_id()
            previous_source = self._sources.get(str(previous)) if previous else None
            if source_id and slot_id == active_slot and previous != source_id:
                self._stop_preview_session(source_id)
                result = self.start(int(source["index"]), int(source["backend"]), True)
                if result.get("error") or result.get("manager", {}).get("state") == "error":
                    if previous_source is not None:
                        self.start(
                            int(previous_source["index"]),
                            int(previous_source["backend"]),
                            True,
                        )
                    raise RuntimeError(str(result.get("error") or "Camera activation failed."))
            if previous and previous != source_id and slot_id != self.active_slot_id():
                self._stop_preview_session(str(previous))
            self._slots[slot_id]["source_id"] = source_id or None
            if side is not None:
                self._slots[slot_id]["side"] = self._validate_side(side)
            self._save_state()
            if source_id and slot_id != self.active_slot_id():
                self._ensure_preview_session(source_id)
            if source_id and slot_id == active_slot and previous != source_id:
                self._save_selected(source)
                if self._active_change_hook is not None:
                    self._active_change_hook({
                        "old_active_slot": active_slot,
                        "active_slot": active_slot,
                        "source_id": source_id,
                    })
            return self.camera_slots()[slot_id - 1]

    def activate_slot(self, slot_id: int) -> dict[str, Any]:
        slot_id = self._validate_slot(slot_id)
        with self._operation_lock:
            old_active = self.active_slot_id()
            if slot_id == old_active:
                return {"ok": True, "already_active": True, "slots": self.camera_slots()}
            source_id = self._slots[slot_id].get("source_id")
            source = self._sources.get(str(source_id)) if source_id else None
            if not source_id or source is None or not source.get("available", True):
                raise ValueError("The requested slot has no available camera source.")
            self._stop_preview_session(str(source_id))
            previous_source_id = self._slots[old_active].get("source_id")
            previous_roles = {slot: value["role"] for slot, value in self._slots.items()}
            self._slots[old_active]["role"] = "staging"
            self._slots[slot_id]["role"] = "active"
            self._save_selected(source)
            result = self.start(int(source["index"]), int(source["backend"]), True)
            if result.get("error") or result.get("manager", {}).get("state") == "error":
                for slot, role in previous_roles.items():
                    self._slots[slot]["role"] = role
                self._save_state()
                if source_id:
                    self._ensure_preview_session(str(source_id))
                if previous_source_id:
                    previous_source = self._sources.get(str(previous_source_id))
                    if previous_source is not None:
                        self.start(
                            int(previous_source["index"]),
                            int(previous_source["backend"]),
                            True,
                        )
                raise RuntimeError(str(result.get("error") or "Camera activation failed."))
            self._save_state()
            if previous_source_id:
                self._ensure_preview_session(str(previous_source_id))
            payload = {
                "old_active_slot": old_active,
                "active_slot": slot_id,
                "source_id": source_id,
            }
            if self._active_change_hook is not None:
                self._active_change_hook(dict(payload))
            return {"ok": True, **payload, "slots": self.camera_slots()}

    def reconnect_source(self, source_id: str) -> dict[str, Any]:
        with self._operation_lock:
            owner = self._slot_for_source(source_id)
            if owner == self.active_slot_id():
                return self.recover()
            session = self._ensure_preview_session(source_id, start=False)
            return session.reconnect()

    def restart_source(self, source_id: str) -> dict[str, Any]:
        return self.reconnect_source(source_id)

    def slot_jpeg(self, slot_id: int) -> bytes | None:
        slot_id = self._validate_slot(slot_id)
        with self._operation_lock:
            source_id = self._slots[slot_id].get("source_id")
            if not source_id:
                return None
            if slot_id == self.active_slot_id():
                return self.vision.latest_jpeg()
            session = self._sessions.get(str(source_id))
            return None if session is None else session.latest_jpeg()

    def subscribe_slot(self, slot_id: int) -> None:
        slot_id = self._validate_slot(slot_id)
        source_id = self._slots[slot_id].get("source_id")
        if source_id and slot_id != self.active_slot_id():
            self._ensure_preview_session(str(source_id)).subscribe()

    def unsubscribe_slot(self, slot_id: int) -> None:
        slot_id = self._validate_slot(slot_id)
        source_id = self._slots[slot_id].get("source_id")
        session = self._sessions.get(str(source_id)) if source_id else None
        if session is not None:
            session.unsubscribe()

    def shutdown(self) -> None:
        with self._operation_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self.vision.stop()
        for session in sessions:
            session.stop()

    def session_statuses(self) -> dict[str, dict[str, Any]]:
        return {source_id: session.status() for source_id, session in self._sessions.items()}

    def _ensure_preview_session(
        self, source_id: str, *, start: bool = True
    ) -> CameraSourceSession:
        source = self._sources.get(str(source_id))
        if source is None or not source.get("available", True):
            raise ValueError("Unknown camera source.")
        session = self._sessions.get(str(source_id))
        created = session is None
        if session is None:
            session = self._session_factory(dict(source))
            self._sessions[str(source_id)] = session
        state = session.status().get("state")
        if start and (created or state not in {"connecting", "connected", "degraded"}):
            session.start()
        return session

    def _stop_preview_session(self, source_id: str) -> None:
        session = self._sessions.pop(str(source_id), None)
        if session is not None:
            session.stop()

    def _slot_for_source(self, source_id: str) -> int | None:
        return next((
            slot for slot, value in self._slots.items()
            if value.get("source_id") == str(source_id)
        ), None)

    @staticmethod
    def _validate_slot(slot_id: int) -> int:
        value = int(slot_id)
        if value not in {1, 2, 3, 4}:
            raise ValueError("Camera slot must be between 1 and 4.")
        return value

    @staticmethod
    def _validate_side(side: str) -> str:
        value = str(side or "unassigned")
        if value not in {"unassigned", "player-1", "player-2"}:
            raise ValueError("Invalid camera side.")
        return value

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
            "active_slot": self.active_slot_id(),
            "camera_slots": self.camera_slots(),
            "camera_sessions": self.session_statuses(),
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
