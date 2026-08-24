from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


JsonFetcher = Callable[[str], dict[str, Any]]


class PokedexService:
    """Resolve verified card identities into cached species intelligence."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        fetcher: JsonFetcher | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._fetcher = fetcher or self._fetch_json
        self._lock = threading.RLock()

    @staticmethod
    def _slug(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text

    @classmethod
    def pokemon_name(cls, card: dict[str, Any] | None) -> str:
        card = card or {}
        for key in (
            "pokemon_name", "canonical_name", "english_name",
            "display_name", "name",
        ):
            value = str(card.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _fetch_json(url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "RareIQ-StudioX/1.0"},
        )
        with urllib.request.urlopen(request, timeout=5.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def _cache_path(self, slug: str) -> Path:
        return self.cache_dir / f"{slug}.json"

    def _read_cache(self, slug: str) -> dict[str, Any] | None:
        path = self._cache_path(slug)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _write_cache(self, slug: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(slug)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _english_flavor(species: dict[str, Any]) -> str | None:
        for entry in species.get("flavor_text_entries") or []:
            if (entry.get("language") or {}).get("name") == "en":
                return " ".join(str(entry.get("flavor_text") or "").split())
        return None

    @staticmethod
    def _english_genus(species: dict[str, Any]) -> str | None:
        for entry in species.get("genera") or []:
            if (entry.get("language") or {}).get("name") == "en":
                return str(entry.get("genus") or "").strip() or None
        return None

    def resolve(self, card: dict[str, Any] | None) -> dict[str, Any]:
        card = dict(card or {})
        name = self.pokemon_name(card)
        slug = self._slug(name)
        if not slug:
            return {"status": "empty", "pokemon": None}

        with self._lock:
            cached = self._read_cache(slug)
        if cached:
            return {"status": "available", "pokemon": cached, "cached": True}

        try:
            encoded = urllib.parse.quote(slug)
            pokemon = self._fetcher(f"https://pokeapi.co/api/v2/pokemon/{encoded}")
            species_url = (pokemon.get("species") or {}).get("url")
            species = self._fetcher(species_url) if species_url else {}
            sprites = pokemon.get("sprites") or {}
            official = (
                ((sprites.get("other") or {}).get("official-artwork") or {})
                .get("front_default")
            )
            payload = {
                "id": pokemon.get("id"),
                "name": str(pokemon.get("name") or name).replace("-", " ").title(),
                "slug": slug,
                "genus": self._english_genus(species),
                "types": [
                    (item.get("type") or {}).get("name")
                    for item in pokemon.get("types") or []
                    if (item.get("type") or {}).get("name")
                ],
                "height_m": round(float(pokemon.get("height") or 0) / 10.0, 2),
                "weight_kg": round(float(pokemon.get("weight") or 0) / 10.0, 2),
                "abilities": [
                    (item.get("ability") or {}).get("name", "").replace("-", " ").title()
                    for item in pokemon.get("abilities") or []
                    if (item.get("ability") or {}).get("name")
                ],
                "base_experience": pokemon.get("base_experience"),
                "base_happiness": species.get("base_happiness"),
                "capture_rate": species.get("capture_rate"),
                "habitat": (species.get("habitat") or {}).get("name"),
                "generation": (species.get("generation") or {}).get("name"),
                "flavor_text": self._english_flavor(species),
                "artwork_url": official or sprites.get("front_default"),
                "source": "PokeAPI",
                "resolved_at": time.time(),
            }
            with self._lock:
                self._write_cache(slug, payload)
            return {"status": "available", "pokemon": payload, "cached": False}
        except Exception as exc:
            fallback = {
                "id": None,
                "name": name,
                "slug": slug,
                "genus": None,
                "types": card.get("types") or (
                    [card.get("energy_type")] if card.get("energy_type") else []
                ),
                "height_m": None,
                "weight_kg": None,
                "abilities": [],
                "flavor_text": None,
                "artwork_url": None,
                "source": "RareIQ card identity",
            }
            return {
                "status": "partial",
                "pokemon": fallback,
                "cached": False,
                "error": str(exc),
            }
