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
