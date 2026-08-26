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
    ocr_collector_number: str | None = None
    ocr_printed_code: str | None = None
    ocr_confidence: float = 0.0
    identifier_reference_match: bool = False
    language: str | None = None
    overall_confidence: float = 0.0
    confidence: float = 0.0
    artwork_fingerprint: str | None = None
    artwork_index: dict[str, Any] = field(default_factory=dict)
    database_match: dict[str, Any] | None = None
    pipeline_stages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    stage_timings: dict[str, Any] = field(default_factory=dict)
    recognition_locked: bool = False
    temporal_confirmation: bool = False
    temporal_confirmation_count: int = 0
    temporal_confirmation_progress: int = 0
    temporal_confirmation_required: int = 2
    exact_reference_diagnostics: dict[str, Any] = field(default_factory=dict)
    identity_evidence: dict[str, Any] = field(default_factory=dict)
    identity_conflicts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    identity_consistent: bool = True
    catalog_gap: dict[str, Any] = field(default_factory=dict)
    catalog_recovery_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
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
        payload["identity_conflicts"] = list(self.identity_conflicts)
        payload["catalog_recovery_candidates"] = list(
            self.catalog_recovery_candidates
        )
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
    def _collector_key(value: Any) -> str:
        raw = str(value or "").strip().casefold()
        if not raw:
            return ""
        return "/".join(
            str(int(part)) if part.isdigit() else part
            for part in raw.split("/")
        )

    @staticmethod
    def _identity_names(item: dict[str, Any]) -> set[str]:
        return {
            str(item.get(key) or "").strip().casefold()
            for key in (
                "english_name",
                "canonical_name",
                "pokemon_name",
                "name",
                "printed_name",
            )
            if str(item.get(key) or "").strip()
        }

    @classmethod
    def _catalog_identity_compatible(
        cls,
        primary: dict[str, Any],
        partner: dict[str, Any],
        wanted_number: str,
    ) -> bool:
        """Require version evidence before catalog metadata may be attached."""
        primary_id = str(primary.get("id") or "").strip().casefold()
        partner_id = str(
            partner.get("id") or partner.get("card_id") or ""
        ).strip().casefold()
        if primary_id and partner_id and primary_id == partner_id:
            return True

        primary_number = cls._collector_key(
            primary.get("collector_number") or wanted_number
        )
        partner_number = cls._collector_key(
            partner.get("collector_number") or partner.get("number")
        )
        if not primary_number or primary_number != partner_number:
            return False

        primary_sets = {
            str(primary.get(key) or "").strip().casefold()
            for key in ("set_id", "set_name")
            if str(primary.get(key) or "").strip()
        }
        partner_sets = {
            str(partner.get(key) or "").strip().casefold()
            for key in ("set_id", "set_name")
            if str(partner.get(key) or "").strip()
        }
        if primary_sets and partner_sets:
            return bool(primary_sets & partner_sets)

        return bool(cls._identity_names(primary) & cls._identity_names(partner))

    @staticmethod
    def _operator_presentable(item: dict[str, Any]) -> bool:
        """Keep retrieval hypotheses out of the operator-facing identity."""
        if item.get("retrieval_only"):
            return False
        source = str(item.get("source") or "").strip().lower()
        if source == "global_visual_index" and not (
            (
                item.get("set_locked_identity_agreement") is True
                and float(
                    (item.get("signals") or {}).get("collector_number") or 0.0
                ) >= 1.0
            )
            or (
                item.get("verification_strong") is True
                and item.get("artwork_verification_strong") is True
                and item.get("collector_fraction_exact") is True
            )
        ):
            return False
        if source == "ocr_provisional":
            return False
        if source == "live_catalog" and not any((
            item.get("verification_strong"),
            item.get("printed_code_match"),
            item.get("exact_reference_resolved"),
            item.get("identity_verified"),
            item.get("set_locked_catalog_lookup"),
        )):
            return False
        return True

    @staticmethod
    def _state_id(
        primary: dict[str, Any] | None,
        fingerprint: str | None,
        generation: int,
    ) -> str:
        identity = {
            "candidate_id": (primary or {}).get("id"),
            "number": (primary or {}).get("collector_number"),
            "name": (primary or {}).get("name")
            or (primary or {}).get("printed_name"),
            "language": (primary or {}).get("language")
            or (primary or {}).get("language_code"),
            "fingerprint": fingerprint,
            "generation": generation,
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

        primary = next(
            (candidate for candidate in candidates if self._operator_presentable(candidate)),
            None,
        )

        # A provisional OCR guess must not outrank a real visual database
        # candidate that has matched reference artwork. OCR remains supporting
        # evidence for the printed name, language, and collector number.
        visual_primary = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, dict)
                and self._operator_presentable(candidate)
                and (
                    candidate.get("reference_image_url")
                    or candidate.get("reference_image")
                    or candidate.get("local_image")
                    or candidate.get("image_path")
                )
            ),
            None,
        )

        if visual_primary is not None:
            primary = copy.deepcopy(visual_primary)

            if printed and not primary.get("printed_name"):
                primary["printed_name"] = printed

            if number and not primary.get("collector_number"):
                primary["collector_number"] = number

            if raw.get("language") and not primary.get("language"):
                primary["language"] = raw.get("language")

            candidates = [
                primary,
                *[
                    candidate
                    for candidate in candidates
                    if self._candidate_key(candidate)
                    != self._candidate_key(visual_primary)
                ],
            ]

        # Enrich the strongest visual candidate with catalog identity and
        # pricing. Recognition and catalog lookup are independent pipelines,
        # so the winning artwork candidate may not contain the metadata that
        # already exists on the matching catalog record.
        if primary:
            wanted_number = str(
                primary.get("collector_number")
                or number
                or ""
            ).strip()

            catalog_partner = None
            wanted_language = str(
                raw.get("language")
                or (raw.get("active_set") or {}).get("language")
                or catalog.get("query", {}).get("language")
                or ""
            ).strip().lower()

            def language_matches(item: dict[str, Any]) -> bool:
                item_language = str(
                    item.get("language") or item.get("language_code") or ""
                ).strip().lower()
                return bool(wanted_language) and (
                    wanted_language == item_language
                    or (wanted_language == "english" and item_language == "en")
                    or (wanted_language == "en" and item_language == "english")
                )

            compatible_catalog_items = [
                item
                for item in catalog_items
                if isinstance(item, dict)
                and self._catalog_identity_compatible(
                    primary,
                    item,
                    wanted_number,
                )
            ]

            if wanted_language:
                catalog_partner = next(
                    (
                        item
                        for item in compatible_catalog_items
                        if language_matches(item)
                    ),
                    None,
                )

            explicit_match = catalog.get("match")
            if (
                catalog_partner is None
                and isinstance(explicit_match, dict)
                and self._catalog_identity_compatible(
                    primary,
                    explicit_match,
                    wanted_number,
                )
            ):
                catalog_partner = explicit_match

            if catalog_partner is None and compatible_catalog_items:
                catalog_partner = compatible_catalog_items[0]

            if catalog_partner is not None:
                enriched = copy.deepcopy(primary)
                aligned_language_variant = language_matches(catalog_partner)

                for key in (
                    "english_name",
                    "canonical_name",
                    "collector_number",
                    "local_id",
                    "set_id",
                    "set_name",
                    "set_total",
                    "set_official",
                    "rarity",
                    "category",
                    "hp",
                    "types",
                    "energy_type",
                    "language",
                    "language_code",
                    "reference_image",
                    "reference_image_url",
                    "english_image_url",
                    "image_url",
                    "pricing",
                ):
                    value = catalog_partner.get(key)
                    if value not in (None, "", [], {}):
                        if aligned_language_variant and key in {
                            "language", "language_code", "reference_image",
                            "reference_image_url", "image_url",
                        }:
                            enriched[key] = copy.deepcopy(value)
                        elif enriched.get(key) in (None, "", [], {}):
                            enriched[key] = copy.deepcopy(value)

                partner_name = str(
                    catalog_partner.get("name")
                    or catalog_partner.get("printed_name")
                    or ""
                ).strip()

                partner_language = str(
                    catalog_partner.get("language_code")
                    or catalog_partner.get("language")
                    or ""
                ).lower()

                if (
                    partner_name
                    and partner_language in {"en", "english"}
                    and not enriched.get("english_name")
                ):
                    enriched["english_name"] = partner_name

                current_name = str(
                    enriched.get("printed_name")
                    or enriched.get("name")
                    or ""
                ).strip()

                looks_like_filename = (
                    len(current_name) > 70
                    or "-set-list-" in current_name.lower()
                    or "-pokemon-" in current_name.lower()
                    or "-pokipair-" in current_name.lower()
                    or current_name.lower().endswith(
                        (".jpg", ".jpeg", ".png", ".webp", ".avif")
                    )
                )

                if printed and (
                    not enriched.get("printed_name")
                    or looks_like_filename
                ):
                    enriched["printed_name"] = printed

                pricing = dict(enriched.get("pricing") or {})
                if pricing:
                    enriched["market_price"] = pricing.get("market")
                    enriched["raw_market"] = pricing.get("market")
                    enriched["raw_value"] = pricing.get("market")
                    enriched["raw_low"] = pricing.get("low")
                    enriched["raw_high"] = pricing.get("high")
                    enriched["price_source"] = pricing.get("source")
                    enriched["pricing_source"] = pricing.get("source")
                    enriched["price_updated_at"] = pricing.get("updated_at")
                    enriched["pricing_updated_at"] = pricing.get("updated_at")
                    enriched["currency"] = (
                        pricing.get("currency")
                        or pricing.get("unit")
                        or "USD"
                    )

                primary = enriched
                candidates[0] = primary

        english_name = None

        if primary:
            english_name = (
                primary.get("english_name")
                or primary.get("canonical_name")
                or primary.get("name_en")
            )

            primary_name = str(
                primary.get("name")
                or ""
            ).strip()

            primary_language = str(
                primary.get("language_code")
                or primary.get("language")
                or ""
            ).strip().lower()

            primary_source = str(
                primary.get("source")
                or ""
            ).strip().lower()

            name_looks_like_filename = (
                len(primary_name) > 70
                or "-set-list-" in primary_name.lower()
                or "-pokemon-" in primary_name.lower()
                or "-pokipair-" in primary_name.lower()
                or "-store-" in primary_name.lower()
                or primary_name.lower().endswith(
                    (
                        ".jpg",
                        ".jpeg",
                        ".png",
                        ".webp",
                        ".avif",
                    )
                )
            )

            if (
                not english_name
                and primary_name
                and not name_looks_like_filename
                and primary_source == "pokipair"
                and primary_language not in {
                    "",
                    "en",
                    "english",
                }
            ):
                english_name = primary_name

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

                if not primary.get("canonical_name"):
                    primary["canonical_name"] = english_name

                if not primary.get("pokemon_name"):
                    primary["pokemon_name"] = english_name

                candidates[0] = primary

        stages = tuple(copy.deepcopy(raw.get("pipeline_stages") or []))
        done = {
            stage.get("key")
            for stage in stages
            if isinstance(stage, dict) and stage.get("state") == "done"
        }

        overall = self._number(raw.get("overall_confidence"))
        catalog_gap = copy.deepcopy(raw.get("catalog_gap") or {})
        reference_missing = bool(
            raw.get("verification_state") == "REFERENCE_MISSING"
            or catalog_gap.get("status") == "missing"
        )
        has_reference = bool(
            not reference_missing
            and primary
            and (
                raw.get("has_reference_evidence")
                or (
                    primary.get("set_locked_identity_agreement") is True
                    and self._number(
                        (primary.get("signals") or {}).get("collector_number")
                    ) >= 1.0
                )
                or (
                    not primary.get("provisional")
                    and self._image(primary)
                )
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
        state_id = self._state_id(primary, fingerprint, self._generation)

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
            ocr_collector_number=raw.get("ocr_collector_number"),
            ocr_printed_code=raw.get("ocr_printed_code"),
            ocr_confidence=self._number(raw.get("confidence")),
            identifier_reference_match=bool(
                (raw.get("collector_ocr") or {}).get("reference_match")
            ),
            language=(primary or {}).get("language") or raw.get("language"),
            overall_confidence=overall,
            confidence=self._number(raw.get("confidence")),
            artwork_fingerprint=fingerprint,
            artwork_index=copy.deepcopy(raw.get("artwork_index") or {}),
            database_match=copy.deepcopy(raw.get("database_match")),
            pipeline_stages=stages,
            stage_timings=copy.deepcopy(raw.get("stage_timings") or {}),
            recognition_locked=verified,
            temporal_confirmation=bool(raw.get("temporal_confirmation")),
            temporal_confirmation_count=int(raw.get("temporal_confirmation_count") or 0),
            temporal_confirmation_progress=int(raw.get("temporal_confirmation_progress") or 0),
            temporal_confirmation_required=int(raw.get("temporal_confirmation_required") or 2),
            exact_reference_diagnostics=copy.deepcopy(
                raw.get("exact_reference_diagnostics") or {}
            ),
            identity_evidence=copy.deepcopy(raw.get("identity_evidence") or {}),
            identity_conflicts=tuple(copy.deepcopy(
                raw.get("identity_conflicts") or []
            )),
            identity_consistent=raw.get("identity_consistent") is not False,
            catalog_gap=catalog_gap,
            catalog_recovery_candidates=tuple(copy.deepcopy(
                raw.get("catalog_recovery_candidates") or []
            )),
            has_reference_evidence=has_reference,
            verification_state=(
                "VERIFIED"
                if verified
                else "REFERENCE_MISSING"
                if reference_missing
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
