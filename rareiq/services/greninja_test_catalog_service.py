
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import httpx


class GreninjaTestCatalogService:
    """Builds a focused multilingual Greninja reference-image catalog."""

    API_BASE = "https://api.tcgdex.net/v2"

    LANGUAGE_CODES = {
        "English": "en",
        "Traditional Chinese": "zh-tw",
    }

    SEARCH_TERMS = (
        "greninja",
        "frogadier",
        "froakie",
        "甲賀忍蛙",
        "甲贺忍蛙",
        "呱頭蛙",
        "呱头蛙",
        "呱呱泡蛙",
    )

    def __init__(
        self,
        project_root: Path,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.emit = emit or (lambda payload: None)

        self.root = (
            self.project_root
            / "catalog_master"
            / "greninja_test"
        )

        self.images_root = self.root / "images"
        self.catalog_path = self.root / "cards.json"
        self.manifest_path = self.root / "manifest.json"
        self.discovery_path = self.root / "discovered_sets.json"

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.images_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()

        self._status: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "languages": list(self.LANGUAGE_CODES),
            "sets_discovered": 0,
            "sets_scanned": 0,
            "cards_scanned": 0,
            "greninja_cards": 0,
            "images_downloaded": 0,
            "images_existing": 0,
            "images_missing": 0,
            "images_corrupt": 0,
            "coverage_percent": 0.0,
            "current_language": None,
            "current_set": None,
            "current_card": None,
            "started_at": None,
            "updated_at": time.time(),
            "error": None,
            "errors": [],
        }

        self._load_manifest()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def _set_status(
        self,
        **values: Any,
    ) -> None:
        with self._lock:
            self._status.update(values)
            self._status["updated_at"] = time.time()
            payload = dict(self._status)

        self.emit({
            "type": "greninja_catalog_status",
            "payload": payload,
        })

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            return

        try:
            payload = json.loads(
                self.manifest_path.read_text(
                    encoding="utf-8"
                )
            )

            with self._lock:
                self._status.update({
                    "phase": "READY",
                    "greninja_cards": int(
                        payload.get("cards") or 0
                    ),
                    "images_downloaded": int(
                        payload.get("images") or 0
                    ),
                    "coverage_percent": float(
                        payload.get("coverage_percent") or 0.0
                    ),
                    "updated_at": float(
                        payload.get("built_at") or time.time()
                    ),
                })
        except Exception:
            return

    @classmethod
    def _matches_target(
        cls,
        *values: Any,
    ) -> bool:
        combined = " ".join(
            str(value or "")
            for value in values
        ).lower()

        return any(
            term.lower() in combined
            for term in cls.SEARCH_TERMS
        )

    @staticmethod
    def _safe_name(value: Any) -> str:
        cleaned = "".join(
            character
            if character.isalnum()
            or character in "-_."
            else "_"
            for character in str(value or "")
        )

        return cleaned.strip("._") or "card"

    @staticmethod
    def _checksum(path: Path) -> str | None:
        try:
            digest = hashlib.sha256()

            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)

                    if not chunk:
                        break

                    digest.update(chunk)

            return digest.hexdigest()
        except Exception:
            return None

    @staticmethod
    def _verify_image(path: Path) -> tuple[bool, str | None]:
        if not path.exists():
            return False, "missing"

        if path.stat().st_size < 1024:
            return False, "too_small"

        image = cv2.imread(str(path))

        if image is None or image.size == 0:
            return False, "decode_failed"

        height, width = image.shape[:2]

        if width < 150 or height < 200:
            return False, "dimensions_too_small"

        return True, None

    @staticmethod
    def _image_url(card: dict[str, Any]) -> str | None:
        raw = card.get("image")

        if not raw:
            return None

        value = str(raw).rstrip("/")

        if value.lower().endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            )
        ):
            return value

        return f"{value}/high.webp"

    @staticmethod
    def _collector_number(
        card: dict[str, Any],
        set_payload: dict[str, Any],
    ) -> str:
        local_id = str(
            card.get("localId")
            or card.get("local_id")
            or ""
        )

        card_count = (
            set_payload.get("cardCount")
            or (card.get("set") or {}).get("cardCount")
            or {}
        )

        total = (
            card_count.get("total")
            or card_count.get("official")
        )

        return (
            f"{local_id}/{total}"
            if total
            else local_id
        )

    def discover_sets(self) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []
        errors: list[str] = []

        with httpx.Client(
            timeout=httpx.Timeout(
                35.0,
                connect=10.0,
            ),
            follow_redirects=True,
            headers={
                "User-Agent": "RareIQ/6.4.10",
                "Accept": "application/json",
            },
        ) as client:
            for language, code in self.LANGUAGE_CODES.items():
                try:
                    response = client.get(
                        f"{self.API_BASE}/{code}/sets"
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    errors.append(
                        f"{language}: {exc}"
                    )
                    continue

                for item in (
                    payload
                    if isinstance(payload, list)
                    else []
                ):
                    discovered.append({
                        "language": language,
                        "language_code": code,
                        "set_id": item.get("id"),
                        "set_name": item.get("name"),
                        "card_count": (
                            (item.get("cardCount") or {}).get(
                                "total"
                            )
                            or (
                                item.get("cardCount") or {}
                            ).get("official")
                        ),
                        "logo": item.get("logo"),
                        "symbol": item.get("symbol"),
                    })

        self.discovery_path.write_text(
            json.dumps(
                discovered,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        self._set_status(
            phase="DISCOVERED",
            sets_discovered=len(discovered),
            errors=errors[-100:],
            error=None,
        )

        return discovered

    def start_build(
        self,
        *,
        max_sets: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get("busy"):
                return {
                    "ok": False,
                    "error": (
                        "Greninja catalog build "
                        "is already running."
                    ),
                }

        self._cancel.clear()

        self._worker = threading.Thread(
            target=self._build_worker,
            kwargs={
                "max_sets": max_sets,
            },
            daemon=True,
            name="RareIQGreninjaCatalog",
        )

        self._worker.start()

        return {
            "ok": True,
            "status": self.status(),
        }

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()

        self._set_status(
            phase="CANCELING",
        )

        return {"ok": True}

    def build(
        self,
        *,
        max_sets: int | None = None,
    ) -> dict[str, Any]:
        self._cancel.clear()
        return self._build_worker(
            max_sets=max_sets,
        )

    def _build_worker(
        self,
        *,
        max_sets: int | None,
    ) -> dict[str, Any]:
        started_at = time.time()

        self._set_status(
            busy=True,
            phase="DISCOVERING",
            started_at=started_at,
            sets_scanned=0,
            cards_scanned=0,
            greninja_cards=0,
            images_downloaded=0,
            images_existing=0,
            images_missing=0,
            images_corrupt=0,
            coverage_percent=0.0,
            current_language=None,
            current_set=None,
            current_card=None,
            error=None,
            errors=[],
        )

        try:
            sets = self.discover_sets()

            if max_sets:
                sets = sets[:max(
                    1,
                    int(max_sets),
                )]

            records: list[dict[str, Any]] = []
            errors: list[str] = []

            sets_scanned = 0
            cards_scanned = 0
            downloaded = 0
            existing = 0
            missing = 0
            corrupt = 0

            with httpx.Client(
                timeout=httpx.Timeout(
                    40.0,
                    connect=10.0,
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": "RareIQ/6.4.10",
                    "Accept": "application/json",
                },
            ) as client:
                for set_item in sets:
                    if self._cancel.is_set():
                        break

                    language = str(
                        set_item.get("language")
                    )

                    language_code = str(
                        set_item.get("language_code")
                    )

                    set_id = str(
                        set_item.get("set_id")
                    )

                    self._set_status(
                        phase="SCANNING",
                        current_language=language,
                        current_set=set_id,
                    )

                    try:
                        response = client.get(
                            (
                                f"{self.API_BASE}/"
                                f"{language_code}/sets/{set_id}"
                            )
                        )

                        response.raise_for_status()
                        set_payload = response.json()
                    except Exception as exc:
                        errors.append(
                            (
                                f"{language}/{set_id}: "
                                f"{exc}"
                            )
                        )
                        continue

                    sets_scanned += 1

                    cards = (
                        set_payload.get("cards")
                        if isinstance(
                            set_payload,
                            dict,
                        )
                        else []
                    )

                    if not isinstance(cards, list):
                        cards = []

                    for brief in cards:
                        if self._cancel.is_set():
                            break

                        card_id = str(
                            brief.get("id")
                            or brief.get("localId")
                            or ""
                        )

                        if not card_id:
                            continue

                        cards_scanned += 1

                        self._set_status(
                            current_card=card_id,
                            sets_scanned=sets_scanned,
                            cards_scanned=cards_scanned,
                        )

                        try:
                            card_response = client.get(
                                (
                                    f"{self.API_BASE}/"
                                    f"{language_code}/cards/"
                                    f"{card_id}"
                                )
                            )

                            card_response.raise_for_status()
                            card = card_response.json()
                        except Exception as exc:
                            errors.append(
                                (
                                    f"{language}/{card_id}: "
                                    f"{exc}"
                                )
                            )
                            continue

                        if not isinstance(card, dict):
                            continue

                        if not self._matches_target(
                            card.get("name"),
                            card.get("description"),
                            card.get("id"),
                        ):
                            continue

                        collector_number = (
                            self._collector_number(
                                card,
                                set_payload,
                            )
                        )

                        image_url = self._image_url(card)

                        language_dir = (
                            self.images_root
                            / language_code
                            / self._safe_name(set_id)
                        )

                        language_dir.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        image_path = (
                            language_dir
                            / (
                                f"{self._safe_name(card_id)}"
                                ".webp"
                            )
                        )

                        image_state = "missing"

                        if image_path.exists():
                            valid, reason = (
                                self._verify_image(
                                    image_path
                                )
                            )

                            if valid:
                                existing += 1
                                image_state = "existing"
                            else:
                                corrupt += 1

                                try:
                                    image_path.unlink()
                                except Exception:
                                    pass
                        else:
                            valid = False
                            reason = "missing"

                        if (
                            not image_path.exists()
                            and image_url
                        ):
                            try:
                                image_response = client.get(
                                    image_url
                                )
                                image_response.raise_for_status()

                                image_path.write_bytes(
                                    image_response.content
                                )

                                valid, reason = (
                                    self._verify_image(
                                        image_path
                                    )
                                )

                                if valid:
                                    downloaded += 1
                                    image_state = "downloaded"
                                else:
                                    corrupt += 1
                                    image_state = (
                                        reason or "corrupt"
                                    )

                                    try:
                                        image_path.unlink()
                                    except Exception:
                                        pass
                            except Exception as exc:
                                missing += 1
                                image_state = "download_failed"

                                errors.append(
                                    (
                                        f"{language}/{card_id} "
                                        f"image: {exc}"
                                    )
                                )
                        elif not image_path.exists():
                            missing += 1

                        record = {
                            "id": card.get("id"),
                            "name": card.get("name"),
                            "printed_name": card.get("name"),
                            "english_name": (
                                card.get("name")
                                if language_code == "en"
                                else None
                            ),
                            "language": language,
                            "language_code": language_code,
                            "set_id": set_id,
                            "set_name": (
                                set_payload.get("name")
                                or set_item.get("set_name")
                            ),
                            "collector_number": (
                                collector_number
                            ),
                            "local_id": card.get("localId"),
                            "rarity": card.get("rarity"),
                            "category": card.get("category"),
                            "hp": card.get("hp"),
                            "illustrator": card.get(
                                "illustrator"
                            ),
                            "image_url": image_url,
                            "reference_image_url": image_url,
                            "local_image": (
                                str(image_path)
                                if image_path.exists()
                                else None
                            ),
                            "image_state": image_state,
                            "image_checksum": (
                                self._checksum(image_path)
                                if image_path.exists()
                                else None
                            ),
                            "source": "TCGdex",
                        }

                        records.append(record)

            english_records = [
                record
                for record in records
                if record.get("language_code") == "en"
            ]

            localized_records = [
                record
                for record in records
                if record.get("language_code") != "en"
            ]

            for localized in localized_records:
                partner = next(
                    (
                        english
                        for english in english_records
                        if (
                            english.get("collector_number")
                            == localized.get(
                                "collector_number"
                            )
                        )
                    ),
                    None,
                )

                if partner:
                    localized["english_name"] = (
                        partner.get("name")
                    )

                    localized["english_reference_image"] = (
                        partner.get("local_image")
                        or partner.get("image_url")
                    )

            records.sort(
                key=lambda record: (
                    str(record.get("language_code") or ""),
                    str(record.get("set_id") or ""),
                    str(record.get("collector_number") or ""),
                )
            )

            valid_images = sum(
                1
                for record in records
                if record.get("local_image")
            )

            coverage = (
                round(
                    valid_images
                    / len(records)
                    * 100.0,
                    2,
                )
                if records
                else 0.0
            )

            self.catalog_path.write_text(
                json.dumps(
                    records,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            manifest = {
                "catalog_format": (
                    "RareIQ Greninja Test Catalog v1"
                ),
                "provider": "TCGdex",
                "languages": list(
                    self.LANGUAGE_CODES
                ),
                "cards": len(records),
                "images": valid_images,
                "images_downloaded": downloaded,
                "images_existing": existing,
                "images_missing": missing,
                "images_corrupt": corrupt,
                "coverage_percent": coverage,
                "sets_scanned": sets_scanned,
                "cards_scanned": cards_scanned,
                "canceled": self._cancel.is_set(),
                "built_at": time.time(),
                "errors": errors[-250:],
            }

            self.manifest_path.write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            phase = (
                "CANCELED"
                if self._cancel.is_set()
                else "READY"
            )

            self._set_status(
                busy=False,
                phase=phase,
                sets_scanned=sets_scanned,
                cards_scanned=cards_scanned,
                greninja_cards=len(records),
                images_downloaded=downloaded,
                images_existing=existing,
                images_missing=missing,
                images_corrupt=corrupt,
                coverage_percent=coverage,
                current_language=None,
                current_set=None,
                current_card=None,
                errors=errors[-100:],
                error=None,
            )

            return {
                "ok": True,
                "manifest": manifest,
                "catalog_path": str(
                    self.catalog_path
                ),
                "images_root": str(
                    self.images_root
                ),
            }

        except Exception as exc:
            self._set_status(
                busy=False,
                phase="FAILED",
                current_language=None,
                current_set=None,
                current_card=None,
                error=str(exc),
            )

            return {
                "ok": False,
                "error": str(exc),
            }
