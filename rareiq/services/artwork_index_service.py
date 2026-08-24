from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
import argparse
import hashlib

import cv2
import numpy as np


class ArtworkIndexService:
    # Live cross-card acceptance showed exact-variant marker evidence can
    # remain geometrically plausible across adjacent Chinese printings.
    # Keep the implementation quarantined until stronger independent evidence exists.
    EXACT_VARIANT_FAST_PATH_ENABLED = False
    FIRST_STAGE_LIMIT = 24
    ARTWORK_STAGE_LIMIT = 12
    OUTPUT_LIMIT = 10
    HINTED_VERIFY_LIMIT = 4
    RECENT_IDENTITY_CACHE_LIMIT = 32
    RECENT_IDENTITY_MAX_DISTANCE = 6
    ACTIVE_SET_CACHE_LIMIT = 2048
    REFERENCE_PREWARM_LIMIT = 24
    NEIGHBOR_PREWARM_LIMIT = 12
    NEIGHBOR_PREWARM_MIN = 8
    NEIGHBOR_PREWARM_MAX = 24
    PACK_TRANSITION_CONTEXT_LIMIT = 256
    PACK_TRANSITION_TTL_SECONDS = 30 * 24 * 60 * 60
    PACK_TRANSITION_MIN_CONFIDENCE = 0.80
    PACK_TRANSITION_MIN_OBSERVATIONS = 2
    PACK_TRANSITION_MIN_DOMINANCE = 0.60
    PACK_TRANSITION_RECENCY_HALF_LIFE_SECONDS = 7 * 24 * 60 * 60
    PACK_TRANSITION_UNDO_SECONDS = 30
    PACK_TRANSITION_BACKUP_LIMIT = 5
    FAILED_VERIFICATION_CAP = 0.49
    NORMALIZED_WIDTH = 500
    NORMALIZED_HEIGHT = 700
    MIN_RATIO_MATCHES = 12
    MIN_HOMOGRAPHY_INLIERS = 10
    MIN_INLIER_RATIO = 0.35
    ARTWORK_REGION = (0.06, 0.13, 0.94, 0.52)
    MARKER_REGIONS = (
        (0.34, 0.50, 0.96, 0.83),
        (0.05, 0.82, 0.95, 0.97),
        (0.55, 0.55, 0.98, 0.86),
    )
    def __init__(self, index_path: Path | None = None) -> None:
        data_dir = Path(__file__).resolve().parents[1] / "data"
        self.reference_dir = data_dir / "reference_cards"
        self.reference_dir.mkdir(parents=True, exist_ok=True)

        self.index_path = index_path or (data_dir / "artwork_index.json")
        self.transition_model_path = self.index_path.with_name("pack_transition_model.json")
        self.transition_backup_dir = self.index_path.with_name("pack_transition_backups")
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._error: str | None = None
        self._last_rebuild: dict[str, Any] | None = None
        self._active_set_name: str | None = None
        self._active_set_id: str | None = None
        self._active_language: str | None = None
        self._active_pack_context = "default"
        self._active_pack_context_label = "Default pack context"
        self._pack_context_labels: dict[str, str] = {
            "default": "Default pack context"
        }
        self._active_records_cache: tuple[dict[str, Any], ...] | None = None
        self._active_records_cache_key: tuple[str, str, str] | None = None
        self._active_records_cache_builds = 0
        self._active_records_cache_hits = 0
        self._identity_bridge_count = 0
        self._reference_feature_cache: OrderedDict[
            str, tuple[np.ndarray, list[Any], np.ndarray | None]
        ] = OrderedDict()
        self._reference_feature_cache_lock = threading.RLock()
        self._reference_feature_cache_limit = 512
        self._reference_image_cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._reference_image_cache_limit = self.REFERENCE_PREWARM_LIMIT
        self._reference_cache_timing = {
            "image_hits": 0, "image_misses": 0, "image_decode_ms": 0.0,
            "feature_hits": 0, "feature_misses": 0, "feature_build_ms": 0.0,
            "recognition_image_hits": 0, "recognition_image_misses": 0,
            "recognition_feature_hits": 0, "recognition_feature_misses": 0,
        }
        self._cache_access_context = threading.local()
        self._pack_transition_counts: OrderedDict[
            tuple[tuple[str, str, str], int], dict[int, int]
        ] = OrderedDict()
        self._pack_transition_updated_at: dict[
            tuple[tuple[str, str, str], int], float
        ] = {}
        self._pack_transition_edge_updated_at: dict[
            tuple[tuple[tuple[str, str, str], int], int], float
        ] = {}
        self._last_verified_number_by_set: dict[tuple[str, str, str, str], int] = {}
        self._pack_transition_observations = 0
        self._pack_transition_low_confidence_rejections = 0
        self._disabled_transition_scopes: set[tuple[str, str, str, str]] = set()
        self._last_transition_removal: dict[str, Any] | None = None
        self._transition_persist_lock = threading.Lock()
        self._transition_save_running = False
        self._transition_save_dirty = False
        self._transition_persistence_error: str | None = None
        self._reference_prewarm_generation = 0
        self._reference_prewarm_stats: dict[str, Any] = {
            "state": "idle", "runs": 0, "requested": 0,
            "warmed": 0, "skipped": 0, "key": None,
            "neighbor_runs": 0, "neighbor_requested": 0,
            "neighbor_anchor": None,
        }
        self._recent_identity_cache: OrderedDict[str, str] = OrderedDict()
        self._pending_variant_identity: tuple[str, int, str] | None = None
        self._fast_cache_stats = {
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "geometry_rejections": 0,
            "stores": 0,
            "invalidations": 0,
        }
        self.load()
        self._load_pack_transition_model()

    @staticmethod
    def _override_keys(row: dict[str, Any]) -> list[str]:
        set_id = str(row.get("set_id") or "").strip().upper()
        number = str(row.get("collector_number") or "").strip()
        if not set_id or not number:
            return []
        keys = [f"{set_id}:{number}"]
        if number.isdigit():
            keys.extend(f"{set_id}:{number.zfill(width)}" for width in (3, 4))
        return list(dict.fromkeys(keys))

    @staticmethod
    def _load_identity_overrides() -> dict[str, dict[str, Any]]:
        root = Path(__file__).resolve().parents[2] / "catalog_master"
        merged: dict[str, dict[str, Any]] = {}
        for name in (
            "pokipair_identity_overrides.json",
            "stream_speed_identity_overrides.json",
        ):
            try:
                payload = json.loads((root / name).read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    merged.update(payload)
            except Exception:
                continue
        return merged

    @staticmethod
    def fingerprint(image: np.ndarray) -> str:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
        dct = cv2.dct(np.float32(small))
        block = dct[:8, :8]
        median = np.median(block[1:, :])
        bits = (block > median).flatten()

        value = 0
        for bit in bits:
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"

    @classmethod
    def _region(cls, image: np.ndarray, bounds: tuple[float, ...]) -> np.ndarray:
        height, width = image.shape[:2]
        left, top, right, bottom = bounds
        return image[
            int(top * height):int(bottom * height),
            int(left * width):int(right * width),
        ]

    @classmethod
    def artwork_fingerprint(cls, image: np.ndarray) -> str:
        normalized = cls._normalize_card(image)
        return cls.fingerprint(cls._region(normalized, cls.ARTWORK_REGION))

    @classmethod
    def variant_marker_fingerprint(cls, image: np.ndarray) -> str:
        normalized = cls._normalize_card(image)
        regions = [cls._region(normalized, bounds) for bounds in cls.MARKER_REGIONS]
        width = max(region.shape[1] for region in regions)
        stacked = np.vstack([
            cv2.resize(region, (width, 160), interpolation=cv2.INTER_AREA)
            for region in regions
        ])
        return cls.fingerprint(stacked)

    @staticmethod
    def hamming(left: str, right: str) -> int:
        return (int(left, 16) ^ int(right, 16)).bit_count()

    def load(self) -> None:
        with self._lock:
            try:
                identity_overrides = self._load_identity_overrides()
                payload = json.loads(
                    self.index_path.read_text(
                        encoding="utf-8"
                    )
                )

                rows = (
                    payload.get("records")
                    if isinstance(payload, dict)
                    else payload
                )

                if rows is None and isinstance(payload, dict):
                    rows = payload.get("references", [])

                normalized: list[dict[str, Any]] = []

                for row in rows or []:
                    if not isinstance(row, dict):
                        continue

                    fingerprint = row.get("fingerprint")

                    if not isinstance(fingerprint, str):
                        continue

                    normalized_row = {
                        **row,
                        "image_path": (
                            row.get("image_path")
                            or row.get("reference_image")
                        ),
                        "fingerprint": fingerprint,
                    }
                    override_key = next(
                        (key for key in self._override_keys(row) if key in identity_overrides),
                        None,
                    )
                    if override_key:
                        override = identity_overrides[override_key]
                        for field in (
                            "printed_name", "english_name", "canonical_name",
                            "pokemon_name", "pricing_lookup_name", "printed_code",
                        ):
                            if override.get(field):
                                normalized_row[field] = override[field]
                        normalized_row["identity_override_key"] = override_key
                    normalized.append(normalized_row)

                self._records = normalized
                self._active_records_cache = None
                self._active_records_cache_key = None
                self._reference_feature_cache.clear()
                self._reference_image_cache.clear()
                self._reference_prewarm_generation += 1
                self._reference_prewarm_stats.update({
                    "state": "idle", "requested": 0, "warmed": 0,
                    "skipped": 0, "key": None, "neighbor_requested": 0,
                    "neighbor_anchor": None,
                })
                self._recent_identity_cache.clear()
                self._pending_variant_identity = None
                self._fast_cache_stats["invalidations"] += 1
                self._identity_bridge_count = sum(
                    bool(row.get("identity_override_key")) for row in normalized
                )
                self._error = None

            except FileNotFoundError:
                self._records = []
                self._error = None

            except Exception as exc:
                self._records = []
                self._error = str(exc)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "loaded": self._error is None,
                "record_count": len(self._records),
                "index_path": str(self.index_path),
                "reference_dir": str(self.reference_dir),
                "last_rebuild": self._last_rebuild,
                "active_set_name": self._active_set_name,
                "active_set_id": self._active_set_id,
                "active_language": self._active_language,
                "error": self._error,
                "identity_bridge_count": self._identity_bridge_count,
                "fast_identity_cache": {
                    **self._fast_cache_stats,
                    "identity_entries": len(self._recent_identity_cache),
                    "reference_feature_entries": len(self._reference_feature_cache),
                    "reference_image_entries": len(self._reference_image_cache),
                    "max_fingerprint_distance": self.RECENT_IDENTITY_MAX_DISTANCE,
                },
                "warmed_set_cache": {
                    "ready": self._active_records_cache is not None,
                    "record_count": len(self._active_records_cache or ()),
                    "limit": self.ACTIVE_SET_CACHE_LIMIT,
                    "builds": self._active_records_cache_builds,
                    "hits": self._active_records_cache_hits,
                    "key": self._active_records_cache_key,
                },
                "reference_prewarm": {
                    **self._reference_prewarm_stats,
                    "limit": self.REFERENCE_PREWARM_LIMIT,
                    "neighbor_limit": self.NEIGHBOR_PREWARM_LIMIT,
                },
                "reference_cache_timing": self._reference_cache_timing_status(),
                "pack_transition_learning": {
                    "observations": self._pack_transition_observations,
                    "contexts": len(self._pack_transition_counts),
                    "active_set_last_number": self._last_verified_number_by_set.get(
                        self._transition_scope_key()
                    ),
                    "active_pack_context": self._active_pack_context,
                    "active_pack_context_label": self._active_pack_context_label,
                    "active_context_enabled": self._transition_scope_key() not in self._disabled_transition_scopes,
                    "limit": self.PACK_TRANSITION_CONTEXT_LIMIT,
                    "ttl_days": self.PACK_TRANSITION_TTL_SECONDS // 86400,
                    "model_path": str(self.transition_model_path),
                    "persistence_error": self._transition_persistence_error,
                    "minimum_confidence": self.PACK_TRANSITION_MIN_CONFIDENCE,
                    "low_confidence_rejections": self._pack_transition_low_confidence_rejections,
                    "minimum_observations": self.PACK_TRANSITION_MIN_OBSERVATIONS,
                    "minimum_dominance": self.PACK_TRANSITION_MIN_DOMINANCE,
                    "recency_half_life_days": self.PACK_TRANSITION_RECENCY_HALF_LIFE_SECONDS // 86400,
                    "promoted_transitions": sum(
                        count >= self.PACK_TRANSITION_MIN_OBSERVATIONS
                        for counts in self._pack_transition_counts.values()
                        for count in counts.values()
                    ),
                    "pending_transitions": sum(
                        count < self.PACK_TRANSITION_MIN_OBSERVATIONS
                        for counts in self._pack_transition_counts.values()
                        for count in counts.values()
                    ),
                    "competing_contexts": sum(
                        len(counts) > 1 for counts in self._pack_transition_counts.values()
                    ),
                    "suppressed_ambiguous_contexts": sum(
                        bool(counts) and len(counts) > 1
                        and max(counts.values()) / sum(counts.values()) < self.PACK_TRANSITION_MIN_DOMINANCE
                        for counts in self._pack_transition_counts.values()
                    ),
                },
            }

    def _reference_cache_timing_status(self) -> dict[str, Any]:
        with self._reference_feature_cache_lock:
            stats = dict(self._reference_cache_timing)
        image_misses = int(stats["image_misses"])
        feature_misses = int(stats["feature_misses"])
        average_decode = float(stats["image_decode_ms"]) / max(1, image_misses)
        average_build = float(stats["feature_build_ms"]) / max(1, feature_misses)
        saved = (
            int(stats["image_hits"]) * average_decode
            + int(stats["feature_hits"]) * average_build
        )
        recognition_hits = int(stats["recognition_image_hits"]) + int(
            stats["recognition_feature_hits"]
        )
        recognition_misses = int(stats["recognition_image_misses"]) + int(
            stats["recognition_feature_misses"]
        )
        recognition_total = recognition_hits + recognition_misses
        recognition_hit_rate = recognition_hits / max(1, recognition_total)
        return {
            **stats,
            "average_image_decode_ms": round(average_decode, 3),
            "average_feature_build_ms": round(average_build, 3),
            "estimated_saved_ms": round(saved, 2),
            "warm_hits": int(stats["image_hits"]) + int(stats["feature_hits"]),
            "recognition_hits": recognition_hits,
            "recognition_misses": recognition_misses,
            "recognition_hit_rate": round(recognition_hit_rate, 4),
            "adaptive_neighbor_limit": self._adaptive_neighbor_limit(
                recognition_hits, recognition_misses
            ),
        }

    def _adaptive_neighbor_limit(
        self, hits: int | None = None, misses: int | None = None
    ) -> int:
        if hits is None or misses is None:
            with self._reference_feature_cache_lock:
                hits = int(self._reference_cache_timing["recognition_image_hits"]) + int(
                    self._reference_cache_timing["recognition_feature_hits"]
                )
                misses = int(self._reference_cache_timing["recognition_image_misses"]) + int(
                    self._reference_cache_timing["recognition_feature_misses"]
                )
        total = int(hits) + int(misses)
        if total < 8:
            return self.NEIGHBOR_PREWARM_LIMIT
        hit_rate = int(hits) / max(1, total)
        if hit_rate < 0.35:
            return self.NEIGHBOR_PREWARM_MAX
        if hit_rate >= 0.75:
            return self.NEIGHBOR_PREWARM_MIN
        return self.NEIGHBOR_PREWARM_LIMIT

    def _record_cache_metric(self, key: str, amount: float = 1) -> None:
        self._reference_cache_timing[key] += amount
        if getattr(self._cache_access_context, "mode", "recognition") == "recognition":
            recognition_key = f"recognition_{key}"
            if recognition_key in self._reference_cache_timing:
                self._reference_cache_timing[recognition_key] += amount

    def records_for_printed_code(self, printed_code: str) -> list[dict[str, Any]]:
        code = str(printed_code or "").strip()
        if not code:
            return []
        with self._lock:
            return [
                dict(row) for row in self._records
                if str(row.get("printed_code") or "").strip() == code
            ]

    def nearest_printed_code_records(
        self, printed_code: str, *, max_distance: int = 1
    ) -> list[dict[str, Any]]:
        code = str(printed_code or "").strip()
        if not code:
            return []
        with self._lock:
            records = list(self._records)
        return [
            dict(row) for row in records
            if len(str(row.get("printed_code") or "").strip()) == len(code)
            and sum(
                left != right for left, right in zip(
                    code, str(row.get("printed_code") or "").strip(), strict=True
                )
            ) <= max(0, int(max_distance))
        ]

    @staticmethod
    def _identity_hint_keys(candidate: dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        for field in ("id", "identity_override_key"):
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

    @staticmethod
    def _readable_hint_image(candidate: dict[str, Any]) -> str | None:
        """Return a real local reference supplied by another bounded index."""
        for field in ("image_path", "reference_image", "local_image"):
            value = str(candidate.get(field) or "").strip()
            if value and Path(value).is_file():
                return value
        return None

    def search_hinted(
        self,
        artwork: np.ndarray | None,
        identity_hints: list[dict[str, Any]],
        *,
        limit: int = HINTED_VERIFY_LIMIT,
    ) -> dict[str, Any]:
        """Verify a tiny identity-matched subset before exhaustive search."""
        started = time.perf_counter()
        if artwork is None or not getattr(artwork, "size", 0):
            return {"ok": False, "matches": [], "latency_ms": 0.0, "hint_hits": 0}
        hint_keys = set().union(*(
            self._identity_hint_keys(candidate) for candidate in identity_hints
        )) if identity_hints else set()
        if not hint_keys:
            return {"ok": True, "matches": [], "latency_ms": 0.0, "hint_hits": 0}

        records = self._records_for_active_filter()
        indexed_hints = [
            record for record in records
            if self._identity_hint_keys(record) & hint_keys
        ]
        query = self.fingerprint(artwork)
        live_verification_features = self._verification_features(artwork)
        indexed_hints.sort(
            key=lambda row: self.hamming(query, str(row["fingerprint"]))
        )

        # The global visual catalog already supplies source-addressable local
        # references. Verify only its bounded leading hints when the smaller
        # artwork index does not contain those identities; never scan the image
        # catalog or silently mutate the active index here.
        hinted: list[dict[str, Any]] = [dict(row) for row in indexed_hints]
        present = {
            str(row.get("id") or row.get("image_path") or "").casefold()
            for row in hinted
        }
        for candidate in identity_hints:
            if len(hinted) >= max(1, int(limit)):
                break
            reference_path = self._readable_hint_image(candidate)
            identity = str(
                candidate.get("id") or reference_path or ""
            ).casefold()
            if not reference_path or identity in present:
                continue
            hinted.append({
                **dict(candidate),
                "image_path": reference_path,
                "external_identity_hint": True,
            })
            present.add(identity)

        matches: list[dict[str, Any]] = []
        for rank, row in enumerate(hinted[:max(1, int(limit))]):
            image_path = row.get("image_path")
            reference = self._cached_reference_image(image_path)
            reference_fingerprint = str(row.get("fingerprint") or "")
            if not reference_fingerprint and reference is not None:
                reference_fingerprint = self.fingerprint(reference)
            distance = (
                self.hamming(query, reference_fingerprint)
                if reference_fingerprint
                else 64
            )
            hash_score = max(0.0, 1.0 - distance / 64.0)
            reference_features = self._cached_reference_features(
                image_path, reference
            )
            evidence = (
                self._second_stage_from_features(
                    live_verification_features, reference_features
                )
                if reference_features is not None
                else self._second_stage_evidence(artwork, reference)
            )
            item = {
                **row,
                "distance": distance,
                "hash_score": round(hash_score, 4),
                "score": round(
                    0.40 * hash_score + 0.60 * float(evidence["verification_score"]),
                    4,
                ) if evidence["verification_strong"] else round(min(
                    self.FAILED_VERIFICATION_CAP, hash_score * 0.55
                ), 4),
                "first_stage_rank": rank + 1,
                "reference_readable": reference is not None,
                "hinted_preflight": True,
                **evidence,
            }
            if evidence["verification_strong"]:
                item.update(self._artwork_region_evidence(artwork, reference))
            else:
                item["retrieval_only"] = True
            matches.append(item)
        matches.sort(key=lambda row: -float(row.get("score", 0.0)))
        return {
            "ok": True,
            "query_fingerprint": query,
            "matches": matches,
            "hint_hits": len(hinted),
            "indexed_hint_hits": len(indexed_hints),
            "external_hint_hits": sum(
                1 for row in hinted if row.get("external_identity_hint")
            ),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": None,
        }

    @staticmethod
    def _apply_identity_consensus(candidates: list[dict[str, Any]]) -> None:
        counts: dict[str, int] = {}
        for item in candidates:
            identity = str(item.get("printed_code") or "").strip()
            if identity and item.get("verification_strong"):
                counts[identity] = counts.get(identity, 0) + 1
        for item in candidates:
            identity = str(item.get("printed_code") or "").strip()
            consensus = counts.get(identity, 0)
            if consensus >= 2 and item.get("verification_strong"):
                item["identity_consensus_count"] = consensus
                item["identity_consensus_boost"] = 0.08
                item["score"] = round(min(1.0, float(item["score"]) + 0.08), 4)

    def rebuild(self) -> dict[str, Any]:
        started = time.perf_counter()
        supported = {".jpg", ".jpeg", ".png", ".webp"}
        records: list[dict[str, Any]] = []
        skipped: list[str] = []

        for image_path in sorted(self.reference_dir.rglob("*")):
            if not image_path.is_file() or image_path.suffix.lower() not in supported:
                continue

            metadata_path = image_path.with_suffix(".json")
            metadata: dict[str, Any] = {}

            if metadata_path.exists():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except Exception:
                    skipped.append(f"{image_path.name}: invalid metadata JSON")
                    continue

            image = cv2.imread(str(image_path))
            if image is None:
                skipped.append(f"{image_path.name}: unreadable image")
                continue

            record = {
                "id": metadata.get("id") or image_path.stem,
                "name": metadata.get("name") or image_path.stem,
                "printed_name": metadata.get("printed_name"),
                "collector_number": metadata.get("collector_number"),
                "language": metadata.get("language") or "Unknown",
                "set_name": metadata.get("set_name"),
                "rarity": metadata.get("rarity"),
                "image_path": str(image_path),
                "fingerprint": self.fingerprint(image),
                "artwork_fingerprint": self.artwork_fingerprint(image),
                "variant_marker_fingerprint": self.variant_marker_fingerprint(image),
            }
            records.append(record)

        payload = {
            "version": 2,
            "generated_at": time.time(),
            "records": records,
        }
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._lock:
            self._records = records
            self._error = None
            self._last_rebuild = {
                "records": len(records),
                "skipped": skipped,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "completed_at": time.time(),
            }

        return {
            "ok": True,
            "status": self.status(),
            "skipped": skipped,
        }

    def enrich_optional_fingerprints(self) -> dict[str, Any]:
        """Explicitly enrich the active index; never called during search."""
        with self._lock:
            records = [dict(row) for row in self._records]
        enriched = 0
        skipped = []
        for row in records:
            if row.get("artwork_fingerprint") and row.get("variant_marker_fingerprint"):
                continue
            image_path = row.get("image_path")
            image = cv2.imread(str(image_path)) if image_path else None
            if image is None:
                skipped.append(str(row.get("id") or image_path or "unknown"))
                continue
            row["artwork_fingerprint"] = self.artwork_fingerprint(image)
            row["variant_marker_fingerprint"] = self.variant_marker_fingerprint(image)
            enriched += 1
        payload = {"version": 3, "generated_at": time.time(), "records": records}
        temporary = self.index_path.with_suffix(self.index_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.index_path)
        self.load()
        return {"ok": True, "enriched": enriched, "skipped": skipped}

    def set_active_filter(
        self,
        set_name: str | None,
        language: str | None,
        set_id: str | None = None,
    ) -> None:
        prewarm_records: tuple[dict[str, Any], ...] = ()
        prewarm_key: tuple[str, str, str] | None = None
        with self._lock:
            self._active_set_name = (
                None if not set_name or set_name == "All Loaded References"
                else str(set_name)
            )
            self._active_set_id = (
                None if not set_id or set_id == "all-loaded"
                else str(set_id)
            )
            self._active_language = (
                None if not language or language in {"Any", "Unknown"}
                else str(language)
            )
            key = (
                str(self._active_set_id or "").casefold(),
                str(self._active_set_name or "").casefold(),
                str(self._active_language or "").casefold(),
            )
            filtered = [
                row for row in self._records
                if self._record_matches_set(row)
                and (
                    not self._active_language
                    or str(row.get("language") or "").casefold()
                    == self._active_language.casefold()
                )
            ]
            self._active_records_cache = (
                tuple(filtered)
                if (self._active_set_id or self._active_set_name)
                and len(filtered) <= self.ACTIVE_SET_CACHE_LIMIT
                else None
            )
            self._active_records_cache_key = key if self._active_records_cache is not None else None
            self._active_records_cache_builds += int(self._active_records_cache is not None)
            self._reference_prewarm_generation += 1
            generation = self._reference_prewarm_generation
            if self._active_records_cache:
                prewarm_records = self._active_records_cache[:self.REFERENCE_PREWARM_LIMIT]
                prewarm_key = self._active_records_cache_key
            self._recent_identity_cache.clear()
            self._pending_variant_identity = None
            self._fast_cache_stats["invalidations"] += 1
        if prewarm_records and prewarm_key is not None:
            self._start_reference_prewarm(
                prewarm_records, prewarm_key, generation
            )

    def set_pack_context(self, context: str | None, label: str | None = None) -> str:
        """Isolate learned ordering by pack/product configuration within a set."""
        normalized = re.sub(r"[^a-z0-9._-]+", "-", str(context or "default").strip().casefold()).strip("-")
        with self._lock:
            self._active_pack_context = normalized or "default"
            fallback = ("Default pack context" if self._active_pack_context == "default"
                        else self._active_pack_context.replace("-", " ").title())
            if label:
                self._pack_context_labels[self._active_pack_context] = str(label).strip()[:120]
            self._active_pack_context_label = self._pack_context_labels.setdefault(
                self._active_pack_context, fallback
            )
        return self._active_pack_context

    def rename_active_pack_context(self, label: str) -> dict[str, Any]:
        """Rename the operator-facing product label without changing its stable scope."""
        normalized_label = " ".join(str(label or "").split()).strip()[:120]
        if not normalized_label:
            raise ValueError("Pack product name cannot be empty.")
        with self._lock:
            self._pack_context_labels[self._active_pack_context] = normalized_label
            self._active_pack_context_label = normalized_label
        self._schedule_transition_model_save()
        return {
            "context": self._active_pack_context,
            "context_label": normalized_label,
        }

    def _transition_scope_key(self) -> tuple[str, str, str, str]:
        key = self._active_records_cache_key or ("", "", "")
        return (*key, self._active_pack_context)

    def transition_context_status(self) -> dict[str, Any]:
        with self._lock:
            scope = self._transition_scope_key()
            undo = self._last_transition_removal
            undo_available = bool(
                undo and undo.get("scope") == scope
                and time.time() - float(undo.get("removed_at") or 0) <= self.PACK_TRANSITION_UNDO_SECONDS
            )
            contexts = [
                {"from": context[1], "successors": dict(counts),
                 "updated_at": self._pack_transition_updated_at.get(context)}
                for context, counts in self._pack_transition_counts.items()
                if context[0] == scope
            ]
            return {"scope": list(scope), "enabled": scope not in self._disabled_transition_scopes,
                    "contexts": contexts, "context_count": len(contexts),
                    "context_label": self._active_pack_context_label,
                    "undo_available": undo_available,
                    "undo_seconds": self.PACK_TRANSITION_UNDO_SECONDS}

    def set_transition_context_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            scope = self._transition_scope_key()
            if enabled:
                self._disabled_transition_scopes.discard(scope)
            else:
                self._disabled_transition_scopes.add(scope)
        self._schedule_transition_model_save()
        return self.transition_context_status()

    def reset_transition_context(self) -> dict[str, Any]:
        backup = self._archive_transition_context("before-reset")
        with self._lock:
            scope = self._transition_scope_key()
            removed = [context for context in self._pack_transition_counts if context[0] == scope]
            for context in removed:
                self._pack_transition_counts.pop(context, None)
                self._pack_transition_updated_at.pop(context, None)
                for edge in [edge for edge in self._pack_transition_edge_updated_at if edge[0] == context]:
                    self._pack_transition_edge_updated_at.pop(edge, None)
            self._last_verified_number_by_set.pop(scope, None)
        self._schedule_transition_model_save()
        return {**self.transition_context_status(), "removed_contexts": len(removed),
                "backup_path": str(backup) if backup else None}

    def remove_transition(self, from_number: int, to_number: int) -> dict[str, Any]:
        """Remove one operator-identified bad edge from the active product only."""
        with self._lock:
            scope = self._transition_scope_key()
            context = (scope, int(from_number))
            counts = self._pack_transition_counts.get(context)
            removed_count = int((counts or {}).pop(int(to_number), 0))
            edge_updated_at = self._pack_transition_edge_updated_at.pop((context, int(to_number)), None)
            if counts == {}:
                self._pack_transition_counts.pop(context, None)
                self._pack_transition_updated_at.pop(context, None)
            if removed_count:
                self._last_transition_removal = {
                    "scope": scope, "from": int(from_number), "to": int(to_number),
                    "count": removed_count, "updated_at": edge_updated_at,
                    "removed_at": time.time(),
                }
        if removed_count:
            self._schedule_transition_model_save()
        return {**self.transition_context_status(), "removed_count": removed_count,
                "from": int(from_number), "to": int(to_number)}

    def undo_transition_removal(self) -> dict[str, Any]:
        with self._lock:
            scope = self._transition_scope_key()
            removal = self._last_transition_removal
            valid = bool(removal and removal.get("scope") == scope and
                         time.time() - float(removal.get("removed_at") or 0) <= self.PACK_TRANSITION_UNDO_SECONDS)
            restored_count = 0
            if valid:
                context = (scope, int(removal["from"]))
                counts = self._pack_transition_counts.setdefault(context, {})
                target = int(removal["to"])
                counts[target] = counts.get(target, 0) + int(removal["count"])
                updated_at = float(removal.get("updated_at") or time.time())
                self._pack_transition_edge_updated_at[(context, target)] = updated_at
                self._pack_transition_updated_at[context] = max(
                    updated_at, self._pack_transition_updated_at.get(context, 0)
                )
                restored_count = int(removal["count"])
                self._last_transition_removal = None
        if not restored_count:
            return {**self.transition_context_status(), "restored_count": 0}
        self._schedule_transition_model_save()
        return {**self.transition_context_status(), "restored_count": restored_count}

    def export_transition_context(self) -> dict[str, Any]:
        with self._lock:
            scope = self._transition_scope_key()
            entries = [
                {"from": context[1], "to": target, "count": count,
                 "updated_at": self._pack_transition_edge_updated_at.get(
                     (context, target), self._pack_transition_updated_at.get(context, time.time())
                 )}
                for context, counts in self._pack_transition_counts.items()
                if context[0] == scope
                for target, count in counts.items()
            ]
            enabled = scope not in self._disabled_transition_scopes
        positions = len({entry["from"] for entry in entries})
        payload = {"format": "rareiq-pack-learning", "version": 2,
                "exported_at": time.time(), "scope": list(scope),
                "enabled": enabled, "entries": entries,
                "metadata": {"positions": positions, "transitions": len(entries),
                             "observations": sum(entry["count"] for entry in entries),
                             "product_label": self._active_pack_context_label,
                             "minimum_confidence": self.PACK_TRANSITION_MIN_CONFIDENCE,
                             "minimum_observations": self.PACK_TRANSITION_MIN_OBSERVATIONS}}
        payload["checksum"] = {"algorithm": "sha256", "value": self._backup_checksum(payload)}
        return payload

    @staticmethod
    def _backup_checksum(payload: dict[str, Any]) -> str:
        unsigned = dict(payload)
        unsigned.pop("checksum", None)
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def preview_transition_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            active_scope = self._transition_scope_key()
        valid_format = isinstance(payload, dict) and payload.get("format") == "rareiq-pack-learning"
        checksum = payload.get("checksum") if isinstance(payload, dict) else None
        integrity_valid = bool(
            isinstance(checksum, dict) and checksum.get("algorithm") == "sha256"
            and isinstance(checksum.get("value"), str)
            and checksum.get("value") == self._backup_checksum(payload)
        )
        incoming_scope = payload.get("scope") if isinstance(payload, dict) else None
        valid_scope = isinstance(incoming_scope, list) and len(incoming_scope) == 4
        scope_matches = valid_scope and tuple(map(str, incoming_scope)) == active_scope
        entries = payload.get("entries") if isinstance(payload, dict) else None
        valid_entries = isinstance(entries, list)
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        compatible = bool(valid_format and integrity_valid and valid_scope and scope_matches and valid_entries)
        reason = None
        if not valid_format:
            reason = "Not a RareIQ pack-learning backup."
        elif not integrity_valid:
            reason = "Backup integrity check failed; the file is incomplete or modified."
        elif not valid_scope:
            reason = "Backup scope is missing or invalid."
        elif not scope_matches:
            reason = "Backup scope does not match the active set, language, and product."
        elif not valid_entries:
            reason = "Backup transition entries are missing or invalid."
        return {"compatible": compatible, "reason": reason,
                "integrity_valid": integrity_valid,
                "checksum_algorithm": checksum.get("algorithm") if isinstance(checksum, dict) else None,
                "version": payload.get("version") if isinstance(payload, dict) else None,
                "exported_at": payload.get("exported_at") if isinstance(payload, dict) else None,
                "scope": incoming_scope, "active_scope": list(active_scope),
                "enabled": payload.get("enabled", True) if isinstance(payload, dict) else None,
                "product_label": (metadata or {}).get("product_label") or (
                    incoming_scope[3] if valid_scope else "Unknown product"
                ),
                "positions": int((metadata or {}).get("positions") or len({
                    row.get("from") for row in entries or [] if isinstance(row, dict)
                })),
                "transitions": int((metadata or {}).get("transitions") or len(entries or [])),
                "observations": int((metadata or {}).get("observations") or sum(
                    int(row.get("count") or 0) for row in entries or [] if isinstance(row, dict)
                ))}

    def import_transition_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.preview_transition_import(payload)
        if not preview["compatible"]:
            raise ValueError(str(preview["reason"]))
        incoming_scope = payload.get("scope")
        with self._lock:
            scope = self._transition_scope_key()
        parsed: list[tuple[int, int, int, float]] = []
        for row in payload.get("entries") or []:
            if not isinstance(row, dict):
                raise ValueError("Backup contains an invalid transition entry.")
            source, target, count = int(row["from"]), int(row["to"]), int(row["count"])
            if not (0 <= source <= 9999 and 0 <= target <= 9999 and 1 <= count <= 1_000_000):
                raise ValueError("Backup transition values are outside supported limits.")
            updated_at = min(time.time(), max(
                time.time() - self.PACK_TRANSITION_TTL_SECONDS,
                float(row.get("updated_at") or time.time()),
            ))
            parsed.append((source, target, count, updated_at))
        if len(parsed) > self.PACK_TRANSITION_CONTEXT_LIMIT * 8:
            raise ValueError("Backup contains too many transition entries.")
        backup = self._archive_transition_context("before-import")
        with self._lock:
            contexts = [context for context in self._pack_transition_counts if context[0] == scope]
            for context in contexts:
                self._pack_transition_counts.pop(context, None)
                self._pack_transition_updated_at.pop(context, None)
                for edge in [edge for edge in self._pack_transition_edge_updated_at if edge[0] == context]:
                    self._pack_transition_edge_updated_at.pop(edge, None)
            for source, target, count, updated_at in parsed:
                context = (scope, source)
                counts = self._pack_transition_counts.setdefault(context, {})
                counts[target] = counts.get(target, 0) + count
                self._pack_transition_updated_at[context] = max(
                    updated_at, self._pack_transition_updated_at.get(context, 0)
                )
                self._pack_transition_edge_updated_at[(context, target)] = updated_at
            if payload.get("enabled", True):
                self._disabled_transition_scopes.discard(scope)
            else:
                self._disabled_transition_scopes.add(scope)
            self._last_verified_number_by_set.pop(scope, None)
        self._schedule_transition_model_save()
        return {**self.transition_context_status(), "imported_entries": len(parsed),
                "backup_path": str(backup) if backup else None}

    def _archive_transition_context(self, reason: str) -> Path | None:
        payload = self.export_transition_context()
        if not payload.get("entries"):
            return None
        payload["archive_reason"] = str(reason)
        payload["checksum"] = {"algorithm": "sha256", "value": self._backup_checksum(payload)}
        scope_token = hashlib.sha256(
            "|".join(payload["scope"]).encode("utf-8")
        ).hexdigest()[:12]
        self.transition_backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.transition_backup_dir / f"{scope_token}-{time.time_ns()}-{reason}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        backups = sorted(
            self.transition_backup_dir.glob(f"{scope_token}-*.json"),
            key=lambda item: item.stat().st_mtime_ns, reverse=True,
        )
        for stale in backups[self.PACK_TRANSITION_BACKUP_LIMIT:]:
            stale.unlink(missing_ok=True)
        return path

    def list_transition_backups(self) -> list[dict[str, Any]]:
        with self._lock:
            scope = self._transition_scope_key()
        scope_token = hashlib.sha256("|".join(scope).encode("utf-8")).hexdigest()[:12]
        results = []
        for path in sorted(
            self.transition_backup_dir.glob(f"{scope_token}-*.json")
            if self.transition_backup_dir.exists() else [],
            key=lambda item: item.stat().st_mtime_ns, reverse=True,
        )[:self.PACK_TRANSITION_BACKUP_LIMIT]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                preview = self.preview_transition_import(payload)
                results.append({"backup_id": path.name,
                                "reason": payload.get("archive_reason") or "manual",
                                **preview})
            except Exception as exc:
                results.append({"backup_id": path.name, "compatible": False,
                                "integrity_valid": False, "reason": str(exc)})
        return results

    def restore_transition_backup(self, backup_id: str) -> dict[str, Any]:
        safe_name = Path(str(backup_id)).name
        if safe_name != str(backup_id) or not safe_name.endswith(".json"):
            raise ValueError("Invalid recovery backup identifier.")
        path = self.transition_backup_dir / safe_name
        if not path.is_file():
            raise ValueError("Recovery backup was not found.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        preview = self.preview_transition_import(payload)
        if not preview["compatible"]:
            raise ValueError(str(preview["reason"] or "Recovery backup is incompatible."))
        return {**self.import_transition_context(payload), "restored_backup_id": safe_name}

    def _start_reference_prewarm(
        self,
        records: tuple[dict[str, Any], ...],
        key: tuple[str, str, str],
        generation: int,
    ) -> None:
        """Prepare a bounded active-set sample without delaying set selection."""
        with self._lock:
            self._reference_prewarm_stats.update({
                "state": "warming", "requested": len(records),
                "warmed": 0, "skipped": 0, "key": key,
            })
        threading.Thread(
            target=self._prewarm_reference_features,
            args=(records, key, generation),
            name="rareiq-reference-prewarm",
            daemon=True,
        ).start()

    def _prewarm_reference_features(
        self,
        records: tuple[dict[str, Any], ...],
        key: tuple[str, str, str],
        generation: int,
    ) -> dict[str, int]:
        """Synchronous worker kept separate for deterministic tests."""
        warmed = skipped = 0
        previous_mode = getattr(self._cache_access_context, "mode", None)
        self._cache_access_context.mode = "prewarm"
        try:
            for row in records[:self.REFERENCE_PREWARM_LIMIT]:
                with self._lock:
                    if generation != self._reference_prewarm_generation:
                        break
                image_path = row.get("image_path")
                image = self._cached_reference_image(image_path)
                if image is not None and self._cached_reference_features(image_path, image) is not None:
                    warmed += 1
                else:
                    skipped += 1
        finally:
            self._cache_access_context.mode = previous_mode or "recognition"
        with self._lock:
            if generation == self._reference_prewarm_generation:
                self._reference_prewarm_stats.update({
                    "state": "ready", "runs": int(
                        self._reference_prewarm_stats.get("runs") or 0
                    ) + 1,
                    "requested": min(len(records), self.REFERENCE_PREWARM_LIMIT),
                    "warmed": warmed, "skipped": skipped, "key": key,
                })
        return {"warmed": warmed, "skipped": skipped}

    @staticmethod
    def _collector_number(record: dict[str, Any]) -> int | None:
        value = str(
            record.get("printed_code") or record.get("collector_number") or ""
        ).strip()
        match = re.match(r"^(\d{1,4})(?:/\d{1,4})?$", value)
        return int(match.group(1)) if match else None

    def prewarm_collector_neighbors(self, printed_code: str) -> int:
        """Queue nearby active-set cards after a verified pack identity."""
        match = re.match(r"^(\d{1,4})(?:/\d{1,4})?$", str(printed_code or "").strip())
        if match is None:
            return 0
        anchor = int(match.group(1))
        with self._lock:
            generation = self._reference_prewarm_generation
            key = self._active_records_cache_key
            records = tuple(self._active_records_cache or ())
            marker = (generation, anchor)
            if self._reference_prewarm_stats.get("neighbor_anchor") == marker:
                return 0
        adaptive_limit = self._adaptive_neighbor_limit()
        predicted_numbers = self._predicted_collector_numbers(anchor)
        proximity_ranked = sorted(
            (
                (abs(number - anchor), number, row)
                for row in records
                if (number := self._collector_number(row)) is not None
            ),
            key=lambda item: (item[0], item[1], str(item[2].get("id") or "")),
        )
        predicted_ranked = [
            item for predicted in predicted_numbers for item in proximity_ranked
            if item[1] == predicted
        ]
        predicted_ids = {id(item[2]) for item in predicted_ranked}
        ranked = predicted_ranked + [
            item for item in proximity_ranked if id(item[2]) not in predicted_ids
        ]
        selected = tuple(row for _, _, row in ranked[:adaptive_limit])
        if not selected or key is None:
            return 0
        with self._lock:
            self._reference_prewarm_stats.update({
                "neighbor_anchor": marker,
                "neighbor_requested": len(selected),
                "adaptive_neighbor_limit": adaptive_limit,
            })
        threading.Thread(
            target=self._prewarm_neighbor_features,
            args=(selected, generation),
            name="rareiq-neighbor-prewarm",
            daemon=True,
        ).start()
        return len(selected)

    def _predicted_collector_numbers(self, anchor: int) -> list[int]:
        now = time.time()
        expired = False
        with self._lock:
            if self._transition_scope_key() in self._disabled_transition_scopes:
                return []
            context = (self._transition_scope_key(), anchor)
            updated_at = self._pack_transition_updated_at.get(context, 0.0)
            if updated_at and now - updated_at > self.PACK_TRANSITION_TTL_SECONDS:
                self._pack_transition_counts.pop(context, None)
                self._pack_transition_updated_at.pop(context, None)
                for edge in [edge for edge in self._pack_transition_edge_updated_at if edge[0] == context]:
                    self._pack_transition_edge_updated_at.pop(edge, None)
                transitions = {}
                expired = True
            else:
                transitions = dict(self._pack_transition_counts.get(context, {}))
        if expired:
            self._schedule_transition_model_save()
        with self._lock:
            edge_updates = {
                number: self._pack_transition_edge_updated_at.get((context, number), updated_at)
                for number in transitions
            }
        weighted = {
            number: count * (0.5 ** (max(0.0, now - edge_updates[number]) / self.PACK_TRANSITION_RECENCY_HALF_LIFE_SECONDS))
            for number, count in transitions.items()
        }
        promoted = [number for number, _ in sorted(
            ((number, weighted[number]) for number, count in transitions.items()
             if count >= self.PACK_TRANSITION_MIN_OBSERVATIONS),
            key=lambda item: (-item[1], item[0]),
        )]
        total = sum(weighted.values())
        if promoted and len(transitions) > 1:
            strongest = weighted[promoted[0]] / max(0.000001, total)
            if strongest < self.PACK_TRANSITION_MIN_DOMINANCE:
                return []
        return promoted

    def predicted_transition_records(self, collector_number: str, limit: int = 3) -> list[dict[str, Any]]:
        """Return active-set records learned as likely successors."""
        match = re.match(r"^(\d{1,4})(?:/\d{1,4})?$", str(collector_number or "").strip())
        if match is None:
            return []
        predicted = self._predicted_collector_numbers(int(match.group(1)))[:max(0, limit)]
        with self._lock:
            records = tuple(self._active_records_cache or ())
        return [
            row for number in predicted for row in records
            if self._collector_number(row) == number
        ][:limit]

    def observe_verified_card(self, collector_number: str, confidence: float | None = None) -> bool:
        """Learn a verified in-set transition and queue likely next references."""
        if confidence is not None:
            normalized_confidence = max(0.0, float(confidence))
            if normalized_confidence > 1.0:
                normalized_confidence /= 100.0
            if normalized_confidence < self.PACK_TRANSITION_MIN_CONFIDENCE:
                with self._lock:
                    self._pack_transition_low_confidence_rejections += 1
                return False
        match = re.match(
            r"^(\d{1,4})(?:/\d{1,4})?$", str(collector_number or "").strip()
        )
        if match is None:
            return False
        number = int(match.group(1))
        learned = False
        with self._lock:
            if self._active_records_cache_key is None:
                return False
            set_key = self._transition_scope_key()
            if set_key in self._disabled_transition_scopes:
                return False
            previous = self._last_verified_number_by_set.get(set_key)
            if previous == number:
                return False
            self._last_verified_number_by_set[set_key] = number
            if previous is not None:
                context = (set_key, previous)
                counts = self._pack_transition_counts.setdefault(context, {})
                counts[number] = counts.get(number, 0) + 1
                self._pack_transition_counts.move_to_end(context)
                self._pack_transition_updated_at[context] = time.time()
                self._pack_transition_edge_updated_at[(context, number)] = time.time()
                self._pack_transition_observations += 1
                learned = True
                while len(self._pack_transition_counts) > self.PACK_TRANSITION_CONTEXT_LIMIT:
                    evicted, _ = self._pack_transition_counts.popitem(last=False)
                    self._pack_transition_updated_at.pop(evicted, None)
                    for edge in [edge for edge in self._pack_transition_edge_updated_at if edge[0] == evicted]:
                        self._pack_transition_edge_updated_at.pop(edge, None)
        if learned:
            self._schedule_transition_model_save()
        self.prewarm_collector_neighbors(collector_number)
        return True

    def _load_pack_transition_model(self) -> None:
        """Restore fresh learned transitions without delaying or failing startup."""
        try:
            payload = json.loads(self.transition_model_path.read_text(encoding="utf-8"))
            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            disabled_scopes = payload.get("disabled_scopes", []) if isinstance(payload, dict) else []
            context_labels = payload.get("context_labels", {}) if isinstance(payload, dict) else {}
            cutoff = time.time() - self.PACK_TRANSITION_TTL_SECONDS
            restored: list[tuple[float, tuple[tuple[str, str, str], int], int, int]] = []
            for row in entries:
                set_key = row.get("set_key") if isinstance(row, dict) else None
                updated_at = float(row.get("updated_at", 0)) if isinstance(row, dict) else 0
                if not isinstance(set_key, list) or len(set_key) not in {3, 4} or updated_at < cutoff:
                    continue
                if len(set_key) == 3:
                    set_key = [*set_key, "default"]
                context = (tuple(str(value) for value in set_key), int(row["from"]))
                restored.append((updated_at, context, int(row["to"]), max(1, int(row["count"]))))
            restored.sort(key=lambda item: item[0])
            with self._lock:
                if isinstance(context_labels, dict):
                    self._pack_context_labels.update({
                        str(key): str(value).strip()[:120]
                        for key, value in context_labels.items() if str(value).strip()
                    })
                self._disabled_transition_scopes = {
                    tuple(str(value) for value in scope)
                    for scope in disabled_scopes if isinstance(scope, list) and len(scope) == 4
                }
                for updated_at, context, target, count in restored:
                    counts = self._pack_transition_counts.setdefault(context, {})
                    counts[target] = counts.get(target, 0) + count
                    self._pack_transition_counts.move_to_end(context)
                    self._pack_transition_updated_at[context] = max(
                        updated_at, self._pack_transition_updated_at.get(context, 0)
                    )
                    self._pack_transition_edge_updated_at[(context, target)] = max(
                        updated_at, self._pack_transition_edge_updated_at.get((context, target), 0)
                    )
                    self._pack_transition_observations += count
                while len(self._pack_transition_counts) > self.PACK_TRANSITION_CONTEXT_LIMIT:
                    evicted, _ = self._pack_transition_counts.popitem(last=False)
                    self._pack_transition_updated_at.pop(evicted, None)
                    for edge in [edge for edge in self._pack_transition_edge_updated_at if edge[0] == evicted]:
                        self._pack_transition_edge_updated_at.pop(edge, None)
                self._transition_persistence_error = None
        except FileNotFoundError:
            return
        except Exception as exc:
            self._transition_persistence_error = str(exc)

    def _transition_model_payload(self) -> dict[str, Any]:
        with self._lock:
            entries = [
                {"set_key": list(context[0]), "from": context[1], "to": target,
                 "count": count, "updated_at": self._pack_transition_edge_updated_at.get(
                     (context, target), self._pack_transition_updated_at.get(context, time.time())
                 )}
                for context, counts in self._pack_transition_counts.items()
                for target, count in counts.items()
            ]
            disabled_scopes = [list(scope) for scope in sorted(self._disabled_transition_scopes)]
            context_labels = dict(self._pack_context_labels)
        return {"version": 3, "saved_at": time.time(),
                "ttl_seconds": self.PACK_TRANSITION_TTL_SECONDS, "entries": entries,
                "disabled_scopes": disabled_scopes,
                "context_labels": context_labels}

    def _save_pack_transition_model(self) -> None:
        """Atomically persist a snapshot; callers keep this off the scan thread."""
        temporary = self.transition_model_path.with_suffix(self.transition_model_path.suffix + ".tmp")
        try:
            self.transition_model_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(self._transition_model_payload(), separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.transition_model_path)
            self._transition_persistence_error = None
        except Exception as exc:
            self._transition_persistence_error = str(exc)

    def _schedule_transition_model_save(self) -> None:
        with self._transition_persist_lock:
            self._transition_save_dirty = True
            if self._transition_save_running:
                return
            self._transition_save_running = True
        threading.Thread(target=self._transition_save_worker,
                         name="rareiq-transition-save", daemon=True).start()

    def _transition_save_worker(self) -> None:
        while True:
            with self._transition_persist_lock:
                self._transition_save_dirty = False
            self._save_pack_transition_model()
            with self._transition_persist_lock:
                if self._transition_save_dirty:
                    continue
                self._transition_save_running = False
                return

    def _prewarm_neighbor_features(
        self, records: tuple[dict[str, Any], ...], generation: int
    ) -> None:
        warmed = 0
        previous_mode = getattr(self._cache_access_context, "mode", None)
        self._cache_access_context.mode = "prewarm"
        try:
            for row in records[:self.NEIGHBOR_PREWARM_MAX]:
                with self._lock:
                    if generation != self._reference_prewarm_generation:
                        return
                image_path = row.get("image_path")
                image = self._cached_reference_image(image_path)
                if image is not None and self._cached_reference_features(image_path, image) is not None:
                    warmed += 1
        finally:
            self._cache_access_context.mode = previous_mode or "recognition"
        with self._lock:
            if generation == self._reference_prewarm_generation:
                self._reference_prewarm_stats["neighbor_runs"] = int(
                    self._reference_prewarm_stats.get("neighbor_runs") or 0
                ) + 1
                self._reference_prewarm_stats["neighbor_warmed"] = warmed

    def _records_for_active_filter(self) -> list[dict[str, Any]]:
        """Return the complete active-set corpus, using a bounded warm cache."""
        with self._lock:
            if self._active_records_cache is not None:
                self._active_records_cache_hits += 1
                return list(self._active_records_cache)
            records = list(self._records)
            active_set_name = self._active_set_name
            active_set_id = self._active_set_id
            active_language = self._active_language
        if active_set_name or active_set_id:
            records = [row for row in records if self._record_matches_set(row)]
        if active_language:
            wanted = active_language.casefold()
            records = [
                row for row in records
                if str(row.get("language") or "").casefold() == wanted
            ]
        return records

    def _record_matches_set(self, record: dict[str, Any]) -> bool:
        if not (self._active_set_id or self._active_set_name):
            return True
        wanted = {
            str(value).strip().casefold()
            for value in (self._active_set_id, self._active_set_name)
            if str(value).strip()
        }
        values = {
            str(record.get("set_id") or "").strip().casefold(),
            str(record.get("set_name") or "").strip().casefold(),
            str(record.get("set_code") or "").strip().casefold(),
        } - {""}
        return bool(wanted.intersection(values))

    def get_record(self, card_id: str) -> dict[str, Any] | None:
        with self._lock:
            for record in self._records:
                if str(record.get("id")) == str(card_id):
                    return dict(record)
        return None

    def text_search(self, query: str, *, limit: int = 24) -> list[dict[str, Any]]:
        """Search loaded card metadata for operator-driven match correction."""
        needle = " ".join(str(query or "").strip().casefold().split())
        if len(needle) < 2:
            return []
        tokens = needle.split()
        with self._lock:
            records = [dict(row) for row in self._records]

        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for row in records:
            name = str(
                row.get("english_name") or row.get("canonical_name")
                or row.get("pokemon_name") or row.get("printed_name")
                or row.get("name") or ""
            ).strip().casefold()
            printed_name = str(row.get("printed_name") or "").strip().casefold()
            collector = str(
                row.get("collector_number") or row.get("printed_code") or ""
            ).strip().casefold()
            set_name = str(row.get("set_name") or "").strip().casefold()
            set_id = str(row.get("set_id") or row.get("set_code") or "").strip().casefold()
            language = str(row.get("language") or "").strip().casefold()
            card_id = str(row.get("id") or "").strip().casefold()
            haystack = " ".join((name, printed_name, collector, set_name, set_id, language, card_id))
            if not all(token in haystack for token in tokens):
                continue
            score = 0
            if needle in {card_id, collector}:
                score += 120
            if needle in {name, printed_name}:
                score += 100
            elif name.startswith(needle) or printed_name.startswith(needle):
                score += 75
            elif needle in name or needle in printed_name:
                score += 55
            if needle in {set_id, set_name}:
                score += 35
            if needle in collector:
                score += 30
            score += sum(5 for token in tokens if token in name)
            ranked.append((score, f"{name}|{set_id}|{collector}|{card_id}", row))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [row for _, _, row in ranked[:max(1, min(100, int(limit)))]]

    def family_records(
        self,
        card: dict[str, Any] | None,
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return a bounded reference family for a previously verified card."""
        card = card or {}
        wanted_name = str(
            card.get("canonical_name")
            or card.get("english_name")
            or card.get("pokemon_name")
            or card.get("name")
            or ""
        ).strip().casefold()
        wanted_set = str(card.get("set_id") or "").strip().casefold()
        if not wanted_name:
            return []
        with self._lock:
            records = [dict(row) for row in self._records]
        matches = []
        for row in records:
            row_name = str(
                row.get("canonical_name")
                or row.get("english_name")
                or row.get("pokemon_name")
                or row.get("name")
                or ""
            ).strip().casefold()
            row_set = str(row.get("set_id") or "").strip().casefold()
            if row_name != wanted_name or (wanted_set and row_set != wanted_set):
                continue
            matches.append(row)
            if len(matches) >= max(1, int(limit)):
                break
        return matches

    @classmethod
    def _normalize_card(cls, image: np.ndarray) -> np.ndarray:
        return cv2.resize(
            image,
            (cls.NORMALIZED_WIDTH, cls.NORMALIZED_HEIGHT),
            interpolation=cv2.INTER_AREA,
        )

    @staticmethod
    def _structural_similarity(left: np.ndarray, right: np.ndarray) -> float:
        left_float = left.astype(np.float32)
        right_float = right.astype(np.float32)
        constant_one = 6.5025
        constant_two = 58.5225
        left_mean = cv2.GaussianBlur(left_float, (11, 11), 1.5)
        right_mean = cv2.GaussianBlur(right_float, (11, 11), 1.5)
        left_variance = (
            cv2.GaussianBlur(left_float * left_float, (11, 11), 1.5)
            - left_mean * left_mean
        )
        right_variance = (
            cv2.GaussianBlur(right_float * right_float, (11, 11), 1.5)
            - right_mean * right_mean
        )
        covariance = (
            cv2.GaussianBlur(left_float * right_float, (11, 11), 1.5)
            - left_mean * right_mean
        )
        numerator = (
            (2.0 * left_mean * right_mean + constant_one)
            * (2.0 * covariance + constant_two)
        )
        denominator = (
            (left_mean * left_mean + right_mean * right_mean + constant_one)
            * (left_variance + right_variance + constant_two)
        )
        score = float(np.mean(numerator / np.maximum(denominator, 1e-6)))
        return max(0.0, min(1.0, score))

    @classmethod
    def _verification_features(
        cls, image: np.ndarray
    ) -> tuple[np.ndarray, list[Any], np.ndarray | None]:
        normalized = cls._normalize_card(image)
        gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.createCLAHE(
            clipLimit=2.0, tileGridSize=(8, 8)
        ).apply(gray)
        orb = cv2.ORB_create(
            nfeatures=1200, scaleFactor=1.2, nlevels=8,
            edgeThreshold=19, fastThreshold=12,
        )
        keypoints, descriptors = orb.detectAndCompute(enhanced, None)
        return gray, keypoints, descriptors

    @classmethod
    def _second_stage_from_features(
        cls,
        live_features: tuple[np.ndarray, list[Any], np.ndarray | None],
        candidate_features: tuple[np.ndarray, list[Any], np.ndarray | None],
    ) -> dict[str, Any]:
        empty = {
            "verification_strong": False,
            "verification_score": 0.0,
            "orb_matches": 0,
            "homography_inliers": 0,
            "inlier_ratio": 0.0,
            "structural_similarity": 0.0,
            "lower_structural_similarity": 0.0,
        }
        live_gray, live_keypoints, live_descriptors = live_features
        candidate_gray, candidate_keypoints, candidate_descriptors = candidate_features
        if (
            live_descriptors is None
            or candidate_descriptors is None
            or len(candidate_descriptors) < 2
        ):
            return empty

        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
            live_descriptors,
            candidate_descriptors,
            k=2,
        )
        ratio_matches = [
            match
            for match, neighbor in pairs
            if match.distance < 0.72 * neighbor.distance
        ]
        evidence = {**empty, "orb_matches": len(ratio_matches)}
        if len(ratio_matches) < cls.MIN_RATIO_MATCHES:
            return evidence

        live_points = np.float32([
            live_keypoints[item.queryIdx].pt for item in ratio_matches
        ]).reshape(-1, 1, 2)
        candidate_points = np.float32([
            candidate_keypoints[item.trainIdx].pt for item in ratio_matches
        ]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(
            live_points,
            candidate_points,
            cv2.RANSAC,
            4.0,
        )
        if homography is None or mask is None:
            return evidence

        inliers = int(mask.sum())
        inlier_ratio = inliers / float(len(ratio_matches))
        evidence.update({
            "homography_inliers": inliers,
            "inlier_ratio": round(inlier_ratio, 4),
        })
        if (
            inliers < cls.MIN_HOMOGRAPHY_INLIERS
            or inlier_ratio < cls.MIN_INLIER_RATIO
        ):
            return evidence

        try:
            inverse = np.linalg.inv(homography)
        except np.linalg.LinAlgError:
            return evidence
        aligned = cv2.warpPerspective(
            candidate_gray,
            inverse,
            (cls.NORMALIZED_WIDTH, cls.NORMALIZED_HEIGHT),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        full_similarity = cls._structural_similarity(live_gray, aligned)
        lower_start = cls.NORMALIZED_HEIGHT // 2
        lower_end = int(cls.NORMALIZED_HEIGHT * 0.93)
        lower_similarity = cls._structural_similarity(
            live_gray[lower_start:lower_end],
            aligned[lower_start:lower_end],
        )
        inlier_strength = min(1.0, inliers / 80.0)
        verification_score = (
            0.35 * inlier_strength
            + 0.15 * inlier_ratio
            + 0.20 * full_similarity
            + 0.30 * lower_similarity
        )
        evidence.update({
            "verification_strong": True,
            "verification_score": round(verification_score, 4),
            "structural_similarity": round(full_similarity, 4),
            "lower_structural_similarity": round(lower_similarity, 4),
        })
        return evidence

    @classmethod
    def _second_stage_evidence(
        cls,
        live_card: np.ndarray,
        reference: np.ndarray,
    ) -> dict[str, Any]:
        if reference is None or reference.size == 0:
            return cls._second_stage_from_features(
                cls._verification_features(live_card),
                (np.empty((0, 0), dtype=np.uint8), [], None),
            )
        return cls._second_stage_from_features(
            cls._verification_features(live_card),
            cls._verification_features(reference),
        )

    def _cached_reference_features(
        self, image_path: Any, image: np.ndarray | None = None
    ) -> tuple[np.ndarray, list[Any], np.ndarray | None] | None:
        key = str(image_path or "")
        if not key:
            return None
        # Single-flight reference preparation: concurrent recognition workers
        # must never decode and extract the same immutable reference twice.
        with self._reference_feature_cache_lock:
            cached = self._reference_feature_cache.get(key)
            if cached is not None:
                self._record_cache_metric("feature_hits")
                self._reference_feature_cache.move_to_end(key)
                return cached
            image = image if image is not None else (
                cv2.imread(key) if Path(key).is_file() else None
            )
            if image is None:
                return None
            started = time.perf_counter()
            features = self._verification_features(image)
            self._record_cache_metric("feature_misses")
            self._reference_cache_timing["feature_build_ms"] += (
                time.perf_counter() - started
            ) * 1000
            self._reference_feature_cache[key] = features
            self._reference_feature_cache.move_to_end(key)
            while len(self._reference_feature_cache) > self._reference_feature_cache_limit:
                self._reference_feature_cache.popitem(last=False)
            return features

    def _cached_reference_image(self, image_path: Any) -> np.ndarray | None:
        """Keep only the pre-warm-sized decoded working set in memory."""
        key = str(image_path or "")
        if not key:
            return None
        with self._reference_feature_cache_lock:
            cached = self._reference_image_cache.get(key)
            if cached is not None:
                self._record_cache_metric("image_hits")
                self._reference_image_cache.move_to_end(key)
                return cached
            started = time.perf_counter()
            image = cv2.imread(key) if Path(key).is_file() else None
            if image is None:
                return None
            self._record_cache_metric("image_misses")
            self._reference_cache_timing["image_decode_ms"] += (
                time.perf_counter() - started
            ) * 1000
            self._reference_image_cache[key] = image
            self._reference_image_cache.move_to_end(key)
            while len(self._reference_image_cache) > self._reference_image_cache_limit:
                self._reference_image_cache.popitem(last=False)
            return image

    def _remember_printed_identity(
        self, query_fingerprint: str, printed_code: str
    ) -> None:
        self._recent_identity_cache[query_fingerprint] = printed_code
        self._fast_cache_stats["stores"] += 1
        self._recent_identity_cache.move_to_end(query_fingerprint)
        while len(self._recent_identity_cache) > self.RECENT_IDENTITY_CACHE_LIMIT:
            self._recent_identity_cache.popitem(last=False)

    def seed_verified_identity(
        self,
        query_fingerprint: str | None,
        candidates: list[dict[str, Any]],
    ) -> bool:
        """Seed a cold identity only after live/reference OCR and geometry agree."""
        if not query_fingerprint:
            return False
        candidate = next((
            item for item in candidates
            if item.get("verification_strong")
            and float(item.get("verification_score") or 0.0) >= 0.70
            and item.get("printed_code_match")
            and re.fullmatch(r"\d{1,3}/\d{2,3}", str(item.get("printed_code") or ""))
        ), None)
        if candidate is None:
            return False
        self._remember_printed_identity(
            str(query_fingerprint), str(candidate["printed_code"])
        )
        self.prewarm_collector_neighbors(str(candidate["printed_code"]))
        return True

    def _nearby_printed_identity(self, query_fingerprint: str) -> str | None:
        nearest: tuple[int, str, str] | None = None
        for fingerprint, printed_code in self._recent_identity_cache.items():
            distance = self.hamming(query_fingerprint, fingerprint)
            candidate = (distance, fingerprint, printed_code)
            if nearest is None or candidate < nearest:
                nearest = candidate
        if nearest is None or nearest[0] > self.RECENT_IDENTITY_MAX_DISTANCE:
            return None
        self._recent_identity_cache.move_to_end(nearest[1])
        return nearest[2]

    def _verify_cached_identity(
        self,
        artwork: np.ndarray,
        query: str,
        live_features: tuple[np.ndarray, list[Any], np.ndarray | None],
        records: list[dict[str, Any]],
        limit: int,
        started: float,
    ) -> dict[str, Any] | None:
        self._fast_cache_stats["lookups"] += 1
        printed_code = self._nearby_printed_identity(query)
        if not printed_code:
            self._fast_cache_stats["misses"] += 1
            return None
        candidates: list[dict[str, Any]] = []
        exact_id = printed_code[3:] if printed_code.startswith("id:") else None
        for row in records:
            if exact_id and str(row.get("id") or "") != exact_id:
                continue
            if not exact_id and str(row.get("printed_code") or "") != printed_code:
                continue
            image_path = row.get("image_path")
            reference_features = self._cached_reference_features(image_path)
            if reference_features is None:
                continue
            evidence = self._second_stage_from_features(
                live_features, reference_features
            )
            if not evidence["verification_strong"]:
                continue
            distance = self.hamming(query, str(row["fingerprint"]))
            hash_score = max(0.0, 1.0 - distance / 64.0)
            candidates.append({
                **row,
                "distance": distance,
                "hash_score": round(hash_score, 4),
                "score": round(
                    0.40 * hash_score
                    + 0.60 * float(evidence["verification_score"]),
                    4,
                ),
                "cached_identity_match": True,
                "first_stage_rank": len(candidates) + 1,
                **evidence,
            })
            if exact_id:
                reference = self._cached_reference_image(image_path)
                candidates[-1].update(self._artwork_region_evidence(artwork, reference))
                candidates[-1].update(self._marker_evidence(artwork, reference))
            if len(candidates) >= 2:
                break
        if exact_id:
            accepted = bool(
                candidates
                and float(candidates[0].get("verification_score") or 0.0) >= 0.70
                and candidates[0].get("artwork_verification_strong")
                and float(candidates[0].get("variant_marker_score") or 0.0) >= 0.20
            )
            if not accepted:
                self._fast_cache_stats["geometry_rejections"] += 1
                return None
            self._fast_cache_stats["hits"] += 1
            self._remember_printed_identity(query, printed_code)
            return {
                "ok": True,
                "query_fingerprint": query,
                "matches": candidates[:1],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "fast_return": "cached_exact_variant",
                "error": None,
            }
        if (
            len(candidates) < 2
            or max(float(item["verification_score"]) for item in candidates) < 0.70
        ):
            self._fast_cache_stats["geometry_rejections"] += 1
            return None
        self._fast_cache_stats["hits"] += 1
        self._apply_identity_consensus(candidates)
        candidates.sort(key=lambda item: -float(item["score"]))
        self._remember_printed_identity(query, printed_code)
        return {
            "ok": True,
            "query_fingerprint": query,
            "matches": candidates[:min(self.OUTPUT_LIMIT, max(1, int(limit)))],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "fast_return": "cached_printed_identity",
            "error": None,
        }

    def _seed_decisive_variant(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> bool:
        resolved = sorted(
            (
                item for item in candidates
                if item.get("variant_resolved")
                and item.get("verification_strong")
                and float(item.get("verification_score") or 0.0) >= 0.70
                and item.get("artwork_verification_strong")
                and item.get("id")
            ),
            key=lambda item: -float(item.get("variant_marker_score") or 0.0),
        )
        if not resolved:
            return False
        best = resolved[0]
        runner_up = (
            float(resolved[1].get("variant_marker_score") or 0.0)
            if len(resolved) > 1 else 0.0
        )
        best_score = float(best.get("variant_marker_score") or 0.0)
        if best_score < 0.20 or best_score - runner_up < 0.03:
            self._pending_variant_identity = None
            return False
        best_id = str(best["id"])
        if not candidates or str(candidates[0].get("id") or "") != best_id:
            self._pending_variant_identity = None
            return False
        if self._pending_variant_identity is None or self._pending_variant_identity[0] != best_id:
            self._pending_variant_identity = (best_id, 1, query)
            return False
        if self._pending_variant_identity[2] == query:
            return False
        confirmations = self._pending_variant_identity[1] + 1
        self._pending_variant_identity = (best_id, confirmations, query)
        if confirmations < 2:
            return False
        self._remember_printed_identity(query, f"id:{best_id}")
        return True

    def _family_siblings(
        self,
        records: list[dict[str, Any]],
        present: set[str],
        strong_families: set[str],
        query_artwork: str,
    ) -> list[dict[str, Any]]:
        return sorted(
            (
                row for row in records
                if row.get("artwork_fingerprint")
                and str(row.get("id")) not in present
            ),
            key=lambda row: (
                0 if str(row.get("artwork_fingerprint")) in strong_families else 1,
                self.hamming(query_artwork, str(row["artwork_fingerprint"])),
                str(row.get("id") or ""),
            ),
        )[:self.ARTWORK_STAGE_LIMIT]

    @staticmethod
    def _edge_similarity(left: np.ndarray, right: np.ndarray) -> float:
        left_edges = cv2.Canny(left, 60, 150) > 0
        right_edges = cv2.Canny(right, 60, 150) > 0
        union = int(np.logical_or(left_edges, right_edges).sum())
        if not union:
            return 0.0
        return float(np.logical_and(left_edges, right_edges).sum()) / union

    @classmethod
    def _marker_evidence(cls, live_card: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
        live = cls._normalize_card(live_card)
        candidate = cls._normalize_card(reference)
        region_scores = []
        for bounds in cls.MARKER_REGIONS:
            live_region = cls._region(live, bounds)
            candidate_region = cls._region(candidate, bounds)
            live_gray = cv2.cvtColor(live_region, cv2.COLOR_BGR2GRAY)
            candidate_gray = cv2.cvtColor(candidate_region, cv2.COLOR_BGR2GRAY)
            structural = cls._structural_similarity(live_gray, candidate_gray)
            edge = cls._edge_similarity(live_gray, candidate_gray)
            correlation = max(0.0, float(cv2.matchTemplate(
                live_gray, candidate_gray, cv2.TM_CCOEFF_NORMED
            )[0, 0]))
            orb = cv2.ORB_create(nfeatures=400, edgeThreshold=10, fastThreshold=8)
            live_keypoints, live_descriptors = orb.detectAndCompute(live_gray, None)
            candidate_keypoints, candidate_descriptors = orb.detectAndCompute(
                candidate_gray, None
            )
            matches = []
            if (
                live_descriptors is not None
                and candidate_descriptors is not None
                and len(candidate_descriptors) > 1
            ):
                pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(
                    live_descriptors, candidate_descriptors, k=2
                )
                matches = [m for m, n in pairs if m.distance < 0.72 * n.distance]
            histograms = []
            for channel in range(3):
                left_hist = cv2.calcHist([live_region], [channel], None, [32], [0, 256])
                right_hist = cv2.calcHist([candidate_region], [channel], None, [32], [0, 256])
                histograms.append(max(0.0, cv2.compareHist(
                    left_hist, right_hist, cv2.HISTCMP_CORREL
                )))
            color = float(np.mean(histograms))
            orb_strength = min(1.0, len(matches) / 40.0)
            score = (
                0.35 * structural
                + 0.20 * edge
                + 0.25 * correlation
                + 0.15 * orb_strength
                + 0.05 * color
            )
            region_scores.append(score)
        return {
            "variant_marker_score": round(float(
                0.04 * region_scores[0]
                + 0.01 * region_scores[1]
                + 0.95 * region_scores[2]
            ), 4),
            "variant_region_scores": [round(score, 4) for score in region_scores],
        }

    @classmethod
    def _artwork_region_evidence(
        cls, live_card: np.ndarray, reference: np.ndarray | None
    ) -> dict[str, Any]:
        if reference is None:
            return {
                "artwork_verification_strong": False,
                "artwork_verification_score": 0.0,
            }
        live = cls._region(cls._normalize_card(live_card), cls.ARTWORK_REGION)
        candidate = cls._region(cls._normalize_card(reference), cls.ARTWORK_REGION)
        evidence = cls._second_stage_evidence(live, candidate)
        return {
            "artwork_verification_strong": bool(evidence["verification_strong"]),
            "artwork_verification_score": float(evidence["verification_score"]),
        }

    def search(self, artwork: np.ndarray | None, limit: int = 10) -> dict[str, Any]:
        started = time.perf_counter()

        if artwork is None:
            return {
                "ok": False,
                "query_fingerprint": None,
                "matches": [],
                "latency_ms": 0.0,
                "error": "No artwork crop available.",
            }

        query = self.fingerprint(artwork)
        live_verification_features = self._verification_features(artwork)

        records = self._records_for_active_filter()

        cached_result = self._verify_cached_identity(
            artwork,
            query,
            live_verification_features,
            records,
            limit,
            started,
        )
        if cached_result is not None:
            return cached_result

        matches: list[dict[str, Any]] = []
        for row in records:
            distance = self.hamming(query, row["fingerprint"])
            score = max(0.0, 1.0 - distance / 64.0)
            matches.append({
                **row,
                "distance": distance,
                "score": round(score, 4),
            })

        matches.sort(key=lambda row: (row["distance"], str(row.get("id") or "")))
        hash_shortlist = matches[:self.FIRST_STAGE_LIMIT]
        for rank, item in enumerate(hash_shortlist, 1):
            item["first_stage_rank"] = rank
        query_artwork = self.artwork_fingerprint(artwork)
        present_ids = {str(row.get("id")) for row in hash_shortlist}
        artwork_shortlist = sorted(
            (
                row for row in records
                if row.get("artwork_fingerprint")
                and str(row.get("id")) not in present_ids
            ),
            key=lambda row: (
                self.hamming(query_artwork, str(row["artwork_fingerprint"])),
                str(row.get("id") or ""),
            ),
        )[:self.ARTWORK_STAGE_LIMIT]
        artwork_candidates: list[dict[str, Any]] = []
        for artwork_rank, row in enumerate(artwork_shortlist, 1):
            distance = self.hamming(query, str(row["fingerprint"]))
            artwork_candidates.append({
                **row,
                "distance": distance,
                "score": round(max(0.0, 1.0 - distance / 64.0), 4),
                "artwork_shortlisted": True,
                "family_expanded": True,
                "first_stage_rank": self.FIRST_STAGE_LIMIT + artwork_rank,
            })
        shortlist = artwork_candidates + hash_shortlist
        decisive_artwork = False
        for first_stage_rank, match in enumerate(shortlist):
            if decisive_artwork and not match.get("artwork_shortlisted"):
                match["hash_score"] = match["score"]
                match["retrieval_only"] = True
                match["verification_skipped"] = "decisive_artwork_preflight"
                match["score"] = round(min(
                    self.FAILED_VERIFICATION_CAP,
                    float(match["hash_score"]) * 0.55,
                ), 4)
                continue
            match["hash_score"] = match["score"]
            match.setdefault("first_stage_rank", first_stage_rank + 1)
            image_path = match.get("image_path")
            reference = self._cached_reference_image(image_path)
            reference_features = self._cached_reference_features(
                image_path, reference
            )
            evidence = (
                self._second_stage_from_features(
                    live_verification_features, reference_features
                )
                if reference_features is not None
                else self._second_stage_evidence(artwork, reference)
            )
            match.update(evidence)
            match["reference_readable"] = reference is not None
            if evidence["verification_strong"]:
                match.update(self._artwork_region_evidence(artwork, reference))
                match["score"] = round(
                    0.40 * float(match["hash_score"])
                    + 0.60 * float(evidence["verification_score"]),
                    4,
                )
                if (
                    match.get("artwork_shortlisted")
                    and float(evidence["verification_score"]) >= 0.70
                ):
                    decisive_artwork = True
            elif reference is not None:
                match["retrieval_only"] = True
                match["score"] = round(min(
                    self.FAILED_VERIFICATION_CAP,
                    float(match["hash_score"]) * 0.55,
                ), 4)

        decisive_print = next(
            (
                str(item.get("printed_code"))
                for item in shortlist
                if item.get("artwork_shortlisted")
                and item.get("verification_strong")
                and float(item.get("verification_score") or 0.0) >= 0.70
                and item.get("printed_code")
            ),
            None,
        )
        if decisive_print:
            present_ids = {str(item.get("id")) for item in shortlist}
            siblings = [
                row for row in records
                if str(row.get("printed_code") or "") == decisive_print
                and str(row.get("id")) not in present_ids
            ][:2]
            for row in siblings:
                image_path = row.get("image_path")
                reference = self._cached_reference_image(image_path)
                reference_features = self._cached_reference_features(
                    image_path, reference
                )
                evidence = (
                    self._second_stage_from_features(
                        live_verification_features, reference_features
                    )
                    if reference_features is not None
                    else self._second_stage_evidence(artwork, reference)
                )
                if not evidence["verification_strong"]:
                    continue
                distance = self.hamming(query, str(row["fingerprint"]))
                hash_score = max(0.0, 1.0 - distance / 64.0)
                shortlist.append({
                    **row,
                    "distance": distance,
                    "hash_score": round(hash_score, 4),
                    "score": round(
                        0.40 * hash_score
                        + 0.60 * float(evidence["verification_score"]),
                        4,
                    ),
                    "family_expanded": True,
                    "printed_identity_expanded": True,
                    "first_stage_rank": len(matches) + 1,
                    **evidence,
                })
            self._apply_identity_consensus(shortlist)
            self._remember_printed_identity(query, decisive_print)
            shortlist.sort(key=lambda row: (
                -float(row["score"]),
                int(row["first_stage_rank"]),
                str(row.get("id") or ""),
            ))
            return {
                "ok": True,
                "query_fingerprint": query,
                "matches": shortlist[:min(self.OUTPUT_LIMIT, max(1, int(limit)))],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "fast_return": "printed_identity_consensus",
                "error": None,
            }

        strong_families = {
            str(match.get("artwork_fingerprint"))
            for match in shortlist
            if (
                match.get("verification_strong")
                and match.get("artwork_verification_strong")
                and match.get("artwork_fingerprint")
            )
        }
        if strong_families:
            present = {str(match.get("id")) for match in shortlist}
            query_artwork = self.artwork_fingerprint(artwork)
            siblings = self._family_siblings(
                records, present, strong_families, query_artwork
            )
            for row in siblings:
                image_path = row.get("image_path")
                reference = self._cached_reference_image(image_path)
                reference_features = self._cached_reference_features(
                    image_path, reference
                )
                evidence = (
                    self._second_stage_from_features(
                        live_verification_features, reference_features
                    )
                    if reference_features is not None
                    else self._second_stage_evidence(artwork, reference)
                )
                artwork_evidence = self._artwork_region_evidence(artwork, reference)
                if (
                    not evidence["verification_strong"]
                    or not artwork_evidence["artwork_verification_strong"]
                ):
                    continue
                distance = self.hamming(query, row["fingerprint"])
                hash_score = max(0.0, 1.0 - distance / 64.0)
                item = {
                    **row,
                    "distance": distance,
                    "hash_score": round(hash_score, 4),
                    "score": round(
                        0.40 * hash_score
                        + 0.60 * float(evidence["verification_score"]), 4
                    ),
                    "first_stage_rank": len(matches) + 1,
                    "family_expanded": True,
                    **evidence,
                    **artwork_evidence,
                }
                shortlist.append(item)
                strong_families.add(str(row.get("artwork_fingerprint")))

            members = [
                item for item in shortlist
                if item.get("verification_strong")
                and item.get("artwork_verification_strong")
            ]
            if len(members) >= 2:
                seed = max(
                    members,
                    key=lambda item: (
                        float(item.get("artwork_verification_score") or 0.0),
                        str(item.get("id") or ""),
                    ),
                )
                seed_image = cv2.imread(str(seed.get("image_path")))
                validated = []
                for member in members:
                    image = cv2.imread(str(member.get("image_path")))
                    pairwise = self._artwork_region_evidence(seed_image, image)
                    member["family_pairwise_strong"] = bool(
                        pairwise["artwork_verification_strong"]
                    )
                    member["family_pairwise_score"] = float(
                        pairwise["artwork_verification_score"]
                    )
                    if member["family_pairwise_strong"]:
                        validated.append(member)
                if len(validated) >= 2:
                    for member in validated:
                        image = cv2.imread(str(member.get("image_path")))
                        member.update(self._marker_evidence(artwork, image))
                    best_marker = max(
                        float(item["variant_marker_score"]) for item in validated
                    )
                    worst_marker = min(
                        float(item["variant_marker_score"]) for item in validated
                    )
                    if best_marker >= 0.20 and best_marker - worst_marker >= 0.02:
                        family_base = max(float(item["score"]) for item in validated)
                        for member in validated:
                            marker = float(member["variant_marker_score"])
                            member["score"] = round(
                                family_base - 0.45 * (best_marker - marker), 4
                            )
                            member["variant_resolved"] = True

        # Exact-print marker comparison must run independently
        # of artwork-family expansion. Chinese printings can share the
        # same artwork while differing mainly in their lower card regions.
        marker_candidates = [
            item
            for item in shortlist
            if (
                str(
                    item.get("source")
                    or ""
                ).lower() == "pokipair"
                and bool(
                    item.get(
                        "verification_strong"
                    )
                )
                and bool(
                    item.get(
                        "artwork_verification_strong"
                    )
                )
                and item.get(
                    "image_path"
                )
            )
        ]

        for member in marker_candidates:
            marker_image_path = member.get(
                "image_path"
            )

            marker_image = (
                cv2.imread(
                    str(
                        marker_image_path
                    )
                )
                if (
                    marker_image_path
                    and Path(
                        str(
                            marker_image_path
                        )
                    ).is_file()
                )
                else None
            )

            if marker_image is None:
                member[
                    "variant_marker_error"
                ] = "reference_unreadable"
                continue

            member.update(
                self._marker_evidence(
                    artwork,
                    marker_image,
                )
            )

            member[
                "variant_marker_evaluated"
            ] = True

        evaluated_markers = [
            item
            for item in marker_candidates
            if item.get(
                "variant_marker_evaluated"
            )
        ]

        if len(evaluated_markers) >= 2:
            best_marker = max(
                float(
                    item.get(
                        "variant_marker_score"
                    )
                    or 0.0
                )
                for item in evaluated_markers
            )

            worst_marker = min(
                float(
                    item.get(
                        "variant_marker_score"
                    )
                    or 0.0
                )
                for item in evaluated_markers
            )

            marker_gap = (
                best_marker
                - worst_marker
            )

            for member in evaluated_markers:
                member[
                    "variant_marker_gap"
                ] = round(
                    marker_gap,
                    4,
                )

            if (
                best_marker >= 0.20
                and marker_gap >= 0.005
            ):
                family_base = max(
                    float(
                        item.get(
                            "score"
                        )
                        or 0.0
                    )
                    for item in evaluated_markers
                )

                for member in evaluated_markers:
                    marker = float(
                        member.get(
                            "variant_marker_score"
                        )
                        or 0.0
                    )

                    member["score"] = round(
                        family_base
                        - 0.70
                        * (
                            best_marker
                            - marker
                        ),
                        4,
                    )

                    member[
                        "variant_resolved"
                    ] = True

                    member[
                        "variant_resolution_source"
                    ] = (
                        "independent_marker_comparison"
                    )

        self._apply_identity_consensus(shortlist)

        shortlist.sort(key=lambda row: (
            -float(row["score"]),
            int(row["first_stage_rank"]),
            str(row.get("id") or ""),
        ))
        if self.EXACT_VARIANT_FAST_PATH_ENABLED:
            self._seed_decisive_variant(query, shortlist)

        return {
            "ok": True,
            "query_fingerprint": query,
            "matches": shortlist[:min(self.OUTPUT_LIMIT, max(1, int(limit)))],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": None,
        }

    def batch_shortlists(
        self,
        artworks: dict[int, np.ndarray],
    ) -> dict[str, Any]:
        """Build first-stage candidate sets for many cards in one catalog pass."""
        started = time.perf_counter()
        valid = {
            int(slot): image for slot, image in artworks.items()
            if image is not None and getattr(image, "size", 0)
        }
        queries = {
            slot: (self.fingerprint(image), self.artwork_fingerprint(image))
            for slot, image in valid.items()
        }
        with self._lock:
            records = list(self._records)
            active_set_name = self._active_set_name
            active_set_id = self._active_set_id
            active_language = self._active_language
        if active_set_name or active_set_id:
            records = [row for row in records if self._record_matches_set(row)]
        if active_language:
            records = [row for row in records if row.get("language") == active_language]

        ranked: dict[int, dict[str, list[tuple[int, dict[str, Any]]]]] = {
            slot: {"hash": [], "artwork": []} for slot in queries
        }
        # One traversal updates every live card's bounded ranking inputs.
        for row in records:
            fingerprint = str(row.get("fingerprint") or "")
            artwork_fingerprint = str(row.get("artwork_fingerprint") or "")
            for slot, (query, query_artwork) in queries.items():
                if fingerprint:
                    ranked[slot]["hash"].append((self.hamming(query, fingerprint), row))
                if artwork_fingerprint:
                    ranked[slot]["artwork"].append((self.hamming(query_artwork, artwork_fingerprint), row))

        results: dict[int, dict[str, Any]] = {}
        for slot, query_rankings in ranked.items():
            hash_rows = sorted(
                query_rankings["hash"],
                key=lambda item: (item[0], str(item[1].get("id") or "")),
            )[:self.FIRST_STAGE_LIMIT]
            present = {str(row.get("id")) for _, row in hash_rows}
            artwork_rows = [
                item for item in sorted(
                    query_rankings["artwork"],
                    key=lambda item: (item[0], str(item[1].get("id") or "")),
                )
                if str(item[1].get("id")) not in present
            ][:self.ARTWORK_STAGE_LIMIT]
            results[slot] = {
                "query_fingerprint": queries[slot][0],
                "hash_candidates": [
                    {**dict(row), "batch_distance": int(distance), "batch_signal": "hash"}
                    for distance, row in hash_rows
                ],
                "artwork_candidates": [
                    {**dict(row), "batch_distance": int(distance), "batch_signal": "artwork"}
                    for distance, row in artwork_rows
                ],
                "candidate_count": len(hash_rows) + len(artwork_rows),
            }
        return {
            "ok": True,
            "slots": results,
            "catalog_records_visited": len(records),
            "live_card_count": len(queries),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="RareIQ artwork-index maintenance")
    parser.add_argument("--enrich-index", action="store_true")
    args = parser.parse_args()
    if not args.enrich_index:
        parser.error("Specify --enrich-index")
    print(json.dumps(ArtworkIndexService().enrich_optional_fingerprints(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
