from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class BackendTestService:
    """Normalized runtime data and end-to-end backend diagnostics."""

    def __init__(self, orchestrator: Any, report_dir: Path) -> None:
        self.orchestrator = orchestrator
        self.report_dir = report_dir
        self.report_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _first(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return default

    def normalize_current_card(
        self,
        recognition: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if recognition is None:
            recognition = self.orchestrator.recognition.status()
        if state is None:
            state = self.orchestrator.recognition_state.snapshot()

        match = (
            recognition.get("database_match")
            or state.get("card")
            or state.get("verified_card")
            or {}
        )
        if not isinstance(match, dict):
            match = {}

        candidates = recognition.get("candidates") or state.get("candidates") or []
        top_candidate = (
            candidates[0]
            if candidates and isinstance(candidates[0], dict)
            else {}
        )

        card_name = self._first(
            match.get("english_name"),
            match.get("card_name"),
            match.get("name"),
            recognition.get("name_candidate"),
            top_candidate.get("english_name"),
            top_candidate.get("card_name"),
            top_candidate.get("name"),
        )
        collector_number = self._first(
            match.get("collector_number"),
            match.get("number"),
            recognition.get("collector_number"),
            recognition.get("ocr_collector_number"),
            top_candidate.get("collector_number"),
            top_candidate.get("number"),
        )

        if not card_name and not collector_number:
            return None

        confidence = float(
            self._first(
                recognition.get("overall_confidence"),
                recognition.get("confidence"),
                match.get("confidence"),
                top_candidate.get("confidence"),
                default=0.0,
            )
            or 0.0
        )

        card_id = self._first(
            match.get("card_id"),
            match.get("id"),
            top_candidate.get("card_id"),
            top_candidate.get("id"),
        )
        reference_url = self._first(
            match.get("reference_image_url"),
            match.get("image_url"),
            match.get("image"),
            top_candidate.get("reference_image_url"),
            top_candidate.get("image_url"),
        )
        if not reference_url and card_id:
            reference_url = f"/api/artwork-index/image/{card_id}"

        return {
            "card_id": card_id,
            "card_name": card_name or "Unknown Card",
            "printed_name": self._first(
                match.get("printed_name"),
                recognition.get("name_candidate"),
                top_candidate.get("printed_name"),
            ),
            "english_name": self._first(
                match.get("english_name"),
                match.get("card_name"),
                top_candidate.get("english_name"),
                card_name,
            ),
            "collector_number": collector_number,
            "set_name": self._first(
                match.get("set_name"),
                match.get("set"),
                top_candidate.get("set_name"),
                top_candidate.get("set"),
            ),
            "set_id": self._first(
                match.get("set_id"),
                top_candidate.get("set_id"),
            ),
            "language": self._first(
                match.get("language"),
                recognition.get("language"),
                top_candidate.get("language"),
                default="Unknown",
            ),
            "rarity": self._first(
                match.get("rarity"),
                top_candidate.get("rarity"),
                default="Unknown",
            ),
            "variant": self._first(
                match.get("variant"),
                top_candidate.get("variant"),
            ),
            "hp": self._first(
                match.get("hp"),
                recognition.get("hp_candidate"),
                top_candidate.get("hp"),
            ),
            "illustrator": self._first(
                match.get("illustrator"),
                top_candidate.get("illustrator"),
            ),
            "raw_value": float(
                self._first(
                    match.get("raw_value"),
                    match.get("market_value"),
                    match.get("price"),
                    top_candidate.get("raw_value"),
                    top_candidate.get("market_value"),
                    default=0.0,
                )
                or 0.0
            ),
            "confidence": confidence,
            "verification_state": self._first(
                recognition.get("verification_state"),
                state.get("verification_state"),
                default="SEARCHING",
            ),
            "recognition_locked": bool(
                recognition.get("recognition_locked")
                or state.get("recognition_locked")
            ),
            "source": self._first(
                match.get("source"),
                top_candidate.get("source"),
                default="recognition",
            ),
            "reference_image_url": reference_url,
            "recognition_signature": self._first(
                recognition.get("recognition_signature"),
                state.get("state_id"),
                f"{card_name}|{collector_number}|{confidence:.4f}",
            ),
            "candidate_count": int(
                recognition.get("candidate_count")
                or len(candidates)
            ),
            "updated_at": self._first(
                recognition.get("updated_at"),
                state.get("updated_at"),
                default=time.time(),
            ),
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        vision = self.orchestrator.vision.status()
        recognition = self.orchestrator.recognition.status()
        catalog = self.orchestrator.catalog.status()
        recognition_state = self.orchestrator.recognition_state.refresh(
            vision=vision,
            recognition=recognition,
            catalog=catalog,
        )
        return {
            "ok": True,
            "timestamp": time.time(),
            "camera": vision,
            "recognition": recognition,
            "recognition_state": recognition_state,
            "current_card": self.normalize_current_card(
                recognition,
                recognition_state,
            ),
            "session": self.orchestrator.sessions.snapshot(),
            "recent_cards": self.orchestrator.sessions.recent_cards(20),
            "rejected_count": len(self.orchestrator.sessions.rejected),
            "catalog": catalog,
            "artwork_index": self.orchestrator.recognition.artwork_index.status(),
            "visual_index": self.orchestrator.global_visual_index.status(),
            "active_set": self.orchestrator.recognition.set_catalog.status(),
        }

    def smoke_test(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name: str, passed: bool, detail: str, data: Any = None) -> None:
            checks.append({
                "name": name,
                "passed": bool(passed),
                "detail": detail,
                "data": data,
            })

        try:
            camera = self.orchestrator.vision.status()
            live = bool(
                camera.get("visible")
                or camera.get("running")
                or camera.get("connected")
            )
            add(
                "camera",
                live,
                "Camera is live." if live else "Camera is not live.",
                camera,
            )
        except Exception as exc:
            add("camera", False, str(exc))

        try:
            frame = self.orchestrator.vision.latest_frame()
            add(
                "latest_frame",
                frame is not None,
                "Live frame available." if frame is not None else "No live frame.",
                {"shape": list(frame.shape) if frame is not None else None},
            )
        except Exception as exc:
            add("latest_frame", False, str(exc))

        try:
            crop = self.orchestrator.vision.latest_crop()
            valid = crop is not None and getattr(crop, "size", 0) > 0
            add(
                "corrected_crop",
                valid,
                "Corrected crop available." if valid else "No corrected crop yet.",
                {"shape": list(crop.shape) if valid else None},
            )
        except Exception as exc:
            add("corrected_crop", False, str(exc))

        try:
            recognition = self.orchestrator.recognition.status()
            add(
                "recognition",
                not bool(recognition.get("error")),
                recognition.get("error") or "Recognition service available.",
                {
                    "enabled": recognition.get("enabled"),
                    "busy": recognition.get("busy"),
                    "verification_state": recognition.get("verification_state"),
                    "candidate_count": recognition.get("candidate_count"),
                },
            )
        except Exception as exc:
            add("recognition", False, str(exc))

        try:
            visual = self.orchestrator.global_visual_index.status()
            records = int(
                visual.get("records")
                or visual.get("indexed_cards")
                or 0
            )
            add(
                "visual_index",
                records > 0,
                f"{records} visual records available.",
                visual,
            )
        except Exception as exc:
            add("visual_index", False, str(exc))

        try:
            artwork = self.orchestrator.recognition.artwork_index.status()
            records = int(
                artwork.get("records")
                or artwork.get("cards")
                or 0
            )
            add(
                "artwork_index",
                records > 0,
                f"{records} artwork records available.",
                artwork,
            )
        except Exception as exc:
            add("artwork_index", False, str(exc))

        try:
            catalog = self.orchestrator.catalog.status()
            add(
                "catalog",
                not bool(catalog.get("error")),
                catalog.get("error") or "Catalog service available.",
                catalog,
            )
        except Exception as exc:
            add("catalog", False, str(exc))

        try:
            session = self.orchestrator.sessions.snapshot()
            add(
                "session",
                isinstance(session, dict),
                "Session state available.",
                session,
            )
        except Exception as exc:
            add("session", False, str(exc))

        try:
            probe = self.report_dir / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            add("storage", True, f"Writable: {self.report_dir}")
        except Exception as exc:
            add("storage", False, str(exc))

        passed = sum(1 for item in checks if item["passed"])
        return {
            "ok": passed == len(checks),
            "passed": passed,
            "total": len(checks),
            "checks": checks,
            "timestamp": time.time(),
        }

    def write_report(self) -> Path:
        path = self.report_dir / f"backend_diagnostic_{int(time.time())}.json"
        path.write_text(
            json.dumps(
                {
                    "generated_at": time.time(),
                    "smoke_test": self.smoke_test(),
                    "runtime": self.runtime_snapshot(),
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        return path

    def submit_latest_crop_for_recognition(self) -> dict[str, Any]:
        crop = self.orchestrator.vision.latest_crop()
        if crop is None or getattr(crop, "size", 0) == 0:
            return {
                "ok": False,
                "error": "No corrected crop is available.",
            }
        before = self.orchestrator.recognition.status()
        self.orchestrator.recognition.submit_frame(crop)
        return {
            "ok": True,
            "message": "Latest corrected crop submitted.",
            "before": {
                "busy": before.get("busy"),
                "verification_state": before.get("verification_state"),
                "candidate_count": before.get("candidate_count"),
            },
        }
