from __future__ import annotations

import threading
import time
from typing import Any


class TriggerManagerService:
    """Own the autonomous camera-to-recognition handoff."""

    POLL_SECONDS = 0.10

    def __init__(
        self,
        vision: Any,
        recognition: Any,
        pipeline_state: Any,
    ) -> None:
        self.vision = vision
        self.recognition = recognition
        self.pipeline_state = pipeline_state
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_capture_path: str | None = None
        self._last_submit_at: float = 0.0
        self._submitted = 0
        self._duplicates = 0
        self._state = "stopped"
        self._reason = "Not started"
        self._last_frame_id: int | None = None
        self._last_error: str | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._state = "watching"
            self._reason = "Waiting for a stable card capture"
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="RareIQTriggerManager",
            )
            self._thread.start()
            return self.status()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self._state = "stopped"
            self._reason = "Stopped"

    def status(self) -> dict[str, Any]:
        vision = self.vision.status() or {}
        recognition = self.recognition.status() or {}
        with self._lock:
            return {
                "state": self._state,
                "reason": self._reason,
                "running": bool(self._thread and self._thread.is_alive()),
                "submitted": self._submitted,
                "duplicates_suppressed": self._duplicates,
                "last_capture_path": self._last_capture_path,
                "last_submit_at": self._last_submit_at or None,
                "last_frame_id": self._last_frame_id,
                "last_error": self._last_error,
                "card_visible": bool(vision.get("visible")),
                "card_stable": bool(vision.get("stable")),
                "stable_frames": int(vision.get("stable_frames") or 0),
                "stable_target": int(vision.get("stable_target") or 0),
                "recognition_busy": bool(recognition.get("busy")),
                "candidate_count": int(
                    recognition.get("candidate_count")
                    or len(recognition.get("candidates") or [])
                ),
                "verification_state": recognition.get("verification_state"),
            }

    def tick(self) -> bool:
        """Run one trigger check. Public for tests and diagnostics."""
        vision = self.vision.status() or {}
        capture_path = vision.get("last_capture_path")
        frame_id = vision.get("frame_id")

        with self._lock:
            self._last_frame_id = frame_id

        if not capture_path:
            self._set("watching", "Waiting for stable card capture")
            return False

        if capture_path == self._last_capture_path:
            self._set("watching", "Current capture already submitted")
            return False

        recognition = self.recognition.status() or {}
        if recognition.get("busy"):
            self._set("waiting", "Recognition worker is busy")
            return False

        crop = self.vision.latest_crop()
        if crop is None or getattr(crop, "size", 0) == 0:
            self._set("waiting", "Capture exists but corrected crop is unavailable")
            return False

        self.pipeline_state.reset(frame_id=frame_id)
        self.pipeline_state.complete("camera", "Live frame available", frame_id)
        self.pipeline_state.complete("detect", "Stable card detected", frame_id)
        self.pipeline_state.complete("crop", "Corrected crop prepared", frame_id)
        self.pipeline_state.start("ocr", "Reading card details", frame_id)
        self.pipeline_state.waiting("artwork", "Waiting for OCR evidence")
        self.pipeline_state.waiting("verify", "Waiting for candidates")
        self.pipeline_state.waiting("current_card", "Waiting for verified card")

        self.recognition.submit_frame(crop)
        with self._lock:
            self._last_capture_path = str(capture_path)
            self._last_submit_at = time.time()
            self._submitted += 1
            self._state = "submitted"
            self._reason = "Corrected crop submitted to recognition"
            self._last_error = None
        return True

    def sync_recognition(self) -> None:
        recognition = self.recognition.status() or {}
        error = recognition.get("error")
        candidates = recognition.get("candidates") or []
        name = recognition.get("name_candidate")
        number = (
            recognition.get("collector_number")
            or recognition.get("ocr_collector_number")
        )
        busy = bool(recognition.get("busy"))
        verified = str(recognition.get("verification_state") or "").upper()

        if error:
            self.pipeline_state.fail("ocr", str(error), "Recognition failed")
            self._set("error", str(error), error=str(error))
            return

        if name or number:
            evidence = " / ".join(str(v) for v in (name, number) if v)
            self.pipeline_state.complete("ocr", f"OCR evidence: {evidence}")
        elif busy:
            self.pipeline_state.start("ocr", "Reading card details")

        if candidates:
            self.pipeline_state.complete(
                "artwork",
                f"{len(candidates)} candidate(s) ranked",
            )
            if verified in {"VERIFIED", "MATCHED", "COMPLETE"}:
                self.pipeline_state.complete("verify", "Recognition verified")
                self._set("complete", "Recognition verified")
            else:
                self.pipeline_state.start("verify", "Evaluating candidates")
        elif busy:
            self.pipeline_state.start("artwork", "Searching artwork references")

    def _run(self) -> None:
        while not self._stop.wait(self.POLL_SECONDS):
            try:
                self.tick()
                self.sync_recognition()
            except Exception as exc:
                self._set("error", str(exc), error=str(exc))

    def _set(
        self,
        state: str,
        reason: str,
        *,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._state = state
            self._reason = reason
            if error is not None:
                self._last_error = error
