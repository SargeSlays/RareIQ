from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import time
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import cv2
import httpx

from rareiq.core.storage import storage
from rareiq.core.provider_http import request_json, download_bytes


class CatalogIntelligenceService:
    """Builds and serves RareIQ's normalized, image-backed master catalog."""

    API_BASE = "https://api.tcgdex.net/v2"

    @classmethod
    def _tcgdex_url(cls, language_code: str, resource: str, resource_id: str) -> str:
        language = quote(str(language_code or "en"), safe="")
        kind = quote(str(resource or ""), safe="")
        identifier = quote(str(resource_id or ""), safe="")
        return f"{cls.API_BASE}/{language}/{kind}/{identifier}"
    LANGUAGE_MAP = {
        "English": "en",
        "Japanese": "ja",
        "French": "fr",
        "German": "de",
        "Italian": "it",
        "Spanish": "es",
        "Portuguese": "pt",
        "Chinese": "zh-tw",
        "Traditional Chinese": "zh-tw",
        "Korean": "ko",
    }

    def __init__(
        self,
        project_root: Path,
        artwork_index: Any,
        shared_dropbox_link: str | None = None,
    ) -> None:
        self.project_root = project_root
        self.root = storage.get_path("catalog_path") / "pokemon"
        self.sets_dir = self.root / "sets"
        self.index_path = self.root / "master_cards.json"
        self.config_path = storage.get_path("config_path") / "catalog_config.json"
        self.sets_dir.mkdir(parents=True, exist_ok=True)

        self.artwork_index = artwork_index
        self._lock = threading.RLock()
        self._cards: list[dict[str, Any]] = []
        self._by_number: dict[str, list[dict[str, Any]]] = {}
        self._by_set_local: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._status: dict[str, Any] = {
            "busy": False,
            "provider": "TCGdex + RareIQ Master Catalog",
            "sets": 0,
            "cards": 0,
            "images": 0,
            "coverage_percent": 0.0,
            "last_import": None,
            "error": None,
        }

        default_config = {
            "dropbox_shared_link": shared_dropbox_link,
            "dropbox_local_path": "",
            "mirror_enabled": False,
            "preferred_language": "Chinese",
        }
        if not self.config_path.exists():
            self.config_path.write_text(
                json.dumps(default_config, indent=2),
                encoding="utf-8",
            )

        self._load_master_index()

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")

    @staticmethod
    def _number_parts(number: str | None) -> tuple[int | None, int | None]:
        if not number or "/" not in str(number):
            return None, None
        left, right = str(number).split("/", 1)
        try:
            return int(re.sub(r"\D", "", left)), int(re.sub(r"\D", "", right))
        except ValueError:
            return None, None

    @classmethod
    def infer_rarity(
        cls,
        rarity: str | None,
        collector_number: str | None,
        card_name: str | None = None,
    ) -> str:
        text = " ".join(
            str(value or "") for value in (rarity, card_name)
        ).lower()

        mappings = (
            (("special art rare", "special illustration rare", " sar"), "SAR"),
            (("illustration rare", " art rare", " ar"), "AR"),
            (("ultra rare", " ur"), "UR"),
            (("super rare", " sr"), "SR"),
            (("double rare", " rr"), "RR"),
            (("rare",), "R"),
            (("uncommon",), "U"),
            (("common",), "C"),
        )
        padded = f" {text} "
        for aliases, normalized in mappings:
            if any(alias in padded for alias in aliases):
                return normalized

        numerator, denominator = cls._number_parts(collector_number)
        if (
            numerator is not None
            and denominator is not None
            and numerator > denominator
        ):
            return "SECRET RARE"
        return str(rarity or "UNKNOWN").upper()

    @staticmethod
    def _image_url(base: str | None) -> str | None:
        if not base:
            return None
        value = str(base).rstrip("/")
        if value.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return value
        return f"{value}/high.webp"

    @staticmethod
    def _dhash(path: Path) -> str | None:
        image = cv2.imread(str(path))
        if image is None:
            return None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        diff = resized[:, 1:] > resized[:, :-1]
        value = 0
        for bit in diff.flatten():
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def config(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def configure(
        self,
        *,
        dropbox_local_path: str | None = None,
        mirror_enabled: bool | None = None,
        preferred_language: str | None = None,
    ) -> dict[str, Any]:
        config = self.config()
        if dropbox_local_path is not None:
            config["dropbox_local_path"] = dropbox_local_path
        if mirror_enabled is not None:
            config["mirror_enabled"] = bool(mirror_enabled)
        if preferred_language is not None:
            config["preferred_language"] = preferred_language

        self.config_path.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "config": config}

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._status)
            payload["config"] = self.config()
            payload["set_manifests"] = self._set_summaries()
            return payload

    def collection_reference_cards(self) -> list[dict[str, Any]]:
        """Return the minimum immutable fields needed for collection checklists."""
        with self._lock:
            return [
                {
                    "game_id": card.get("game_id") or "pokemon",
                    "card_name": card.get("english_name") or card.get("name"),
                    "printed_name": card.get("printed_name"),
                    "set_name": card.get("set_name"),
                    "set_code": card.get("set_code") or card.get("set_id"),
                    "collector_number": card.get("collector_number"),
                    "language": card.get("language"),
                    "reference_image_url": card.get("reference_image_url") or card.get("image_url"),
                }
                for card in self._cards
                if card.get("collector_number")
                and (card.get("set_code") or card.get("set_id") or card.get("set_name"))
            ]

    def _set_summaries(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for path in sorted(self.sets_dir.glob("*/manifest.json")):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                summaries.append({
                    "set_id": manifest.get("set_id"),
                    "set_name": manifest.get("set_name"),
                    "language": manifest.get("language"),
                    "cards": manifest.get("cards", 0),
                    "images": manifest.get("images", 0),
                    "coverage_percent": manifest.get("coverage_percent", 0),
                })
            except Exception:
                continue
        return summaries

    def _load_master_index(self) -> None:
        cards: list[dict[str, Any]] = []
        if self.index_path.exists():
            try:
                cards = json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                cards = []

        by_number: dict[str, list[dict[str, Any]]] = {}
        by_set_local: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for card in cards:
            card.setdefault("game_id", "pokemon")
            number = str(card.get("collector_number") or "").lower()
            if number:
                by_number.setdefault(number, []).append(card)
            set_id = str(card.get("set_id") or card.get("set_code") or "").strip().casefold()
            local_id = str(card.get("local_id") or "").strip()
            if not local_id and number:
                local_id = number.split("/", 1)[0]
            local_digits = re.sub(r"\D", "", local_id).lstrip("0") or "0"
            if set_id and local_digits:
                by_set_local.setdefault((set_id, local_digits), []).append(card)

        images = sum(
            1 for card in cards
            if card.get("local_image") and Path(card["local_image"]).exists()
        )
        with self._lock:
            self._cards = cards
            self._by_number = by_number
            self._by_set_local = by_set_local
            self._status.update({
                "sets": len(self._set_summaries()),
                "cards": len(cards),
                "images": images,
                "coverage_percent": (
                    round(images / len(cards) * 100, 2) if cards else 0.0
                ),
            })

    def rebuild_master_index(self) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        for cards_path in sorted(self.sets_dir.glob("*/cards.json")):
            try:
                payload = json.loads(cards_path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    for card in payload:
                        if isinstance(card, dict):
                            card.setdefault("game_id", "pokemon")
                            cards.append(card)
            except Exception:
                continue

        self.index_path.write_text(
            json.dumps(cards, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._load_master_index()
        return {"ok": True, "status": self.status()}

    def resolve(self, recognition: dict[str, Any]) -> dict[str, Any] | None:
        number = str(
            recognition.get("collector_number")
            or recognition.get("ocr_collector_number")
            or ""
        ).lower()
        if not number:
            return None

        active_set = dict(recognition.get("active_set") or {})
        wanted_set_ids = {
            str(value or "").strip().casefold()
            for value in (
                recognition.get("set_id"),
                recognition.get("set_name"),
                active_set.get("id"),
                active_set.get("set_id"),
                active_set.get("name"),
            )
            if str(value or "").strip()
        }
        candidates = list(self._by_number.get(number) or [])
        wanted_game = str(recognition.get("game_id") or "pokemon").casefold()
        candidates = [
            card for card in candidates
            if str(card.get("game_id") or "pokemon").casefold() == wanted_game
        ]
        observed_local = re.sub(
            r"\D", "", number.split("/", 1)[0]
        ).lstrip("0") or "0"
        for set_id in wanted_set_ids:
            for card in self._by_set_local.get((set_id, observed_local), []):
                if card not in candidates:
                    candidates.append(card)
        if wanted_set_ids:
            set_matches = [
                card for card in candidates
                if wanted_set_ids.intersection({
                    str(card.get("set_id") or "").strip().casefold(),
                    str(card.get("set_name") or "").strip().casefold(),
                } - {""})
            ]
            if set_matches:
                candidates = set_matches
        if not candidates:
            return None

        language = str(
            recognition.get("language") or active_set.get("language") or ""
        ).lower()
        name = str(recognition.get("name_candidate") or "").lower()

        # A translated printing is a different catalog variant even when the
        # artwork, set and collector number are identical.  Prefer the exact
        # requested language before image availability can influence ranking.
        if language:
            language_matches = [
                card for card in candidates
                if language in str(card.get("language") or "").lower()
                or language == str(card.get("language_code") or "").lower()
                or (language == "english" and str(card.get("language_code") or "").lower() == "en")
            ]
            if language_matches:
                candidates = language_matches

        def score(card: dict[str, Any]) -> float:
            value = 0.70
            card_language = str(card.get("language") or "").lower()
            printed = str(card.get("printed_name") or card.get("name") or "").lower()
            if language and language in card_language:
                value += 0.12
            card_set_ids = {
                str(card.get("set_id") or "").strip().casefold(),
                str(card.get("set_name") or "").strip().casefold(),
            } - {""}
            if wanted_set_ids and wanted_set_ids.intersection(card_set_ids):
                value += 0.15
            if name and (name in printed or printed in name):
                value += 0.12
            if card.get("local_image"):
                value += 0.06
            return min(0.99, value)

        best = max(candidates, key=score)
        result = dict(best)
        result["score"] = score(best)
        result["fused_score"] = result["score"]
        result["source"] = "rareiq_master_catalog"
        result["set_locked_catalog_lookup"] = bool(wanted_set_ids)
        return result

    def import_tcgdex_set(
        self,
        set_id: str,
        language_name: str,
        max_cards: int | None = None,
        *,
        progress_callback: Any | None = None,
        defer_indexes: bool = False,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        set_id = set_id.strip()
        if not set_id:
            return {"ok": False, "error": "Set ID is required."}

        language_code = self.LANGUAGE_MAP.get(language_name, "en")
        set_dir = self.sets_dir / self._safe(f"{language_code}_{set_id}")
        images_dir = (
            storage.get_path("image_path")
            / "pokemon"
            / language_code
            / self._safe(set_id)
        )
        set_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        started = time.perf_counter()
        with self._lock:
            self._status.update({"busy": True, "error": None})

        errors: list[str] = []
        images_downloaded = 0
        cards: list[dict[str, Any]] = []

        try:
            with httpx.Client(
                timeout=httpx.Timeout(40.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=max(8, max_workers * 2),
                    max_keepalive_connections=max(4, max_workers),
                ),
            ) as client:
                set_payload, _ = request_json(
                    client,
                    "GET",
                    self._tcgdex_url(language_code, "sets", set_id),
                )

            briefs = list(set_payload.get("cards") or [])
            if max_cards:
                briefs = briefs[:max_cards]

            set_name = str(set_payload.get("name") or set_id)
            card_count = set_payload.get("cardCount") or {}
            official_count = (
                card_count.get("official")
                or card_count.get("total")
                or len(briefs)
            )

            def process_card(
                position: int,
                brief: dict[str, Any],
            ) -> tuple[dict[str, Any] | None, list[str], bool]:
                local_errors: list[str] = []
                card_id = str(brief.get("id") or "")
                if not card_id:
                    return None, ["Missing card ID"], False

                detail: dict[str, Any] = {}
                with httpx.Client(
                    timeout=httpx.Timeout(40.0, connect=10.0),
                    follow_redirects=True,
                ) as card_client:
                    try:
                        detail, _ = request_json(
                            card_client,
                            "GET",
                            self._tcgdex_url(language_code, "cards", card_id),
                        )
                    except Exception as exc:
                        local_errors.append(f"{card_id}: metadata {exc}")

                    source = detail or brief
                    local_id = str(
                        source.get("localId")
                        or brief.get("localId")
                        or position
                    )
                    denominator = (
                        (source.get("set") or {})
                        .get("cardCount", {})
                        .get("total")
                        or official_count
                    )
                    collector_number = (
                        f"{local_id}/{denominator}"
                        if denominator
                        else local_id
                    )
                    image_url = self._image_url(
                        source.get("image") or brief.get("image")
                    )
                    image_path = images_dir / f"{self._safe(card_id)}.webp"
                    downloaded = False

                    if image_url and not image_path.exists():
                        try:
                            content, _ = download_bytes(card_client, image_url)
                            image_path.write_bytes(content)
                            downloaded = True
                        except Exception as exc:
                            local_errors.append(f"{card_id}: image {exc}")

                image_exists = image_path.exists()
                normalized = {
                    "game_id": "pokemon",
                    "id": card_id,
                    "name": source.get("name"),
                    "printed_name": source.get("name"),
                    "english_name": (
                        source.get("name")
                        if language_code == "en"
                        else None
                    ),
                    "language": language_name,
                    "language_code": language_code,
                    "set_id": set_id,
                    "set_name": set_name,
                    "collector_number": collector_number,
                    "local_id": local_id,
                    "rarity": self.infer_rarity(
                        source.get("rarity"),
                        collector_number,
                        source.get("name"),
                    ),
                    "raw_rarity": source.get("rarity"),
                    "category": source.get("category"),
                    "hp": source.get("hp"),
                    "types": source.get("types") or [],
                    "illustrator": source.get("illustrator"),
                    "regulation_mark": source.get("regulationMark"),
                    "image_url": image_url,
                    "reference_image_url": (
                        f"/api/catalog-engine/image/"
                        f"{language_code}_{set_id}/{image_path.name}"
                        if image_exists else image_url
                    ),
                    "local_image": str(image_path) if image_exists else None,
                    "dhash": self._dhash(image_path) if image_exists else None,
                    "sha256": self._sha256(image_path) if image_exists else None,
                    "source": "TCGdex",
                }
                return normalized, local_errors, downloaded

            workers = max(1, min(16, int(max_workers)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(process_card, index, brief): index
                    for index, brief in enumerate(briefs, start=1)
                }
                processed = 0
                for future in as_completed(futures):
                    card, local_errors, downloaded = future.result()
                    processed += 1
                    errors.extend(local_errors)
                    if card:
                        cards.append(card)
                    if downloaded:
                        images_downloaded += 1
                    if progress_callback:
                        progress_callback({
                            "provider": "tcgdex",
                            "language": language_name,
                            "set_id": set_id,
                            "set_name": set_name,
                            "processed": processed,
                            "total": len(briefs),
                            "cards": len(cards),
                            "images": sum(
                                1 for item in cards
                                if item.get("local_image")
                            ),
                        })

            cards.sort(key=lambda item: str(item.get("local_id") or ""))
            cards_path = set_dir / "cards.json"
            cards_path.write_text(
                json.dumps(cards, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            images_present = sum(
                1 for card in cards if card.get("local_image")
            )
            manifest = {
                "catalog_format": "RareIQ Master Catalog v1",
                "game_id": "pokemon",
                "provider": "tcgdex",
                "set_id": set_id,
                "set_name": set_name,
                "language": language_name,
                "language_code": language_code,
                "official_count": official_count,
                "cards": len(cards),
                "images": images_present,
                "coverage_percent": (
                    round(images_present / len(cards) * 100, 2)
                    if cards else 0.0
                ),
                "imported_at": time.time(),
                "errors": errors,
                # Means every card in this provider response was visited. It
                # does not claim 100% coverage: providers may omit artwork.
                "download_complete": True,
            }
            (set_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            index_result: dict[str, Any] = {"deferred": True}
            if not defer_indexes:
                self.rebuild_master_index()
                index_result = self.artwork_index.rebuild()

            result = {
                "ok": True,
                "set_id": set_id,
                "set_name": set_name,
                "language": language_name,
                "cards": len(cards),
                "images": images_present,
                "images_downloaded": images_downloaded,
                "coverage_percent": manifest["coverage_percent"],
                "errors": errors,
                "index_status": index_result,
                "mirror": self._mirror_set(set_dir),
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000,
                    1,
                ),
            }
            with self._lock:
                self._status.update({
                    "busy": False,
                    "last_import": result,
                    "error": None,
                })
            return result
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            with self._lock:
                self._status.update({
                    "busy": False,
                    "error": str(exc),
                    "last_import": result,
                })
            return result

    def _mirror_set(self, set_dir: Path) -> dict[str, Any]:
        config = self.config()
        if not config.get("mirror_enabled"):
            return {"enabled": False}

        target_root = str(config.get("dropbox_local_path") or "").strip()
        if not target_root:
            return {
                "enabled": True,
                "ok": False,
                "error": "Set a local Dropbox sync folder first.",
            }

        target = Path(target_root).expanduser() / "RareIQ Catalogs" / set_dir.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(set_dir, target, dirs_exist_ok=True)
            return {"enabled": True, "ok": True, "path": str(target)}
        except Exception as exc:
            return {"enabled": True, "ok": False, "error": str(exc)}
