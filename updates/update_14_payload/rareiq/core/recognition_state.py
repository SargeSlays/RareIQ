from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RecognitionSnapshot:
    revision: int
    state_id: str
    updated_at: float
    phase: str
    vision: dict[str, Any] = field(default_factory=dict)
    raw_recognition: dict[str, Any] = field(default_factory=dict)
    catalog: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    primary_candidate: dict[str, Any] | None = None
    name_candidate: str | None = None
    english_name: str | None = None
    collector_number: str | None = None
    language: str | None = None
    overall_confidence: float = 0.0
    confidence: float = 0.0
    artwork_fingerprint: str | None = None
    artwork_index: dict[str, Any] = field(default_factory=dict)
    database_match: dict[str, Any] | None = None
    pipeline_stages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    stage_timings: dict[str, Any] = field(default_factory=dict)
    recognition_locked: bool = False
    has_reference_evidence: bool = False
    verification_state: str = "SEARCHING"
    provisional_candidate: bool = False
    auto_add: dict[str, Any] = field(default_factory=dict)
    generation: int = 0
    frame_id: int | None = None
    continuous_state: str = "EMPTY"
    card_present: bool = False
    result_current: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = list(self.candidates)
        payload["pipeline_stages"] = list(self.pipeline_stages)
        payload["candidate_count"] = len(self.candidates)
        return payload


class RecognitionStateStore:
    """Single writer that publishes immutable snapshots."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vision: dict[str, Any] = {}
        self._recognition: dict[str, Any] = {}
        self._catalog: dict[str, Any] = {}
        self._revision = 0
        self._generation = 0
        self._continuous_state = "EMPTY"
        self._frame_id: int | None = None
        self._card_present = False
        self._snapshot = self._compose()

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _score(cls, item: dict[str, Any]) -> float:
        for key in ("fused_score", "score", "confidence"):
            if item.get(key) is not None:
                return cls._number(item.get(key))
        return 0.0

    @staticmethod
    def _candidate_key(item: dict[str, Any]) -> str:
        return "|".join(
            str(value or "").strip().lower()
            for value in (
                item.get("id"),
                item.get("collector_number"),
                item.get("name") or item.get("printed_name"),
                item.get("language_code") or item.get("language"),
                item.get("set_id") or item.get("set_name"),
            )
        )

    @staticmethod
    def _image(item: dict[str, Any]) -> str | None:
        value = (
            item.get("reference_image_url")
            or item.get("image_url")
            or item.get("card_image_url")
            or item.get("image")
        )
        if not value:
            return None
        value = str(value).strip().rstrip("/")
        if value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return value
        return f"{value}/high.webp"

    @staticmethod
    def _state_id(
        primary: dict[str, Any] | None,
        fingerprint: str | None,
        revision: int,
    ) -> str:
        identity = {
            "candidate_id": (primary or {}).get("id"),
            "number": (primary or {}).get("collector_number"),
            "name": (primary or {}).get("name")
            or (primary or {}).get("printed_name"),
            "language": (primary or {}).get("language")
            or (primary or {}).get("language_code"),
            "fingerprint": fingerprint,
            "revision": revision,
        }
        encoded = json.dumps(
            identity,
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha1(encoded).hexdigest()[:16]

    def refresh(
        self,
        *,
        vision: dict[str, Any] | None = None,
        recognition: dict[str, Any] | None = None,
        catalog: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if vision is not None:
                self._vision = copy.deepcopy(vision)
            if recognition is not None:
                self._recognition = copy.deepcopy(recognition)
            if catalog is not None:
                self._catalog = copy.deepcopy(catalog)
            self._revision += 1
            self._snapshot = self._compose()
            return self._snapshot.to_dict()

    def update_vision(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self.refresh(vision=payload or {})

    def update_recognition(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self.refresh(recognition=payload or {})

    def update_catalog(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        return self.refresh(catalog=payload or {})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot.to_dict()

    def set_continuous_state(
        self,
        state: str,
        *,
        generation: int,
        frame_id: int | None = None,
        card_present: bool = False,
        clear_result: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._continuous_state = str(state)
            self._generation = int(generation)
            self._frame_id = frame_id
            self._card_present = bool(card_present)
            if clear_result:
                self._recognition = {}
            self._revision += 1
            self._snapshot = self._compose()
            return self._snapshot.to_dict()

    def clear(
        self,
        *,
        generation: int,
        state: str = "EMPTY",
        frame_id: int | None = None,
    ) -> dict[str, Any]:
        return self.set_continuous_state(
            state,
            generation=generation,
            frame_id=frame_id,
            card_present=False,
            clear_result=True,
        )

    def _compose(self) -> RecognitionSnapshot:
        vision = copy.deepcopy(self._vision)
        raw = copy.deepcopy(self._recognition)
        catalog = copy.deepcopy(self._catalog)
        pool: list[dict[str, Any]] = []

        for item in raw.get("candidates") or raw.get("matches") or []:
            if isinstance(item, dict):
                pool.append(copy.deepcopy(item))

        catalog_items = list(catalog.get("candidates") or [])
        if isinstance(catalog.get("match"), dict):
            catalog_items.insert(0, catalog["match"])

        for item in catalog_items:
            if not isinstance(item, dict):
                continue
            card = copy.deepcopy(item)
            card.setdefault("source", "live_catalog")
            card.setdefault("score", 0.50)
            card.setdefault("fused_score", card.get("score", 0.50))
            image = self._image(card)
            if image:
                card["reference_image_url"] = image
            pool.append(card)

        printed = raw.get("name_candidate")
        number = raw.get("collector_number") or raw.get("ocr_collector_number")
        if printed or number:
            provisional_score = max(
                0.40,
                self._number(raw.get("overall_confidence")),
                self._number(raw.get("confidence")),
                self._number((raw.get("artwork_index") or {}).get("top_score")),
            )
            pool.append({
                "id": f"ocr:{number or printed}",
                "name": printed or f"Card {number}",
                "printed_name": printed or f"Card {number}",
                "collector_number": number,
                "language": raw.get("language") or "Unknown",
                "source": "ocr_provisional",
                "score": provisional_score,
                "fused_score": provisional_score,
                "reference_image_url": "/api/camera/crop.jpg",
                "provisional": True,
            })

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in sorted(pool, key=self._score, reverse=True):
            key = self._candidate_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(item)

        primary = candidates[0] if candidates else None
        english_name = None

        if primary:
            english_name = (
                primary.get("english_name")
                or primary.get("canonical_name")
                or primary.get("name_en")
            )
            wanted_number = str(primary.get("collector_number") or "")
            if not english_name and wanted_number:
                for item in catalog_items:
                    if not isinstance(item, dict):
                        continue
                    is_english = (
                        item.get("language_code") == "en"
                        or str(item.get("language") or "").lower() == "english"
                    )
                    if (
                        is_english
                        and str(item.get("collector_number") or "")
                        == wanted_number
                    ):
                        english_name = item.get("name")
                        break

            if english_name:
                primary = copy.deepcopy(primary)
                primary["english_name"] = english_name
                candidates[0] = primary

        stages = tuple(copy.deepcopy(raw.get("pipeline_stages") or []))
        done = {
            stage.get("key")
            for stage in stages
            if isinstance(stage, dict) and stage.get("state") == "done"
        }

        overall = self._number(raw.get("overall_confidence"))
        has_reference = bool(
            raw.get("has_reference_evidence")
            or (
                primary
                and not primary.get("provisional")
                and self._image(primary)
            )
        )
        verified = bool(raw.get("recognition_locked") and has_reference)
        production_ready = bool(
            primary
            and has_reference
            and (verified or "verify" in done or overall >= 0.55)
        )
        test_ready = bool(primary and overall >= 0.40)

        phase = "SEARCHING"
        if vision.get("visible") or vision.get("stable"):
            phase = "DETECTED"
        if "ocr" in done:
            phase = "OCR COMPLETE"
        if "fingerprint" in done or "artwork" in done:
            phase = "ARTWORK MATCH"
        if primary:
            phase = "CANDIDATE FOUND"
        if has_reference:
            phase = "REFERENCE FOUND"
        if verified:
            phase = "VERIFIED"

        fingerprint = raw.get("artwork_fingerprint")
        state_id = self._state_id(primary, fingerprint, self._revision)

        return RecognitionSnapshot(
            revision=self._revision,
            state_id=state_id,
            updated_at=time.time(),
            phase=phase,
            vision=vision,
            raw_recognition=raw,
            catalog=catalog,
            candidates=tuple(copy.deepcopy(candidates[:10])),
            primary_candidate=copy.deepcopy(primary),
            name_candidate=(
                (primary or {}).get("printed_name")
                or (primary or {}).get("name")
                or printed
            ),
            english_name=english_name,
            collector_number=(primary or {}).get("collector_number") or number,
            language=(primary or {}).get("language") or raw.get("language"),
            overall_confidence=overall,
            confidence=self._number(raw.get("confidence")),
            artwork_fingerprint=fingerprint,
            artwork_index=copy.deepcopy(raw.get("artwork_index") or {}),
            database_match=copy.deepcopy(raw.get("database_match")),
            pipeline_stages=stages,
            stage_timings=copy.deepcopy(raw.get("stage_timings") or {}),
            recognition_locked=verified,
            has_reference_evidence=has_reference,
            verification_state=(
                "VERIFIED"
                if verified
                else "REFERENCE NEEDED"
                if primary and not has_reference
                else raw.get("verification_state") or "SEARCHING"
            ),
            provisional_candidate=bool(primary and primary.get("provisional")),
            auto_add={
                "production_ready": production_ready,
                "test_ready": test_ready,
                "candidate_available": bool(primary),
                "reference_available": has_reference,
            },
            generation=self._generation,
            frame_id=self._frame_id,
            continuous_state=self._continuous_state,
            card_present=self._card_present,
            result_current=bool(
                primary
                and int(raw.get("generation") or 0) == self._generation
            ),
        )
