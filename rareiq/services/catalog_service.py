from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable


class CatalogService:
    API_BASE = "https://api.tcgdex.net/v2"
    LANGUAGE_MAP = {
        "English": ["en"],
        "Japanese": ["ja"],
        "Chinese": ["zh-tw", "en"],
        "Unknown": ["en"],
    }

    def __init__(self, emit: Callable[[dict[str, Any]], None], cache_dir: Path) -> None:
        self.emit = emit
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._busy = False
        self._last_key: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._status: dict[str, Any] = {
            "busy": False,
            "source": None,
            "query": None,
            "match": None,
            "candidates": [],
            "latency_ms": None,
            "error": None,
            "note": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def submit(self, recognition: dict[str, Any]) -> None:
        number = (
            recognition.get("collector_number")
            or recognition.get("ocr_collector_number")
        )
        name = (
            recognition.get("name_candidate")
            or recognition.get("printed_name")
            or recognition.get("name")
        )

        number_text = str(number or "").strip()
        name_text = str(name or "").strip()

        has_number = bool(number_text and "/" in number_text)
        has_name = bool(name_text)

        if not has_number and not has_name:
            return

        language = str(
            recognition.get("language") or "Unknown"
        )

        key = f"{language}|{number_text}|{name_text}"

        with self._lock:
            if self._busy or key == self._last_key:
                return

            self._busy = True
            self._last_key = key
            self._status.update({
                "busy": True,
                "query": {
                    "language": language,
                    "number": number_text or None,
                    "name": name_text or None,
                },
                "error": None,
            })

        threading.Thread(
            target=self._lookup_worker,
            args=(
                language,
                number_text,
                name_text or None,
            ),
            daemon=True,
        ).start()

    @staticmethod
    def _http_json(url: str, timeout: float = 6.0) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RareIQ/0.8",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _split_number(number: str) -> tuple[str, str]:
        left, right = number.split("/", 1)
        return left.lstrip("0") or "0", right.lstrip("0") or "0"

    def _cache_path(self, language_code: str, number: str) -> Path:
        safe = number.replace("/", "-")
        return self.cache_dir / f"{language_code}_{safe}.json"

    def _read_cache(self, language_code: str, number: str) -> dict[str, Any] | None:
        path = self._cache_path(language_code, number)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(payload.get("cached_at", 0)) < 86400:
                return payload
        except Exception:
            return None
        return None

    def _write_cache(self, language_code: str, number: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(language_code, number)
        payload = dict(payload)
        payload["cached_at"] = time.time()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_price(card: dict[str, Any]) -> dict[str, Any] | None:
        pricing = card.get("pricing") or {}
        tcgplayer = pricing.get("tcgplayer") or {}
        for variant_name in ("normal", "holofoil", "reverse-holofoil"):
            variant = tcgplayer.get(variant_name)
            if isinstance(variant, dict):
                market = variant.get("marketPrice")
                low = variant.get("lowPrice")
                high = variant.get("highPrice")
                if any(value is not None for value in (market, low, high)):
                    return {
                        "source": "TCGPlayer",
                        "variant": variant_name,
                        "market": market,
                        "low": low,
                        "high": high,
                        "unit": tcgplayer.get("unit", "USD"),
                        "updated_at": time.time(),
                    }

        cardmarket = pricing.get("cardmarket") or {}
        if cardmarket:
            return {
                "source": "Cardmarket",
                "variant": "standard",
                "market": cardmarket.get("trend") or cardmarket.get("avg"),
                "low": cardmarket.get("low"),
                "high": None,
                "unit": cardmarket.get("unit", "EUR"),
                "updated_at": time.time(),
            }
        return None

    @classmethod
    def _normalize_card(cls, card: dict[str, Any], language_code: str) -> dict[str, Any]:
        set_info = card.get("set") or {}
        counts = set_info.get("cardCount") or {}
        total = counts.get("total")
        official = counts.get("official")
        denominator = total or official
        local_id = str(card.get("localId") or "")
        number = f"{local_id}/{denominator}" if denominator else local_id

        raw_image = card.get("image")
        image_url = None
        if raw_image:
            raw_image = str(raw_image).rstrip("/")
            image_url = (
                raw_image
                if raw_image.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                else f"{raw_image}/high.webp"
            )

        return {
            "id": card.get("id"),
            "name": card.get("name"),
            "english_name": card.get("name") if language_code == "en" else None,
            "language_code": language_code,
            "collector_number": number,
            "local_id": local_id,
            "set_id": set_info.get("id"),
            "set_name": set_info.get("name"),
            "set_total": total,
            "set_official": official,
            "rarity": card.get("rarity"),
            "category": card.get("category"),
            "hp": card.get("hp"),
            "image": raw_image,
            "image_url": image_url,
            "reference_image_url": image_url,
            "pricing": cls._extract_price(card),
        }

    def _lookup_language(self, language_code: str, number: str) -> dict[str, Any]:
        cached = self._read_cache(language_code, number)
        if cached is not None:
            cached["source"] = "cache"
            return cached

        numerator, denominator = self._split_number(number)
        query = urllib.parse.urlencode({"localId": f"eq:{numerator}"})
        cards_url = f"{self.API_BASE}/{language_code}/cards?{query}"
        briefs = self._http_json(cards_url)

        if not isinstance(briefs, list):
            briefs = []

        details: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    self._http_json,
                    f"{self.API_BASE}/{language_code}/cards/{brief.get('id')}",
                ): brief
                for brief in briefs[:40]
                if brief.get("id")
            }
            for future in as_completed(futures):
                try:
                    card = future.result()
                except Exception:
                    continue
                if not isinstance(card, dict):
                    continue
                set_info = card.get("set") or {}
                counts = set_info.get("cardCount") or {}
                values = {str(counts.get("total")), str(counts.get("official"))}
                if denominator in values:
                    details.append(self._normalize_card(card, language_code))

        payload = {
            "source": "tcgdex",
            "language_code": language_code,
            "number": number,
            "candidates": details,
        }
        self._write_cache(language_code, number, payload)
        return payload

    def _lookup_name(
        self,
        language_code: str,
        name: str,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode({
            "name": f"eq:{name}",
        })

        cards_url = (
            f"{self.API_BASE}/{language_code}/cards?{query}"
        )

        briefs = self._http_json(cards_url)

        if not isinstance(briefs, list):
            briefs = []

        details: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    self._http_json,
                    (
                        f"{self.API_BASE}/{language_code}/cards/"
                        f"{brief.get('id')}"
                    ),
                ): brief
                for brief in briefs[:30]
                if brief.get("id")
            }

            for future in as_completed(futures):
                try:
                    card = future.result()
                except Exception:
                    continue

                if not isinstance(card, dict):
                    continue

                details.append(
                    self._normalize_card(
                        card,
                        language_code,
                    )
                )

        return {
            "source": "tcgdex",
            "language_code": language_code,
            "name": name,
            "candidates": details,
        }

    def _lookup_worker(self, language: str, number: str, name: str | None) -> None:
        started = time.perf_counter()
        try:
            language_codes = self.LANGUAGE_MAP.get(language, ["en"])
            all_candidates: list[dict[str, Any]] = []
            source = "tcgdex"
            notes: list[str] = []

            for code in language_codes:
                try:
                    if number and "/" in number:
                        result = self._lookup_language(
                            code,
                            number,
                        )
                    elif name:
                        result = self._lookup_name(
                            code,
                            name,
                        )
                    else:
                        continue

                    source = result.get("source") or source
                    all_candidates.extend(
                        result.get("candidates") or []
                    )
                except Exception as exc:
                    notes.append(f"{code}: {exc}")

            if language == "Chinese":
                notes.append(
                    "TCGdex currently lists Traditional Chinese, not Simplified Chinese; English fallback candidates may appear."
                )

            # Deduplicate by card id while preserving order.
            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for card in all_candidates:
                key = str(card.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(card)

            english_candidates = [
                card for card in deduped if card.get("language_code") == "en"
            ]
            local_candidates = [
                card for card in deduped if card.get("language_code") != "en"
            ]

            for card in local_candidates:
                partner = next(
                    (
                        english
                        for english in english_candidates
                        if english.get("collector_number") == card.get("collector_number")
                    ),
                    None,
                )
                if partner:
                    card["english_name"] = partner.get("name")
                    card["english_image_url"] = partner.get("image_url")
                    if not card.get("reference_image_url"):
                        card["reference_image_url"] = partner.get("image_url")

            ordered = local_candidates + english_candidates if local_candidates else english_candidates
            match = ordered[0] if len(ordered) == 1 else None
            payload = {
                "busy": False,
                "source": source,
                "query": {"language": language, "number": number, "name": name},
                "match": match,
                "candidates": ordered[:8],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": None,
                "note": " | ".join(notes) if notes else None,
            }

        except Exception as exc:
            payload = {
                "busy": False,
                "source": None,
                "query": {"language": language, "number": number, "name": name},
                "match": None,
                "candidates": [],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": str(exc),
                "note": None,
            }

        with self._lock:
            self._busy = False
            self._status.update(payload)
            self._last_result = payload

        self.emit({"type": "catalog_update", "payload": payload})
