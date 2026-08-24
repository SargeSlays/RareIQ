from __future__ import annotations

import copy
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class PipelineStage:
    key: str
    label: str
    state: str = "waiting"
    message: str = "Waiting"
    started_at: float | None = None
    finished_at: float | None = None
    duration_ms: float = 0.0
    frame_id: int | None = None
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


class PipelineStateService:
    """Single source of truth for recognition pipeline telemetry."""

    STAGES = (
        ("camera", "Camera"),
        ("detect", "Detect Card"),
        ("crop", "Prepare Image"),
        ("ocr", "Read Details"),
        ("artwork", "Match Artwork"),
        ("verify", "Verify"),
        ("current_card", "Current Card"),
        ("session", "Session"),
    )

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._updated_at = time.time()
        self._frame_id: int | None = None
        self._stages = {
            key: PipelineStage(key=key, label=label)
            for key, label in self.STAGES
        }

    def reset(self, frame_id: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._frame_id = frame_id
            self._stages = {
                key: PipelineStage(
                    key=key,
                    label=label,
                    frame_id=frame_id,
                )
                for key, label in self.STAGES
            }
            self._touch()
            return self.snapshot()

    def start(
        self,
        key: str,
        message: str,
        frame_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            stage = self._stage(key)
            now = time.time()
            stage.state = "running"
            stage.message = message
            stage.started_at = now
            stage.finished_at = None
            stage.duration_ms = 0.0
            stage.frame_id = frame_id if frame_id is not None else self._frame_id
            stage.error = None
            self._touch()
            return stage.public()

    def complete(
        self,
        key: str,
        message: str,
        frame_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            stage = self._stage(key)
            now = time.time()
            stage.state = "done"
            stage.message = message
            stage.finished_at = now
            stage.frame_id = frame_id if frame_id is not None else stage.frame_id
            if stage.started_at is not None:
                stage.duration_ms = round((now - stage.started_at) * 1000.0, 2)
            stage.error = None
            self._touch()
            return stage.public()

    def fail(
        self,
        key: str,
        error: str,
        message: str | None = None,
        frame_id: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            stage = self._stage(key)
            now = time.time()
            stage.state = "failed"
            stage.message = message or "Stage failed"
            stage.finished_at = now
            stage.frame_id = frame_id if frame_id is not None else stage.frame_id
            if stage.started_at is not None:
                stage.duration_ms = round((now - stage.started_at) * 1000.0, 2)
            stage.error = error
            self._touch()
            return stage.public()

    def waiting(
        self,
        key: str,
        message: str = "Waiting",
    ) -> dict[str, Any]:
        with self._lock:
            stage = self._stage(key)
            stage.state = "waiting"
            stage.message = message
            stage.error = None
            self._touch()
            return stage.public()

    def sync_from_runtime(
        self,
        *,
        camera: dict[str, Any] | None = None,
        recognition: dict[str, Any] | None = None,
        current_card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Best-effort adapter for existing services during Sprint 6.4."""
        camera = camera or {}
        recognition = recognition or {}

        with self._lock:
            camera_live = bool(
                camera.get("visible")
                or camera.get("running")
                or camera.get("connected")
                or camera.get("state") == "running"
            )
            self._set_simple(
                "camera",
                "done" if camera_live else "waiting",
                "Live frame available" if camera_live else "Waiting for camera",
            )

            detected = bool(
                recognition.get("card_detected")
                or recognition.get("detection")
                or recognition.get("latest_crop_available")
            )
            self._set_simple(
                "detect",
                "done" if detected else "waiting",
                "Card detected" if detected else "Waiting for card",
            )

            crop_ready = bool(
                recognition.get("crop_ready")
                or recognition.get("corrected_crop")
                or recognition.get("latest_crop_available")
            )
            self._set_simple(
                "crop",
                "done" if crop_ready else "waiting",
                "Corrected crop ready" if crop_ready else "Waiting for crop",
            )

            ocr_value = (
                recognition.get("collector_number")
                or recognition.get("ocr_collector_number")
                or recognition.get("name_candidate")
            )
            self._set_simple(
                "ocr",
                "done" if ocr_value else (
                    "running" if recognition.get("busy") else "waiting"
                ),
                "OCR result available" if ocr_value else (
                    "Reading card details" if recognition.get("busy") else "Waiting for OCR"
                ),
            )

            candidates = recognition.get("candidates") or recognition.get("matches") or []
            self._set_simple(
                "artwork",
                "done" if candidates else (
                    "running" if recognition.get("busy") else "waiting"
                ),
                f"{len(candidates)} candidate(s)" if candidates else (
                    "Searching artwork" if recognition.get("busy") else "Waiting for artwork search"
                ),
            )

            verified = bool(
                recognition.get("recognition_locked")
                or recognition.get("verification_state") in {"VERIFIED", "COMPLETE", "MATCHED"}
            )
            self._set_simple(
                "verify",
                "done" if verified else (
                    "running" if candidates else "waiting"
                ),
                "Match verified" if verified else (
                    "Evaluating candidates" if candidates else "Waiting for candidates"
                ),
            )

            self._set_simple(
                "current_card",
                "done" if current_card else "waiting",
                "Current Card populated" if current_card else "Waiting for verified card",
            )

            self._touch()
            return self.snapshot()


    @staticmethod
    def _first_path(payload: dict[str, Any], *paths: str, default: Any = None) -> Any:
        for path in paths:
            value: Any = payload
            valid = True
            for part in path.split("."):
                if not isinstance(value, dict) or part not in value:
                    valid = False
                    break
                value = value[part]
            if valid and value not in (None, "", [], {}):
                return value
        return default

    @classmethod
    def _truthy_path(cls, payload: dict[str, Any], *paths: str) -> bool:
        return cls._first_path(payload, *paths, default=None) not in (
            None, False, 0, "", [], {}
        )

    def sync_from_snapshot(self, snapshot: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = snapshot or {}
        camera = snapshot.get("camera") or snapshot.get("vision") or {}
        recognition = snapshot.get("recognition") or {}
        recognition_state = snapshot.get("recognition_state") or {}
        current_card = snapshot.get("current_card")
        session = snapshot.get("session") or {}

        data = {
            "camera": camera,
            "recognition": recognition,
            "recognition_state": recognition_state,
        }

        camera_state = str(self._first_path(
            data, "camera.state", "camera.manager.state", default=""
        )).lower()

        camera_live = self._truthy_path(
            data,
            "camera.visible",
            "camera.running",
            "camera.connected",
            "camera.live",
            "camera.frame_available",
            "camera.latest_frame_available",
            "camera.manager.running",
        ) or camera_state in {"running","live","ready","connected"}

        detected = self._truthy_path(
            data,
            "recognition.card_detected",
            "recognition.detection.card_detected",
            "recognition_state.card_detected",
            "recognition_state.detected",
            "recognition.latest_crop_available",
            "camera.latest_crop_available",
        )

        crop_ready = self._truthy_path(
            data,
            "recognition.crop_ready",
            "recognition.corrected_crop",
            "recognition.latest_crop_available",
            "recognition_state.crop_ready",
            "recognition_state.corrected_crop_available",
            "camera.latest_crop_available",
        )

        busy = self._truthy_path(
            data,
            "recognition.busy",
            "recognition.processing",
            "recognition_state.busy",
            "recognition_state.processing",
        )

        ocr_value = self._first_path(
            data,
            "recognition.collector_number",
            "recognition.ocr_collector_number",
            "recognition.name_candidate",
            "recognition.ocr.number",
            "recognition.ocr.name",
            "recognition_state.collector_number",
            "recognition_state.name_candidate",
        )

        candidates = self._first_path(
            data,
            "recognition.candidates",
            "recognition.matches",
            "recognition_state.candidates",
            default=[],
        )
        if not isinstance(candidates, list):
            candidates=[]

        verification_state = str(self._first_path(
            data,
            "recognition.verification_state",
            "recognition_state.verification_state",
            default="",
        )).upper()

        verified = self._truthy_path(
            data,
            "recognition.recognition_locked",
            "recognition.verified",
            "recognition_state.recognition_locked",
            "recognition_state.verified",
        ) or verification_state in {
            "VERIFIED","COMPLETE","MATCHED","CONFIRMED"
        }

        with self._lock:
            self._set_simple(
                "camera",
                "done" if camera_live else "waiting",
                "Live frame available" if camera_live else "Waiting for camera frame",
            )
            self._set_simple(
                "detect",
                "done" if detected else ("running" if camera_live else "waiting"),
                "Card detected" if detected else (
                    "Watching for card" if camera_live else "Waiting for camera"
                ),
            )
            self._set_simple(
                "crop",
                "done" if crop_ready else ("running" if detected else "waiting"),
                "Corrected crop ready" if crop_ready else (
                    "Preparing detected card" if detected else "Waiting for detection"
                ),
            )
            self._set_simple(
                "ocr",
                "done" if ocr_value else ("running" if busy or crop_ready else "waiting"),
                f"OCR result: {ocr_value}" if ocr_value else (
                    "Reading card details" if busy or crop_ready else "Waiting for corrected crop"
                ),
            )
            self._set_simple(
                "artwork",
                "done" if candidates else ("running" if busy and bool(ocr_value) else "waiting"),
                f"{len(candidates)} candidate(s) found" if candidates else (
                    "Searching artwork database" if busy and bool(ocr_value) else "Waiting for OCR result"
                ),
            )
            self._set_simple(
                "verify",
                "done" if verified else ("running" if candidates else "waiting"),
                "Match verified" if verified else (
                    "Ranking candidates" if candidates else "Waiting for candidates"
                ),
            )
            self._set_simple(
                "current_card",
                "done" if current_card else ("running" if verified else "waiting"),
                "Current Card populated" if current_card else (
                    "Building Current Card" if verified else "Waiting for verified card"
                ),
            )
            self._set_simple(
                "session",
                "done" if session else "waiting",
                "Session available" if session else "Waiting for session",
            )
            self._touch()
            return self.snapshot()
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stages = [
                copy.deepcopy(self._stages[key].public())
                for key, _ in self.STAGES
            ]
            failed = next(
                (stage for stage in stages if stage["state"] == "failed"),
                None,
            )
            running = next(
                (stage for stage in stages if stage["state"] == "running"),
                None,
            )
            completed = sum(1 for stage in stages if stage["state"] == "done")
            return {
                "ok": failed is None,
                "revision": self._revision,
                "updated_at": self._updated_at,
                "frame_id": self._frame_id,
                "phase": (
                    "failed" if failed else
                    running["key"] if running else
                    "complete" if completed == len(stages) else
                    "waiting"
                ),
                "completed_stages": completed,
                "total_stages": len(stages),
                "failed_stage": failed,
                "active_stage": running,
                "stages": stages,
            }

    def _stage(self, key: str) -> PipelineStage:
        if key not in self._stages:
            raise KeyError(f"Unknown pipeline stage: {key}")
        return self._stages[key]

    def _set_simple(self, key: str, state: str, message: str) -> None:
        stage = self._stage(key)
        stage.state = state
        stage.message = message
        stage.error = None

    def _touch(self) -> None:
        self._revision += 1
        self._updated_at = time.time()

