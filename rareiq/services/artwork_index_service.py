from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class ArtworkIndexService:
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

    @staticmethod
    def hamming(left: str, right: str) -> int:
        return (int(left, 16) ^ int(right, 16)).bit_count()

    def load(self) -> None:
        with self._lock:
            try:
                payload = json.loads(self.index_path.read_text(encoding="utf-8"))
                rows = payload.get("records", payload)
                self._records = [
                    row for row in rows
                    if isinstance(row, dict)
                    and isinstance(row.get("fingerprint"), str)
                ]
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

        matches.sort(key=lambda row: (row["distance"], -row["score"]))

        return {
            "ok": True,
            "query_fingerprint": query,
            "matches": matches[:max(1, int(limit))],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": None,
        }
