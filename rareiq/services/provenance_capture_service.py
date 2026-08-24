"""Truthful screenshot capture and durable provenance records.

The service consumes frames already owned by CameraManagerService.  It never
opens camera hardware and deliberately keeps capture failure isolated from the
recognition pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np


EVENT_VERSION = 1
WORKFLOWS = {"single-card-sales", "pack-ripping", "pack-battle"}
TRIGGERS = {"manual", "exact-match", "rarity-threshold", "value-threshold", "qualifying-hit"}
CAPTURE_TYPES = {"full_frame", "card_crop"}
PLAYER_SIDES = {"player-1", "player-2"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any, limit: int = 120) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class ProvenanceCaptureService:
    """Own settings, capture assets, dedupe, manifests, and corrections."""

    def __init__(
        self,
        root: Path,
        *,
        legacy_roots: tuple[Path, ...] = (),
        server_session_id: str,
        frame_provider: Callable[[], np.ndarray | None],
        crop_provider: Callable[[], np.ndarray | None],
        camera_context_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.legacy_roots = tuple(
            candidate
            for candidate in (Path(path).resolve() for path in legacy_roots)
            if candidate != self.root and candidate.is_dir()
        )
        self.settings_path = self.root / "settings.json"
        self.index_path = self.root / "events.jsonl"
        self.server_session_id = str(server_session_id)
        self._frame_provider = frame_provider
        self._crop_provider = crop_provider
        self._camera_context_provider = camera_context_provider
        self._lock = threading.RLock()
        self._inflight = False
        self._dedupe: dict[str, str] = {}
        self._pending_dedupe: set[str] = set()
        self._events: dict[str, dict[str, Any]] = {}
        self._event_roots: dict[str, Path] = {}
        self._last_status: dict[str, Any] = {
            "state": "configured",
            "event_id": None,
            "error": None,
        }
        self._load_index()

    @staticmethod
    def default_settings() -> dict[str, Any]:
        return {
            "version": 1,
            "enabled": False,
            "workflowMode": "single-card-sales",
            "triggerReason": "exact-match",
            "captureTypes": {
                "fullFrame": True,
                "cardFocus": False,
                "evidenceView": False,
            },
            "customerId": None,
            "vendorId": None,
            "packNumber": None,
            "turnNumber": None,
            "playerSide": None,
            "includeTimestamp": True,
            "includeRecognitionEvidence": True,
            "minimumConfidence": 0.9,
            "oneCapturePerCard": True,
        }

    @classmethod
    def normalize_settings(cls, value: dict[str, Any] | None) -> dict[str, Any]:
        value = dict(value or {})
        defaults = cls.default_settings()
        workflow = str(value.get("workflowMode") or value.get("workflow") or defaults["workflowMode"])
        trigger = str(value.get("triggerReason") or value.get("trigger_type") or defaults["triggerReason"])
        if workflow not in WORKFLOWS:
            raise ValueError("Unsupported provenance workflow.")
        if trigger not in TRIGGERS:
            raise ValueError("Unsupported provenance trigger.")
        try:
            confidence = float(value.get("minimumConfidence", defaults["minimumConfidence"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("Minimum confidence must be numeric.") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Minimum confidence must be between 0 and 1.")
        requested = dict(value.get("captureTypes") or {})
        side = _optional_text(value.get("playerSide"))
        return {
            **defaults,
            "enabled": value.get("enabled") is True,
            "workflowMode": workflow,
            "triggerReason": trigger,
            "captureTypes": {
                "fullFrame": requested.get("fullFrame", True) is not False,
                "cardFocus": requested.get("cardFocus") is True,
                # Evidence-view rendering is not implemented in Phase 1.
                "evidenceView": False,
            },
            "customerId": _optional_text(value.get("customerId")),
            "vendorId": _optional_text(value.get("vendorId")),
            "packNumber": _positive_int(value.get("packNumber")),
            "turnNumber": _positive_int(value.get("turnNumber")),
            "playerSide": side if workflow == "pack-battle" and side in PLAYER_SIDES else None,
            "includeTimestamp": value.get("includeTimestamp") is not False,
            "includeRecognitionEvidence": value.get("includeRecognitionEvidence") is not False,
            "minimumConfidence": confidence,
            "oneCapturePerCard": True,
        }

    def settings(self) -> dict[str, Any]:
        for path in (self.settings_path, *(root / "settings.json" for root in self.legacy_roots)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return self.normalize_settings(payload)
            except FileNotFoundError:
                continue
            except (json.JSONDecodeError, ValueError, OSError):
                continue
        return self.default_settings()

    def save_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_settings(value)
        self._atomic_json(self.settings_path, normalized)
        with self._lock:
            self._last_status = {
                "state": "armed" if normalized["enabled"] else "configured",
                "event_id": self._last_status.get("event_id"),
                "error": None,
            }
        return deepcopy(normalized)

    def capability(self) -> dict[str, Any]:
        settings = self.settings()
        with self._lock:
            status = deepcopy(self._last_status)
            event_count = len(self._events)
            legacy_event_count = sum(
                1 for root in self._event_roots.values() if root != self.root
            )
        return {
            "available": True,
            "automatic_available": True,
            "manual_available": True,
            "supported_capture_types": ["full_frame", "card_crop"],
            "unsupported_capture_types": ["evidence_view"],
            "settings": settings,
            "status": status,
            "storage": {
                "root": str(self.root),
                "event_count": event_count,
                "legacy_event_count": legacy_event_count,
                "legacy_roots": [str(root) for root in self.legacy_roots],
            },
        }

    def evaluate_recognition(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings()
        if not settings["enabled"]:
            return {"ok": False, "captured": False, "reason": "disabled"}
        trigger = settings["triggerReason"]
        if trigger == "manual":
            return {"ok": False, "captured": False, "reason": "manual_only"}
        verdict = self._identity_verdict(snapshot)
        confidence = self._confidence(snapshot)
        if verdict != "exact-match":
            return {"ok": False, "captured": False, "reason": "identity_not_exact"}
        if confidence < settings["minimumConfidence"]:
            return {"ok": False, "captured": False, "reason": "confidence_below_threshold"}
        primary = dict(snapshot.get("primary_candidate") or {})
        if trigger == "rarity-threshold":
            return {"ok": False, "captured": False, "reason": "rarity_trigger_unavailable"}
        if trigger == "value-threshold":
            return {"ok": False, "captured": False, "reason": "value_trigger_unavailable"}
        if trigger == "qualifying-hit" and not primary.get("qualifying_hit"):
            return {"ok": False, "captured": False, "reason": "qualifying_hit_unavailable"}
        return self.capture(trigger=trigger, snapshot=snapshot, settings=settings)

    def capture(
        self,
        *,
        trigger: str = "manual",
        snapshot: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        snapshot = deepcopy(snapshot or {})
        settings = self.normalize_settings(settings or self.settings())
        camera = self._camera_context()
        identity = self._identity(snapshot)
        generation = int(snapshot.get("generation") or 0)
        dedupe_key = self._dedupe_key(generation, identity, camera)
        with self._lock:
            if trigger != "manual" and dedupe_key in self._dedupe:
                return {
                    "ok": True,
                    "captured": False,
                    "duplicate": True,
                    "eventId": self._dedupe[dedupe_key],
                }
            if trigger != "manual" and dedupe_key in self._pending_dedupe:
                return {
                    "ok": True,
                    "captured": False,
                    "duplicate": True,
                    "pending": True,
                    "eventId": None,
                }
            if self._inflight:
                return {"ok": False, "captured": False, "reason": "capture_busy"}
            if trigger != "manual":
                self._pending_dedupe.add(dedupe_key)
            self._inflight = True
            self._last_status = {"state": "capturing", "event_id": None, "error": None}
        try:
            frame = self._frame_provider()
            if frame is None or getattr(frame, "size", 0) == 0:
                raise ValueError("No current active-camera frame is available.")
            event_id = uuid.uuid4().hex
            captured_at = _utc_now()
            day = datetime.now(timezone.utc)
            event_dir = self._safe_event_dir(day, event_id)
            event_dir.mkdir(parents=True, exist_ok=False)
            assets: list[dict[str, Any]] = []
            requested = settings["captureTypes"]
            if requested["fullFrame"] or not requested["cardFocus"]:
                assets.append(self._write_image(event_dir, event_id, "full_frame", frame))
            if requested["cardFocus"] and camera.get("card_crop_valid"):
                crop = self._crop_provider()
                if crop is not None and getattr(crop, "size", 0) > 0:
                    assets.append(self._write_image(event_dir, event_id, "card_crop", crop))
            if not assets:
                raise ValueError("No requested capture asset is currently available.")
            event = {
                "event_id": event_id,
                "event_version": EVENT_VERSION,
                "event_type": "screenshot",
                "created_at": captured_at,
                "workflow": settings["workflowMode"],
                "trigger_reason": trigger,
                "server_session_id": self.server_session_id,
                "recognition_generation": generation,
                "card_context_id": str(snapshot.get("state_id") or dedupe_key),
                "camera": camera,
                "identity": identity,
                "recognition": self._recognition_evidence(snapshot, settings),
                "context": {
                    "customer": settings["customerId"],
                    "vendor": settings["vendorId"],
                    "pack_id": settings["packNumber"],
                    "turn_id": settings["turnNumber"],
                    "player_side": settings["playerSide"] or camera.get("player_side"),
                },
                "assets": assets,
                "revision_of": None,
            }
            self._atomic_json(event_dir / "event.json", event)
            self._append_event(event)
            with self._lock:
                if trigger != "manual":
                    self._dedupe[dedupe_key] = event_id
                self._last_status = {"state": "saved", "event_id": event_id, "error": None}
            return {
                "ok": True,
                "captured": True,
                "eventId": event_id,
                "capturedAt": captured_at,
                "cardContextId": event["card_context_id"],
                "cameraSource": camera.get("display_name"),
                "assets": self._public_assets(event),
                "event": deepcopy(event),
            }
        except Exception as exc:
            with self._lock:
                self._last_status = {"state": "error", "event_id": None, "error": str(exc)}
            return {"ok": False, "captured": False, "reason": "capture_failed", "error": str(exc)}
        finally:
            with self._lock:
                if trigger != "manual":
                    self._pending_dedupe.discard(dedupe_key)
                self._inflight = False

    def list_events(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(100, int(limit)))
        with self._lock:
            events = sorted(self._events.values(), key=lambda item: item.get("created_at", ""), reverse=True)
            return deepcopy(events[:limit])

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            event = self._events.get(str(event_id))
            return None if event is None else deepcopy(event)

    def correct_event(self, event_id: str, correction: dict[str, Any]) -> dict[str, Any]:
        original = self.get_event(event_id)
        if original is None:
            raise KeyError("Provenance event not found.")
        corrected_at = _utc_now()
        revision_id = uuid.uuid4().hex
        identity = deepcopy(original.get("identity") or {})
        for key, value in dict(correction.get("identity") or {}).items():
            if key in identity:
                identity[key] = value
        revision = {
            **deepcopy(original),
            "event_id": revision_id,
            "event_type": "correction",
            "created_at": corrected_at,
            "identity": identity,
            "assets": [],
            "revision_of": original["event_id"],
            "correction_reason": _optional_text(correction.get("reason"), 300),
            "corrected_at": corrected_at,
        }
        revision_dir = self._safe_event_dir(datetime.now(timezone.utc), revision_id)
        revision_dir.mkdir(parents=True, exist_ok=False)
        self._atomic_json(revision_dir / "event.json", revision)
        self._append_event(revision)
        return deepcopy(revision)

    def asset_path(self, event_id: str, asset_id: str) -> Path | None:
        event = self.get_event(event_id)
        if event is None:
            return None
        asset = next((item for item in event.get("assets") or [] if item.get("asset_id") == asset_id), None)
        if asset is None:
            return None
        with self._lock:
            event_root = self._event_roots.get(str(event_id), self.root)
        candidate = (event_root / str(asset.get("relative_path") or "")).resolve()
        try:
            candidate.relative_to(event_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _camera_context(self) -> dict[str, Any]:
        raw = dict(self._camera_context_provider() or {})
        return {
            "slot_id": raw.get("slot_id"),
            "source_id": _optional_text(raw.get("source_id")),
            "display_name": _optional_text(raw.get("display_name")),
            "player_side": raw.get("player_side") if raw.get("player_side") in PLAYER_SIDES else None,
            "frame_id": raw.get("frame_id"),
            "frame_timestamp": raw.get("frame_timestamp"),
            "card_crop_valid": raw.get("card_crop_valid") is True,
        }

    @staticmethod
    def _identity_verdict(snapshot: dict[str, Any]) -> str:
        exact_match = (
            str(snapshot.get("verification_state") or "").upper() == "VERIFIED"
            and snapshot.get("has_reference_evidence") is True
            and snapshot.get("identity_consistent") is True
            and snapshot.get("recognition_locked") is True
            and snapshot.get("result_current") is True
        )
        if exact_match:
            return "exact-match"
        return "provisional" if snapshot.get("primary_candidate") else "unknown"

    @classmethod
    def _identity(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        card = dict(snapshot.get("primary_candidate") or {})
        verdict = cls._identity_verdict(snapshot)
        if verdict != "exact-match":
            return {
                "card_id": None,
                "set_id": None,
                "set_name": None,
                "local_card_id": None,
                "collector_number": None,
                "printed_name": None,
                "english_name": None,
                "language": None,
                "variant": None,
                "finish": None,
                "rarity": None,
                "release_year": None,
                "identity_verdict": verdict,
            }
        return {
            "card_id": _optional_text(card.get("id")),
            "set_id": _optional_text(card.get("set_id")),
            "set_name": _optional_text(card.get("set_name")),
            "local_card_id": _optional_text(card.get("local_id") or card.get("collector_number")),
            "collector_number": _optional_text(card.get("collector_number")),
            "printed_name": _optional_text(card.get("printed_name") or card.get("name")),
            "english_name": _optional_text(card.get("english_name") or card.get("canonical_name")),
            "language": _optional_text(card.get("language") or card.get("language_code")),
            "variant": _optional_text(card.get("variant")),
            "finish": _optional_text(card.get("finish")),
            "rarity": _optional_text(card.get("rarity")),
            "release_year": card.get("release_year"),
            "identity_verdict": verdict,
        }

    @staticmethod
    def _confidence(snapshot: dict[str, Any]) -> float:
        try:
            return float(snapshot.get("overall_confidence") or snapshot.get("confidence") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _recognition_evidence(cls, snapshot: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        if not settings["includeRecognitionEvidence"]:
            return {"verdict": cls._identity_verdict(snapshot)}
        return {
            "verdict": cls._identity_verdict(snapshot),
            "recognition_confidence": cls._confidence(snapshot),
            "visual_confidence": snapshot.get("artwork_index", {}).get("top_score"),
            "verification_state": snapshot.get("verification_state"),
            "has_reference_evidence": bool(snapshot.get("has_reference_evidence")),
        }

    def _dedupe_key(self, generation: int, identity: dict[str, Any], camera: dict[str, Any]) -> str:
        raw = "|".join((self.server_session_id, str(generation), str(identity.get("card_id") or identity.get("local_card_id") or "unknown"), str(camera.get("slot_id") or ""), str(camera.get("source_id") or "")))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _safe_event_dir(self, day: datetime, event_id: str) -> Path:
        if not event_id.isalnum():
            raise ValueError("Invalid event identifier.")
        path = (self.root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}" / event_id).resolve()
        path.relative_to(self.root)
        return path

    def _write_image(self, event_dir: Path, event_id: str, asset_type: str, image: np.ndarray) -> dict[str, Any]:
        if asset_type not in CAPTURE_TYPES:
            raise ValueError("Unsupported asset type.")
        filename = "full-frame.png" if asset_type == "full_frame" else "card-crop.png"
        ok, encoded = cv2.imencode(".png", np.asarray(image))
        if not ok:
            raise OSError("PNG encoding failed.")
        data = encoded.tobytes()
        path = event_dir / filename
        temp = path.with_suffix(".tmp")
        temp.write_bytes(data)
        os.replace(temp, path)
        height, width = image.shape[:2]
        return {
            "asset_id": f"{event_id}-{asset_type}",
            "type": asset_type,
            "relative_path": path.relative_to(self.root).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": int(width),
            "height": int(height),
            "bytes": len(data),
        }

    def _public_assets(self, event: dict[str, Any]) -> dict[str, str | None]:
        output = {"fullFrame": None, "cardFocus": None, "evidenceView": None, "clipId": None}
        for asset in event.get("assets") or []:
            key = "fullFrame" if asset.get("type") == "full_frame" else "cardFocus"
            output[key] = f"/api/provenance/events/{event['event_id']}/assets/{asset['asset_id']}"
        return output

    def _append_event(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            with self.index_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            self._events[event["event_id"]] = deepcopy(event)
            self._event_roots[event["event_id"]] = self.root

    def _load_index(self) -> None:
        for root in (*self.legacy_roots, self.root):
            try:
                lines = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            except (FileNotFoundError, OSError):
                continue
            for line in lines:
                try:
                    event = json.loads(line)
                    event_id = str(event["event_id"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                self._events[event_id] = event
                self._event_roots[event_id] = root
                if event.get("trigger_reason") != "manual" and not event.get("revision_of"):
                    camera = dict(event.get("camera") or {})
                    identity = dict(event.get("identity") or {})
                    key = self._dedupe_key(int(event.get("recognition_generation") or 0), identity, camera)
                    self._dedupe[key] = event_id

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
