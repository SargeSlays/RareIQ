from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from rareiq.core.storage import storage


class GlobalVisualIndexService:
    """Disk-first local visual index that does not depend on in-memory catalog state."""

    def __init__(self, project_root: Path, catalog_engine: Any) -> None:
        self.project_root = project_root
        self.catalog_engine = catalog_engine
        self.root = storage.get_path("index_path") / "pokemon" / "visual"
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.root / "records.json"
        self.matrix_path = self.root / "features.npy"
        self.state_path = self.root / "build_state.json"

        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._matrix: np.ndarray | None = None
        self._status = {
            "ready": False,
            "busy": False,
            "records": 0,
            "dimensions": 0,
            "discovered_cards": 0,
            "processed_cards": 0,
            "skipped_missing": 0,
            "skipped_corrupt": 0,
            "progress_percent": 0,
            "current_card": None,
            "last_build": None,
            "latency_ms": 0.0,
            "error": None,
        }
        self._load()

    @staticmethod
    def _feature(image: np.ndarray) -> np.ndarray:
        if image is None or image.size == 0:
            raise ValueError("Empty image")

        resized = cv2.resize(image, (160, 224), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

        hist_parts = []
        for channel, bins, value_range in (
            (0, 32, [0, 180]),
            (1, 32, [0, 256]),
            (2, 32, [0, 256]),
        ):
            hist = cv2.calcHist([hsv], [channel], None, [bins], value_range)
            hist = cv2.normalize(hist, hist).flatten()
            hist_parts.append(hist)

        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 80, 180)
        edge_hist = cv2.resize(edges, (16, 16), interpolation=cv2.INTER_AREA)
        edge_hist = edge_hist.astype(np.float32).flatten() / 255.0

        feature = np.concatenate([*hist_parts, edge_hist]).astype(np.float32)
        norm = float(np.linalg.norm(feature))
        if norm > 0:
            feature /= norm
        return feature

    def _load(self) -> None:
        try:
            if self.records_path.exists() and self.matrix_path.exists():
                records = json.loads(
                    self.records_path.read_text(encoding="utf-8")
                )
                matrix = np.load(self.matrix_path)
                if matrix.ndim != 2 or len(records) != matrix.shape[0]:
                    raise ValueError("Visual index record/matrix count mismatch")
                with self._lock:
                    self._records = records
                    self._matrix = matrix.astype(np.float32, copy=False)
                    self._status.update({
                        "ready": bool(records),
                        "records": len(records),
                        "dimensions": int(matrix.shape[1]) if len(records) else 0,
                    })
        except Exception as exc:
            with self._lock:
                self._status["error"] = str(exc)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def _discover_cards(self) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        sets_dir = storage.get_path("catalog_path") / "pokemon" / "sets"
        image_root = storage.get_path("image_path") / "pokemon"

        for cards_file in sorted(sets_dir.glob("*/cards.json")):
            try:
                payload = json.loads(cards_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, list):
                continue

            for card in payload:
                if not isinstance(card, dict):
                    continue
                item = dict(card)
                path_value = item.get("local_image")
                path = Path(path_value) if path_value else None

                if path is None or not path.exists():
                    language_code = str(item.get("language_code") or "unknown")
                    set_id = str(item.get("set_id") or "unknown")
                    card_id = str(
                        item.get("id")
                        or item.get("local_id")
                        or item.get("collector_number")
                        or "card"
                    )
                    safe = "".join(
                        character if character.isalnum() or character in "-_."
                        else "_"
                        for character in card_id
                    ).strip("._") or "card"
                    candidate = image_root / language_code / set_id / f"{safe}.webp"
                    if candidate.exists():
                        path = candidate
                        item["local_image"] = str(candidate)

                cards.append(item)

        return cards

    def rebuild(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        cards = self._discover_cards()
        total = len(cards)
        records: list[dict[str, Any]] = []
        features: list[np.ndarray] = []
        missing = corrupt = 0

        with self._lock:
            self._status.update({
                "busy": True,
                "ready": False,
                "discovered_cards": total,
                "processed_cards": 0,
                "skipped_missing": 0,
                "skipped_corrupt": 0,
                "progress_percent": 0,
                "current_card": None,
                "error": None,
            })

        for position, card in enumerate(cards, start=1):
            if stop_event and stop_event.is_set():
                break

            card_id = str(card.get("id") or card.get("collector_number") or position)
            image_path = card.get("local_image")
            with self._lock:
                self._status["current_card"] = card_id

            if not image_path:
                missing += 1
            else:
                path = Path(image_path)
                if not path.exists() or path.stat().st_size < 1024:
                    missing += 1
                else:
                    try:
                        image = cv2.imread(str(path))
                        feature = self._feature(image)
                        records.append({
                            "id": card.get("id"),
                            "name": card.get("name"),
                            "english_name": card.get("english_name"),
                            "printed_name": card.get("printed_name"),
                            "set_id": card.get("set_id"),
                            "set_name": card.get("set_name"),
                            "collector_number": card.get("collector_number"),
                            "language": card.get("language"),
                            "rarity": card.get("rarity"),
                            "reference_image_url": card.get("reference_image_url"),
                            "local_image": str(path),
                            "source": card.get("source"),
                        })
                        features.append(feature)
                    except Exception:
                        corrupt += 1

            percent = round(position / total * 100) if total else 100
            with self._lock:
                self._status.update({
                    "processed_cards": position,
                    "records": len(records),
                    "skipped_missing": missing,
                    "skipped_corrupt": corrupt,
                    "progress_percent": percent,
                })

            if progress_callback and (
                position == 1 or position == total or position % 100 == 0
            ):
                progress_callback(self.status())

        matrix = (
            np.vstack(features).astype(np.float32)
            if features
            else np.zeros((0, 352), dtype=np.float32)
        )

        temp_records = self.records_path.with_suffix(".json.part")
        temp_matrix = self.matrix_path.with_suffix(".npy.part")
        temp_records.write_text(
            json.dumps(records, ensure_ascii=False),
            encoding="utf-8",
        )
        with temp_matrix.open("wb") as handle:
            np.save(handle, matrix)
        temp_records.replace(self.records_path)
        temp_matrix.replace(self.matrix_path)

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        stopped = bool(stop_event and stop_event.is_set())

        with self._lock:
            self._records = records
            self._matrix = matrix
            self._status.update({
                "busy": False,
                "ready": bool(records),
                "records": len(records),
                "dimensions": int(matrix.shape[1]) if matrix.ndim == 2 else 0,
                "processed_cards": min(total, self._status["processed_cards"]),
                "skipped_missing": missing,
                "skipped_corrupt": corrupt,
                "progress_percent": (
                    self._status["progress_percent"] if stopped else 100
                ),
                "current_card": None,
                "last_build": time.time(),
                "latency_ms": elapsed,
                "error": None,
            })

        return {
            "ok": True,
            "stopped": stopped,
            "records": len(records),
            "dimensions": self._status["dimensions"],
            "discovered_cards": total,
            "missing": missing,
            "corrupt": corrupt,
            "latency_ms": elapsed,
        }


    def incremental_update(
        self,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Add only local images not already represented in the index."""
        started = time.perf_counter()
        cards = self._discover_cards()

        with self._lock:
            existing_records = list(self._records)
            existing_matrix = (
                self._matrix.copy()
                if self._matrix is not None
                else np.zeros((0, 352), dtype=np.float32)
            )

        existing_keys = {
            (
                str(item.get("id") or ""),
                str(item.get("local_image") or ""),
            )
            for item in existing_records
        }

        pending = []
        for card in cards:
            key = (
                str(card.get("id") or ""),
                str(card.get("local_image") or ""),
            )
            if key not in existing_keys and card.get("local_image"):
                pending.append(card)

        total = len(pending)
        added_records: list[dict[str, Any]] = []
        added_features: list[np.ndarray] = []
        missing = corrupt = 0

        with self._lock:
            self._status.update({
                "busy": True,
                "error": None,
                "discovered_cards": total,
                "processed_cards": 0,
                "progress_percent": 0,
                "current_card": None,
            })

        for position, card in enumerate(pending, start=1):
            if stop_event and stop_event.is_set():
                break

            card_id = str(card.get("id") or card.get("collector_number") or position)
            path_value = card.get("local_image")
            path = Path(path_value) if path_value else None

            with self._lock:
                self._status["current_card"] = card_id

            if path is None or not path.exists() or path.stat().st_size < 1024:
                missing += 1
            else:
                try:
                    image = cv2.imread(str(path))
                    feature = self._feature(image)
                    added_records.append({
                        "id": card.get("id"),
                        "name": card.get("name"),
                        "english_name": card.get("english_name"),
                        "printed_name": card.get("printed_name"),
                        "set_id": card.get("set_id"),
                        "set_name": card.get("set_name"),
                        "collector_number": card.get("collector_number"),
                        "language": card.get("language"),
                        "rarity": card.get("rarity"),
                        "reference_image_url": card.get("reference_image_url"),
                        "local_image": str(path),
                        "source": card.get("source"),
                    })
                    added_features.append(feature)
                except Exception:
                    corrupt += 1

            percent = round(position / total * 100) if total else 100
            with self._lock:
                self._status.update({
                    "processed_cards": position,
                    "progress_percent": percent,
                    "skipped_missing": missing,
                    "skipped_corrupt": corrupt,
                })

            if progress_callback and (
                position == 1 or position == total or position % 100 == 0
            ):
                progress_callback(self.status())

        if added_features:
            new_matrix = np.vstack(added_features).astype(np.float32)
            matrix = (
                np.vstack([existing_matrix, new_matrix])
                if len(existing_matrix)
                else new_matrix
            )
        else:
            matrix = existing_matrix

        records = existing_records + added_records

        temp_records = self.records_path.with_suffix(".json.part")
        temp_matrix = self.matrix_path.with_suffix(".npy.part")
        temp_records.write_text(
            json.dumps(records, ensure_ascii=False),
            encoding="utf-8",
        )
        with temp_matrix.open("wb") as handle:
            np.save(handle, matrix)
        temp_records.replace(self.records_path)
        temp_matrix.replace(self.matrix_path)

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        stopped = bool(stop_event and stop_event.is_set())

        with self._lock:
            self._records = records
            self._matrix = matrix
            self._status.update({
                "busy": False,
                "ready": bool(records),
                "records": len(records),
                "dimensions": int(matrix.shape[1]) if matrix.ndim == 2 and len(matrix) else 0,
                "progress_percent": (
                    self._status["progress_percent"] if stopped else 100
                ),
                "current_card": None,
                "last_build": time.time(),
                "latency_ms": elapsed,
                "error": None,
            })

        return {
            "ok": True,
            "stopped": stopped,
            "pending": total,
            "added": len(added_records),
            "records": len(records),
            "missing": missing,
            "corrupt": corrupt,
            "latency_ms": elapsed,
        }

    def available_local_image_count(self) -> int:
        return sum(
            1
            for card in self._discover_cards()
            if card.get("local_image")
            and Path(str(card.get("local_image"))).exists()
        )

    def search_image(
        self,
        image: np.ndarray,
        limit: int = 25,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        with self._lock:
            matrix = self._matrix
            records = list(self._records)

        if matrix is None or not len(records):
            return {
                "ok": False,
                "error": "Global visual index is empty.",
                "matches": [],
            }

        query = self._feature(image)
        scores = matrix @ query
        count = min(max(1, int(limit)), len(records))
        indices = np.argpartition(scores, -count)[-count:]
        indices = indices[np.argsort(scores[indices])[::-1]]

        matches = []
        for index in indices:
            record = dict(records[int(index)])
            score = float(scores[int(index)])
            record["visual_score"] = max(0.0, min(1.0, score))
            record["score"] = record["visual_score"]
            record["fused_score"] = record["visual_score"]
            record["source"] = "global_visual_index"
            matches.append(record)

        return {
            "ok": True,
            "matches": matches,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
