from __future__ import annotations

from typing import Any

import httpx

from rareiq.catalog_providers.base import CatalogProvider
from rareiq.core.provider_http import request_json


class TCGdexProvider(CatalogProvider):
    provider_id = "tcgdex"
    display_name = "TCGdex"
    API_BASE = "https://api.tcgdex.net/v2"

    LANGUAGE_CODES = {
        "English": "en",
        "Japanese": "ja",
        "French": "fr",
        "German": "de",
        "Italian": "it",
        "Spanish": "es",
        "Portuguese": "pt",
        "Traditional Chinese": "zh-tw",
    }
    languages = tuple(LANGUAGE_CODES)


    def health(self) -> dict[str, Any]:
        import time

        started = time.perf_counter()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=8.0),
                follow_redirects=True,
            ) as client:
                payload, response = request_json(
                    client,
                    "GET",
                    f"{self.API_BASE}/en/sets",
                    attempts=2,
                )
            return {
                "online": True,
                "status_code": response.status_code,
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000, 1
                ),
                "authenticated": True,
                "sample_count": len(payload) if isinstance(payload, list) else 0,
                "error": None,
            }
        except Exception as exc:
            return {
                "online": False,
                "status_code": None,
                "latency_ms": round(
                    (time.perf_counter() - started) * 1000, 1
                ),
                "authenticated": True,
                "sample_count": 0,
                "error": str(exc),
            }

    def _code(self, language: str) -> str:
        return self.LANGUAGE_CODES[language]

    def discover_sets(self, language: str) -> list[dict[str, Any]]:
        code = self._code(language)
        with httpx.Client(timeout=35.0, follow_redirects=True) as client:
            payload, _ = request_json(
                client,
                "GET",
                f"{self.API_BASE}/{code}/sets",
            )

        result: list[dict[str, Any]] = []
        for item in payload if isinstance(payload, list) else []:
            result.append({
                "provider": self.provider_id,
                "language": language,
                "set_id": item.get("id"),
                "set_name": item.get("name"),
                "logo": item.get("logo"),
                "symbol": item.get("symbol"),
                "card_count": (
                    (item.get("cardCount") or {}).get("total")
                    or (item.get("cardCount") or {}).get("official")
                ),
            })
        return result

    def fetch_set(self, language: str, set_id: str) -> dict[str, Any]:
        code = self._code(language)
        with httpx.Client(timeout=35.0, follow_redirects=True) as client:
            payload, _ = request_json(
                client,
                "GET",
                f"{self.API_BASE}/{code}/sets/{set_id}",
            )
            return payload

    def fetch_card(
        self,
        language: str,
        card_id: str,
    ) -> dict[str, Any] | None:
        code = self._code(language)
        with httpx.Client(timeout=35.0, follow_redirects=True) as client:
            response = client.get(f"{self.API_BASE}/{code}/cards/{card_id}")
            if response.status_code != 200:
                return None
            return response.json()
