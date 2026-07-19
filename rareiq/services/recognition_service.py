from __future__ import annotations

import json
import re
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from rapidocr import RapidOCR

from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.set_catalog_service import SetCatalogService
from rareiq.services.live_catalog_service import LiveCatalogService


COLLECTOR_NUMBER_RE = re.compile(
    r"\b(?:[A-Z]{1,4}\s*)?(\d{1,4})\s*[/／]\s*(\d{1,4})\b",
    re.IGNORECASE,
)


class RecognitionService:
    def __init__(
        self,
        emit: Callable[[dict[str, Any]], None],
        database_path: Path | None = None,
    ) -> None:
        self._shutdown_event = threading.Event()
        self.emit = emit
        self._lock = threading.Lock()
        self._engine: RapidOCR | None = None
        self._busy = False
        self._last_started_at = 0.0
        self._last_full_pass_at = 0.0
        self._fast_interval = 0.18
        self._full_interval = 4.0
        self._current_generation = 0

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
        active = self.set_catalog.active_set()
        if active:
            self.artwork_index.set_active_filter(
                active.get("name"),
                active.get("language"),
            )

        self._status: dict[str, Any] = {
            "enabled": True,
            "busy": False,
            "mode": "ARTEMIS_INDEX",
            "last_latency_ms": None,
            "stage_timings": {},
            "raw_text": [],
            "name_candidate": None,
            "hp_candidate": None,
            "ocr_collector_number": None,
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


    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

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

    def submit_frame(
        self,
        frame: np.ndarray | None,
        *,
        generation: int = 0,
        frame_id: int | None = None,
        source: str = "auto",
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

        threading.Thread(
            target=self._recognize_worker,
            args=(frame.copy(), int(generation), frame_id, source),
            daemon=True,
        ).start()
        return "accepted"

    def _engine_instance(self) -> RapidOCR:
        if self._engine is None:
            self._engine = RapidOCR()
        return self._engine

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
        if re.search(r"[\u3040-\u30ff]", text):
            return "Japanese"
        if re.search(r"[\u4e00-\u9fff]", text):
            return "Chinese"
        if re.search(r"[A-Za-z]", text):
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
        for item in self._extract_result(
            self._engine_instance()(prepared)
        ):
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
    def _best_collector_number(
        items: list[dict[str, Any]],
    ) -> str | None:
        votes: dict[str, float] = {}

        for item in items:
            for match in COLLECTOR_NUMBER_RE.finditer(item["text"]):
                number = f"{match.group(1)}/{match.group(2)}"
                weight = max(0.01, float(item["score"]))
                if item.get("source") == "bottom":
                    weight *= 2.2
                votes[number] = votes.get(number, 0.0) + weight

        if not votes:
            return None

        winner = max(votes, key=votes.get)
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

        return winner

    @staticmethod
    def _valid_collector_number(number: str | None) -> bool:
        if not number:
            return False
        match = re.fullmatch(r"(\d{1,3})/(\d{2,3})", str(number).strip())
        if not match:
            return False
        return int(match.group(1)) > 0 and int(match.group(2)) > 0

    @staticmethod
    def _best_name(items: list[dict[str, Any]]) -> str | None:
        candidates: dict[str, float] = {}

        for item in items:
            if item.get("source") not in {"top", "full"}:
                continue

            text = item["text"].strip()
            if (
                COLLECTOR_NUMBER_RE.search(text)
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
    ) -> None:
        started = time.perf_counter()

        try:
            pipeline_stages: list[dict[str, Any]] = []

            already_rectified = self._is_rectified_card(frame)
            card = self._prepare_card(frame)
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
            pipeline_stages.append({
                "key": "perspective",
                "label": "Card crop prepared",
                "state": "done",
            })

            global_visual_result = (
                self.global_visual_index.search_image(card, limit=15)
                if self.global_visual_index is not None
                else {"ok": False, "matches": [], "latency_ms": 0.0}
            )
            global_visual_candidates = list(
                global_visual_result.get("matches") or []
            )
            global_visual_top_score = (
                float(global_visual_candidates[0].get("score", 0.0))
                if global_visual_candidates else 0.0
            )

            artwork_started = time.perf_counter()
            # Artwork-index fingerprints are built from normalized full-card
            # references, so query with the same full-card geometry.
            artwork_result = self.artwork_index.search(
                card,
                limit=10,
            )
            artwork_ms = round(
                (time.perf_counter() - artwork_started) * 1000,
                1,
            )
            artwork_candidates = artwork_result.get("matches", [])
            artwork_top_score = (
                float(artwork_candidates[0].get("score", 0.0))
                if artwork_candidates
                else 0.0
            )
            fingerprint = artwork_result.get(
                "query_fingerprint"
            )
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

            ocr_started = time.perf_counter()
            top_items = self._run_ocr(
                regions["top"],
                "top",
            )
            bottom_items = self._run_ocr(
                regions["bottom"],
                "bottom",
            )

            now = time.time()
            prior = self.status()
            need_fallback = (
                not prior.get("collector_number")
                or not prior.get("name_candidate")
            )
            run_full = (
                need_fallback
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

            ocr_ms = round(
                (time.perf_counter() - ocr_started) * 1000,
                1,
            )

            items = top_items + bottom_items + full_items
            name = self._best_name(items)
            hp = self._best_hp(items)
            ocr_number = self._best_collector_number(items)
            combined = " ".join(
                item["text"]
                for item in items
            )
            language = self._language_from_text(combined)
            pipeline_stages.append({
                "key": "ocr",
                "label": "OCR complete",
                "state": "done" if items else "waiting",
            })
            pipeline_stages.append({
                "key": "collector",
                "label": "Collector number",
                "state": "done" if ocr_number else "waiting",
            })
            pipeline_stages.append({
                "key": "language",
                "label": "Language identified",
                "state": "done" if language != "Unknown" else "waiting",
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
            collector_evidence = (
                1.0 if collector_valid and db_match
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

            if self.candidate_ranker is not None:
                candidates = self.candidate_ranker.rank(
                    visual_candidates=combined_candidates,
                    ocr_payload={
                        "text": combined,
                        "collector_number": validated_number,
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

            diagnostics_payload: dict[str, Any] = {}
            if self.recognition_diagnostics is not None:
                diagnostics_payload = self.recognition_diagnostics.analyze(
                    quality=quality_payload,
                    candidates=candidates,
                    ocr_payload={
                        "text": combined,
                        "collector_number": validated_number,
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

            ocr_locked = (
                bool(db_match)
                or (
                    overall_confidence >= 0.72
                    and collector_valid
                    and language != "Unknown"
                    and bool(top_candidate.get("verification_strong"))
                    and (
                        float((top_candidate.get("signals") or {}).get("ocr_name", 0.0)) >= 0.75
                        or float((top_candidate.get("signals") or {}).get("collector_number", 0.0)) >= 1.0
                    )
                )
            )

            recognition_locked = (
                artwork_locked
                or ocr_locked
            )

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
                    "strong artwork reference",
                    (
                        "safe candidate gap "
                        f"{score_gap:.3f}"
                    ),
                ]

            verification_state = (
                "VERIFIED"
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

            payload = {
                "enabled": True,
                "busy": False,
                "mode": "ARTEMIS_INDEX",
                "last_latency_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "stage_timings": {
                    "global_visual_ms": float(
                        global_visual_result.get("latency_ms", 0.0)
                    ),
                    "artwork_search_ms": artwork_ms,
                    "ocr_ms": ocr_ms,
                    "total_ms": round(
                        (
                            time.perf_counter()
                            - started
                        )
                        * 1000,
                        1,
                    ),
                },
                "raw_text": items,
                "name_candidate": name,
                "hp_candidate": hp,
                "ocr_collector_number": ocr_number,
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
                "has_reference_evidence": has_reference_evidence,
                "verification_state": verification_state,
                "pipeline_stages": pipeline_stages,
                "lock_reason": (
                    ", ".join(lock_reasons)
                    if recognition_locked
                    else None
                ),
                "candidates": candidates,
                "candidate_count": len(candidates),
                "quality": quality_payload,
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
