from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
import argparse

import cv2
import numpy as np


class ArtworkIndexService:
    FIRST_STAGE_LIMIT = 24
    ARTWORK_STAGE_LIMIT = 12
    OUTPUT_LIMIT = 10
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
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._error: str | None = None
        self._last_rebuild: dict[str, Any] | None = None
        self._active_set_name: str | None = None
        self._active_language: str | None = None
        self.load()

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

                    normalized.append({
                        **row,
                        "image_path": (
                            row.get("image_path")
                            or row.get("reference_image")
                        ),
                        "fingerprint": fingerprint,
                    })

                self._records = normalized
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
                "active_language": self._active_language,
                "error": self._error,
            }

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
    ) -> None:
        with self._lock:
            self._active_set_name = (
                None if not set_name or set_name == "All Loaded References"
                else str(set_name)
            )
            self._active_language = (
                None if not language or language in {"Any", "Unknown"}
                else str(language)
            )

    def get_record(self, card_id: str) -> dict[str, Any] | None:
        with self._lock:
            for record in self._records:
                if str(record.get("id")) == str(card_id):
                    return dict(record)
        return None

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
    def _second_stage_evidence(
        cls,
        live_card: np.ndarray,
        reference: np.ndarray,
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
        if reference is None or reference.size == 0:
            return empty

        live = cls._normalize_card(live_card)
        candidate = cls._normalize_card(reference)
        live_gray = cv2.cvtColor(live, cv2.COLOR_BGR2GRAY)
        candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        live_features = clahe.apply(live_gray)
        candidate_features = clahe.apply(candidate_gray)
        orb = cv2.ORB_create(
            nfeatures=1200,
            scaleFactor=1.2,
            nlevels=8,
            edgeThreshold=19,
            fastThreshold=12,
        )
        live_keypoints, live_descriptors = orb.detectAndCompute(
            live_features, None
        )
        candidate_keypoints, candidate_descriptors = orb.detectAndCompute(
            candidate_features, None
        )
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

        with self._lock:
            records = list(self._records)
            active_set_name = self._active_set_name
            active_language = self._active_language

        if active_set_name:
            records = [
                row for row in records
                if row.get("set_name") == active_set_name
            ]

        if active_language:
            records = [
                row for row in records
                if row.get("language") == active_language
            ]

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
        shortlist = matches[:self.FIRST_STAGE_LIMIT]
        for first_stage_rank, match in enumerate(shortlist):
            match["hash_score"] = match["score"]
            match["first_stage_rank"] = first_stage_rank + 1
            image_path = match.get("image_path")
            reference = (
                cv2.imread(str(image_path))
                if image_path and Path(str(image_path)).is_file()
                else None
            )
            evidence = self._second_stage_evidence(artwork, reference)
            match.update(evidence)
            match["reference_readable"] = reference is not None
            if evidence["verification_strong"]:
                match.update(self._artwork_region_evidence(artwork, reference))
                match["score"] = round(
                    0.40 * float(match["hash_score"])
                    + 0.60 * float(evidence["verification_score"]),
                    4,
                )
            elif reference is not None:
                match["retrieval_only"] = True
                match["score"] = round(min(
                    self.FAILED_VERIFICATION_CAP,
                    float(match["hash_score"]) * 0.55,
                ), 4)

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
            siblings = sorted(
                (
                    row for row in records
                    if row.get("artwork_fingerprint")
                    and str(row.get("id")) not in present
                ),
                key=lambda row: (
                    self.hamming(query_artwork, str(row["artwork_fingerprint"])),
                    str(row.get("id") or ""),
                ),
            )[:self.ARTWORK_STAGE_LIMIT]
            for row in siblings:
                image_path = row.get("image_path")
                reference = (
                    cv2.imread(str(image_path))
                    if image_path and Path(str(image_path)).is_file()
                    else None
                )
                evidence = self._second_stage_evidence(artwork, reference)
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
            "error": None,
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
