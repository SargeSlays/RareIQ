from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class PackArtworkRecognitionService:
    """Persistent, fail-closed recognition for sealed-pack artwork."""

    MIN_SCORE = 0.72
    MIN_MARGIN = 0.06

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.image_dir = self.root / "images"
        self.index_path = self.root / "pack_artwork_index.json"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._last_match: dict[str, Any] | None = None
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._records = [
                dict(item) for item in payload.get("records", [])
                if isinstance(item, dict)
            ]
        except Exception:
            self._records = []

    def _save(self) -> None:
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "version": 1,
            "updated_at": time.time(),
            "records": self._records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.index_path)

    @staticmethod
    def _focus(frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 45, 135)
        edges = cv2.morphologyEx(
            edges,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)),
            iterations=2,
        )
        frame_area = float(width * height)
        center_x, center_y = width / 2.0, height / 2.0
        candidates: list[tuple[float, tuple[int, int, int, int]]] = []
        for contour in cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_height <= 0:
                continue
            area_ratio = (box_width * box_height) / frame_area
            aspect = box_width / float(box_height)
            rectangularity = cv2.contourArea(contour) / float(max(1, box_width * box_height))
            if not (0.018 <= area_ratio <= 0.48 and 0.28 <= aspect <= 0.90):
                continue
            if box_height < height * 0.24 or rectangularity < 0.28:
                continue
            dx = ((x + box_width / 2.0) - center_x) / max(1.0, center_x)
            dy = ((y + box_height / 2.0) - center_y) / max(1.0, center_y)
            center_distance = min(1.0, (dx * dx + dy * dy) ** 0.5)
            score = area_ratio * (1.0 + rectangularity) * (1.2 - 0.55 * center_distance)
            candidates.append((score, (x, y, box_width, box_height)))
        if candidates:
            _, (x, y, box_width, box_height) = max(candidates, key=lambda item: item[0])
            pad_x, pad_y = int(box_width * 0.025), int(box_height * 0.025)
            left, top = max(0, x - pad_x), max(0, y - pad_y)
            right = min(width, x + box_width + pad_x)
            bottom = min(height, y + box_height + pad_y)
            crop = frame[top:bottom, left:right]
        else:
            # Fail gracefully for wrappers with low-contrast edges while still
            # excluding the operator's outer workspace.
            margin_x, margin_y = int(width * 0.25), int(height * 0.08)
            crop = frame[margin_y:height - margin_y, margin_x:width - margin_x]
        return cv2.resize(crop, (480, 640), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _hash(image: np.ndarray) -> str:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        bits = small[:, 1:] > small[:, :-1]
        return f"{int(''.join('1' if bit else '0' for bit in bits.flat), 2):016x}"

    @staticmethod
    def _histogram(image: np.ndarray) -> list[float]:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return [round(float(value), 7) for value in hist.flatten()]

    @staticmethod
    def _hash_score(left: str, right: str) -> float:
        try:
            distance = (int(left, 16) ^ int(right, 16)).bit_count()
            return max(0.0, 1.0 - distance / 64.0)
        except Exception:
            return 0.0

    @staticmethod
    def _histogram_score(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        distance = cv2.compareHist(
            np.asarray(left, dtype=np.float32),
            np.asarray(right, dtype=np.float32),
            cv2.HISTCMP_BHATTACHARYYA,
        )
        return max(0.0, min(1.0, 1.0 - float(distance)))

    def enroll(self, frame: np.ndarray, set_info: dict[str, Any]) -> dict[str, Any]:
        if frame is None or not getattr(frame, "size", 0):
            return {"ok": False, "error": "No live camera frame is available."}
        set_id = str(set_info.get("set_id") or set_info.get("id") or "").strip()
        set_name = str(set_info.get("set_name") or set_info.get("name") or "").strip()
        if not set_id and not set_name:
            return {"ok": False, "error": "Choose the pack's set before learning it."}
        focused = self._focus(frame)
        timestamp = int(time.time() * 1000)
        safe_id = "".join(ch if ch.isalnum() else "_" for ch in (set_id or set_name))
        image_path = self.image_dir / f"{safe_id}_{timestamp}.jpg"
        if not cv2.imwrite(str(image_path), focused):
            return {"ok": False, "error": "Pack reference image could not be saved."}
        with self._lock:
            variant_index = 1 + sum(
                str(item.get("set_id") or "").casefold() == str(set_id or set_name).casefold()
                for item in self._records
            )
        record = {
            "id": f"pack-{safe_id}-{timestamp}",
            "set_id": set_id or set_name,
            "set_name": set_name or set_id,
            "language": str(set_info.get("language") or "Any"),
            "provider": str(set_info.get("provider") or ""),
            "pack_label": str(
                set_info.get("pack_label")
                or f"{set_name or set_id} · Wrapper {variant_index}"
            ).strip(),
            "pack_profile": {"expected_cards": 10, "rare_slot": 10},
            "pack_profile_learning": {"observations": []},
            "image_path": str(image_path),
            "dhash": self._hash(focused),
            "histogram": self._histogram(focused),
            "created_at": time.time(),
        }
        with self._lock:
            self._records.append(record)
            self._save()
        return {"ok": True, "reference": dict(record), "status": self.status()}

    def identify(self, frame: np.ndarray) -> dict[str, Any]:
        if frame is None or not getattr(frame, "size", 0):
            return {"ok": False, "error": "No live camera frame is available."}
        focused = self._focus(frame)
        query_hash = self._hash(focused)
        query_histogram = self._histogram(focused)
        with self._lock:
            records = [dict(item) for item in self._records]
        matches = []
        for record in records:
            hash_score = self._hash_score(query_hash, str(record.get("dhash") or ""))
            histogram_score = self._histogram_score(
                query_histogram, list(record.get("histogram") or [])
            )
            # Pack layouts often share the same silhouette, so palette evidence
            # must outweigh structure to avoid cross-set false positives.
            score = 0.35 * hash_score + 0.65 * histogram_score
            matches.append({
                **{key: record.get(key) for key in (
                    "id", "set_id", "set_name", "language", "provider", "pack_label", "pack_profile", "pack_profile_learning", "image_path"
                )},
                "score": round(score, 4),
                "hash_score": round(hash_score, 4),
                "color_score": round(histogram_score, 4),
                "profile_learning": self._learning_summary(record),
            })
        matches.sort(key=lambda item: -float(item["score"]))
        top = matches[0] if matches else None
        top_identity = (
            str(top.get("provider") or "").casefold(),
            str(top.get("language") or "").casefold(),
            str(top.get("set_id") or top.get("set_name") or "").casefold(),
        ) if top else None
        runner_up = next((item for item in matches if (
            str(item.get("provider") or "").casefold(),
            str(item.get("language") or "").casefold(),
            str(item.get("set_id") or item.get("set_name") or "").casefold(),
        ) != top_identity), None)
        second_score = float(runner_up["score"]) if runner_up else 0.0
        margin = float(top["score"]) - second_score if top else 0.0
        accepted = bool(
            top and float(top["score"]) >= self.MIN_SCORE
            and (runner_up is None or margin >= self.MIN_MARGIN)
        )
        result = {
            "ok": accepted,
            "match": top if accepted else None,
            "candidate": top,
            "score": float(top["score"]) if top else 0.0,
            "margin": round(margin, 4),
            "matches": matches[:5],
            "error": None if accepted else (
                "No learned pack matched confidently. Choose its set and use Learn Pack first."
            ),
        }
        with self._lock:
            # Retain the last verified match when a later frame is empty or
            # ambiguous; unverified scans must not erase operator context.
            if accepted and top:
                self._last_match = dict(top)
        return result

    def reference_path(self, reference_id: str) -> Path | None:
        with self._lock:
            record = next(
                (item for item in self._records if str(item.get("id")) == str(reference_id)),
                None,
            )
        if not record:
            return None
        try:
            path = Path(str(record.get("image_path") or "")).resolve()
            if path.parent != self.image_dir.resolve() or not path.is_file():
                return None
            return path
        except OSError:
            return None

    def reference_summary(self, reference_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = next(
                (item for item in self._records if str(item.get("id")) == str(reference_id)),
                None,
            )
            if not record:
                return None
            return {
                "id": str(record.get("id") or ""),
                "pack_label": str(record.get("pack_label") or ""),
                "set_id": str(record.get("set_id") or ""),
                "set_name": str(record.get("set_name") or record.get("set_id") or ""),
                "language": str(record.get("language") or "Any"),
                "provider": str(record.get("provider") or ""),
                "pack_profile": dict(record.get("pack_profile") or {}),
                "profile_learning": self._learning_summary(record),
                "image_url": f"/api/recognition/pack-reference/{record.get('id')}",
            }

    @staticmethod
    def _learning_summary(record: dict[str, Any]) -> dict[str, Any]:
        observations = list((record.get("pack_profile_learning") or {}).get("observations") or [])
        result: dict[str, Any] = {"observation_count": len(observations), "suggested_profile": None, "confidence": 0.0}
        if len(observations) < 3:
            return result
        card_counts = Counter(int(item.get("observed_cards") or 0) for item in observations if int(item.get("observed_cards") or 0) > 0)
        rare_counts = Counter(int(item.get("rare_slot") or 0) for item in observations if int(item.get("rare_slot") or 0) > 0)
        if not card_counts:
            return result
        expected, support = card_counts.most_common(1)[0]
        confidence = support / len(observations)
        if support < 2 or confidence < (2 / 3):
            return result
        rare = rare_counts.most_common(1)[0][0] if rare_counts else expected
        rare = max(1, min(expected, rare))
        current = record.get("pack_profile") or {}
        suggestion = {"expected_cards": expected, "rare_slot": rare}
        if suggestion != {"expected_cards": int(current.get("expected_cards") or 10), "rare_slot": int(current.get("rare_slot") or 10)}:
            result["suggested_profile"] = suggestion
        result["confidence"] = round(confidence, 3)
        return result

    def observe_reference_profile(
        self, reference_id: str, observed_cards: int, rare_slot: int | None = None
    ) -> dict[str, Any] | None:
        cards = max(1, min(30, int(observed_cards)))
        rare = max(1, min(cards, int(rare_slot))) if rare_slot else None
        with self._lock:
            record = next((item for item in self._records if str(item.get("id")) == str(reference_id)), None)
            if not record:
                return None
            learning = record.setdefault("pack_profile_learning", {"observations": []})
            observations = list(learning.get("observations") or [])
            observations.append({"observed_cards": cards, "rare_slot": rare, "observed_at": time.time()})
            learning["observations"] = observations[-20:]
            summary = self._learning_summary(record)
            if self._last_match and str(self._last_match.get("id")) == str(reference_id):
                self._last_match["pack_profile_learning"] = dict(learning)
                self._last_match["profile_learning"] = dict(summary)
            self._save()
            return summary

    def update_reference_profile(
        self, reference_id: str, expected_cards: int, rare_slot: int
    ) -> dict[str, int] | None:
        expected = max(1, min(30, int(expected_cards)))
        rare = max(1, min(expected, int(rare_slot)))
        with self._lock:
            record = next(
                (item for item in self._records if str(item.get("id")) == str(reference_id)),
                None,
            )
            if not record:
                return None
            profile = {"expected_cards": expected, "rare_slot": rare}
            record["pack_profile"] = profile
            if self._last_match and str(self._last_match.get("id")) == str(reference_id):
                self._last_match["pack_profile"] = dict(profile)
            self._save()
        return profile

    def rename_reference(self, reference_id: str, label: str) -> bool:
        clean = " ".join(str(label or "").split()).strip()[:120]
        if not clean:
            return False
        with self._lock:
            record = next(
                (item for item in self._records if str(item.get("id")) == str(reference_id)),
                None,
            )
            if not record:
                return False
            record["pack_label"] = clean
            self._save()
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            records = [dict(item) for item in self._records]
        sets = sorted({
            (str(item.get("set_name") or item.get("set_id") or "Unknown"),
             str(item.get("language") or "Any"))
            for item in records
        })
        return {
            "ok": True,
            "reference_count": len(records),
            "sets": [{"set_name": name, "language": language} for name, language in sets],
            "references": [
                {
                    "id": str(item.get("id") or ""),
                    "set_id": str(item.get("set_id") or ""),
                    "set_name": str(item.get("set_name") or ""),
                    "language": str(item.get("language") or "Any"),
                    "provider": str(item.get("provider") or ""),
                    "pack_label": str(item.get("pack_label") or ""),
                    "pack_profile": dict(item.get("pack_profile") or {}),
                    "profile_learning": self._learning_summary(item),
                    "image_url": f"/api/recognition/pack-reference/{item.get('id')}",
                    "created_at": float(item.get("created_at") or 0.0),
                }
                for item in records
            ],
            "last_match": dict(self._last_match) if self._last_match else None,
        }
