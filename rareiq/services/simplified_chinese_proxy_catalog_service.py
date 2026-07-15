from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import cv2
import httpx


class SimplifiedChineseProxyCatalogService:
    API_BASE = "https://api.tcgdex.net/v2"

    PROXY_LANGUAGES = {
        "English": "en",
        "Japanese": "ja",
        "Traditional Chinese": "zh-tw",
    }

    IMAGE_EXTENSIONS = (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    )

    def __init__(
        self,
        project_root: Path,
        emit: Callable[
            [dict[str, Any]],
            None,
        ] | None = None,
    ) -> None:
        self.project_root = Path(
            project_root
        )

        self.emit = emit or (
            lambda payload: None
        )

        self.root = (
            self.project_root
            / "catalog_master"
            / "simplified_chinese_proxy"
        )

        self.images_root = (
            self.root
            / "images"
        )

        self.registry_path = (
            self.root
            / "registry.json"
        )

        self.catalog_path = (
            self.root
            / "proxy_cards.json"
        )

        self.manifest_path = (
            self.root
            / "manifest.json"
        )

        self.errors_path = (
            self.root
            / "errors.json"
        )

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.images_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

        self._status: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "registry_records": 0,
            "records_processed": 0,
            "records_matched": 0,
            "records_unmatched": 0,
            "proxy_images_downloaded": 0,
            "proxy_images_existing": 0,
            "proxy_images_failed": 0,
            "current_registry_id": None,
            "current_language": None,
            "started_at": None,
            "updated_at": time.time(),
            "error": None,
            "errors": [],
        }

        self._load_manifest()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                self._status
            )

    def _set_status(
        self,
        **values: Any,
    ) -> None:
        with self._lock:
            self._status.update(
                values
            )

            self._status[
                "updated_at"
            ] = time.time()

            payload = dict(
                self._status
            )

        self.emit({
            "type": (
                "simplified_chinese_proxy_catalog_status"
            ),
            "payload": payload,
        })

    def _load_manifest(
        self,
    ) -> None:
        if not self.manifest_path.exists():
            return

        try:
            payload = json.loads(
                self.manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return

        with self._lock:
            self._status.update({
                "phase": "READY",
                "registry_records": int(
                    payload.get(
                        "registry_records"
                    )
                    or 0
                ),
                "records_processed": int(
                    payload.get(
                        "records_processed"
                    )
                    or 0
                ),
                "records_matched": int(
                    payload.get(
                        "records_matched"
                    )
                    or 0
                ),
                "records_unmatched": int(
                    payload.get(
                        "records_unmatched"
                    )
                    or 0
                ),
                "proxy_images_downloaded": int(
                    payload.get(
                        "proxy_images_downloaded"
                    )
                    or 0
                ),
                "proxy_images_existing": int(
                    payload.get(
                        "proxy_images_existing"
                    )
                    or 0
                ),
                "proxy_images_failed": int(
                    payload.get(
                        "proxy_images_failed"
                    )
                    or 0
                ),
            })

    @staticmethod
    def _read_json(
        path: Path,
        default: Any,
    ) -> Any:
        if not path.exists():
            return default

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return default

    @staticmethod
    def _write_json(
        path: Path,
        payload: Any,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_filename(
        value: Any,
    ) -> str:
        cleaned = "".join(
            character
            if character.isalnum()
            or character in "-_."
            else "_"
            for character in str(
                value or ""
            )
        )

        return (
            cleaned.strip("._")
            or "card"
        )

    @staticmethod
    def _normalize_name(
        value: Any,
    ) -> str:
        text = unicodedata.normalize(
            "NFKC",
            str(
                value or ""
            ),
        ).lower()

        return re.sub(
            r"[\s\-_:：·・'’\"“”()\[\]{}]+",
            "",
            text,
        )

    @staticmethod
    def _split_collector_number(
        value: Any,
    ) -> tuple[
        str,
        str | None,
    ]:
        text = str(
            value or ""
        ).strip()

        if "/" not in text:
            return (
                text.lstrip(
                    "0"
                )
                or "0",
                None,
            )

        left, right = text.split(
            "/",
            1,
        )

        return (
            left.strip().lstrip(
                "0"
            )
            or "0",
            right.strip().lstrip(
                "0"
            )
            or "0",
        )

    @staticmethod
    def _card_total(
        card: dict[str, Any],
    ) -> str | None:
        set_info = (
            card.get(
                "set"
            )
            or {}
        )

        counts = (
            set_info.get(
                "cardCount"
            )
            or {}
        )

        total = (
            counts.get(
                "total"
            )
            or counts.get(
                "official"
            )
        )

        if total is None:
            return None

        return str(
            total
        )

    @classmethod
    def _image_url(
        cls,
        card: dict[str, Any],
    ) -> str | None:
        raw = card.get(
            "image"
        )

        if not raw:
            return None

        value = str(
            raw
        ).rstrip(
            "/"
        )

        if value.lower().endswith(
            cls.IMAGE_EXTENSIONS
        ):
            return value

        return (
            f"{value}/high.webp"
        )

    @staticmethod
    def _sha256_file(
        path: Path,
    ) -> str | None:
        try:
            digest = hashlib.sha256()

            with path.open(
                "rb"
            ) as handle:
                while True:
                    chunk = handle.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    digest.update(
                        chunk
                    )

            return digest.hexdigest()

        except Exception:
            return None

    @staticmethod
    def _verify_image(
        path: Path,
    ) -> tuple[
        bool,
        str | None,
    ]:
        if not path.exists():
            return (
                False,
                "missing",
            )

        if path.stat().st_size < 1024:
            return (
                False,
                "too_small",
            )

        image = cv2.imread(
            str(
                path
            )
        )

        if image is None or image.size == 0:
            return (
                False,
                "decode_failed",
            )

        height, width = (
            image.shape[:2]
        )

        if width < 150 or height < 200:
            return (
                False,
                "dimensions_too_small",
            )

        return (
            True,
            None,
        )

    def initialize_registry(
        self,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if (
            self.registry_path.exists()
            and not overwrite
        ):
            return {
                "ok": True,
                "created": False,
                "registry_path": str(
                    self.registry_path
                ),
            }

        template = {
            "format": (
                "RareIQ Simplified Chinese "
                "Proxy Registry v1"
            ),
            "records": [
                {
                    "id": "CSV7C-084",
                    "set_id": "CSV7C",
                    "set_name": (
                        "Greninja Jumbo Box"
                    ),
                    "collector_number": (
                        "084/204"
                    ),
                    "printed_name": (
                        "甲贺忍蛙"
                    ),
                    "english_name": (
                        "Greninja"
                    ),
                    "japanese_name": (
                        "ゲッコウガ"
                    ),
                    "traditional_chinese_name": (
                        "甲賀忍蛙"
                    ),
                    "rarity": None,
                    "variant": None,
                    "proxy_set_ids": {
                        "en": [],
                        "ja": [],
                        "zh-tw": [],
                    },
                    "exact_zh_cn_image": None,
                }
            ],
        }

        self._write_json(
            self.registry_path,
            template,
        )

        return {
            "ok": True,
            "created": True,
            "registry_path": str(
                self.registry_path
            ),
        }

    def load_registry(
        self,
    ) -> list[
        dict[str, Any]
    ]:
        payload = self._read_json(
            self.registry_path,
            {},
        )

        records = (
            payload.get(
                "records"
            )
            if isinstance(
                payload,
                dict,
            )
            else None
        )

        if not isinstance(
            records,
            list,
        ):
            return []

        return [
            record
            for record in records
            if isinstance(
                record,
                dict,
            )
        ]

    def _fetch_card_candidates(
        self,
        *,
        client: httpx.Client,
        language_code: str,
        local_number: str,
    ) -> list[
        dict[str, Any]
    ]:
        query = (
            f"localId=eq:{local_number}"
        )

        response = client.get(
            (
                f"{self.API_BASE}/"
                f"{language_code}/cards?"
                f"{query}"
            )
        )

        response.raise_for_status()

        briefs = response.json()

        if not isinstance(
            briefs,
            list,
        ):
            return []

        details: list[
            dict[str, Any]
        ] = []

        for brief in briefs[:60]:
            card_id = brief.get(
                "id"
            )

            if not card_id:
                continue

            try:
                detail_response = (
                    client.get(
                        (
                            f"{self.API_BASE}/"
                            f"{language_code}/cards/"
                            f"{card_id}"
                        )
                    )
                )

                detail_response.raise_for_status()

                card = (
                    detail_response.json()
                )

            except Exception:
                continue

            if isinstance(
                card,
                dict,
            ):
                details.append(
                    card
                )

        return details

    @classmethod
    def _candidate_score(
        cls,
        *,
        registry: dict[str, Any],
        candidate: dict[str, Any],
        language_code: str,
    ) -> float:
        (
            local_number,
            denominator,
        ) = (
            cls._split_collector_number(
                registry.get(
                    "collector_number"
                )
            )
        )

        candidate_local = str(
            candidate.get(
                "localId"
            )
            or candidate.get(
                "local_id"
            )
            or ""
        ).lstrip(
            "0"
        ) or "0"

        if (
            candidate_local
            != local_number
        ):
            return 0.0

        score = 0.40

        candidate_total = (
            cls._card_total(
                candidate
            )
        )

        if denominator:
            if (
                candidate_total
                == denominator
            ):
                score += 0.30

            elif (
                candidate_total
                is not None
            ):
                score -= 0.20

        allowed_sets = (
            registry.get(
                "proxy_set_ids"
            )
            or {}
        ).get(
            language_code
        ) or []

        candidate_set_id = str(
            (
                candidate.get(
                    "set"
                )
                or {}
            ).get(
                "id"
            )
            or ""
        )

        if allowed_sets:
            normalized_allowed = {
                str(
                    value
                )
                for value in allowed_sets
            }

            if (
                candidate_set_id
                in normalized_allowed
            ):
                score += 0.20

            else:
                score -= 0.25

        expected_name = {
            "en": registry.get(
                "english_name"
            ),
            "ja": registry.get(
                "japanese_name"
            ),
            "zh-tw": registry.get(
                "traditional_chinese_name"
            ),
        }.get(
            language_code
        )

        if expected_name:
            expected = (
                cls._normalize_name(
                    expected_name
                )
            )

            actual = (
                cls._normalize_name(
                    candidate.get(
                        "name"
                    )
                )
            )

            if expected and actual:
                similarity = (
                    SequenceMatcher(
                        None,
                        expected,
                        actual,
                    ).ratio()
                )

                score += (
                    similarity
                    * 0.30
                )

        return round(
            max(
                0.0,
                min(
                    1.0,
                    score,
                ),
            ),
            4,
        )

    @classmethod
    def choose_best_candidate(
        cls,
        *,
        registry: dict[str, Any],
        candidates: list[
            dict[str, Any]
        ],
        language_code: str,
    ) -> tuple[
        dict[str, Any] | None,
        float,
    ]:
        ranked = [
            (
                cls._candidate_score(
                    registry=registry,
                    candidate=candidate,
                    language_code=(
                        language_code
                    ),
                ),
                candidate,
            )
            for candidate in candidates
        ]

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if not ranked:
            return (
                None,
                0.0,
            )

        score, candidate = (
            ranked[0]
        )

        if score < 0.55:
            return (
                None,
                score,
            )

        return (
            candidate,
            score,
        )

    def _download_proxy_image(
        self,
        *,
        client: httpx.Client,
        registry_id: str,
        language_code: str,
        card: dict[str, Any],
    ) -> dict[str, Any]:
        image_url = self._image_url(
            card
        )

        if not image_url:
            return {
                "ok": False,
                "state": "missing_url",
                "error": (
                    "Card has no image URL."
                ),
            }

        card_id = self._safe_filename(
            card.get(
                "id"
            )
            or registry_id
        )

        destination = (
            self.images_root
            / language_code
            / (
                f"{self._safe_filename(registry_id)}"
                f"__{card_id}.webp"
            )
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if destination.exists():
            valid, reason = (
                self._verify_image(
                    destination
                )
            )

            if valid:
                return {
                    "ok": True,
                    "state": "existing",
                    "path": str(
                        destination
                    ),
                    "checksum": (
                        self._sha256_file(
                            destination
                        )
                    ),
                    "image_url": image_url,
                }

            try:
                destination.unlink()
            except Exception:
                pass

        response = client.get(
            image_url
        )

        response.raise_for_status()

        destination.write_bytes(
            response.content
        )

        valid, reason = (
            self._verify_image(
                destination
            )
        )

        if not valid:
            try:
                destination.unlink()
            except Exception:
                pass

            return {
                "ok": False,
                "state": (
                    reason
                    or "invalid"
                ),
                "error": (
                    reason
                    or "invalid image"
                ),
                "image_url": image_url,
            }

        return {
            "ok": True,
            "state": "downloaded",
            "path": str(
                destination
            ),
            "checksum": (
                self._sha256_file(
                    destination
                )
            ),
            "image_url": image_url,
        }

    def build(
        self,
    ) -> dict[str, Any]:
        self._cancel.clear()

        started_at = time.time()

        registry = self.load_registry()

        if not registry:
            return {
                "ok": False,
                "error": (
                    "Registry is empty. Run "
                    "--init-registry first."
                ),
            }

        self._set_status(
            busy=True,
            phase="STARTING",
            registry_records=len(
                registry
            ),
            records_processed=0,
            records_matched=0,
            records_unmatched=0,
            proxy_images_downloaded=0,
            proxy_images_existing=0,
            proxy_images_failed=0,
            current_registry_id=None,
            current_language=None,
            started_at=started_at,
            error=None,
            errors=[],
        )

        output_records: list[
            dict[str, Any]
        ] = []

        errors: list[
            dict[str, Any]
        ] = []

        processed = 0
        matched = 0
        unmatched = 0
        downloaded = 0
        existing = 0
        failed = 0

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    40.0,
                    connect=10.0,
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "RareIQ/6.4.10.3"
                    ),
                    "Accept": (
                        "application/json,"
                        "image/*,*/*;q=0.8"
                    ),
                },
            ) as client:
                for registry_record in registry:
                    if self._cancel.is_set():
                        break

                    registry_id = str(
                        registry_record.get(
                            "id"
                        )
                        or ""
                    )

                    if not registry_id:
                        errors.append({
                            "registry_id": None,
                            "error": (
                                "Registry record "
                                "is missing id."
                            ),
                        })

                        continue

                    processed += 1

                    self._set_status(
                        phase="MATCHING",
                        current_registry_id=(
                            registry_id
                        ),
                        records_processed=(
                            processed
                        ),
                    )

                    (
                        local_number,
                        _,
                    ) = (
                        self._split_collector_number(
                            registry_record.get(
                                "collector_number"
                            )
                        )
                    )

                    proxies: dict[
                        str,
                        Any,
                    ] = {}

                    for (
                        language,
                        language_code,
                    ) in self.PROXY_LANGUAGES.items():
                        if self._cancel.is_set():
                            break

                        self._set_status(
                            current_language=(
                                language
                            ),
                        )

                        try:
                            candidates = (
                                self._fetch_card_candidates(
                                    client=client,
                                    language_code=(
                                        language_code
                                    ),
                                    local_number=(
                                        local_number
                                    ),
                                )
                            )

                            (
                                candidate,
                                match_score,
                            ) = (
                                self.choose_best_candidate(
                                    registry=(
                                        registry_record
                                    ),
                                    candidates=(
                                        candidates
                                    ),
                                    language_code=(
                                        language_code
                                    ),
                                )
                            )

                            if candidate is None:
                                proxies[
                                    language_code
                                ] = {
                                    "matched": False,
                                    "match_score": (
                                        match_score
                                    ),
                                    "candidate_count": len(
                                        candidates
                                    ),
                                }

                                continue

                            image_result = (
                                self._download_proxy_image(
                                    client=client,
                                    registry_id=(
                                        registry_id
                                    ),
                                    language_code=(
                                        language_code
                                    ),
                                    card=candidate,
                                )
                            )

                            state = (
                                image_result.get(
                                    "state"
                                )
                            )

                            if state == "downloaded":
                                downloaded += 1

                            elif state == "existing":
                                existing += 1

                            elif not image_result.get(
                                "ok"
                            ):
                                failed += 1

                            proxies[
                                language_code
                            ] = {
                                "matched": True,
                                "match_score": (
                                    match_score
                                ),
                                "candidate_count": len(
                                    candidates
                                ),
                                "card_id": (
                                    candidate.get(
                                        "id"
                                    )
                                ),
                                "name": (
                                    candidate.get(
                                        "name"
                                    )
                                ),
                                "set_id": (
                                    (
                                        candidate.get(
                                            "set"
                                        )
                                        or {}
                                    ).get(
                                        "id"
                                    )
                                ),
                                "set_name": (
                                    (
                                        candidate.get(
                                            "set"
                                        )
                                        or {}
                                    ).get(
                                        "name"
                                    )
                                ),
                                "local_id": (
                                    candidate.get(
                                        "localId"
                                    )
                                ),
                                "rarity": (
                                    candidate.get(
                                        "rarity"
                                    )
                                ),
                                "image_url": (
                                    image_result.get(
                                        "image_url"
                                    )
                                ),
                                "local_image": (
                                    image_result.get(
                                        "path"
                                    )
                                ),
                                "image_checksum": (
                                    image_result.get(
                                        "checksum"
                                    )
                                ),
                                "image_state": (
                                    image_result.get(
                                        "state"
                                    )
                                ),
                                "image_error": (
                                    image_result.get(
                                        "error"
                                    )
                                ),
                            }

                        except Exception as exc:
                            failed += 1

                            proxies[
                                language_code
                            ] = {
                                "matched": False,
                                "error": str(
                                    exc
                                ),
                            }

                            errors.append({
                                "registry_id": (
                                    registry_id
                                ),
                                "language_code": (
                                    language_code
                                ),
                                "error": str(
                                    exc
                                ),
                            })

                        self._set_status(
                            proxy_images_downloaded=(
                                downloaded
                            ),
                            proxy_images_existing=(
                                existing
                            ),
                            proxy_images_failed=(
                                failed
                            ),
                        )

                    exact_image = (
                        registry_record.get(
                            "exact_zh_cn_image"
                        )
                    )

                    exact_available = bool(
                        exact_image
                        and Path(
                            str(
                                exact_image
                            )
                        ).exists()
                    )

                    matched_proxy_count = sum(
                        1
                        for proxy in proxies.values()
                        if proxy.get(
                            "matched"
                        )
                    )

                    if matched_proxy_count:
                        matched += 1

                    else:
                        unmatched += 1

                    preferred_proxy = None

                    for language_code in (
                        "zh-tw",
                        "ja",
                        "en",
                    ):
                        proxy = (
                            proxies.get(
                                language_code
                            )
                            or {}
                        )

                        if proxy.get(
                            "local_image"
                        ):
                            preferred_proxy = {
                                "language_code": (
                                    language_code
                                ),
                                **proxy,
                            }

                            break

                    record = {
                        "id": registry_id,
                        "language": (
                            "Simplified Chinese"
                        ),
                        "language_code": (
                            "zh-cn"
                        ),
                        "set_id": (
                            registry_record.get(
                                "set_id"
                            )
                        ),
                        "set_name": (
                            registry_record.get(
                                "set_name"
                            )
                        ),
                        "collector_number": (
                            registry_record.get(
                                "collector_number"
                            )
                        ),
                        "printed_name": (
                            registry_record.get(
                                "printed_name"
                            )
                        ),
                        "english_name": (
                            registry_record.get(
                                "english_name"
                            )
                        ),
                        "japanese_name": (
                            registry_record.get(
                                "japanese_name"
                            )
                        ),
                        "traditional_chinese_name": (
                            registry_record.get(
                                "traditional_chinese_name"
                            )
                        ),
                        "rarity": (
                            registry_record.get(
                                "rarity"
                            )
                        ),
                        "variant": (
                            registry_record.get(
                                "variant"
                            )
                        ),
                        "exact_zh_cn_image": (
                            str(
                                exact_image
                            )
                            if exact_available
                            else None
                        ),
                        "image_source": (
                            "exact_simplified_chinese"
                            if exact_available
                            else (
                                (
                                    "proxy_"
                                    f"{preferred_proxy['language_code']}"
                                )
                                if preferred_proxy
                                else None
                            )
                        ),
                        "reference_image": (
                            str(
                                exact_image
                            )
                            if exact_available
                            else (
                                preferred_proxy.get(
                                    "local_image"
                                )
                                if preferred_proxy
                                else None
                            )
                        ),
                        "proxy_matches": proxies,
                        "proxy_match_count": (
                            matched_proxy_count
                        ),
                        "built_at": time.time(),
                    }

                    output_records.append(
                        record
                    )

                    self._set_status(
                        records_matched=(
                            matched
                        ),
                        records_unmatched=(
                            unmatched
                        ),
                    )

            self._write_json(
                self.catalog_path,
                output_records,
            )

            self._write_json(
                self.errors_path,
                errors,
            )

            manifest = {
                "catalog_format": (
                    "RareIQ Simplified Chinese "
                    "Proxy Catalog v1"
                ),
                "registry_records": len(
                    registry
                ),
                "records_processed": (
                    processed
                ),
                "records_matched": (
                    matched
                ),
                "records_unmatched": (
                    unmatched
                ),
                "proxy_images_downloaded": (
                    downloaded
                ),
                "proxy_images_existing": (
                    existing
                ),
                "proxy_images_failed": (
                    failed
                ),
                "exact_zh_cn_images": sum(
                    1
                    for record in output_records
                    if record.get(
                        "exact_zh_cn_image"
                    )
                ),
                "reference_images": sum(
                    1
                    for record in output_records
                    if record.get(
                        "reference_image"
                    )
                ),
                "canceled": (
                    self._cancel.is_set()
                ),
                "duration_seconds": round(
                    time.time()
                    - started_at,
                    2,
                ),
                "built_at": time.time(),
                "errors": errors[-500:],
            }

            self._write_json(
                self.manifest_path,
                manifest,
            )

            phase = (
                "CANCELED"
                if self._cancel.is_set()
                else "READY"
            )

            self._set_status(
                busy=False,
                phase=phase,
                records_processed=(
                    processed
                ),
                records_matched=(
                    matched
                ),
                records_unmatched=(
                    unmatched
                ),
                proxy_images_downloaded=(
                    downloaded
                ),
                proxy_images_existing=(
                    existing
                ),
                proxy_images_failed=(
                    failed
                ),
                current_registry_id=None,
                current_language=None,
                errors=errors[-200:],
                error=None,
            )

            return {
                "ok": True,
                "manifest": manifest,
                "registry_path": str(
                    self.registry_path
                ),
                "catalog_path": str(
                    self.catalog_path
                ),
                "images_root": str(
                    self.images_root
                ),
                "errors_path": str(
                    self.errors_path
                ),
            }

        except Exception as exc:
            self._set_status(
                busy=False,
                phase="FAILED",
                current_registry_id=None,
                current_language=None,
                error=str(
                    exc
                ),
                errors=errors[-200:],
            )

            return {
                "ok": False,
                "error": str(
                    exc
                ),
            }

    def start_build(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get(
                "busy"
            ):
                return {
                    "ok": False,
                    "error": (
                        "Proxy catalog build "
                        "is already running."
                    ),
                }

        self._worker = threading.Thread(
            target=self.build,
            daemon=True,
            name=(
                "RareIQSimplifiedChineseProxyCatalog"
            ),
        )

        self._worker.start()

        return {
            "ok": True,
            "status": self.status(),
        }

    def cancel(
        self,
    ) -> dict[str, Any]:
        self._cancel.set()

        self._set_status(
            phase="CANCELING"
        )

        return {
            "ok": True
        }
