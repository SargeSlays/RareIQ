from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from rareiq.catalog_providers.base import CatalogProvider


class SimplifiedTCGProvider(CatalogProvider):
    """Public mainland-China catalog provider, distinct from zh-tw."""

    provider_id = "simplifiedtcg"
    display_name = "SimplifiedTCG"
    API_BASE = "https://simplifiedtcg.com"
    languages = ("Simplified Chinese",)

    @staticmethod
    def _embedded_objects(document: str) -> list[dict[str, Any]]:
        candidates = re.findall(
            r'\{\\"id\\":(?:\\"[^"\\]+\\"|\d+).*?\}',
            document,
            flags=re.DOTALL,
        )
        records: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                value = json.loads(candidate.replace('\\"', '"'))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=25.0, follow_redirects=True) as client:
                response = client.get(f"{self.API_BASE}/tcg/")
                response.raise_for_status()
            sets = [item for item in self._embedded_objects(response.text)
                    if item.get("n_cards") is not None and item.get("name")]
            return {
                "online": True, "status_code": response.status_code,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "authenticated": True, "sample_count": len(sets), "error": None,
            }
        except Exception as exc:
            return {
                "online": False, "status_code": None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "authenticated": True, "sample_count": 0, "error": str(exc),
            }

    def discover_sets(self, language: str) -> list[dict[str, Any]]:
        if language != "Simplified Chinese":
            return []
        with httpx.Client(timeout=35.0, follow_redirects=True) as client:
            response = client.get(f"{self.API_BASE}/tcg/")
            response.raise_for_status()
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in self._embedded_objects(response.text):
            set_id = str(item.get("id") or "").strip()
            if (not set_id or set_id.casefold() in seen
                    or item.get("n_cards") is None or not item.get("name")):
                continue
            seen.add(set_id.casefold())
            result.append({
                "provider": self.provider_id,
                "language": "Simplified Chinese",
                "set_id": set_id,
                "set_name": str(item.get("name") or set_id),
                "local_name": item.get("local_name"),
                "logo": item.get("pack_image_url"),
                "card_count": int(item.get("n_cards") or 0),
                "release_date": item.get("release_date"),
                "series": item.get("series"),
                "category": item.get("category"),
            })
        return result

    def fetch_set(self, language: str, set_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=40.0, follow_redirects=True) as client:
            response = client.get(f"{self.API_BASE}/set/{set_id}/")
            response.raise_for_status()
        cards: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in self._embedded_objects(response.text):
            if str(item.get("set_id") or "").casefold() != set_id.casefold():
                continue
            card_id = str(item.get("id") or "")
            if not card_id or card_id in seen or not item.get("card_number"):
                continue
            seen.add(card_id)
            cards.append(item)
        name_match = re.search(r"<h1>(.*?)</h1>", response.text, flags=re.DOTALL)
        set_name = re.sub(r"<[^>]+>", "", name_match.group(1)).strip() if name_match else set_id
        return {"id": set_id, "name": set_name, "cards": cards}

    def fetch_card(self, language: str, card_id: str) -> dict[str, Any] | None:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(f"{self.API_BASE}/card/{card_id}/")
            if response.status_code != 200:
                return None
        for item in self._embedded_objects(response.text):
            if str(item.get("id") or "") == str(card_id):
                return item
        return None
