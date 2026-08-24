from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from rareiq.services.artwork_index_service import ArtworkIndexService


class LiveCatalogService:
    BASE_URL = "https://api.tcgdex.net/v2"
    LANGUAGE_MAP = {
        "English": "en",
        "Japanese": "ja",
        "French": "fr",
        "German": "de",
        "Italian": "it",
        "Spanish": "es",
        "Portuguese": "pt",
        "Chinese": "zh-tw",
        "Korean": "ko",
    }

    def __init__(
        self,
        artwork_index: ArtworkIndexService,
        cache_root: Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.cache_root = cache_root or (project_root / "catalog_cache")
        self.images_dir = self.cache_root / "images"
        self.metadata_dir = self.cache_root / "metadata"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

        self.artwork_index = artwork_index
        self._lock = threading.Lock()
        self._last_import: dict[str, Any] | None = None
        self._error: str | None = None

    @staticmethod
    def _image_url(base: str | None) -> str | None:
        if not base:
            return None
        return f"{base}/high.webp"

    @staticmethod
    def _safe_name(value: str) -> str:
        return re_sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": self._error is None,
                "provider": "TCGdex",
                "cache_root": str(self.cache_root),
                "last_import": self._last_import,
                "error": self._error,
            }

    def import_set(
        self,
        set_id: str,
        language_name: str,
        max_cards: int | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        language_code = self.LANGUAGE_MAP.get(language_name, "en")
        url = f"{self.BASE_URL}/{language_code}/sets/{set_id}"

        imported = 0
        skipped = 0
        stages = {
            "connected": False,
            "set_loaded": False,
            "metadata_downloaded": 0,
            "images_downloaded": 0,
            "references_copied": 0,
            "index_rebuilt": False,
        }
        errors: list[str] = []
        set_payload: dict[str, Any] = {}

        try:
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                stages["connected"] = True
                set_payload = response.json()
                stages["set_loaded"] = True

                cards = list(set_payload.get("cards") or [])
                if max_cards:
                    cards = cards[:max_cards]

                set_name = str(set_payload.get("name") or set_id)

                for brief in cards:
                    card_id = str(brief.get("id") or "")
                    local_id = str(brief.get("localId") or "")
                    name = str(brief.get("name") or card_id)
                    image_base = brief.get("image")
                    image_url = self._image_url(image_base)

                    if not card_id or not image_url:
                        skipped += 1
                        continue

                    card_url = f"{self.BASE_URL}/{language_code}/cards/{card_id}"
                    detail: dict[str, Any] = {}
                    try:
                        card_response = client.get(card_url)
                        if card_response.status_code == 200:
                            detail = card_response.json()
                    except Exception:
                        detail = {}

                    safe_id = card_id.replace("/", "_")
                    image_path = self.images_dir / f"{safe_id}.webp"
                    metadata_path = self.metadata_dir / f"{safe_id}.json"

                    try:
                        if not image_path.exists():
                            image_response = client.get(image_url)
                            image_response.raise_for_status()
                            image_path.write_bytes(image_response.content)
                            stages["images_downloaded"] += 1

                        metadata = {
                            "id": card_id,
                            "name": detail.get("name") or name,
                            "printed_name": detail.get("name") or name,
                            "collector_number": local_id,
                            "language": language_name,
                            "set_name": set_name,
                            "set_id": set_id,
                            "rarity": detail.get("rarity"),
                            "hp": detail.get("hp"),
                            "category": detail.get("category"),
                            "image_url": image_url,
                            "image_path": str(image_path),
                            "pricing": detail.get("pricing"),
                            "source": "TCGdex",
                        }
                        metadata_path.write_text(
                            json.dumps(metadata, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        imported += 1
                        stages["metadata_downloaded"] += 1
                    except Exception as exc:
                        skipped += 1
                        errors.append(f"{card_id}: {exc}")

            # Copy imported references into the artwork-index folder.
            reference_dir = self.artwork_index.reference_dir / set_id
            reference_dir.mkdir(parents=True, exist_ok=True)

            for metadata_path in self.metadata_dir.glob("*.json"):
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("set_id") != set_id:
                    continue

                source_image = Path(str(metadata["image_path"]))
                target_image = reference_dir / source_image.name
                target_metadata = reference_dir / f"{source_image.stem}.json"

                if source_image.exists():
                    shutil_copy(source_image, target_image)
                    stages["references_copied"] += 1
                    target_metadata.write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

            rebuild_result = self.artwork_index.rebuild()
            stages["index_rebuilt"] = bool(rebuild_result.get("ok"))

            result = {
                "ok": True,
                "provider": "TCGdex",
                "language_code": language_code,
                "set_id": set_id,
                "set_name": set_payload.get("name") or set_id,
                "imported": imported,
                "skipped": skipped,
                "errors": errors[:20],
                "stages": stages,
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "index_status": rebuild_result.get("status"),
            }

            with self._lock:
                self._last_import = result
                self._error = None
            return result

        except Exception as exc:
            result = {
                "ok": False,
                "provider": "TCGdex",
                "language_code": language_code,
                "set_id": set_id,
                "imported": imported,
                "skipped": skipped,
                "errors": errors[:20],
                "stages": stages,
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
                "error": str(exc),
            }
            with self._lock:
                self._last_import = result
                self._error = str(exc)
            return result


def re_sub(pattern: str, replacement: str, value: str) -> str:
    import re
    return re.sub(pattern, replacement, value)


def shutil_copy(source: Path, target: Path) -> None:
    import shutil
    shutil.copy2(source, target)
