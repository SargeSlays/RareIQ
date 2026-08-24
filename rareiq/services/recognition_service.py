from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from rapidocr import RapidOCR

from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.set_catalog_service import SetCatalogService
from rareiq.services.live_catalog_service import LiveCatalogService


PRINTED_IDENTIFIER_RE = re.compile(
    r"\b(?:[A-Z]{1,4}\s*)?(\d{1,4})\s*[/／]\s*(\d{1,4})\b",
    re.IGNORECASE,
)
COLLECTOR_NUMBER_RE = re.compile(r"^\d{1,3}/\d{2,3}$")
COLLECTOR_CANDIDATE_RE = re.compile(r"^\d{1,3}/\d{2,4}$")
PRINTED_CARD_CODE_RE = re.compile(r"^\d{4}/\d{2}$")
OCR_IDENTIFIER_FRAGMENT_RE = re.compile(
    r"(?<![A-Z0-9])([0-9OQILSBZG|]{1,4})/([0-9OQILSBZG|]{1,4})(?![A-Z0-9])",
    re.IGNORECASE,
)
EMBEDDED_COLLECTOR_FRAGMENT_RE = re.compile(
    r"(?<![0-9])(\d{1,3})/(\d{2,4})(?![0-9])"
)
OCR_IDENTIFIER_DIGIT_MAP = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "q": "0",
    "I": "1", "i": "1", "L": "1", "l": "1", "|": "1",
    "S": "5", "s": "5", "B": "8", "b": "8",
    "Z": "2", "z": "2", "G": "6", "g": "6",
})


class RecognitionService:
    FAST_PATH_VISUAL_SCORE = 0.97
    FAST_PATH_ARTWORK_SCORE = 0.96
    FAST_PATH_MIN_MARGIN = 0.04

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        database_path: Path | None = None,
        temporal_path: Path | None = None,
    ) -> None:
        self._shutdown_event = threading.Event()
        self.emit = emit
        self._lock = threading.Lock()
        self._engine: RapidOCR | None = None
        self._engine_lock = threading.Lock()
        self._ocr_inference_lock = threading.Lock()
        self._ocr_runtime = {
            "warmed": False,
            "warming": False,
            "warmup_ms": None,
            "warmup_error": None,
            "footer_recognition_only_attempts": 0,
            "footer_recognition_only_hits": 0,
            "footer_detector_fallbacks": 0,
            "footer_recognition_only_hit_rate": 0.0,
            "last_footer_mode": None,
        }
        self._reference_identifier_cache_path = (
            temporal_path.with_name("reference_identifier_cache.json")
            if temporal_path else None
        )
        self._reference_identifier_cache: dict[str, str | None] = (
            self._load_reference_identifier_cache()
        )
        self._reference_identifier_cache_lock = threading.Lock()
        self._recent_family_hints: list[dict[str, Any]] = []
        self._recent_family_hints_lock = threading.Lock()
        self._batch_artwork_hints: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self._batch_artwork_hints_lock = threading.Lock()
        self._footer_observations: dict[tuple[int, str], dict[str, int]] = {}
        self._footer_observations_lock = threading.Lock()
        self._busy = False
        self._last_started_at = 0.0
        self._last_full_pass_at = 0.0
        self._fast_interval = 0.18
        self._full_interval = 4.0
        self._current_generation = 0
        self._latency_samples: list[dict[str, Any]] = []
        self._temporal_path = temporal_path
        self._temporal_history = self._load_temporal_history() if temporal_path else None

        if database_path is None:
            database_path = (
                Path(__file__).resolve().parents[1]
                / "data"
                / "cards_poc.json"
            )

        self._cards = self._load_cards(database_path)
        self.artwork_index = ArtworkIndexService()
        self.set_catalog = SetCatalogService()
        self.live_catalog = LiveCatalogService(self.artwork_index)
        self.global_visual_index: Any | None = None
        self.vision_optimizer: Any | None = None
        self.candidate_ranker: Any | None = None
        self.recognition_diagnostics: Any | None = None
        self.catalog_resolver: Callable[
            [dict[str, Any]], dict[str, Any] | None
        ] | None = None
        self.prediction_prefetcher: Callable[[list[dict[str, Any]]], int] | None = None
        self.exact_reference_resolver: Callable[[np.ndarray, str], dict[str, Any] | None] | None = None
        active = self.set_catalog.active_set()
        if active:
            self.artwork_index.set_active_filter(
                active.get("name"),
                active.get("language"),
                active.get("set_id") or active.get("id"),
            )

        self._status: dict[str, Any] = {
            "enabled": True,
            "busy": False,
            "mode": "ARTEMIS_INDEX",
            "last_latency_ms": None,
            "stage_timings": {},
            "recognition_path": None,
            "latency_summary": {},
            "raw_text": [],
            "name_candidate": None,
            "hp_candidate": None,
            "ocr_collector_number": None,
            "ocr_printed_code": None,
            "collector_number": None,
            "language": None,
            "confidence": 0.0,
            "text_detected": False,
            "database_match": None,
            "database_confidence": 0.0,
            "correction_applied": False,
            "overall_confidence": 0.0,
            "recognition_locked": False,
                "verification_state": "ERROR",
                "pipeline_stages": [],
            "lock_reason": None,
            "candidates": [],
            "candidate_count": 0,
            "artwork_fingerprint": None,
            "active_set": self.set_catalog.status(),
            "live_catalog": self.live_catalog.status(),
            "artwork_index": {
                "status": self.artwork_index.status(),
                "search_ms": 0.0,
                "top_score": 0.0,
                "matches": [],
            },
            "regions": {
                "top": False,
                "bottom": False,
                "artwork": False,
                "full": False,
            },
            "error": None,
            "pipeline_stages": [],
            "verification_state": "SEARCHING",
            "updated_at": None,
        }

    @staticmethod
    def _load_cards(path: Path) -> list[dict[str, Any]]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []


    def shutdown(self) -> None:
        """Signal recognition workers to stop and wait briefly."""
        self._shutdown_event.set()
        worker = getattr(self, "_worker", None)
        if worker and worker.is_alive():
            worker.join(timeout=2.0)



    def set_intelligence_services(
        self,
        vision_optimizer: Any,
        candidate_ranker: Any,
        recognition_diagnostics: Any,
    ) -> None:
        self.vision_optimizer = vision_optimizer
        self.candidate_ranker = candidate_ranker
        self.recognition_diagnostics = recognition_diagnostics

    def set_global_visual_index(self, visual_index: Any) -> None:
        self.global_visual_index = visual_index

    def set_exact_reference_resolver(
        self,
        resolver: Callable[[np.ndarray, str], dict[str, Any] | None] | None,
    ) -> None:
        self.exact_reference_resolver = resolver

    def set_catalog_resolver(
        self,
        resolver: Callable[[dict[str, Any]], dict[str, Any] | None] | None,
    ) -> None:
        self.catalog_resolver = resolver

    def set_prediction_prefetcher(
        self, prefetcher: Callable[[list[dict[str, Any]]], int] | None,
    ) -> None:
        self.prediction_prefetcher = prefetcher

    def isolated_copy(self, emit: Callable[[dict[str, Any]], None]) -> "RecognitionService":
        """Create an isolated worker that shares read-only recognition indexes."""
        service = RecognitionService(emit)
        service._cards = self._cards
        service._reference_identifier_cache = self._reference_identifier_cache
        service._reference_identifier_cache_lock = self._reference_identifier_cache_lock
        service._recent_family_hints = self._recent_family_hints
        service._recent_family_hints_lock = self._recent_family_hints_lock
        service._batch_artwork_hints = self._batch_artwork_hints
        service._batch_artwork_hints_lock = self._batch_artwork_hints_lock
        service._footer_observations = self._footer_observations
        service._footer_observations_lock = self._footer_observations_lock
        service.artwork_index = self.artwork_index
        service.set_catalog = self.set_catalog
        service.live_catalog = self.live_catalog
        service.global_visual_index = self.global_visual_index
        service.vision_optimizer = self.vision_optimizer
        service.candidate_ranker = self.candidate_ranker
        service.recognition_diagnostics = self.recognition_diagnostics
        service.catalog_resolver = self.catalog_resolver
        service.prediction_prefetcher = self.prediction_prefetcher
        return service

    def seed_batch_artwork_hints(
        self,
        generation: int,
        frame_id: int,
        candidates: list[dict[str, Any]],
    ) -> None:
        """Supply catalog candidates selected by the multi-card batch traversal."""
        key = (int(generation), int(frame_id))
        with self._batch_artwork_hints_lock:
            self._batch_artwork_hints[key] = [dict(item) for item in candidates]
            stale = [item for item in self._batch_artwork_hints if item[0] < int(generation)]
            for item in stale:
                self._batch_artwork_hints.pop(item, None)

    def _take_batch_artwork_hints(
        self,
        generation: int,
        frame_id: int | None,
    ) -> list[dict[str, Any]]:
        if frame_id is None:
            return []
        with self._batch_artwork_hints_lock:
            return self._batch_artwork_hints.pop(
                (int(generation), int(frame_id)), []
            )

    @staticmethod
    def _temporal_version_key(card: dict[str, Any] | None) -> str:
        card = card or {}
        parts = (
            str(card.get("set_id") or "").upper(),
            str(card.get("collector_number") or ""),
            str(card.get("printed_code") or ""),
        )
        return "|".join(parts) if any(parts) else ""

    @staticmethod
    def _temporal_fingerprint_distance(left: str, right: str) -> int | None:
        """Return perceptual-hash distance when both values are comparable."""
        left = str(left or "").strip().lower()
        right = str(right or "").strip().lower()
        if not left or not right:
            return None
        if left == right:
            return 0
        if len(left) != 16 or len(right) != 16:
            return None
        try:
            return (int(left, 16) ^ int(right, 16)).bit_count()
        except ValueError:
            return None

    @classmethod
    def _temporal_fingerprint_agrees(cls, left: str, right: str) -> tuple[bool, int | None]:
        distance = cls._temporal_fingerprint_distance(left, right)
        return distance is not None and distance <= 6, distance

    @staticmethod
    def _temporal_version_conflicts(current: dict[str, Any], expected: dict[str, Any]) -> bool:
        for field in ("set_id", "collector_number", "printed_code"):
            current_value = str(current.get(field) or "").strip().casefold()
            expected_value = str(expected.get(field) or "").strip().casefold()
            if current_value and expected_value and current_value != expected_value:
                return True
        return False

    def _load_temporal_history(self) -> dict[str, Any]:
        try:
            payload = json.loads(Path(self._temporal_path).read_text(encoding="utf-8"))
            return payload if payload.get("version") == 1 and payload.get("card") else {}
        except Exception:
            return {}

    def _persist_temporal_history(self) -> None:
        if not self._temporal_path or not self._temporal_history:
            return
        try:
            path = Path(self._temporal_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps({
                "version": 1,
                **self._temporal_history,
            }, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        except Exception:
            return

    def _load_reference_identifier_cache(self) -> dict[str, str | None]:
        if self._reference_identifier_cache_path is None:
            return {}
        try:
            payload = json.loads(
                self._reference_identifier_cache_path.read_text(encoding="utf-8")
            )
            entries = payload.get("entries") if isinstance(payload, dict) else None
            if payload.get("version") != 1 or not isinstance(entries, dict):
                return {}
            return {
                str(path): str(code) if code else None
                for path, code in entries.items()
            }
        except Exception:
            return {}

    def _persist_reference_identifier_cache(self) -> None:
        path = self._reference_identifier_cache_path
        if path is None:
            return
        try:
            with self._reference_identifier_cache_lock:
                entries = dict(self._reference_identifier_cache)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps({
                "version": 1,
                "updated_at": time.time(),
                "entries": entries,
            }, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        except Exception:
            return

    def _apply_single_temporal_confirmation(self, payload: dict[str, Any]) -> None:
        """Confirm repeated exact single-card evidence without trusting position."""
        if self._temporal_path is None:
            return
        card = payload.get("database_match") or next(iter(payload.get("candidates") or []), None)
        fingerprint = str(payload.get("artwork_fingerprint") or "")
        history = self._temporal_history or {}
        confirmations = int(history.get("confirmations") or 0)
        history_fingerprint = str(history.get("fingerprint") or "")
        fingerprint_agrees, fingerprint_distance = self._temporal_fingerprint_agrees(
            fingerprint, history_fingerprint
        )
        payload["temporal_confirmation_progress"] = min(2, confirmations)
        payload["temporal_confirmation_required"] = 2
        if fingerprint_distance is not None:
            payload["temporal_fingerprint_distance"] = fingerprint_distance
        if payload.get("recognition_locked") and self._temporal_version_key(card) and fingerprint:
            same_version = self._temporal_version_key(card) == self._temporal_version_key(history.get("card"))
            confirmations = min(8, confirmations + 1) if same_version and fingerprint_agrees else 1
            self._temporal_history = {
                "card": dict(card),
                "fingerprint": fingerprint,
                "confirmations": confirmations,
                "updated_at": time.time(),
            }
            payload["temporal_confirmation_progress"] = min(2, confirmations)
            payload["temporal_confirmation"] = confirmations >= 2
            payload["temporal_confirmation_count"] = confirmations
            self._persist_temporal_history()
            return
        if confirmations < 2 or not fingerprint or not fingerprint_agrees:
            return
        expected = history.get("card") or {}
        if self._temporal_version_conflicts(card or {}, expected):
            return
        candidate_name = str((card or {}).get("canonical_name") or (card or {}).get("english_name") or "").casefold()
        expected_name = str(expected.get("canonical_name") or expected.get("english_name") or "").casefold()
        if candidate_name and expected_name and candidate_name != expected_name:
            return
        payload.update({
            "database_match": dict(expected),
            "recognition_locked": True,
            "verification_state": "VERIFIED",
            "temporal_confirmation": True,
            "temporal_confirmation_count": confirmations,
            "temporal_confirmation_progress": 2,
            "temporal_identity_restored": True,
            "lock_reason": "temporally confirmed exact single-card identity",
        })


    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._status)
        payload["ocr_runtime"] = dict(self._ocr_runtime)
        return payload

    def update_exact_reference_follow_up(self, state: str) -> None:
        """Publish scheduler state without replacing recognition evidence."""
        with self._lock:
            diagnostics = dict(self._status.get("exact_reference_diagnostics") or {})
            if not diagnostics:
                return
            diagnostics["follow_up_state"] = str(state)
            self._status["exact_reference_diagnostics"] = diagnostics

    def _publish_visual_interim(
        self,
        *,
        generation: int,
        frame_id: int | None,
        source: str,
        candidates: list[dict[str, Any]],
        fingerprint: str | None,
        resolution: dict[str, Any],
        started: float,
        stage_timings: dict[str, Any],
    ) -> None:
        """Publish usable visual evidence while OCR enrichment continues."""
        if generation != self._current_generation:
            return
        if self.set_catalog.status().get("locked"):
            candidates = [
                candidate for candidate in candidates
                if self.set_catalog.candidate_allowed(candidate)
            ]
        diagnostics = dict(resolution.get("diagnostics") or {})
        presentable = next(
            (
                item for item in candidates
                if item
                and not item.get("retrieval_only")
                and (
                    str(item.get("source") or "").lower()
                    not in {"global_visual_index", "ocr_provisional", "live_catalog"}
                    or (
                        str(item.get("source") or "").lower() == "live_catalog"
                        and item.get("set_locked_catalog_lookup") is True
                    )
                )
                and (
                    item.get("verification_strong")
                    or item.get("printed_code_match")
                    or item.get("source") == "pokipair"
                    or item.get("set_locked_catalog_lookup") is True
                )
            ),
            None,
        )
        payload = {
            "enabled": True,
            "busy": True,
            "mode": "ARTEMIS_INDEX",
            "recognition_path": "visual-interim",
            "background_enrichment": True,
            "last_latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "stage_timings": {
                **stage_timings,
                "total_ms": round((time.perf_counter() - started) * 1000, 1),
                "path": "visual-interim",
                "skipped_stages": [],
            },
            "raw_text": [],
            "name_candidate": (
                presentable.get("canonical_name")
                or presentable.get("english_name")
                or presentable.get("name")
            ) if presentable else None,
            "collector_number": presentable.get("collector_number") if presentable else None,
            "language": presentable.get("language") if presentable else None,
            "confidence": float(presentable.get("score", 0.0)) if presentable else 0.0,
            "overall_confidence": float(presentable.get("score", 0.0)) if presentable else 0.0,
            "recognition_locked": False,
            "has_reference_evidence": bool(presentable),
            "verification_state": "SEARCHING",
            "candidates": [dict(item) for item in candidates[:10]],
            "candidate_count": min(10, len(candidates)),
            "artwork_fingerprint": fingerprint,
            "exact_reference_diagnostics": diagnostics,
            "generation": generation,
            "frame_id": frame_id,
            "capture_source": source,
            "error": None,
            "updated_at": time.time(),
        }
        with self._lock:
            if generation != self._current_generation:
                return
            self._status.update(payload)
        self.emit({"type": "recognition_update", "payload": payload})

    @staticmethod
    def _candidate_identity_keys(candidate: dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        for field in (
            "id", "identity_override_key", "collector_number", "printed_code",
            "image_path", "reference_image", "local_image",
        ):
            value = str(candidate.get(field) or "").strip().casefold()
            if value:
                keys.add(f"{field}:{value}")
        set_id = str(candidate.get("set_id") or "").strip().casefold()
        number = str(candidate.get("collector_number") or "").strip().casefold()
        if set_id and number:
            keys.add(f"set-number:{set_id}:{number}")
        for field in ("english_name", "canonical_name", "pokemon_name", "pricing_lookup_name"):
            value = str(candidate.get(field) or "").strip().casefold()
            if value:
                keys.add(f"canonical-name:{value}")
        return keys

    @classmethod
    def _candidate_version_keys(cls, candidate: dict[str, Any]) -> set[str]:
        """Return keys that identify one printing, not merely one character."""
        return {
            key for key in cls._candidate_identity_keys(candidate)
            if not key.startswith("canonical-name:")
            and not key.startswith("collector_number:")
        }

    @staticmethod
    def _candidate_family_name(candidate: dict[str, Any]) -> str:
        family = str(
            candidate.get("canonical_name")
            or candidate.get("english_name")
            or candidate.get("pokemon_name")
            or candidate.get("name")
            or ""
        ).strip().casefold()
        return "" if family in {
            "visual match", "unknown card", "database match", "candidate"
        } else family

    @classmethod
    def _variant_family_ambiguous(
        cls,
        candidates: list[dict[str, Any]],
        *,
        limit: int = 8,
    ) -> bool:
        """True when strong visual candidates represent multiple printings.

        Shared-art variants may agree across visual indexes while still pointing
        at the wrong collector number.  Artwork can identify the family quickly,
        but it cannot certify one printing without footer/marker evidence.
        """
        if not candidates:
            return False
        anchor = next(
            (
                candidate for candidate in candidates[: max(2, int(limit))]
                if candidate.get("verification_strong")
                and not candidate.get("retrieval_only")
                and cls._candidate_family_name(candidate)
            ),
            candidates[0],
        )
        family = cls._candidate_family_name(anchor)
        if not family:
            return False
        versions: set[tuple[str, str]] = set()
        for candidate in candidates[: max(2, int(limit))]:
            if cls._candidate_family_name(candidate) != family:
                continue
            set_id = str(candidate.get("set_id") or candidate.get("set_name") or "").strip().casefold()
            identifier = str(
                candidate.get("printed_code")
                or candidate.get("collector_number")
                or candidate.get("id")
                or ""
            ).strip().casefold()
            if identifier:
                versions.add((set_id, identifier))
            if len(versions) >= 2:
                return True
        return False

    @staticmethod
    def _variant_fast_path_is_ocr_safe(evidence: dict[str, Any] | None) -> bool:
        """Artwork continuity cannot certify one shared-art printing."""
        return bool(
            evidence
            and evidence.get("locked_set_number_exact") is True
            and evidence.get("footer_identifier")
        )

    @classmethod
    def _visual_preflight_can_skip_footer(
        cls,
        evidence: dict[str, Any] | None,
        direct_candidates: list[dict[str, Any]],
        indexed_family: list[dict[str, Any]],
    ) -> bool:
        """Allow an OCR bypass only for decisive, unique-art consensus."""
        return bool(
            evidence
            and not cls._variant_family_ambiguous(direct_candidates)
            and not cls._variant_family_ambiguous(indexed_family)
        )

    @classmethod
    def _confirm_locked_set_number_fast_path(
        cls,
        evidence: dict[str, Any] | None,
        catalog_match: dict[str, Any] | None,
        footer_identifier: str | None,
    ) -> dict[str, Any] | None:
        """Mark decisive visual evidence safe when set + number already agree.

        This does not create fast-path evidence. It only upgrades an existing
        decisive cross-index visual match after the locked catalog resolved the
        observed footer to the same exact printing.
        """
        if not evidence or not catalog_match or not footer_identifier:
            return evidence
        if catalog_match.get("set_locked_catalog_lookup") is not True:
            return evidence
        version_key = str(evidence.get("version_key") or "").casefold()
        catalog_versions = cls._candidate_version_keys(catalog_match)
        if version_key not in catalog_versions:
            return evidence
        confirmed = dict(evidence)
        confirmed.update({
            "reason": "locked_set_number_visual_consensus",
            "locked_set_number_exact": True,
            "footer_identifier": str(footer_identifier),
        })
        return confirmed

    def _indexed_variant_family_ambiguous(
        self,
        candidates: list[dict[str, Any]],
    ) -> bool:
        anchor = next((
            item for item in candidates
            if item.get("verification_strong")
            and not item.get("retrieval_only")
            and self._candidate_family_name(item)
        ), None)
        if anchor is None:
            return False
        return self._variant_family_ambiguous(
            self.artwork_index.family_records(anchor, limit=8)
        )

    @staticmethod
    def _collector_retry_needed(
        *,
        artwork_candidates: list[dict[str, Any]],
        fast_path_evidence: dict[str, Any] | None,
        strong_printed_identifier_match: bool,
    ) -> bool:
        """Retry missing or conflicting footer evidence exactly once upstream."""
        return bool(
            artwork_candidates
            and not fast_path_evidence
            and not strong_printed_identifier_match
        )

    @classmethod
    def _fast_path_evidence(
        cls,
        global_candidates: list[dict[str, Any]],
        artwork_candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return decisive cross-index evidence, or None for the full path."""
        if not global_candidates or not artwork_candidates:
            return None
        global_top, artwork_top = global_candidates[0], artwork_candidates[0]
        global_score = float(global_top.get("score", 0.0) or 0.0)
        artwork_score = float(artwork_top.get("score", 0.0) or 0.0)
        global_runner_up = (
            float(global_candidates[1].get("score", 0.0) or 0.0)
            if len(global_candidates) > 1 else 0.0
        )
        artwork_runner_up = (
            float(artwork_candidates[1].get("score", 0.0) or 0.0)
            if len(artwork_candidates) > 1 else 0.0
        )
        version_agreement = (
            cls._candidate_version_keys(global_top)
            & cls._candidate_version_keys(artwork_top)
        )
        agrees = bool(version_agreement)
        has_reference = bool(
            artwork_top.get("verification_strong")
            and (artwork_top.get("image_path") or artwork_top.get("reference_image")
                 or artwork_top.get("local_image"))
        )
        if not (
            agrees and has_reference
            and global_score >= cls.FAST_PATH_VISUAL_SCORE
            and artwork_score >= cls.FAST_PATH_ARTWORK_SCORE
            and global_score - global_runner_up >= cls.FAST_PATH_MIN_MARGIN
            and artwork_score - artwork_runner_up >= cls.FAST_PATH_MIN_MARGIN
        ):
            return None
        return {
            "reason": "cross_index_decisive_match",
            "version_key": sorted(version_agreement)[0],
            "global_score": round(global_score, 4),
            "artwork_score": round(artwork_score, 4),
            "global_margin": round(global_score - global_runner_up, 4),
            "artwork_margin": round(artwork_score - artwork_runner_up, 4),
        }

    def _record_latency(
        self,
        path: str,
        total_ms: float,
        capture_to_result_ms: float | None = None,
    ) -> dict[str, Any]:
        self._latency_samples.append({
            "path": path,
            "total_ms": float(total_ms),
            "capture_to_result_ms": (
                float(capture_to_result_ms)
                if capture_to_result_ms is not None else None
            ),
        })
        del self._latency_samples[:-100]
        values = sorted(item["total_ms"] for item in self._latency_samples)
        fast_count = sum(item["path"] == "fast" for item in self._latency_samples)
        capture_values = sorted(
            float(item["capture_to_result_ms"])
            for item in self._latency_samples
            if item.get("capture_to_result_ms") is not None
        )

        def percentile(fraction: float) -> float:
            return round(values[int((len(values) - 1) * fraction)], 1)

        summary = {
            "sample_count": len(values),
            "fast_path_count": fast_count,
            "fast_path_rate": round(fast_count / len(values), 3),
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
        }
        if capture_values:
            capture_percentile = lambda fraction: round(
                capture_values[int((len(capture_values) - 1) * fraction)], 1
            )
            under_one_second = sum(value <= 1000.0 for value in capture_values)
            summary.update({
                "capture_sample_count": len(capture_values),
                "capture_p50_ms": capture_percentile(0.50),
                "capture_p95_ms": capture_percentile(0.95),
                "under_one_second_count": under_one_second,
                "under_one_second_rate": round(
                    under_one_second / len(capture_values), 3
                ),
            })
        return summary

    @staticmethod
    def _early_footer_variant_budget(
        *, locked_to_set: bool, visual_score: float, source: str
    ) -> int:
        """Choose the cheap first OCR probe without weakening fallback verification.

        A locked set plus a useful visual family match makes one footer variant
        sufficient for the first-pass shortlist. Any ambiguity continues through
        the existing full OCR path later in the worker.
        """
        if source == "six-card-grid":
            return 1
        if locked_to_set and float(visual_score or 0.0) >= 0.80:
            return 1
        return 2

    @staticmethod
    def _cached_artwork_fast_path_evidence(
        artwork_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if artwork_result.get("fast_return") == "cached_exact_variant":
            # Quarantined after live cross-card testing demonstrated that
            # adjacent printings can pass the current marker geometry gate.
            return None
        if artwork_result.get("fast_return") != "cached_printed_identity":
            return None
        matches = list(artwork_result.get("matches") or [])
        if len(matches) < 2:
            return None
        printed_codes = {
            str(item.get("printed_code") or "") for item in matches[:2]
        }
        if len(printed_codes) != 1 or not next(iter(printed_codes), ""):
            return None
        if not all(item.get("verification_strong") for item in matches[:2]):
            return None
        best_verification = max(
            float(item.get("verification_score") or 0.0) for item in matches[:2]
        )
        if best_verification < 0.70:
            return None
        return {
            "reason": "cached_printed_identity_geometry_consensus",
            "printed_code": next(iter(printed_codes)),
            "reference_count": 2,
            "best_verification_score": round(best_verification, 4),
        }

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._status["enabled"] = bool(enabled)
        return self.status()

    def invalidate_before(self, generation: int) -> None:
        with self._lock:
            self._current_generation = max(
                self._current_generation,
                int(generation),
            )

    @staticmethod
    def _snapshot_frame_inputs(
        frame: np.ndarray,
        ocr_frame: np.ndarray | None,
        collector_frames: list[np.ndarray] | tuple[np.ndarray, ...] | None,
    ) -> tuple[np.ndarray, np.ndarray | None, tuple[np.ndarray, ...]]:
        """Copy every unique camera array once for asynchronous recognition."""
        snapshots: dict[int, np.ndarray] = {}

        def snapshot(item: np.ndarray | None) -> np.ndarray | None:
            if item is None or not getattr(item, "size", 0):
                return None
            identity = id(item)
            cached = snapshots.get(identity)
            if cached is None:
                cached = item.copy()
                snapshots[identity] = cached
            return cached

        frame_snapshot = snapshot(frame)
        if frame_snapshot is None:  # Defensive; submit_frame rejects this first.
            raise ValueError("frame must contain image data")
        ocr_snapshot = snapshot(ocr_frame)
        collector_snapshots = tuple(
            copied
            for item in (collector_frames or ())
            if (copied := snapshot(item)) is not None
        )
        return frame_snapshot, ocr_snapshot, collector_snapshots

    def submit_frame(
        self,
        frame: np.ndarray | None,
        *,
        generation: int = 0,
        frame_id: int | None = None,
        source: str = "auto",
        captured_at: float | None = None,
        ocr_frame: np.ndarray | None = None,
        collector_frames: list[np.ndarray] | tuple[np.ndarray, ...] | None = None,
    ) -> str:
        if frame is None:
            return "rejected_no_frame"

        with self._lock:
            now = time.time()
            if (
                not bool(self._status["enabled"])
            ):
                return "rejected_disabled"
            if self._busy:
                return "busy_queued"
            if now - self._last_started_at < self._fast_interval:
                return "rejected_rate_limit"

            self._busy = True
            self._current_generation = max(
                self._current_generation,
                int(generation),
            )
            self._status["busy"] = True
            self._status["generation"] = int(generation)
            self._status["frame_id"] = frame_id
            self._status["capture_source"] = source
            self._last_started_at = now

        # The coordinator commonly supplies the same rectified crop as the
        # primary, OCR, and first collector frame. Snapshot each unique array
        # once so the asynchronous worker is isolated from camera-buffer
        # mutation without paying for duplicate 4K memory copies.
        frame_snapshot, ocr_snapshot, collector_snapshots = (
            self._snapshot_frame_inputs(frame, ocr_frame, collector_frames)
        )

        threading.Thread(
            target=self._recognize_worker,
            args=(
                frame_snapshot,
                int(generation),
                frame_id,
                source,
                float(captured_at or now),
                ocr_snapshot,
                collector_snapshots,
            ),
            daemon=True,
        ).start()
        return "accepted"

    def _engine_instance(self) -> RapidOCR:
        if self._engine is None:
            with self._engine_lock:
                if self._engine is None:
                    self._engine = RapidOCR()
        return self._engine

    def _infer_ocr(self, image: np.ndarray) -> Any:
        with self._ocr_inference_lock:
            return self._engine_instance()(image)

    def _infer_ocr_recognition_only(self, image: np.ndarray) -> Any:
        """Recognize one known text line without running text detection."""
        with self._ocr_inference_lock:
            return self._engine_instance()(
                image,
                use_det=False,
                use_cls=False,
                use_rec=True,
            )

    def warm_ocr(self) -> dict[str, Any]:
        """Load OCR models and run one representative footer inference."""
        if self._ocr_runtime["warmed"] or self._ocr_runtime["warming"]:
            return dict(self._ocr_runtime)
        self._ocr_runtime.update({"warming": True, "warmup_error": None})
        started = time.perf_counter()
        try:
            canvas = np.full((128, 480, 3), 245, dtype=np.uint8)
            cv2.putText(
                canvas, "PBL EN 013/084", (14, 82),
                cv2.FONT_HERSHEY_SIMPLEX, 1.15, (20, 20, 20), 2,
                cv2.LINE_AA,
            )
            self._infer_ocr(canvas)
            self._ocr_runtime["warmed"] = True
        except Exception as exc:
            self._ocr_runtime["warmup_error"] = str(exc)
        finally:
            self._ocr_runtime["warming"] = False
            self._ocr_runtime["warmup_ms"] = round(
                (time.perf_counter() - started) * 1000, 1
            )
        return dict(self._ocr_runtime)

    def _trusted_recent_family_hints(self) -> list[dict[str, Any]]:
        with self._recent_family_hints_lock:
            return [dict(item) for item in self._recent_family_hints]

    def _temporal_family_hints(self) -> list[dict[str, Any]]:
        history = self._temporal_history or {}
        if int(history.get("confirmations") or 0) < 2:
            return []
        return self.artwork_index.family_records(history.get("card"), limit=12)

    def _temporal_shortlist_evidence(
        self,
        artwork_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        history = self._temporal_history or {}
        if int(history.get("confirmations") or 0) < 2:
            return None
        fingerprint = str(
            artwork_result.get("continuity_fingerprint")
            or artwork_result.get("query_fingerprint")
            or ""
        )
        agrees, distance = self._temporal_fingerprint_agrees(
            fingerprint,
            str(history.get("fingerprint") or ""),
        )
        if not agrees:
            return None
        expected = history.get("card") or {}
        expected_name = self._candidate_family_name(expected)
        matching = [
            item for item in (artwork_result.get("matches") or [])
            if item.get("verification_strong")
            and self._candidate_family_name(item) == expected_name
        ]
        if not expected_name or not matching:
            return None
        return {
            "reason": "temporal_fingerprint_continuity",
            "fingerprint_distance": distance,
            "family": expected_name,
            "reference_count": len(matching),
        }

    def _remember_trusted_family(self, candidates: list[dict[str, Any]]) -> None:
        strong = [
            dict(item) for item in candidates
            if item.get("verification_strong")
            and (item.get("canonical_name") or item.get("english_name"))
            and (item.get("image_path") or item.get("reference_image"))
        ]
        if len(strong) < 2:
            return
        names: dict[str, list[dict[str, Any]]] = {}
        for item in strong:
            name = str(item.get("canonical_name") or item.get("english_name")).strip().casefold()
            names.setdefault(name, []).append(item)
        family = max(names.values(), key=len)
        if len(family) < 2:
            return
        with self._recent_family_hints_lock:
            self._recent_family_hints[:] = family[:12]

    @staticmethod
    def _card_roi(frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        roi_width = int(width * 0.48)
        roi_height = int(height * 0.82)
        x1 = max(0, (width - roi_width) // 2)
        y1 = max(0, (height - roi_height) // 2)
        return frame[y1:y1 + roi_height, x1:x1 + roi_width]

    @staticmethod
    def _is_rectified_card(frame: np.ndarray) -> bool:
        """Return whether Vision already supplied a normalized portrait card."""
        if frame is None or frame.ndim < 2:
            return False
        height, width = frame.shape[:2]
        if width < 400 or height < 560 or height <= width:
            return False
        aspect_ratio = width / float(height)
        return 0.66 <= aspect_ratio <= 0.78

    @classmethod
    def _prepare_card(cls, frame: np.ndarray) -> np.ndarray:
        if cls._is_rectified_card(frame):
            return frame
        return cls._card_roi(frame)

    @staticmethod
    def _regions(card: np.ndarray) -> dict[str, np.ndarray]:
        height, width = card.shape[:2]
        return {
            "top": card[0:int(height * 0.17), 0:width],
            "artwork": card[
                int(height * 0.12):int(height * 0.52),
                int(width * 0.05):int(width * 0.95),
            ],
            "bottom": card[int(height * 0.70):height, 0:width],
            "full": card,
        }

    @staticmethod
    def _resize(image: np.ndarray, target_width: int) -> np.ndarray:
        height, width = image.shape[:2]
        if width >= target_width:
            return image
        scale = target_width / width
        return cv2.resize(
            image,
            (int(width * scale), int(height * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    @staticmethod
    def _fast_variant(image: np.ndarray) -> np.ndarray:
        enlarged = RecognitionService._resize(image, 1200)
        gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.createCLAHE(
            clipLimit=2.2,
            tileGridSize=(8, 8),
        ).apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 1.4)
        return cv2.addWeighted(enhanced, 1.55, blurred, -0.55, 0)

    @staticmethod
    def _language_from_text(text: str) -> str:
        # Treat isolated OCR glyphs as noise. English cards routinely contain
        # energy symbols or footer artifacts that OCR turns into one CJK
        # character; a single glyph must not overrule a page of Latin text.
        japanese_count = len(re.findall(r"[\u3040-\u30ff]", text))
        chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        if japanese_count >= 2 or (japanese_count and latin_count < 6):
            return "Japanese"
        if chinese_count >= 2 or (chinese_count and latin_count < 6):
            return "Chinese"
        if latin_count:
            return "English"
        return "Unknown"

    @staticmethod
    def _extract_result(result: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        boxes = getattr(result, "boxes", None)

        if texts is not None:
            texts_list = list(texts)
            scores_list = (
                list(scores)
                if scores is not None
                else [0.0] * len(texts_list)
            )
            boxes_list = (
                list(boxes)
                if boxes is not None
                else [None] * len(texts_list)
            )

            for text, score, box in zip(
                texts_list,
                scores_list,
                boxes_list,
            ):
                items.append({
                    "text": str(text).strip(),
                    "score": float(score or 0.0),
                    "box": (
                        box.tolist()
                        if hasattr(box, "tolist")
                        else box
                    ),
                })
            return items

        if isinstance(result, tuple) and result:
            result = result[0]

        if isinstance(result, list):
            for entry in result:
                if (
                    not isinstance(entry, (list, tuple))
                    or len(entry) < 2
                ):
                    continue

                box = entry[0]
                text_score = entry[1]
                if (
                    isinstance(text_score, (list, tuple))
                    and text_score
                ):
                    items.append({
                        "text": str(text_score[0]).strip(),
                        "score": (
                            float(text_score[1])
                            if len(text_score) > 1
                            else 0.0
                        ),
                        "box": (
                            box.tolist()
                            if hasattr(box, "tolist")
                            else box
                        ),
                    })
        return items

    def _run_ocr(
        self,
        image: np.ndarray,
        source: str,
        full_pass: bool = False,
    ) -> list[dict[str, Any]]:
        prepared = (
            self._resize(image, 1300)
            if full_pass
            else self._fast_variant(image)
        )

        items: list[dict[str, Any]] = []
        result = self._infer_ocr(prepared)
        for item in self._extract_result(result):
            if item["text"] and item["score"] >= 0.25:
                item["source"] = source
                item["variant"] = (
                    "color"
                    if full_pass
                    else "sharp"
                )
                items.append(item)
        return items

    @staticmethod
    def _collector_region(card: np.ndarray) -> np.ndarray:
        """Return the normalized footer area where printed identifiers live."""
        height, width = card.shape[:2]
        return card[
            int(round(height * 0.82)):max(1, int(round(height * 0.995))),
            int(round(width * 0.015)):max(1, int(round(width * 0.80))),
        ]

    @staticmethod
    def _printed_code_region(card: np.ndarray) -> np.ndarray:
        """Return the tight lower-left strip containing set print identifiers."""
        height, width = card.shape[:2]
        return card[
            int(round(height * 0.88)):max(1, int(round(height * 0.985))),
            int(round(width * 0.015)):max(1, int(round(width * 0.42))),
        ]

    @staticmethod
    def _printed_identifier_line(card: np.ndarray) -> np.ndarray:
        """Return the normalized line containing set mark and card number."""
        height, width = card.shape[:2]
        return card[
            int(round(height * 0.94)):max(1, int(round(height * 0.985))),
            int(round(width * 0.015)):max(1, int(round(width * 0.42))),
        ]

    @staticmethod
    def _collector_retry_canvas(card: np.ndarray) -> np.ndarray:
        """Stack offset footer bands for one bounded recovery inference."""
        height, width = card.shape[:2]
        bounds = (
            (0.74, 0.94, 0.00, 0.92),
            (0.79, 0.995, 0.00, 0.92),
        )
        bands = [
            card[
                int(round(height * top)):max(1, int(round(height * bottom))),
                int(round(width * left)):max(1, int(round(width * right))),
            ]
            for top, bottom, left, right in bounds
        ]
        target_width = max(band.shape[1] for band in bands)
        normalized = [
            cv2.resize(
                band,
                (target_width, max(1, int(round(band.shape[0] * target_width / band.shape[1])))),
                interpolation=cv2.INTER_CUBIC,
            )
            for band in bands
        ]
        separator = np.full((8, target_width, 3), 255, dtype=np.uint8)
        return np.vstack((normalized[0], separator, normalized[1]))

    @classmethod
    def _collector_frame_metrics(cls, card: np.ndarray) -> dict[str, float]:
        region = cls._collector_region(card)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        glare_ratio = float(np.mean(gray >= 245))
        contrast = float(gray.std())
        score = (
            min(1.0, sharpness / 120.0) * 0.55
            + (1.0 - min(1.0, glare_ratio / 0.18)) * 0.30
            + min(1.0, contrast / 48.0) * 0.15
        )
        return {
            "score": round(score, 5),
            "sharpness": round(sharpness, 3),
            "glare_ratio": round(glare_ratio, 5),
            "contrast": round(contrast, 3),
        }

    @classmethod
    def _select_collector_frames(
        cls,
        frames: list[np.ndarray],
        *,
        limit: int = 3,
        preserve_first: bool = False,
    ) -> list[tuple[np.ndarray, dict[str, float]]]:
        ranked: list[tuple[float, int, np.ndarray, dict[str, float]]] = []
        seen: set[tuple[tuple[int, ...], bytes]] = set()
        for order, frame in enumerate(frames):
            if frame is None or getattr(frame, "size", 0) == 0:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            signature = cv2.resize(
                gray,
                (8, 8),
                interpolation=cv2.INTER_AREA,
            ).tobytes()
            key = (tuple(frame.shape), signature)
            if key in seen:
                continue
            seen.add(key)
            metrics = cls._collector_frame_metrics(frame)
            ranked.append((float(metrics["score"]), -order, frame, metrics))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [
            (frame, metrics)
            for _, _, frame, metrics in ranked[:max(1, int(limit))]
        ]
        if preserve_first and frames and getattr(frames[0], "size", 0):
            primary = frames[0]
            primary_metrics = cls._collector_frame_metrics(primary)
            selected = [(primary, primary_metrics)] + [
                item for item in selected if item[0] is not primary
            ]
            selected = selected[:max(1, int(limit))]
        return selected

    @classmethod
    def _collector_variants(
        cls,
        card: np.ndarray,
    ) -> list[tuple[str, np.ndarray]]:
        height, width = card.shape[:2]
        bottom = card[int(round(height * 0.70)):height, 0:width]
        bottom_gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
        region = cls._collector_region(card)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.createCLAHE(
            clipLimit=2.2,
            tileGridSize=(8, 8),
        ).apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
        sharpened = cv2.addWeighted(enhanced, 1.45, blurred, -0.45, 0)
        upscaled = cv2.resize(
            sharpened,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC,
        )
        _, thresholded = cv2.threshold(
            upscaled,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        thresholded_inverse = cv2.bitwise_not(thresholded)
        code_region = cls._printed_code_region(card)
        code_upscaled = cv2.resize(
            code_region,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC,
        )
        code_gray = cv2.cvtColor(code_upscaled, cv2.COLOR_BGR2GRAY)
        code_clahe = cv2.createCLAHE(
            clipLimit=1.8,
            tileGridSize=(6, 4),
        ).apply(code_gray)
        return [
            ("bottom30_original", bottom),
            ("bottom30_grayscale", bottom_gray),
            ("clahe_sharp_2x", upscaled),
            ("otsu", thresholded),
            ("otsu_inverse", thresholded_inverse),
            ("printed_code_2x", code_upscaled),
            ("printed_code_clahe_2x", code_clahe),
        ]

    def _run_collector_ocr(
        self,
        card: np.ndarray,
        source: str,
        *,
        expected_codes: set[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for variant_name, prepared in self._collector_variants(card):
            variant_items: list[dict[str, Any]] = []
            result = self._infer_ocr(prepared)
            for item in self._extract_result(result):
                if item["text"] and item["score"] >= 0.25:
                    item["source"] = source
                    item["variant"] = variant_name
                    variant_items.append(item)
            items.extend(variant_items)
            number, number_score = self._best_collector_evidence(items)
            code, code_score = self._best_printed_code_evidence(items)
            diagnostics.append({
                "variant": variant_name,
                "shape": list(prepared.shape),
                "texts": [item["text"] for item in variant_items],
                "collector_number": number,
                "collector_score": round(number_score, 4),
                "printed_code": code,
                "printed_code_score": round(code_score, 4),
            })
            variant_codes = self._printed_code_candidates(variant_items)
            expected_code_found = bool(
                expected_codes and variant_codes.intersection(expected_codes)
            )
            if max(number_score, code_score) >= 0.78 and (
                not expected_codes or expected_code_found
            ):
                break
        return items, diagnostics

    def _run_collector_ocr_batched(
        self,
        card: np.ndarray,
        source: str,
        *,
        max_variants: int = 3,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read several footer treatments with one neural inference call."""
        if int(max_variants) == 1:
            with self._lock:
                self._ocr_runtime["footer_recognition_only_attempts"] += 1
            direct = self._printed_identifier_line(card)
            if direct.size:
                direct = cv2.resize(
                    direct,
                    None,
                    fx=3.0,
                    fy=3.0,
                    interpolation=cv2.INTER_CUBIC,
                )
                direct_items = [
                    item for item in self._extract_result(
                        self._infer_ocr_recognition_only(direct)
                    )
                    if item["text"] and item["score"] >= 0.25
                ]
                for item in direct_items:
                    item["source"] = source
                    item["variant"] = "printed_identifier_line_recognition_only"
                number, number_score = self._best_collector_evidence(direct_items)
                code, code_score = self._best_printed_code_evidence(direct_items)
                direct_diagnostic = {
                    "variant": "printed_identifier_line_recognition_only",
                    "shape": list(direct.shape),
                    "texts": [item["text"] for item in direct_items],
                    "collector_number": number,
                    "collector_score": round(number_score, 4),
                    "printed_code": code,
                    "printed_code_score": round(code_score, 4),
                    "batched": False,
                    "recognition_only": True,
                }
                if self._decisive_footer_identifier(
                    direct_items, [direct_diagnostic]
                ):
                    with self._lock:
                        self._ocr_runtime["footer_recognition_only_hits"] += 1
                        attempts = max(
                            1,
                            self._ocr_runtime["footer_recognition_only_attempts"],
                        )
                        self._ocr_runtime["footer_recognition_only_hit_rate"] = round(
                            self._ocr_runtime["footer_recognition_only_hits"] / attempts,
                            3,
                        )
                        self._ocr_runtime["last_footer_mode"] = "recognition_only"
                    return direct_items, [direct_diagnostic]

            with self._lock:
                self._ocr_runtime["footer_detector_fallbacks"] += 1
                attempts = max(
                    1, self._ocr_runtime["footer_recognition_only_attempts"]
                )
                self._ocr_runtime["footer_recognition_only_hit_rate"] = round(
                    self._ocr_runtime["footer_recognition_only_hits"] / attempts,
                    3,
                )
                self._ocr_runtime["last_footer_mode"] = "detector_fallback"

        variants = self._collector_variants(card)
        # Two tight lower-left treatments isolate the tiny printed identifier;
        # retain one broad footer tile for layout/context recovery.
        # Tight identifier crop first, then the broad footer for layout context.
        # CLAHE is retained in the full fallback list but was both slower and
        # less reliable than the broad footer in live foil-card traces.
        preferred = [variants[index] for index in (5, 0, 6) if index < len(variants)]
        selected = preferred[:max(1, int(max_variants))]
        if not selected:
            return [], []
        # RapidOCR cost grows with canvas area. The stream-speed pass sends one
        # isolated identifier crop, which stays legible at 720 px and avoids
        # the OCR engine's slower internal upscaling observed below that size.
        # Multi-treatment recovery retains the
        # broader 900 px canvas for difficult glare and layout cases.
        width_cap = 720 if len(selected) == 1 else 900
        target_width = min(
            width_cap,
            max(image.shape[1] for _, image in selected),
        )
        tiles: list[np.ndarray] = []
        bands: list[tuple[str, int, int, list[int]]] = []
        cursor = 0
        for variant_name, image in selected:
            tile = image
            if tile.ndim == 2:
                tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
            if tile.shape[1] != target_width:
                scale = target_width / float(tile.shape[1])
                tile = cv2.resize(
                    tile,
                    (target_width, max(1, int(round(tile.shape[0] * scale)))),
                    interpolation=cv2.INTER_CUBIC,
                )
            start = cursor
            end = start + tile.shape[0]
            bands.append((variant_name, start, end, list(tile.shape)))
            tiles.append(tile)
            cursor = end
        canvas = np.vstack(tiles)
        extracted = self._extract_result(self._infer_ocr(canvas))
        items: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        by_variant: dict[str, list[dict[str, Any]]] = {name: [] for name, *_ in bands}
        for item in extracted:
            if not item["text"] or item["score"] < 0.25:
                continue
            box = item.get("box") or []
            try:
                center_y = sum(float(point[1]) for point in box) / len(box)
            except (TypeError, ValueError, ZeroDivisionError, IndexError):
                center_y = 0.0
            variant_name = next(
                (name for name, start, end, _ in bands if start <= center_y < end),
                bands[0][0],
            )
            item["source"] = source
            item["variant"] = variant_name
            items.append(item)
            by_variant[variant_name].append(item)
        for variant_name, _start, _end, shape in bands:
            variant_items = by_variant[variant_name]
            number, number_score = self._best_collector_evidence(variant_items)
            code, code_score = self._best_printed_code_evidence(variant_items)
            diagnostics.append({
                "variant": variant_name,
                "shape": shape,
                "texts": [item["text"] for item in variant_items],
                "collector_number": number,
                "collector_score": round(number_score, 4),
                "printed_code": code,
                "printed_code_score": round(code_score, 4),
                "batched": True,
            })
        return items, diagnostics

    @staticmethod
    def _normalized_identifier_matches(text: Any) -> list[str]:
        normalized = unicodedata.normalize("NFKC", str(text or ""))
        normalized = normalized.translate(str.maketrans({
            "⁄": "/", "∕": "/", "╱": "/", "\\": "/",
        }))
        compact = re.sub(r"\s+", "", normalized)
        matches: list[str] = []
        for match in OCR_IDENTIFIER_FRAGMENT_RE.finditer(compact):
            left = match.group(1).translate(OCR_IDENTIFIER_DIGIT_MAP)
            right = match.group(2).translate(OCR_IDENTIFIER_DIGIT_MAP)
            if left.isdigit() and right.isdigit():
                matches.append(f"{left}/{right}")

        # Set marks and collector numbers are often returned in one OCR box
        # (for example ``PBLEN 001/084``). Whitespace compaction makes the
        # number touch the set code, so the guarded OCR-tolerant expression
        # above intentionally rejects it. Recover only an embedded, strictly
        # numeric collector expression; this keeps letter-to-digit correction
        # constrained to standalone identifier-shaped text.
        for match in EMBEDDED_COLLECTOR_FRAGMENT_RE.finditer(compact):
            number = f"{match.group(1)}/{match.group(2)}"
            if number not in matches:
                matches.append(number)
        return matches

    @classmethod
    def _identifier_observations(
        cls,
        items: list[dict[str, Any]],
    ) -> list[tuple[str, float, str]]:
        observations: list[tuple[str, float, str]] = []
        for index, item in enumerate(items):
            text = str(item.get("text") or "")
            score = max(0.01, float(item.get("score") or 0.0))
            source = str(item.get("source") or "")
            observations.append((text, score, source))

            # OCR frequently returns the numerator, slash, and denominator as
            # adjacent boxes. Rejoin only nearby results from the same pass;
            # the identifier parser still requires a slash-shaped expression.
            for window_size in (2, 3):
                window = items[index:index + window_size]
                if len(window) != window_size:
                    continue
                if any(str(part.get("source") or "") != source for part in window):
                    continue
                variant = str(item.get("variant") or "")
                if any(str(part.get("variant") or "") != variant for part in window):
                    continue
                joined = "".join(str(part.get("text") or "") for part in window)
                normalized_joined = unicodedata.normalize("NFKC", joined)
                if not any(mark in normalized_joined for mark in ("/", "⁄", "∕", "╱", "\\")):
                    continue
                joined_score = min(
                    max(0.01, float(part.get("score") or 0.0))
                    for part in window
                ) * 0.9
                observations.append((joined, joined_score, source))
        return observations

    @classmethod
    def _best_identifier_evidence(
        cls,
        items: list[dict[str, Any]],
        pattern: re.Pattern[str],
    ) -> tuple[str | None, float]:
        votes: dict[str, float] = {}

        for text, score, source in cls._identifier_observations(items):
            for number in cls._normalized_identifier_matches(text):
                if not pattern.fullmatch(number):
                    continue
                weight = score
                if source.startswith(("bottom", "collector")):
                    weight *= 2.2
                votes[number] = votes.get(number, 0.0) + weight

        if not votes:
            return None, 0.0

        winner = max(votes, key=votes.get)
        return winner, float(votes[winner])

    @classmethod
    def _best_collector_evidence(
        cls,
        items: list[dict[str, Any]],
    ) -> tuple[str | None, float]:
        winner, score = cls._best_identifier_evidence(
            items,
            COLLECTOR_CANDIDATE_RE,
        )
        if not winner:
            return None, 0.0
        left, right = winner.split("/", 1)

        # Common OCR error on tiny foil numbers: 239/204 becomes 239/2040.
        try:
            left_value = int(left)
            right_value = int(right)
            if (
                right_value >= 1000
                and right.endswith("0")
                and int(right[:-1]) >= left_value
            ):
                winner = f"{left}/{right[:-1]}"
        except ValueError:
            pass

        return (
            (winner, score)
            if COLLECTOR_NUMBER_RE.fullmatch(winner)
            else (None, 0.0)
        )

    @classmethod
    def _best_collector_number(
        cls,
        items: list[dict[str, Any]],
    ) -> str | None:
        return cls._best_collector_evidence(items)[0]

    @classmethod
    def _best_printed_code_evidence(
        cls,
        items: list[dict[str, Any]],
    ) -> tuple[str | None, float]:
        return cls._best_identifier_evidence(items, PRINTED_CARD_CODE_RE)

    @classmethod
    def _best_printed_code(
        cls,
        items: list[dict[str, Any]],
    ) -> str | None:
        return cls._best_printed_code_evidence(items)[0]

    @classmethod
    def _decisive_footer_identifier(
        cls,
        items: list[dict[str, Any]],
        diagnostics: list[dict[str, Any]],
    ) -> str | None:
        """Return strong early footer evidence that does not need another frame."""
        number, number_score = cls._best_collector_evidence(items)
        code, code_score = cls._best_printed_code_evidence(items)
        winner = number or code
        winner_score = number_score if number else code_score
        if not winner:
            return None

        variant_votes = 0
        for diagnostic in diagnostics:
            observed = str(
                diagnostic.get("collector_number")
                or diagnostic.get("printed_code")
                or ""
            ).strip()
            if observed == winner:
                variant_votes += 1

        # The evidence scorer boosts footer observations by 2.2, so 1.7 is
        # equivalent to the established 0.78 strong single-read threshold.
        if variant_votes >= 2 or winner_score >= 1.7:
            return winner
        return None

    @staticmethod
    def _printed_code_candidates(items: list[dict[str, Any]]) -> set[str]:
        candidates: set[str] = set()
        for item in items:
            for value in RecognitionService._normalized_identifier_matches(
                item.get("text")
            ):
                if PRINTED_CARD_CODE_RE.fullmatch(value):
                    candidates.add(value)
        return candidates

    @staticmethod
    def _printed_code_distance(left: str | None, right: str | None) -> int | None:
        left = str(left or "").strip()
        right = str(right or "").strip()
        if not PRINTED_CARD_CODE_RE.fullmatch(left) or not PRINTED_CARD_CODE_RE.fullmatch(right):
            return None
        return sum(a != b for a, b in zip(left, right, strict=True))

    @staticmethod
    def _frame_vote_winner(votes: dict[str, int]) -> tuple[str | None, int]:
        eligible = [
            (str(code), int(count)) for code, count in votes.items()
            if PRINTED_CARD_CODE_RE.fullmatch(str(code))
        ]
        if not eligible:
            return None, 0
        eligible.sort(key=lambda item: (-item[1], item[0]))
        winner, count = eligible[0]
        if count < 2 or (len(eligible) > 1 and eligible[1][1] == count):
            return None, count
        return winner, count

    @staticmethod
    def _select_printed_code(
        observed_code: str | None,
        matched_reference_code: str | None,
        frame_vote_code: str | None,
        cross_job_code: str | None,
    ) -> tuple[str | None, str]:
        """Prefer repeated camera evidence over a candidate's reference metadata."""
        if frame_vote_code:
            return frame_vote_code, "frame-consensus"
        if cross_job_code:
            return cross_job_code, "cross-job-consensus"
        if matched_reference_code:
            return matched_reference_code, "reference-match"
        return observed_code, "single-observation"

    @staticmethod
    def _reconcile_locked_collector_number(
        candidate: dict[str, Any], observed_number: str | None
    ) -> bool:
        """Prefer the number printed on-card when only the provider total differs."""
        observed = str(observed_number or "").strip()
        catalog = str(candidate.get("collector_number") or "").strip()
        if "/" not in observed or "/" not in catalog:
            return False
        observed_local, observed_total = observed.split("/", 1)
        catalog_local, catalog_total = catalog.split("/", 1)
        if not all(
            part.isdigit()
            for part in (observed_local, observed_total, catalog_local, catalog_total)
        ):
            return False
        if int(observed_local) != int(catalog_local) or int(observed_total) == int(catalog_total):
            return False
        candidate["provider_collector_number"] = catalog
        candidate["collector_number"] = observed
        candidate["official_collector_number"] = observed
        candidate["collector_number_reconciled"] = True
        candidate["collector_number_reconciliation"] = "printed-number-provider-total-mismatch"
        return True

    @classmethod
    def _locked_footer_visual_consensus(
        cls,
        catalog_candidate: dict[str, Any] | None,
        visual_candidate: dict[str, Any] | None,
        observed_number: str | None,
        active_set: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Certify a locked-set identity without a redundant artwork search."""
        if not catalog_candidate or not visual_candidate or not active_set:
            return None
        observed = str(observed_number or "").strip()
        if not cls._valid_collector_number(observed):
            return None
        if (
            float(visual_candidate.get("score") or 0.0) < 0.90
            or visual_candidate.get("retrieval_only") is True
        ):
            return None

        locked_set_id = str(
            active_set.get("set_id") or active_set.get("id") or ""
        ).strip().casefold()
        catalog_set_id = str(catalog_candidate.get("set_id") or "").strip().casefold()
        visual_set_id = str(visual_candidate.get("set_id") or "").strip().casefold()
        if not locked_set_id or catalog_set_id != locked_set_id or visual_set_id != locked_set_id:
            return None

        catalog_family = cls._candidate_family_name(catalog_candidate)
        visual_family = cls._candidate_family_name(visual_candidate)
        if not catalog_family or catalog_family != visual_family:
            return None

        observed_local = observed.split("/", 1)[0]
        candidate_locals: list[str] = []
        for candidate in (catalog_candidate, visual_candidate):
            number = str(candidate.get("collector_number") or "").strip()
            if "/" not in number:
                return None
            local = number.split("/", 1)[0]
            if not local.isdigit():
                return None
            candidate_locals.append(local)
        if not observed_local.isdigit() or any(
            int(local) != int(observed_local) for local in candidate_locals
        ):
            return None

        return {
            "reason": "locked_footer_visual_consensus",
            "set_id": locked_set_id,
            "collector_number": observed,
            "family": catalog_family,
            "visual_score": round(float(visual_candidate.get("score") or 0.0), 4),
        }

    @staticmethod
    def _locked_set_mismatch(
        observed_number: str | None,
        observed_language: str | None,
        active_set: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Explain decisive evidence that the visible card is outside a manual set lock."""
        if not active_set:
            return None
        locked_language = str(active_set.get("language") or "").strip()
        seen_language = str(observed_language or "").strip()
        language_conflict = bool(
            locked_language
            and locked_language.casefold() not in {"any", "unknown"}
            and seen_language
            and seen_language.casefold() != "unknown"
            and seen_language.casefold() != locked_language.casefold()
        )

        observed = str(observed_number or "").strip()
        observed_parts = observed.split("/", 1)
        catalog_numbers = {
            str(candidate.get("collector_number") or "").strip()
            for candidate in candidates
            if "/" in str(candidate.get("collector_number") or "")
        }
        catalog_parts = [number.split("/", 1) for number in catalog_numbers]
        number_conflict = False
        catalog_totals: list[str] = []
        if (
            len(observed_parts) == 2
            and all(part.isdigit() for part in observed_parts)
            and catalog_parts
        ):
            observed_local, observed_total = map(int, observed_parts)
            valid_catalog_parts = [
                (int(local), int(total))
                for local, total in catalog_parts
                if local.isdigit() and total.isdigit()
            ]
            catalog_totals = sorted({str(total) for _, total in valid_catalog_parts})
            # Provider totals can differ, so an equal local number remains
            # eligible for reconciliation. A different local and total is a
            # decisive signal that the operator selected another set.
            number_conflict = bool(
                valid_catalog_parts
                and all(local != observed_local for local, _ in valid_catalog_parts)
                and all(total != observed_total for _, total in valid_catalog_parts)
            )

        if not language_conflict and not number_conflict:
            return None
        reasons: list[str] = []
        if language_conflict:
            reasons.append(
                f"card language is {seen_language}; locked language is {locked_language}"
            )
        if number_conflict:
            reasons.append(
                f"printed number {observed} is outside locked catalog totals "
                f"{', '.join(catalog_totals)}"
            )
        return {
            "detected": True,
            "reason": "; ".join(reasons),
            "observed_collector_number": observed or None,
            "observed_language": seen_language or None,
            "locked_set_id": active_set.get("set_id") or active_set.get("id"),
            "locked_set_name": active_set.get("name") or active_set.get("set_name"),
            "locked_language": locked_language or None,
            "action": "Choose the correct set or switch Set mode to Auto.",
        }

    def _search_global_visual(
        self, card: Any, active_set: dict[str, Any]
    ) -> dict[str, Any]:
        if self.global_visual_index is None:
            return {"ok": False, "matches": [], "latency_ms": 0.0}
        try:
            return self.global_visual_index.search_image(
                card,
                limit=15,
                set_id=active_set.get("set_id") or active_set.get("id"),
                set_name=active_set.get("name"),
                language=active_set.get("language"),
            )
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            return self.global_visual_index.search_image(card, limit=15)

    @staticmethod
    def _unique_matched_reference_code(
        candidates: list[dict[str, Any]],
    ) -> str | None:
        codes = {
            str(item.get("printed_code") or "").strip()
            for item in candidates
            if item.get("verification_strong")
            and item.get("printed_code_match")
            and item.get("printed_code")
        }
        return next(iter(codes)) if len(codes) == 1 else None

    @staticmethod
    def _promote_printed_code_candidate(
        candidates: list[dict[str, Any]], printed_code: str | None
    ) -> list[dict[str, Any]]:
        code = str(printed_code or "").strip()
        if not code:
            return candidates
        index = next((
            position for position, item in enumerate(candidates)
            if str(item.get("printed_code") or "").strip() == code
            and item.get("verification_strong")
        ), None)
        if index is None or index == 0:
            return candidates
        return [candidates[index], *candidates[:index], *candidates[index + 1:]]

    @staticmethod
    def _enforce_payload_printed_code_consistency(payload: dict[str, Any]) -> None:
        if not payload.get("variant_ambiguity"):
            return
        if payload.get("locked_set_reconciled_identity") is True:
            return
        evidence = payload.get("collector_ocr") or {}
        repeated_identity = bool(
            evidence.get("frame_vote_winner")
            or evidence.get("cross_job_winner")
            or (evidence.get("catalog_visual_correction") or {}).get("applied")
            or (evidence.get("reference_aware_correction") or {}).get("applied")
        )
        observed = str(payload.get("ocr_printed_code") or "").strip()
        card = payload.get("database_match") or next(
            iter(payload.get("candidates") or []), {}
        )
        selected = str((card or {}).get("printed_code") or "").strip()
        mismatch = bool(observed and selected and observed != selected)
        if not repeated_identity or mismatch:
            payload.update({
                "recognition_locked": False,
                "verification_state": "SEARCHING",
                "lock_reason": None,
                "printed_identity_confirmed": False,
                "identity_conflict": {
                    "observed": observed,
                    "selected": selected,
                    "reason": (
                        "printed codes disagree"
                        if mismatch
                        else "shared-art identity lacks repeated footer evidence"
                    ),
                },
            })

    def _record_footer_observations(
        self,
        *,
        generation: int,
        fingerprint: str,
        codes: set[str],
    ) -> tuple[str | None, int, dict[str, int]]:
        """Combine bounded footer evidence across initial and retry jobs."""
        key = (int(generation), str(fingerprint or ""))
        if not key[1]:
            return None, 0, {}
        valid_codes = {
            str(code) for code in codes
            if PRINTED_CARD_CODE_RE.fullmatch(str(code))
        }
        with self._footer_observations_lock:
            votes = self._footer_observations.setdefault(key, {})
            for code in valid_codes:
                votes[code] = votes.get(code, 0) + 1
            stale = [item for item in self._footer_observations if item[0] < int(generation)]
            for item in stale:
                self._footer_observations.pop(item, None)
            snapshot = dict(votes)
        return (*self._frame_vote_winner(snapshot), snapshot)

    def _reference_aware_printed_code_correction(
        self,
        observed_code: str | None,
        artwork_candidates: list[dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Correct one noisy digit only with temporal and visual agreement."""
        history = self._temporal_history or {}
        expected = history.get("card") or {}
        expected_code = str(expected.get("printed_code") or "").strip()
        if int(history.get("confirmations") or 0) < 2 or not expected_code:
            return observed_code, None
        distance = self._printed_code_distance(observed_code, expected_code)
        if distance is None or distance > 1:
            return observed_code, None
        expected_key = self._temporal_version_key(expected)
        top_score = max(
            (float(item.get("score") or item.get("fused_score") or 0.0) for item in artwork_candidates[:3]),
            default=0.0,
        )
        supporting = next((
            item for item in artwork_candidates[:3]
            if item.get("verification_strong")
            and self._temporal_version_key(item) == expected_key
            and str(item.get("printed_code") or "") == expected_code
            and top_score - float(item.get("score") or item.get("fused_score") or 0.0) <= 0.08
        ), None)
        if supporting is None:
            return observed_code, None
        if expected_code == observed_code:
            return observed_code, None
        return expected_code, {
            "applied": True,
            "observed": observed_code,
            "corrected": expected_code,
            "distance": distance,
            "reason": "temporal version and current visual reference agree",
        }

    def _catalog_visual_printed_code_correction(
        self,
        observed_code: str | None,
        artwork_candidates: list[dict[str, Any]],
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Repair one OCR character only when catalog and visual evidence agree."""
        code = str(observed_code or "").strip()
        if not PRINTED_CARD_CODE_RE.fullmatch(code):
            return observed_code, None
        if self.artwork_index.records_for_printed_code(code):
            return observed_code, None
        nearby = self.artwork_index.nearest_printed_code_records(
            code, max_distance=1
        )
        nearby_codes = {
            str(item.get("printed_code") or "").strip() for item in nearby
            if item.get("printed_code")
        }
        if len(nearby_codes) != 1:
            return observed_code, None
        corrected = next(iter(nearby_codes))
        nearby_keys = {
            key for item in nearby for key in self._candidate_identity_keys(item)
        }
        supporting = next((
            item for item in artwork_candidates[:5]
            if item.get("verification_strong")
            and item.get("artwork_verification_strong")
            and self._candidate_identity_keys(item).intersection(nearby_keys)
        ), None)
        if supporting is None:
            return observed_code, None
        return corrected, {
            "applied": True,
            "observed": code,
            "corrected": corrected,
            "distance": 1,
            "reason": "unique catalog neighbor and current visual reference agree",
        }

    def _reference_printed_code(self, image_path: Any) -> str | None:
        raw_path = str(image_path or "").strip()
        if not raw_path:
            return None
        with self._reference_identifier_cache_lock:
            if raw_path in self._reference_identifier_cache:
                return self._reference_identifier_cache[raw_path]
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.is_file() else None
        code: str | None = None
        if image is not None and image.size:
            items, _ = self._run_collector_ocr(image, "reference_collector")
            code = self._best_printed_code(items)
        with self._reference_identifier_cache_lock:
            self._reference_identifier_cache[raw_path] = code
        self._persist_reference_identifier_cache()
        return code

    def _annotate_reference_identifiers(
        self,
        candidates: list[dict[str, Any]],
        live_printed_code: str | set[str] | None,
        *,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        annotated = [dict(candidate) for candidate in candidates]
        live_codes = (
            set(live_printed_code)
            if isinstance(live_printed_code, set)
            else {live_printed_code}
            if live_printed_code
            else set()
        )
        checked = 0
        for candidate in annotated:
            if checked >= max(1, int(limit)):
                break
            if not candidate.get("verification_strong"):
                continue
            catalog_code = str(candidate.get("printed_code") or "").strip()
            if PRINTED_CARD_CODE_RE.fullmatch(catalog_code):
                exact_match = catalog_code in live_codes
                candidate["printed_code_match"] = exact_match
                candidate["printed_code_match_mode"] = "exact" if exact_match else None
                candidate["printed_code_matching_frames"] = 1 if exact_match else 0
                candidate["printed_code_distance"] = 0 if exact_match else None
                checked += 1
                continue
            image_path = (
                candidate.get("image_path")
                or candidate.get("reference_image")
                or candidate.get("local_image")
            )
            if not image_path:
                continue
            checked += 1
            reference_code = self._reference_printed_code(image_path)
            exact_match = bool(reference_code and reference_code in live_codes)
            candidate["printed_code"] = reference_code
            candidate["printed_code_match"] = exact_match
            candidate["printed_code_match_mode"] = "exact" if exact_match else None
            candidate["printed_code_matching_frames"] = 1 if exact_match else 0
            candidate["printed_code_distance"] = 0 if exact_match else None
        return annotated

    def _expand_variant_family_for_printed_code(
        self,
        candidates: list[dict[str, Any]],
        live_codes: set[str],
    ) -> list[dict[str, Any]]:
        """Recover an exact shared-art variant omitted by visual top-k."""
        if not live_codes or any(
            item.get("printed_code_match") for item in candidates
        ):
            return candidates
        anchor = next((
            item for item in candidates
            if item.get("verification_strong")
            and not item.get("retrieval_only")
            and self._candidate_family_name(item)
        ), None)
        if anchor is None:
            return candidates
        family = self.artwork_index.family_records(anchor, limit=12)
        if not family:
            return candidates
        annotated = self._annotate_reference_identifiers(
            family,
            live_codes,
            limit=12,
        )
        exact = next((
            item for item in annotated if item.get("printed_code_match")
        ), None)
        if exact is None:
            return candidates
        exact = {
            **exact,
            "verification_strong": True,
            "artwork_verification_strong": bool(
                anchor.get("artwork_verification_strong")
            ),
            "score": max(
                float(anchor.get("score") or 0.0),
                float(exact.get("score") or 0.0),
            ),
            "variant_family_expanded": True,
        }
        exact_keys = self._candidate_identity_keys(exact)
        remaining = [
            item for item in candidates
            if not (exact_keys & self._candidate_identity_keys(item))
        ]
        return [exact, *remaining]

    @staticmethod
    def _valid_collector_number(number: str | None) -> bool:
        if not number:
            return False
        match = re.fullmatch(r"(\d{1,3})/(\d{2,3})", str(number).strip())
        if not match:
            return False
        return int(match.group(1)) > 0 and int(match.group(2)) > 0

    @staticmethod
    def _strong_printed_identifier_agreement(
        candidate: dict[str, Any],
        printed_code: str | None,
    ) -> bool:
        return bool(
            printed_code
            and candidate.get("printed_code_match") is True
            and candidate.get("verification_strong") is True
            and candidate.get("artwork_verification_strong") is True
        )

    @classmethod
    def _strong_printed_identifier_lock_ready(
        cls,
        candidate: dict[str, Any],
        printed_code: str | None,
        overall_confidence: float,
        language: str | None,
    ) -> bool:
        return bool(
            cls._strong_printed_identifier_agreement(candidate, printed_code)
            and float(overall_confidence) >= 0.68
            and str(language or "").strip().lower() not in {"", "unknown"}
        )

    @staticmethod
    def _locked_set_reconciled_identity_ready(
        candidate: dict[str, Any],
        printed_code: str | None,
        active_set: dict[str, Any],
        visual_similarity: float,
    ) -> bool:
        """Accept an official printed total when a provider total is stale.

        This is deliberately narrower than the normal OCR lock: it only applies
        inside an operator-locked set, after collector reconciliation, with an
        exact numerator/denominator read and strong visual agreement.
        """
        observed = str(printed_code or "").strip()
        official = str(candidate.get("official_collector_number") or "").strip()
        return bool(
            active_set
            and candidate.get("set_locked_identity_agreement") is True
            and candidate.get("collector_number_reconciled") is True
            and observed
            and official
            and observed.casefold() == official.casefold()
            and "/" in observed
            and float(visual_similarity or 0.0) >= 0.86
        )

    @staticmethod
    def _best_name(items: list[dict[str, Any]]) -> str | None:
        candidates: dict[str, float] = {}

        for item in items:
            if item.get("source") not in {"top", "full"}:
                continue

            text = item["text"].strip()
            if (
                PRINTED_IDENTIFIER_RE.search(text)
                or len(text) < 2
                or re.fullmatch(r"[\d\W_]+", text)
            ):
                continue

            weight = float(item["score"])
            if item.get("source") == "top":
                weight *= 1.8

            candidates[text] = candidates.get(text, 0.0) + weight

        return max(candidates, key=candidates.get) if candidates else None

    @staticmethod
    def _best_hp(items: list[dict[str, Any]]) -> str | None:
        patterns = [
            re.compile(r"\bHP\s*(\d{1,3})\b", re.IGNORECASE),
            re.compile(r"\b(\d{2,3})\s*HP\b", re.IGNORECASE),
        ]

        for item in items:
            if item.get("source") != "top":
                continue
            for pattern in patterns:
                match = pattern.search(item["text"])
                if match:
                    return match.group(1)
        return None

    @staticmethod
    def _split_number(
        number: str | None,
    ) -> tuple[str | None, str | None]:
        if not number or "/" not in number:
            return None, None
        left, right = number.split("/", 1)
        return left, right

    def _database_validate(
        self,
        name: str | None,
        number: str | None,
        language: str,
    ) -> tuple[dict[str, Any] | None, float]:
        if not self._cards:
            return None, 0.0

        left, right = self._split_number(number)
        scored: list[tuple[float, dict[str, Any]]] = []

        for card in self._cards:
            score = 0.0

            if (
                language != "Unknown"
                and card.get("language") == language
            ):
                score += 0.20

            printed_name = str(card.get("printed_name", ""))
            if name and printed_name:
                score += (
                    SequenceMatcher(
                        None,
                        name,
                        printed_name,
                    ).ratio()
                    * 0.50
                )

            db_left, db_right = self._split_number(
                card.get("collector_number")
            )

            if left and db_left:
                score += (
                    0.25
                    if left == db_left
                    else SequenceMatcher(
                        None,
                        left,
                        db_left,
                    ).ratio()
                    * 0.10
                )

            if right and db_right:
                score += (
                    0.20
                    if right == db_right
                    else SequenceMatcher(
                        None,
                        right,
                        db_right,
                    ).ratio()
                    * 0.12
                )

            scored.append((score, card))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best_card = scored[0]

        if best_score < 0.55:
            return None, best_score

        return best_card, min(1.0, best_score)

    @staticmethod
    def _fuse_confidence(
        ocr_confidence: float,
        collector_evidence: float,
        language: str,
        evidence_confidence: float,
    ) -> tuple[float, list[str]]:
        components = [
            (
                max(0.0, min(1.0, ocr_confidence)),
                0.25,
                "OCR",
            ),
            (
                max(0.0, min(1.0, collector_evidence)),
                0.25,
                "Collector number",
            ),
            (
                1.0
                if language and language != "Unknown"
                else 0.0,
                0.10,
                "Language",
            ),
            (
                max(0.0, min(1.0, evidence_confidence)),
                0.40,
                "Database or artwork",
            ),
        ]

        score = sum(
            value * weight
            for value, weight, _ in components
        )
        reasons = [
            name
            for value, _, name in components
            if value >= 0.75
        ]
        return round(score, 3), reasons

    @staticmethod
    @staticmethod
    def _usable_ocr_identity(
        name: str | None,
        collector_number: str | None,
    ) -> bool:
        if collector_number:
            return True

        value = str(
            name
            or ""
        ).strip()

        if len(
            value
        ) < 2:
            return False

        mojibake_markers = (
            "Ã",
            "Â",
            "â",
            "�",
            "¤",
            "©",
        )

        if any(
            marker in value
            for marker in mojibake_markers
        ):
            return False

        readable = sum(
            1
            for character in value
            if (
                character.isalnum()
                or "\u3400"
                <= character
                <= "\u9fff"
            )
        )

        return (
            readable
            / max(
                1,
                len(
                    value
                ),
            )
        ) >= 0.55

    @staticmethod
    def _score_candidate(
        candidate: dict[str, Any],
        observed_name: str | None,
        observed_number: str | None,
        observed_language: str,
    ) -> float:
        base = float(candidate.get("score", 0.0))
        score = base * 0.65

        candidate_number = candidate.get("collector_number")
        candidate_language = candidate.get("language")
        candidate_name = (
            candidate.get("printed_name")
            or candidate.get("name")
            or ""
        )

        if observed_number and candidate_number:
            if observed_number == candidate_number:
                score += 0.25
            else:
                score -= 0.10

        if (
            observed_language
            and observed_language != "Unknown"
            and candidate_language
        ):
            score += 0.07 if observed_language == candidate_language else -0.05

        if observed_name and candidate_name:
            name_ratio = SequenceMatcher(
                None,
                observed_name,
                str(candidate_name),
            ).ratio()
            score += name_ratio * 0.08

        return round(max(0.0, min(1.0, score)), 4)

    def _recognize_worker(
        self,
        frame: np.ndarray,
        generation: int = 0,
        frame_id: int | None = None,
        source: str = "auto",
        captured_at: float | None = None,
        ocr_frame: np.ndarray | None = None,
        collector_frames: tuple[np.ndarray, ...] = (),
    ) -> None:
        started = time.perf_counter()
        worker_started_at = time.time()
        stage_started = started

        try:
            pipeline_stages: list[dict[str, Any]] = []
            stage_timings: dict[str, Any] = {}
            stage_timings["queue_ms"] = round(
                max(0.0, worker_started_at - float(captured_at or worker_started_at))
                * 1000,
                1,
            )

            already_rectified = self._is_rectified_card(frame)
            prepared_card = self._prepare_card(frame)
            detail_card = (
                prepared_card
                if ocr_frame is frame
                else self._prepare_card(ocr_frame)
                if ocr_frame is not None and getattr(ocr_frame, "size", 0)
                else prepared_card
            )
            card = prepared_card
            quality_payload: dict[str, Any] = {}
            if self.vision_optimizer is not None:
                if already_rectified:
                    card = self.vision_optimizer._normalize(card)
                    quality_payload = vars(self.vision_optimizer.quality(card))
                else:
                    optimized_result = self.vision_optimizer.optimize(card)
                    card = optimized_result["image"]
                    quality_payload = optimized_result["quality"]
            pipeline_stages.append({
                "key": "detect",
                "label": "Card detected",
                "state": "done",
            })
            regions = self._regions(card)
            ocr_regions = self._regions(detail_card)
            stage_timings["prepare_ms"] = round(
                (time.perf_counter() - stage_started) * 1000, 1
            )
            pipeline_stages.append({
                "key": "perspective",
                "label": "Card crop prepared",
                "state": "done",
            })

            global_started = time.perf_counter()
            set_context = self.set_catalog.status()
            active_set = (
                dict(set_context.get("active_set") or {})
                if set_context.get("locked")
                else {}
            )
            locked_to_set = bool(set_context.get("locked"))

            def _filter_locked_candidates(
                candidates: list[dict[str, Any]],
            ) -> list[dict[str, Any]]:
                if not locked_to_set:
                    return candidates
                return [
                    item
                    for item in candidates
                    if self.set_catalog.candidate_allowed(item)
                ]

            global_visual_result = self._search_global_visual(card, active_set)
            global_visual_candidates = list(
                global_visual_result.get("matches") or []
            )
            global_visual_candidates = _filter_locked_candidates(
                global_visual_candidates
            )
            global_visual_top_score = (
                float(global_visual_candidates[0].get("score", 0.0))
                if global_visual_candidates else 0.0
            )
            stage_timings["global_visual_ms"] = round(
                (time.perf_counter() - global_started) * 1000, 1
            )

            # Stream-speed contract: surface the cached visual identity before
            # exhaustive artwork comparison and OCR. Those slower stages refine
            # the exact printing in the background; they must not delay the first
            # useful card result shown to the operator.
            if global_visual_candidates:
                self._publish_visual_interim(
                    generation=generation,
                    frame_id=frame_id,
                    source=source,
                    candidates=list(global_visual_candidates),
                    fingerprint=None,
                    resolution={
                        "diagnostics": {
                            "status": "visual-candidate",
                            "background_enrichment": True,
                        }
                    },
                    started=started,
                    stage_timings=dict(stage_timings),
                )

            # Locked-set pack scans usually have unique artwork.  Confirm the
            # leading global candidate against the small hinted artwork index
            # before paying for footer OCR.  Shared-art families deliberately
            # remain on the footer path so artwork alone can never certify the
            # wrong printing.
            visual_preflight_result: dict[str, Any] | None = None
            visual_preflight_evidence: dict[str, Any] | None = None
            visual_preflight_safe = False
            visual_preflight_started = time.perf_counter()
            if (
                locked_to_set
                and global_visual_candidates
                and global_visual_top_score >= self.FAST_PATH_VISUAL_SCORE
                and hasattr(self.artwork_index, "search_hinted")
            ):
                visual_preflight_result = self.artwork_index.search_hinted(
                    card,
                    global_visual_candidates[:5],
                    limit=4,
                )
                preflight_matches = _filter_locked_candidates(
                    list(visual_preflight_result.get("matches") or [])
                )
                visual_preflight_result["matches"] = preflight_matches
                visual_preflight_evidence = self._fast_path_evidence(
                    global_visual_candidates,
                    preflight_matches,
                )
                indexed_family: list[dict[str, Any]] = []
                preflight_anchor = next((
                    item for item in preflight_matches
                    if item.get("verification_strong")
                    and not item.get("retrieval_only")
                    and self._candidate_family_name(item)
                ), None)
                if preflight_anchor is not None:
                    indexed_family = _filter_locked_candidates(
                        list(self.artwork_index.family_records(
                            preflight_anchor, limit=8
                        ))
                    )
                visual_preflight_safe = self._visual_preflight_can_skip_footer(
                    visual_preflight_evidence,
                    [*global_visual_candidates, *preflight_matches],
                    indexed_family,
                )
            stage_timings["visual_preflight_ms"] = round(
                (time.perf_counter() - visual_preflight_started) * 1000, 1
            )
            stage_timings["visual_preflight_safe"] = visual_preflight_safe

            # Read the footer before exhaustive artwork retrieval. When two
            # independent preprocessing variants agree on a unique catalog
            # identity, use its family as a small visual-verification shortlist.
            early_footer_started = time.perf_counter()
            early_footer_items: list[dict[str, Any]] = []
            early_footer_diagnostics: list[dict[str, Any]] = []
            early_footer_code: str | None = None
            early_footer_catalog_code: str | None = None
            early_footer_hints: list[dict[str, Any]] = []
            early_footer_identifier: str | None = None
            early_footer_variant_count = 0
            early_footer_card = detail_card
            early_footer_metrics = self._collector_frame_metrics(detail_card)
            if source != "six-card-grid" and not visual_preflight_safe:
                early_choices = self._select_collector_frames(
                    [detail_card, *collector_frames],
                    limit=1,
                )
                if early_choices:
                    early_footer_card, early_footer_metrics = early_choices[0]
                early_footer_variant_count = self._early_footer_variant_budget(
                    locked_to_set=locked_to_set,
                    visual_score=global_visual_top_score,
                    source=source,
                )
                early_footer_items, early_footer_diagnostics = (
                    self._run_collector_ocr_batched(
                        early_footer_card,
                        "collector_frame_0",
                        # Pair the tight identifier crop with one broad footer.
                        # Ambiguous reads still fall through to multi-frame
                        # verification below.
                        max_variants=early_footer_variant_count,
                    )
                )
                variant_votes: dict[str, int] = {}
                for diagnostic in early_footer_diagnostics:
                    code = str(diagnostic.get("printed_code") or "").strip()
                    if PRINTED_CARD_CODE_RE.fullmatch(code):
                        variant_votes[code] = variant_votes.get(code, 0) + 1
                early_footer_code, _ = self._frame_vote_winner(variant_votes)
                early_footer_identifier = self._decisive_footer_identifier(
                    early_footer_items,
                    early_footer_diagnostics,
                )
                if early_footer_code and hasattr(
                    self.artwork_index, "records_for_printed_code"
                ):
                    exact_records = self.artwork_index.records_for_printed_code(
                        early_footer_code
                    ) or []
                    exact_records = _filter_locked_candidates(exact_records)
                    if not exact_records:
                        nearby = self.artwork_index.nearest_printed_code_records(
                            early_footer_code, max_distance=1
                        ) or []
                        nearby = _filter_locked_candidates(
                            list(nearby)
                        )
                        nearby_codes = {
                            str(item.get("printed_code") or "").strip()
                            for item in nearby if item.get("printed_code")
                        }
                        if len(nearby_codes) == 1:
                            exact_records = nearby
                            early_footer_catalog_code = next(iter(nearby_codes))
                    if len(exact_records) == 1:
                        early_footer_catalog_code = (
                            early_footer_catalog_code or early_footer_code
                        )
                        early_footer_hints = self.artwork_index.family_records(
                            exact_records[0], limit=12
                        )
            stage_timings["early_footer_ms"] = round(
                (time.perf_counter() - early_footer_started) * 1000, 1
            )
            stage_timings["early_footer_variant_count"] = early_footer_variant_count
            stage_timings["early_footer_code"] = early_footer_code
            stage_timings["early_footer_identifier"] = early_footer_identifier
            stage_timings["early_footer_reused"] = bool(early_footer_identifier)
            stage_timings["early_footer_quality"] = early_footer_metrics
            stage_timings["early_footer_catalog_code"] = early_footer_catalog_code
            stage_timings["early_footer_shortlist"] = bool(early_footer_hints)
            stage_timings["early_footer_skipped_visual_consensus"] = (
                visual_preflight_safe
            )

            early_catalog_match: dict[str, Any] | None = None
            if (
                early_footer_identifier
                and locked_to_set
                and self.catalog_resolver is not None
            ):
                early_catalog_started = time.perf_counter()
                try:
                    resolved = self.catalog_resolver({
                        "collector_number": early_footer_identifier,
                        "language": active_set.get("language"),
                        "active_set": active_set,
                        "set_id": active_set.get("set_id") or active_set.get("id"),
                        "set_name": active_set.get("name"),
                    })
                    if resolved:
                        early_catalog_match = dict(resolved)
                        catalog_score = min(
                            0.89, float(early_catalog_match.get("score") or 0.0)
                        )
                        catalog_signals = dict(
                            early_catalog_match.get("signals") or {}
                        )
                        catalog_signals["collector_number"] = 1.0
                        early_catalog_match.update({
                            "source": "live_catalog",
                            "score": catalog_score,
                            "fused_score": catalog_score,
                            "provisional": True,
                            "retrieval_only": False,
                            "set_locked_catalog_lookup": True,
                            "signals": catalog_signals,
                            "provider_collector_number": early_catalog_match.get(
                                "collector_number"
                            ),
                        })
                        self._reconcile_locked_collector_number(
                            early_catalog_match, early_footer_identifier
                        )
                except Exception:
                    early_catalog_match = None
                stage_timings["locked_catalog_ms"] = round(
                    (time.perf_counter() - early_catalog_started) * 1000, 1
                )
                stage_timings["locked_catalog_hit"] = bool(early_catalog_match)
                if early_catalog_match:
                    self._publish_visual_interim(
                        generation=generation,
                        frame_id=frame_id,
                        source=source,
                        candidates=[early_catalog_match],
                        fingerprint=None,
                        resolution={
                            "diagnostics": {
                                "status": "set-locked-catalog-candidate",
                                "background_enrichment": True,
                            }
                        },
                        started=started,
                        stage_timings=dict(stage_timings),
                    )

            early_exact_resolution: dict[str, Any] | None = None
            early_exact_reference: dict[str, Any] | None = None
            early_canonical = ""
            if (
                self.exact_reference_resolver is not None
                and "manual-picked-slot-" in str(source)
                and global_visual_candidates
            ):
                visual_seed = next(
                    (
                        item for item in global_visual_candidates
                        if item.get("canonical_name")
                        or item.get("english_name")
                        or item.get("pokemon_name")
                    ),
                    None,
                )
                if visual_seed:
                    early_canonical = str(
                        visual_seed.get("canonical_name")
                        or visual_seed.get("english_name")
                        or visual_seed.get("pokemon_name")
                        or ""
                    ).strip()
                    exact_started = time.perf_counter()
                    early_exact_resolution = self.exact_reference_resolver(
                        prepared_card, early_canonical
                    )
                    stage_timings["exact_reference_ms"] = round(
                        (time.perf_counter() - exact_started) * 1000, 1
                    )
                    if isinstance(early_exact_resolution, dict):
                        early_exact_reference = early_exact_resolution.get("card")
                    if early_exact_resolution and not early_exact_reference:
                        self._publish_visual_interim(
                            generation=generation,
                            frame_id=frame_id,
                            source=source,
                            candidates=list(global_visual_candidates),
                            fingerprint=None,
                            resolution=early_exact_resolution,
                            started=started,
                            stage_timings=stage_timings,
                        )

            artwork_started = time.perf_counter()
            # Artwork-index fingerprints are built from normalized full-card
            # references, so query with the same full-card geometry.
            continuity_fingerprint = self.artwork_index.artwork_fingerprint(card)
            exact_diagnostics = (
                early_exact_resolution.get("diagnostics")
                if isinstance(early_exact_resolution, dict)
                else {}
            ) or {}
            exact_shortlist = list(exact_diagnostics.get("candidates") or [])
            exact_shortlist = _filter_locked_candidates(exact_shortlist)
            trusted_exact_shortlist = bool(
                len(exact_shortlist) >= 2
                and float(exact_diagnostics.get("top_score") or 0.0) >= 28.0
                and float(exact_diagnostics.get("score_gap") or 0.0) >= 4.0
                and all(
                    item.get("set_id") and item.get("collector_number")
                    for item in exact_shortlist[:2]
                )
            )
            recent_family_hints = (
                early_footer_hints or self._trusted_recent_family_hints()
            )
            recent_family_hints = _filter_locked_candidates(
                list(recent_family_hints)
            ) if locked_to_set else list(recent_family_hints)
            temporal_family_hints = self._temporal_family_hints()
            temporal_family_hints = _filter_locked_candidates(
                list(temporal_family_hints)
            ) if locked_to_set else list(temporal_family_hints)
            batch_artwork_hints = self._take_batch_artwork_hints(
                generation, frame_id
            )
            batch_artwork_hints = _filter_locked_candidates(
                list(batch_artwork_hints)
            ) if locked_to_set else list(batch_artwork_hints)
            artwork_hints = (
                exact_shortlist[:5]
                if trusted_exact_shortlist
                else recent_family_hints
                if recent_family_hints
                else temporal_family_hints
                if temporal_family_hints
                else batch_artwork_hints
                if batch_artwork_hints
                else global_visual_candidates[:15]
            )
            artwork_hints = _filter_locked_candidates(list(artwork_hints))
            locked_footer_visual_evidence = self._locked_footer_visual_consensus(
                early_catalog_match,
                global_visual_candidates[0] if global_visual_candidates else None,
                early_footer_identifier,
                active_set,
            )
            hinted_result = (
                {
                    "matches": [dict(global_visual_candidates[0])],
                    "latency_ms": 0.0,
                    "hint_hits": 1,
                    "locked_footer_visual_consensus": True,
                }
                if locked_footer_visual_evidence
                else visual_preflight_result
                if visual_preflight_safe and visual_preflight_result is not None
                else self.artwork_index.search_hinted(
                    card,
                    artwork_hints,
                    limit=(
                        5 if trusted_exact_shortlist
                        else 12 if batch_artwork_hints
                        else 4
                    ),
                )
                if hasattr(self.artwork_index, "search_hinted")
                else {"matches": [], "latency_ms": 0.0, "hint_hits": 0}
            )
            hinted_result["continuity_fingerprint"] = continuity_fingerprint
            hinted_matches = _filter_locked_candidates(
                list(hinted_result.get("matches") or [])
            )
            hinted_result["matches"] = hinted_matches
            hinted_fast_path_evidence = (
                locked_footer_visual_evidence
                or visual_preflight_evidence
                if visual_preflight_safe
                else locked_footer_visual_evidence
                or self._fast_path_evidence(
                    global_visual_candidates,
                    hinted_matches,
                )
            )
            temporal_shortlist_evidence = (
                self._temporal_shortlist_evidence(hinted_result)
                if temporal_family_hints else None
            )
            shortlist_verified = bool(
                trusted_exact_shortlist
                and hinted_matches
                and int(hinted_result.get("hint_hits") or 0) >= 2
            )
            family_shortlist_verified = bool(
                recent_family_hints
                and int(hinted_result.get("hint_hits") or 0) >= 2
                and sum(
                    1 for item in (hinted_result.get("matches") or [])
                    if item.get("verification_strong")
                    and (item.get("image_path") or item.get("reference_image"))
                ) >= 2
            )
            batch_family_counts: dict[str, int] = {}
            for hint in batch_artwork_hints[:16]:
                if hint.get("source") != "pokipair" or hint.get("retrieval_only"):
                    continue
                family_name = str(
                    hint.get("canonical_name")
                    or hint.get("english_name")
                    or hint.get("pokemon_name")
                    or ""
                ).strip().casefold()
                if family_name:
                    batch_family_counts[family_name] = batch_family_counts.get(family_name, 0) + 1
            batch_family_consensus = bool(
                batch_family_counts and max(batch_family_counts.values()) >= 2
            )
            batch_shortlist_verified = bool(
                batch_artwork_hints
                and (
                    batch_family_consensus
                    or any(
                        item.get("source") == "pokipair"
                        and item.get("verification_strong")
                        and item.get("artwork_verification_strong")
                        for item in (hinted_result.get("matches") or [])
                    )
                )
            )
            artwork_fallback = not bool(
                hinted_fast_path_evidence
                or temporal_shortlist_evidence
                or shortlist_verified
                or family_shortlist_verified
                or batch_shortlist_verified
            )
            artwork_result = (
                self.artwork_index.search(card, limit=10)
                if artwork_fallback
                else hinted_result
            )
            artwork_result["matches"] = _filter_locked_candidates(
                list(artwork_result.get("matches") or [])
            )
            cached_artwork_evidence = self._cached_artwork_fast_path_evidence(
                artwork_result
            )
            if cached_artwork_evidence:
                artwork_fallback = False
            artwork_ms = round(
                (time.perf_counter() - artwork_started) * 1000,
                1,
            )
            artwork_candidates = artwork_result.get("matches", [])
            self._remember_trusted_family(list(artwork_candidates))
            artwork_top_score = (
                float(artwork_candidates[0].get("score", 0.0))
                if artwork_candidates
                else 0.0
            )
            # Continuity intentionally tracks only the normalized artwork
            # window. Borders and footer markers remain part of exact-version
            # verification but are too sensitive to live crop jitter.
            fingerprint = continuity_fingerprint
            pipeline_stages.append({
                "key": "fingerprint",
                "label": "Artwork fingerprint",
                "state": "done" if fingerprint else "waiting",
            })
            pipeline_stages.append({
                "key": "index",
                "label": "Artwork index searched",
                "state": "done" if artwork_candidates else "waiting",
            })

            fast_path_evidence = (
                hinted_fast_path_evidence
                or temporal_shortlist_evidence
                or cached_artwork_evidence
                or self._fast_path_evidence(
                    global_visual_candidates,
                    artwork_candidates,
                )
            )
            fast_path_evidence = self._confirm_locked_set_number_fast_path(
                fast_path_evidence,
                early_catalog_match,
                early_footer_identifier,
            )
            visual_variant_ambiguity = self._variant_family_ambiguous(
                [*global_visual_candidates, *artwork_candidates]
            ) or self._indexed_variant_family_ambiguous(artwork_candidates)
            if (
                fast_path_evidence
                and visual_variant_ambiguity
                and not self._variant_fast_path_is_ocr_safe(fast_path_evidence)
                and not early_exact_reference
            ):
                # Keep the sub-second visual candidate, but run footer OCR before
                # certifying a version when multiple printings share its artwork.
                fast_path_evidence = None
            if (
                early_exact_resolution is None
                and
                self.exact_reference_resolver is not None
                and "manual-picked-slot-" in str(source)
            ):
                visual_seed = next(
                    (
                        item
                        for item in [*artwork_candidates, *global_visual_candidates]
                        if item.get("canonical_name")
                        or item.get("english_name")
                        or item.get("pokemon_name")
                    ),
                    None,
                )
                if visual_seed:
                    early_canonical = str(
                        visual_seed.get("canonical_name")
                        or visual_seed.get("english_name")
                        or visual_seed.get("pokemon_name")
                        or ""
                    ).strip()
                    exact_started = time.perf_counter()
                    early_exact_resolution = self.exact_reference_resolver(
                        prepared_card,
                        early_canonical,
                    )
                    stage_timings["exact_reference_ms"] = round(
                        (time.perf_counter() - exact_started) * 1000,
                        1,
                    )
                    if isinstance(early_exact_resolution, dict):
                        early_exact_reference = early_exact_resolution.get("card")
            if early_exact_reference:
                fast_path_evidence = True
            elif early_exact_resolution and artwork_candidates and not global_visual_candidates:
                self._publish_visual_interim(
                    generation=generation,
                    frame_id=frame_id,
                    source=source,
                    candidates=list(artwork_candidates),
                    fingerprint=fingerprint,
                    resolution=early_exact_resolution,
                    started=started,
                    stage_timings=stage_timings,
                )
            recognition_path = "fast" if fast_path_evidence else "full"
            skipped_stages: list[str] = []
            reference_identifier_ms = 0.0
            grid_fast_ocr = source == "six-card-grid"
            if fast_path_evidence:
                skipped_stages.extend(["reference_identifier", "ocr"])
            elif grid_fast_ocr:
                # The batch coordinator reconciles the live footer against its
                # complete reference catalog once per capture.  OCRing up to
                # eight reference images in every card worker duplicated that
                # work and dominated grid latency.
                skipped_stages.append("reference_identifier")
            else:
                reference_identifier_started = time.perf_counter()
                artwork_candidates = self._annotate_reference_identifiers(
                    artwork_candidates,
                    None,
                    limit=8,
                )
                reference_identifier_ms = round(
                    (time.perf_counter() - reference_identifier_started) * 1000,
                    1,
                )
            stage_timings["reference_identifier_ms"] = reference_identifier_ms
            stage_timings["artwork_search_ms"] = artwork_ms
            stage_timings["artwork_preflight_ms"] = float(
                hinted_result.get("latency_ms", 0.0) or 0.0
            )
            stage_timings["artwork_fallback"] = artwork_fallback
            stage_timings["locked_footer_visual_consensus"] = bool(
                locked_footer_visual_evidence
            )
            stage_timings["exact_shortlist_verified"] = shortlist_verified
            stage_timings["family_shortlist_verified"] = family_shortlist_verified
            stage_timings["temporal_shortlist_verified"] = bool(temporal_shortlist_evidence)
            stage_timings["batch_family_consensus"] = batch_family_consensus
            reference_printed_codes = {
                str(item.get("printed_code"))
                for item in artwork_candidates
                if item.get("verification_strong") and item.get("printed_code")
            }

            ocr_started = time.perf_counter()
            # Read the footer first. A printed identifier is substantially
            # more discriminating than a translated/name OCR guess and lets
            # us avoid the expensive top and full-card passes in the common
            # case.
            top_items: list[dict[str, Any]] = []
            selected_collector_frames = self._select_collector_frames(
                [detail_card, *collector_frames],
                limit=4,
                preserve_first=True,
            )
            if early_footer_variant_count:
                selected_collector_frames = [
                    item for item in selected_collector_frames
                    if item[0] is not early_footer_card
                ]
            bottom_items: list[dict[str, Any]] = list(early_footer_items)
            collector_diagnostics: list[dict[str, Any]] = []
            frame_identifier_votes: dict[str, int] = {}
            if early_footer_items:
                collector_diagnostics.append({
                    "frame_index": 0,
                    "frame_shape": list(early_footer_card.shape),
                    **early_footer_metrics,
                    "variants": early_footer_diagnostics,
                })
                early_frame_code = self._best_printed_code(early_footer_items)
                if early_frame_code:
                    frame_identifier_votes[early_frame_code] = 1
            collector_inputs = (
                () if fast_path_evidence
                else selected_collector_frames[:1] if grid_fast_ocr
                else () if early_footer_identifier
                else () if early_footer_code in reference_printed_codes
                else selected_collector_frames if early_footer_items
                else selected_collector_frames
            )
            for collector_index, (collector_frame, frame_metrics) in enumerate(
                collector_inputs,
                start=1 if early_footer_items else 0,
            ):
                frame_items, variant_diagnostics = self._run_collector_ocr_batched(
                    collector_frame,
                    f"collector_frame_{collector_index}",
                    max_variants=1 if grid_fast_ocr else 3,
                )
                bottom_items.extend(frame_items)
                collector_diagnostics.append({
                    "frame_index": collector_index,
                    "frame_shape": list(collector_frame.shape),
                    **frame_metrics,
                    "variants": variant_diagnostics,
                })
                frame_number = self._best_collector_number(frame_items)
                frame_code = self._best_printed_code(frame_items)
                frame_identifier = frame_number or frame_code
                if frame_identifier:
                    frame_identifier_votes[frame_identifier] = (
                        frame_identifier_votes.get(frame_identifier, 0) + 1
                    )
                if frame_identifier and (
                    frame_identifier in reference_printed_codes
                    or frame_identifier_votes[frame_identifier] >= 2
                ):
                    break

            collector_retry_used = False
            collector_retry_items: list[dict[str, Any]] = []
            if not fast_path_evidence and not grid_fast_ocr and not (
                self._best_collector_number(bottom_items)
                or self._best_printed_code(bottom_items)
            ):
                collector_retry_used = True
                collector_retry_items = self._run_ocr(
                    self._collector_retry_canvas(detail_card),
                    "collector_retry",
                )
                for item in collector_retry_items:
                    item["variant"] = "offset_footer_bands"
                bottom_items.extend(collector_retry_items)

            if not fast_path_evidence and not grid_fast_ocr and not (
                self._best_collector_number(bottom_items)
                or self._best_printed_code(bottom_items)
            ):
                bottom_items.extend(self._run_ocr(
                    ocr_regions["bottom"],
                    "bottom",
                ))

            footer_identifier = (
                self._best_collector_number(bottom_items)
                or self._best_printed_code(bottom_items)
            )
            if not fast_path_evidence and not grid_fast_ocr and not footer_identifier:
                top_items = self._run_ocr(
                    ocr_regions["top"],
                    "top",
                )
            elif footer_identifier:
                skipped_stages.append("top_ocr")

            now = time.time()
            prior = self.status()
            need_fallback = (
                not prior.get("collector_number")
                or not prior.get("name_candidate")
            )
            run_full = (
                not fast_path_evidence
                and not grid_fast_ocr
                and not footer_identifier
                and need_fallback
                and now - self._last_full_pass_at
                >= self._full_interval
            )

            full_items: list[dict[str, Any]] = []
            if run_full:
                full_items = self._run_ocr(
                    regions["full"],
                    "full",
                    True,
                )
                self._last_full_pass_at = now
            elif footer_identifier:
                skipped_stages.append("full_ocr")

            ocr_ms = round(
                (time.perf_counter() - ocr_started) * 1000,
                1,
            )
            stage_timings["ocr_ms"] = ocr_ms
            stage_timings["ocr_mode"] = (
                "skipped" if fast_path_evidence
                else "single-shot-footer" if grid_fast_ocr
                else "footer-first" if footer_identifier
                else "full"
            )

            items = top_items + bottom_items + full_items
            name = self._best_name(items)
            hp = self._best_hp(items)
            ocr_number = self._best_collector_number(items)
            printed_code = self._best_printed_code(items)
            frame_vote_code, frame_vote_count = self._frame_vote_winner(
                frame_identifier_votes
            )
            printed_code_candidates = self._printed_code_candidates(items)
            cross_job_code, cross_job_count, cross_job_votes = (
                self._record_footer_observations(
                    generation=generation,
                    fingerprint=fingerprint,
                    codes=printed_code_candidates,
                )
            )
            # Once repeated evidence has selected a code, noisy alternatives
            # from individual OCR treatments must not remain eligible to boost
            # a conflicting catalog variant during ranking.
            if frame_vote_code:
                printed_code_candidates = {frame_vote_code}
            elif cross_job_code:
                printed_code_candidates = {cross_job_code}
            consensus_code = frame_vote_code or cross_job_code or printed_code
            corrected_code, catalog_visual_correction = (
                self._catalog_visual_printed_code_correction(
                    consensus_code, artwork_candidates
                )
            )
            if catalog_visual_correction and corrected_code:
                printed_code_candidates = {corrected_code}
            if not fast_path_evidence and not grid_fast_ocr:
                artwork_candidates = self._annotate_reference_identifiers(
                    artwork_candidates,
                    printed_code_candidates,
                    limit=8,
                )
                artwork_candidates = self._expand_variant_family_for_printed_code(
                    artwork_candidates,
                    printed_code_candidates,
                )
            matched_reference_code = self._unique_matched_reference_code(
                artwork_candidates
            )
            printed_code, printed_code_source = self._select_printed_code(
                printed_code,
                matched_reference_code,
                frame_vote_code,
                cross_job_code,
            )
            if catalog_visual_correction and corrected_code:
                printed_code = corrected_code
                printed_code_source = "catalog-visual-correction"
            if matched_reference_code and printed_code == matched_reference_code:
                if ocr_number and ocr_number != matched_reference_code:
                    ocr_number = None
                seed_identity = getattr(
                    self.artwork_index, "seed_verified_identity", None
                )
                if callable(seed_identity):
                    seed_identity(
                        artwork_result.get("query_fingerprint"),
                        artwork_candidates,
                    )
            printed_code_correction = None
            if printed_code_source not in {
                "frame-consensus", "cross-job-consensus", "catalog-visual-correction"
            }:
                printed_code, printed_code_correction = (
                    self._reference_aware_printed_code_correction(
                        printed_code,
                        artwork_candidates,
                    )
                )
            combined = " ".join(
                item["text"]
                for item in items
            )
            observed_language = self._language_from_text(combined)
            language = observed_language
            # A locked set is authoritative about language. Footer glare can
            # produce a stray CJK glyph even when the title/name OCR is plainly
            # Latin (for example English Pitch Black Mankey). The visual search
            # above has already been restricted to this exact set/language, so
            # allowing noisy OCR to contradict it only suppresses the correct
            # candidate after retrieval.
            locked_language = str(active_set.get("language") or "").strip()
            if (
                global_visual_candidates
                and locked_language
                and locked_language.casefold() not in {"any", "unknown"}
            ):
                language = locked_language
            if language == "Unknown" and footer_identifier:
                candidate_language = str(next(
                    (
                        item.get("language_code") or item.get("language")
                        for item in artwork_candidates
                        if item.get("language_code") or item.get("language")
                    ),
                    "",
                )).strip().lower()
                if candidate_language.startswith("zh") or "chinese" in candidate_language:
                    language = "Chinese"
                elif candidate_language.startswith("ja") or "japanese" in candidate_language:
                    language = "Japanese"
                elif candidate_language.startswith("en") or "english" in candidate_language:
                    language = "English"
            pipeline_stages.append({
                "key": "ocr",
                "label": "OCR bypassed" if fast_path_evidence else "OCR complete",
                "state": "skipped" if fast_path_evidence else "done" if items else "waiting",
            })
            pipeline_stages.append({
                "key": "collector",
                "label": "Collector number",
                "state": "skipped" if fast_path_evidence else "done" if (
                    ocr_number or printed_code
                ) else "waiting",
            })
            pipeline_stages.append({
                "key": "language",
                "label": "Language identified",
                "state": "skipped" if fast_path_evidence else "done" if (
                    language != "Unknown"
                ) else "waiting",
            })

            db_match, db_confidence = self._database_validate(
                name,
                ocr_number,
                language,
            )

            validated_number = ocr_number
            correction_applied = False

            if db_match:
                validated_number = db_match.get(
                    "collector_number"
                )
                correction_applied = (
                    validated_number != ocr_number
                )

            # In Auto Set mode, an exact footer number must constrain the
            # global visual search before a color-similar card can become the
            # leading candidate. This is intentionally a second, tiny search:
            # it compares only references with the same complete collector
            # fraction (053/084 and 53/84 normalize to the same identity).
            identifier_visual_candidates: list[dict[str, Any]] = []
            if (
                validated_number
                and not locked_to_set
                and self.global_visual_index is not None
            ):
                identifier_visual_started = time.perf_counter()
                try:
                    identifier_visual_result = self.global_visual_index.search_image(
                        prepared_card,
                        limit=15,
                        collector_number=validated_number,
                    )
                    identifier_visual_candidates = list(
                        identifier_visual_result.get("matches") or []
                    )
                except Exception:
                    identifier_visual_candidates = []
                stage_timings["identifier_visual_ms"] = round(
                    (time.perf_counter() - identifier_visual_started) * 1000,
                    1,
                )
                stage_timings["identifier_visual_hits"] = len(
                    identifier_visual_candidates
                )
                if identifier_visual_candidates:
                    known_ids = {
                        str(item.get("id") or "")
                        for item in identifier_visual_candidates
                    }
                    global_visual_candidates = [
                        *identifier_visual_candidates,
                        *[
                            item for item in global_visual_candidates
                            if str(item.get("id") or "") not in known_ids
                        ],
                    ]

            if (
                not validated_number
                and artwork_candidates
                and artwork_top_score >= 0.90
            ):
                validated_number = str(
                    artwork_candidates[0].get(
                        "collector_number"
                    )
                )

            locked_catalog_match: dict[str, Any] | None = (
                dict(early_catalog_match)
                if early_catalog_match
                and early_footer_identifier == validated_number
                else None
            )
            if (
                validated_number
                and locked_to_set
                and self.catalog_resolver is not None
                and locked_catalog_match is None
            ):
                catalog_started = time.perf_counter()
                try:
                    locked_catalog_match = self.catalog_resolver({
                        "collector_number": validated_number,
                        "language": active_set.get("language") or language,
                        "active_set": active_set,
                        "set_id": active_set.get("set_id") or active_set.get("id"),
                        "set_name": active_set.get("name"),
                        "name_candidate": name,
                    })
                except Exception:
                    locked_catalog_match = None
                stage_timings["locked_catalog_ms"] = round(
                    (time.perf_counter() - catalog_started) * 1000, 1
                )
                stage_timings["locked_catalog_hit"] = bool(locked_catalog_match)

            ocr_confidence = (
                sum(
                    float(item["score"])
                    for item in items
                )
                / len(items)
                if items
                else 0.0
            )

            evidence_confidence = max(
                float(db_confidence),
                max(
                    (
                        float(item.get("score", 0.0))
                        for item in artwork_candidates
                        if item.get("verification_strong")
                    ),
                    default=0.0,
                ),
            )

            collector_valid = self._valid_collector_number(validated_number)
            strong_printed_identifier_match = any(
                bool(item.get("verification_strong"))
                and bool(item.get("printed_code_match"))
                for item in artwork_candidates
            )
            collector_evidence = (
                1.0 if collector_valid and db_match
                else 1.0 if strong_printed_identifier_match
                else 0.35 if collector_valid
                else 0.0
            )

            overall_confidence, lock_reasons = (
                self._fuse_confidence(
                    float(ocr_confidence),
                    collector_evidence,
                    language,
                    evidence_confidence,
                )
            )

            visual_candidates = [
                {
                    "id": item.get("id"),
                    "name": (
                        item.get("english_name")
                        or item.get("canonical_name")
                        or item.get("pokemon_name")
                        or item.get("name")
                        or item.get("printed_name")
                        or "Visual match"
                    ),
                    "display_name": (
                        item.get("english_name")
                        or item.get("canonical_name")
                        or item.get("pokemon_name")
                        or item.get("display_name")
                        or item.get("name")
                        or item.get("printed_name")
                        or "Visual match"
                    ),
                    "printed_name": item.get("printed_name"),
                    "english_name": item.get("english_name"),
                    "canonical_name": item.get("canonical_name"),
                    "pokemon_name": item.get("pokemon_name"),
                    "pricing_lookup_name": item.get(
                        "pricing_lookup_name"
                    ),
                    "identity_override_key": item.get(
                        "identity_override_key"
                    ),
                    "category": item.get("category"),
                    "hp": item.get("hp"),
                    "types": item.get("types"),
                    "energy_type": item.get("energy_type"),
                    "collector_number": item.get("collector_number"),
                    "printed_code": item.get("printed_code"),
                    "printed_code_match": bool(item.get("printed_code_match")),
                    "printed_code_match_mode": item.get("printed_code_match_mode"),
                    "printed_code_matching_frames": item.get(
                        "printed_code_matching_frames"
                    ),
                    "printed_code_distance": item.get("printed_code_distance"),
                    "language": item.get("language"),
                    "language_code": (
                        item.get("language_code")
                        or item.get("language")
                    ),
                    "score": float(item.get("score", 0.0)),
                    "source": item.get("source") or "global_visual_index",
                    "distance": item.get("distance"),
                    "set_id": item.get("set_id"),
                    "set_name": item.get("set_name"),
                    "rarity": item.get("rarity"),
                    "visual_score": float(
                        item.get(
                            "visual_score",
                            item.get("score", 0.0),
                        )
                    ),
                    "image_path": item.get("image_path"),
                    "reference_image": item.get("reference_image"),
                    "reference_image_url": item.get("reference_image_url"),
                    "local_image": item.get("local_image"),
                    "source_url": item.get("source_url"),
                    "verification_strong": bool(item.get("verification_strong")),
                    "retrieval_only": bool(item.get("retrieval_only")),
                    "artwork_verification_strong": bool(
                        item.get("artwork_verification_strong")
                    ),
                }
                for item in (global_visual_candidates + artwork_candidates)
            ]

            ocr_candidates: list[dict[str, Any]] = []
            if locked_catalog_match:
                catalog_candidate = dict(locked_catalog_match)
                catalog_score = min(
                    0.89, float(catalog_candidate.get("score") or 0.0)
                )
                catalog_signals = dict(catalog_candidate.get("signals") or {})
                catalog_signals["collector_number"] = 1.0
                catalog_candidate.update({
                    "source": "live_catalog",
                    "score": catalog_score,
                    "fused_score": catalog_score,
                    "provisional": True,
                    "retrieval_only": False,
                    "set_locked_catalog_lookup": True,
                    "signals": catalog_signals,
                    "provider_collector_number": (
                        catalog_candidate.get("provider_collector_number")
                        or catalog_candidate.get("collector_number")
                    ),
                })
                self._reconcile_locked_collector_number(
                    catalog_candidate, validated_number
                )
                ocr_candidates.append(catalog_candidate)
            if db_match:
                ocr_candidates.append({
                    "name": (
                        db_match.get("english_name")
                        or db_match.get("name")
                        or db_match.get("printed_name")
                        or "Database match"
                    ),
                    "printed_name": db_match.get(
                        "printed_name"
                    ),
                    "collector_number": db_match.get(
                        "collector_number"
                    ) or validated_number,
                    "language": db_match.get(
                        "language"
                    ) or language,
                    "score": round(
                        float(db_confidence),
                        3,
                    ),
                    "source": "database",
                })

            if self._usable_ocr_identity(
                name,
                validated_number,
            ):
                provisional_score = max(
                    0.40,
                    min(
                        0.78,
                        float(ocr_confidence) * 0.65
                        + (0.13 if validated_number else 0.0)
                        + (0.05 if language != "Unknown" else 0.0),
                    ),
                )
                ocr_candidates.append({
                    "id": f"ocr:{validated_number or name}",
                    "name": name or (
                        f"Card {validated_number}"
                        if validated_number
                        else "Unknown card"
                    ),
                    "printed_name": name,
                    "collector_number": validated_number,
                    "language": language,
                    "score": round(provisional_score, 3),
                    "source": "ocr_provisional",
                    "provisional": True,
                    "reference_image_url": "/api/camera/crop.jpg",
                })

            combined_candidates = visual_candidates + ocr_candidates

            set_context = self.set_catalog.status()
            if set_context.get("locked"):
                combined_candidates = [
                    candidate for candidate in combined_candidates
                    if self.set_catalog.candidate_allowed(candidate)
                ]
                visual_candidates = [
                    candidate for candidate in visual_candidates
                    if self.set_catalog.candidate_allowed(candidate)
                ]
                ocr_candidates = [
                    candidate for candidate in ocr_candidates
                    if self.set_catalog.candidate_allowed(candidate)
                ]

            ranking_started = time.perf_counter()
            if self.candidate_ranker is not None:
                candidates = self.candidate_ranker.rank(
                    visual_candidates=combined_candidates,
                    ocr_payload={
                        "text": combined,
                        "collector_number": validated_number,
                        "printed_code": printed_code,
                        "hp": hp,
                        "language": language,
                    },
                    quality=quality_payload,
                    limit=10,
                )
            else:
                for candidate in combined_candidates:
                    candidate["fused_score"] = self._score_candidate(
                        candidate,
                        name,
                        validated_number,
                        language,
                    )
                candidates = sorted(
                    combined_candidates,
                    key=lambda candidate: float(
                        candidate.get(
                            "fused_score",
                            candidate.get("score", 0.0),
                        )
                    ),
                    reverse=True,
                )[:10]
            if frame_vote_code or cross_job_code or catalog_visual_correction:
                candidates = self._promote_printed_code_candidate(
                    candidates, printed_code
                )
            if set_context.get("locked"):
                candidates = [
                    candidate for candidate in candidates
                    if self.set_catalog.candidate_allowed(candidate)
                ]
                for candidate in candidates:
                    self._reconcile_locked_collector_number(
                        candidate, validated_number
                    )
                # A set lock plus exact printed identity evidence is safe to
                # present immediately as a provisional match. Keep approval
                # disabled until verification finishes, but do not hide the
                # correct card merely because it came from the global index.
                if candidates:
                    leading = candidates[0]
                    leading_signals = dict(leading.get("signals") or {})
                    leading_visual = float(
                        leading.get("visual_similarity")
                        or leading.get("visual_score")
                        or leading.get("score")
                        or 0.0
                    )
                    identity_agreement = max(
                        float(leading_signals.get("collector_number") or 0.0),
                        float(leading_signals.get("ocr_name") or 0.0),
                    )
                    if leading_visual >= 0.72 and identity_agreement >= 0.75:
                        leading["retrieval_only"] = False
                        leading["provisional"] = True
                        leading["set_locked_identity_agreement"] = True
            locked_set_mismatch = self._locked_set_mismatch(
                validated_number,
                observed_language,
                active_set if set_context.get("locked") else {},
                candidates,
            )
            if locked_set_mismatch:
                # Do not surface plausible-looking identities from the wrong
                # locked set. Preserve observed OCR so the operator can fix the
                # set context without losing the useful scan evidence.
                candidates = []
                visual_candidates = []
                ocr_candidates = []
                language = observed_language
            stage_timings["ranking_ms"] = round(
                (time.perf_counter() - ranking_started) * 1000, 1
            )
            ranking_finished = time.perf_counter()

            diagnostics_payload: dict[str, Any] = {}
            if self.recognition_diagnostics is not None:
                diagnostics_payload = self.recognition_diagnostics.analyze(
                    quality=quality_payload,
                    candidates=candidates,
                    ocr_payload={
                        "text": combined,
                        "collector_number": validated_number,
                        "printed_code": printed_code,
                        "hp": hp,
                        "language": language,
                    },
                )

            pipeline_stages.append({
                "key": "candidates",
                "label": "Candidates ranked",
                "state": "done" if candidates else "waiting",
            })

            has_reference_evidence = bool(
                db_match
                or (
                    artwork_candidates
                    and any(
                        item.get("verification_strong")
                        and item.get("image_path")
                        for item in artwork_candidates
                    )
                )
            )

            top_candidate = (
                candidates[0]
                if candidates
                else {}
            )

            second_candidate = (
                candidates[1]
                if len(candidates) > 1
                else {}
            )

            top_source = str(
                top_candidate.get(
                    "source",
                    ""
                )
            ).lower()

            top_visual = float(
                top_candidate.get(
                    "visual_similarity",
                    top_candidate.get(
                        "visual_score",
                        top_candidate.get(
                            "score",
                            0.0,
                        ),
                    ),
                )
                or 0.0
            )

            top_fused = float(
                top_candidate.get(
                    "fused_score",
                    0.0,
                )
                or 0.0
            )

            second_fused = float(
                second_candidate.get(
                    "fused_score",
                    0.0,
                )
                or 0.0
            )

            score_gap = (
                top_fused
                - second_fused
            )

            artwork_locked = (
                top_source
                in {
                    "artwork_index",
                    "pokipair",
                    "pokipair_visual_index",
                }
                and top_visual >= 0.94
                and top_fused >= 0.82
                and score_gap >= 0.05
                and bool(
                    top_candidate.get(
                        "image_path"
                    )
                    or top_candidate.get(
                        "reference_image"
                    )
                    or top_candidate.get(
                        "local_image"
                    )
                )
            )

            top_signals = top_candidate.get("signals") or {}
            top_collector_score = float(
                top_signals.get("collector_number", 0.0)
            )
            standard_identifier_agreement = bool(
                collector_valid and top_collector_score >= 1.0
            )
            variant_ambiguity = self._variant_family_ambiguous(candidates)
            repeated_printed_identity = bool(
                printed_code
                and str(top_candidate.get("printed_code") or "") == printed_code
                and (
                    frame_vote_code
                    or cross_job_code
                    or catalog_visual_correction
                    or printed_code_correction
                )
            )
            printed_identity_confirmed = bool(
                (strong_printed_identifier_match and repeated_printed_identity)
                or standard_identifier_agreement
                or db_match
            )
            ocr_locked = (
                self._strong_printed_identifier_lock_ready(
                    top_candidate,
                    printed_code,
                    overall_confidence,
                    language,
                )
                or bool(db_match)
                or (
                    overall_confidence >= 0.72
                    and (
                        standard_identifier_agreement
                    )
                    and language != "Unknown"
                    and bool(top_candidate.get("verification_strong"))
                )
            )

            locked_set_reconciled_identity = (
                self._locked_set_reconciled_identity_ready(
                    top_candidate,
                    printed_code or ocr_number,
                    active_set,
                    top_visual,
                )
            )

            recognition_locked = (
                artwork_locked
                or ocr_locked
                or locked_set_reconciled_identity
            )
            if variant_ambiguity and not (
                (printed_identity_confirmed and repeated_printed_identity)
                or locked_set_reconciled_identity
            ):
                recognition_locked = False
                artwork_locked = False
                ocr_locked = False
            elif fast_path_evidence and candidates:
                recognition_locked = True
                artwork_locked = True

            if locked_set_reconciled_identity:
                printed_identity_confirmed = True
                lock_reasons = [
                    "operator-locked set",
                    "exact reconciled printed collector number",
                    f"strong visual reference {top_visual:.3f}",
                ]

            if candidates:
                overall_confidence = round(
                    max(
                        float(
                            overall_confidence
                        ),
                        top_fused,
                    ),
                    4,
                )

            if artwork_locked:
                lock_reasons = [
                    (
                        "decisive cross-index agreement"
                        if fast_path_evidence
                        else "strong artwork reference"
                    ),
                    (
                        "safe candidate gap "
                        f"{score_gap:.3f}"
                    ),
                ]

            verification_state = (
                "SET_MISMATCH"
                if locked_set_mismatch
                else "VERIFIED"
                if recognition_locked and candidates
                else "REFERENCE NEEDED"
                if candidates and not has_reference_evidence
                else "SEARCHING"
            )

            pipeline_stages.append({
                "key": "verify",
                "label": "Final verification",
                "state": "done" if verification_state == "VERIFIED" else "waiting",
            })

            finalize_ms = round(
                (time.perf_counter() - ranking_finished) * 1000,
                1,
            )
            total_ms = round((time.perf_counter() - started) * 1000, 1)
            capture_to_result_ms = round(
                max(0.0, time.time() - float(captured_at or worker_started_at))
                * 1000,
                1,
            )
            stage_timings.update({
                "finalize_ms": max(0.0, finalize_ms),
                "total_ms": total_ms,
                "capture_to_result_ms": capture_to_result_ms,
                "path": recognition_path,
                "skipped_stages": skipped_stages,
            })
            latency_summary = self._record_latency(
                recognition_path,
                total_ms,
                capture_to_result_ms,
            )
            payload = {
                "enabled": True,
                "busy": False,
                "mode": "ARTEMIS_INDEX",
                "last_latency_ms": total_ms,
                "capture_to_result_ms": capture_to_result_ms,
                "stage_timings": stage_timings,
                "recognition_path": recognition_path,
                "fast_path": fast_path_evidence,
                "latency_summary": latency_summary,
                "raw_text": items,
                "name_candidate": name,
                "hp_candidate": hp,
                "ocr_collector_number": ocr_number,
                "ocr_printed_code": printed_code,
                "collector_number": validated_number,
                "language": language,
                "confidence": round(
                    float(ocr_confidence),
                    3,
                ),
                "text_detected": bool(items),
                "database_match": db_match,
                "database_confidence": round(
                    float(db_confidence),
                    3,
                ),
                "correction_applied": correction_applied,
                "overall_confidence": overall_confidence,
                "recognition_locked": recognition_locked,
                "locked_set_reconciled_identity": locked_set_reconciled_identity,
                "variant_ambiguity": variant_ambiguity,
                "printed_identity_confirmed": printed_identity_confirmed,
                "has_reference_evidence": has_reference_evidence,
                "verification_state": verification_state,
                "set_mismatch": locked_set_mismatch,
                "pipeline_stages": pipeline_stages,
                "lock_reason": (
                    ", ".join(lock_reasons)
                    if recognition_locked
                    else None
                ),
                "candidates": candidates,
                "candidate_count": len(candidates),
                "quality": quality_payload,
                "collector_ocr": {
                    "card_shape": list(detail_card.shape),
                    "region_shape": list(
                        self._collector_region(detail_card).shape
                    ),
                    "frames_considered": len(selected_collector_frames),
                    "frames_evaluated": len(collector_diagnostics),
                    "retry_used": collector_retry_used,
                    "retry_texts": [item.get("text") for item in collector_retry_items],
                    "printed_code": printed_code,
                    "printed_code_source": printed_code_source,
                    "frame_votes": dict(frame_identifier_votes),
                    "frame_vote_winner": frame_vote_code,
                    "frame_vote_count": frame_vote_count,
                    "cross_job_votes": cross_job_votes,
                    "cross_job_winner": cross_job_code,
                    "cross_job_count": cross_job_count,
                    "reference_aware_correction": printed_code_correction,
                    "catalog_visual_correction": catalog_visual_correction,
                    "reference_match": strong_printed_identifier_match,
                    "reference_match_mode": next(
                        (
                            item.get("printed_code_match_mode")
                            for item in artwork_candidates
                            if item.get("printed_code_match")
                        ),
                        None,
                    ),
                    "diagnostics": collector_diagnostics,
                },
                "collector_retry_recommended": self._collector_retry_needed(
                    artwork_candidates=artwork_candidates,
                    fast_path_evidence=fast_path_evidence,
                    strong_printed_identifier_match=strong_printed_identifier_match,
                ),
                "diagnostics": diagnostics_payload,
                "intelligence_version": "X7",
                "provisional_candidate": bool(
                    candidates and candidates[0].get("provisional")
                ),
                "artwork_fingerprint": fingerprint,
                "active_set": self.set_catalog.status(),
                "live_catalog": self.live_catalog.status(),
                "artwork_index": {
                    "status": self.artwork_index.status(),
                    "search_ms": artwork_ms,
                    "top_score": round(
                        artwork_top_score,
                        4,
                    ),
                    "matches": artwork_candidates,
                },
                "regions": {
                    "top": bool(top_items),
                    "bottom": bool(bottom_items),
                    "artwork": True,
                    "full": bool(full_items),
                },
                "error": None,
                "updated_at": time.time(),
            }
            if early_exact_resolution:
                payload["exact_reference_diagnostics"] = (
                    early_exact_resolution.get("diagnostics") or {}
                )
            if early_exact_reference:
                payload.update({
                    "database_match": dict(early_exact_reference),
                    "recognition_locked": True,
                    "verification_state": "VERIFIED",
                    "has_reference_evidence": True,
                    "lock_reason": "early strict local reference resolution",
                    "exact_reference_resolved": True,
                })
            if payload.get("recognition_locked") and payload.get("candidates"):
                verified_number = str(
                    payload.get("collector_number")
                    or payload["candidates"][0].get("collector_number")
                    or ""
                ).strip()
                payload["pack_transition_observed"] = (
                    self.artwork_index.observe_verified_card(
                        verified_number,
                        payload.get("overall_confidence")
                        or payload.get("database_confidence")
                        or payload.get("confidence"),
                    )
                )
                predicted_records = self.artwork_index.predicted_transition_records(verified_number)
                payload["pack_prediction_prefetch_queued"] = (
                    self.prediction_prefetcher(predicted_records)
                    if predicted_records and self.prediction_prefetcher is not None else 0
                )
                payload["artwork_index"]["status"] = self.artwork_index.status()

        except Exception as exc:
            payload = {
                "enabled": True,
                "busy": False,
                "mode": "ARTEMIS_INDEX",
                "last_latency_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "stage_timings": {},
                "raw_text": [],
                "name_candidate": None,
                "hp_candidate": None,
                "ocr_collector_number": None,
                "ocr_printed_code": None,
                "collector_number": None,
                "language": None,
                "confidence": 0.0,
                "text_detected": False,
                "database_match": None,
                "database_confidence": 0.0,
                "correction_applied": False,
                "overall_confidence": 0.0,
                "recognition_locked": False,
                "lock_reason": None,
                "candidates": [],
                "candidate_count": 0,
                "artwork_fingerprint": None,
                "artwork_index": {
                    "status": self.artwork_index.status(),
                    "search_ms": 0.0,
                    "top_score": 0.0,
                    "matches": [],
                },
                "regions": {
                    "top": False,
                    "bottom": False,
                    "artwork": False,
                    "full": False,
                },
                "error": str(exc),
                "updated_at": time.time(),
            }

        payload.update({
            "generation": generation,
            "frame_id": frame_id,
            "capture_source": source,
        })
        if (
            not payload.get("recognition_locked")
            and self.exact_reference_resolver is not None
            and payload.get("candidates")
            and "manual-picked-slot-" in str(source)
        ):
            top = payload["candidates"][0]
            canonical = str(
                top.get("canonical_name")
                or top.get("english_name")
                or top.get("pokemon_name")
                or ""
            ).strip()
            resolution = (
                early_exact_resolution
                if 'early_exact_resolution' in locals()
                and early_exact_resolution
                and canonical.casefold() == early_canonical.casefold()
                else self.exact_reference_resolver(self._prepare_card(frame), canonical)
            )
            reference = resolution.get("card") if isinstance(resolution, dict) else None
            diagnostics = (
                resolution.get("diagnostics")
                if isinstance(resolution, dict)
                else None
            )
            if diagnostics:
                payload["exact_reference_diagnostics"] = diagnostics
            if reference:
                payload.update({
                    "database_match": dict(reference),
                    "recognition_locked": True,
                    "verification_state": "VERIFIED",
                    "has_reference_evidence": True,
                    "lock_reason": "strict local reference score and margin",
                    "exact_reference_resolved": True,
                })
        self._apply_single_temporal_confirmation(payload)
        self._enforce_payload_printed_code_consistency(payload)

        with self._lock:
            current = self._current_generation
            self._busy = False
            if generation == current:
                self._status.update(payload)
            else:
                self._status["busy"] = False

        if generation == current:
            self.emit({
                "type": "recognition_update",
                "payload": payload,
            })
        else:
            self.emit({
                "type": "recognition_discarded",
                "payload": {
                    "generation": generation,
                    "current_generation": current,
                    "frame_id": frame_id,
                },
            })
