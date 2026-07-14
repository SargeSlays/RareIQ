from __future__ import annotations

from typing import Any

import httpx

from rareiq.catalog_providers.base import CatalogProvider
from rareiq.core.provider_http import request_json
from rareiq.core.secrets import secrets


class PokemonTCGProvider(CatalogProvider):
    provider_id = "pokemontcg"
    display_name = "Pokémon TCG API"
    API_BASE = "https://api.pokemontcg.io/v2"
    languages = ("English",)

    def _headers(self) -> dict[str, str]:
        secrets.reload()
        key = str(secrets.get("pokemontcg_api_key") or "").strip()
        return {"X-Api-Key": key} if key else {}

    def health(self) -> dict[str, Any]:
        started = __import__("time").perf_counter()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=8.0),
                follow_redirects=True,
                headers=self._headers(),
            ) as client:
                payload, response = request_json(
                    client,
                    "GET",
                    f"{self.API_BASE}/sets",
                    params={"page": 1, "pageSize": 1, "select": "id,name"},
                    attempts=2,
                )
            return {
                "online": True,
                "status_code": response.status_code,
                "latency_ms": round(
                    (__import__("time").perf_counter() - started) * 1000, 1
                ),
                "authenticated": bool(self._headers()),
                "sample_count": len(payload.get("data") or []),
                "error": None,
            }
        except Exception as exc:
            return {
                "online": False,
                "status_code": None,
                "latency_ms": round(
                    (__import__("time").perf_counter() - started) * 1000, 1
                ),
                "authenticated": bool(self._headers()),
                "sample_count": 0,
                "error": str(exc),
            }

    def discover_sets(self, language: str) -> list[dict[str, Any]]:
        with httpx.Client(
            timeout=httpx.Timeout(35.0, connect=10.0),
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            payload, _ = request_json(
                client,
                "GET",
                f"{self.API_BASE}/sets",
                params={"pageSize": 250},
            )

        result: list[dict[str, Any]] = []
        for item in payload.get("data") or []:
            result.append({
                "provider": self.provider_id,
                "language": "English",
                "set_id": item.get("id"),
                "set_name": item.get("name"),
                "logo": (item.get("images") or {}).get("logo"),
                "symbol": (item.get("images") or {}).get("symbol"),
                "card_count": item.get("total"),
                "release_date": item.get("releaseDate"),
            })
        return result

    def fetch_set(self, language: str, set_id: str) -> dict[str, Any]:
        with httpx.Client(
            timeout=httpx.Timeout(35.0, connect=10.0),
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            set_payload, _ = request_json(
                client,
                "GET",
                f"{self.API_BASE}/sets/{set_id}",
            )
            cards_payload, _ = request_json(
                client,
                "GET",
                f"{self.API_BASE}/cards",
                params={
                    "q": f"set.id:{set_id}",
                    "pageSize": 250,
                },
            )

        set_data = set_payload.get("data") or {}
        set_data["cards"] = cards_payload.get("data") or []
        return set_data

    def fetch_card(
        self,
        language: str,
        card_id: str,
    ) -> dict[str, Any] | None:
        with httpx.Client(
            timeout=httpx.Timeout(35.0, connect=10.0),
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            try:
                payload, _ = request_json(
                    client,
                    "GET",
                    f"{self.API_BASE}/cards/{card_id}",
                )
                return payload.get("data")
            except Exception:
                return None
