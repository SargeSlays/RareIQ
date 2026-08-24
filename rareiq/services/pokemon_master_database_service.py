from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rareiq.catalog_providers.pokemontcg_provider import PokemonTCGProvider
from rareiq.catalog_providers.tcgdex_provider import TCGdexProvider
from rareiq.catalog_providers.simplifiedtcg_provider import SimplifiedTCGProvider
from rareiq.core.storage import storage


class PokemonMasterDatabaseService:
    """Discovers and imports Pokémon sets into one global RareIQ index."""

    DEFAULT_LANGUAGES = (
        "English",
        "Japanese",
        "Traditional Chinese",
        "Simplified Chinese",
        "French",
        "German",
        "Italian",
        "Spanish",
        "Portuguese",
    )

    def __init__(
        self,
        project_root: Path,
        catalog_engine: Any,
    ) -> None:
        self.project_root = project_root
        self.catalog_engine = catalog_engine
        self.root = storage.get_path("config_path") / "pokemon_master_database"
        self.discovery_path = self.root / "discovered_sets.json"
        self.progress_path = self.root / "world_build_progress.json"
        self.root.mkdir(parents=True, exist_ok=True)

        self.providers = {
            "tcgdex": TCGdexProvider(),
            "pokemontcg": PokemonTCGProvider(),
            "simplifiedtcg": SimplifiedTCGProvider(),
        }

        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._status: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "provider": None,
            "language": None,
            "set_id": None,
            "set_name": None,
            "sets_discovered": 0,
            "sets_completed": 0,
            "sets_failed": 0,
            "cards": 0,
            "images": 0,
            "coverage_percent": 0.0,
            "started_at": None,
            "updated_at": time.time(),
            "errors": [],
        }
        self._load_progress()

    def _load_progress(self) -> None:
        if not self.progress_path.exists():
            return
        try:
            payload = json.loads(
                self.progress_path.read_text(encoding="utf-8")
            )
            payload["busy"] = False
            payload["phase"] = "PAUSED"
            self._status.update(payload)
        except Exception:
            pass

    def _save_progress(self) -> None:
        with self._lock:
            payload = dict(self._status)
        self.progress_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = dict(self._status)
        payload["providers"] = {
            provider_id: {
                "display_name": provider.display_name,
                "languages": list(provider.languages),
            }
            for provider_id, provider in self.providers.items()
        }
        payload["database"] = self.catalog_engine.status()
        return payload


    def provider_health(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for provider_id, provider in self.providers.items():
            try:
                results[provider_id] = provider.health()
            except Exception as exc:
                results[provider_id] = {
                    "online": False,
                    "error": str(exc),
                }
        return results

    def discover_all(
        self,
        languages: list[str] | None = None,
    ) -> dict[str, Any]:
        selected = tuple(languages or self.DEFAULT_LANGUAGES)
        discovered: list[dict[str, Any]] = []
        errors: list[str] = []

        for provider_id, provider in self.providers.items():
            for language in selected:
                if language not in provider.languages:
                    continue
                try:
                    discovered.extend(provider.discover_sets(language))
                except Exception as exc:
                    errors.append(
                        f"{provider_id}/{language}: {exc}"
                    )

        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in discovered:
            key = "|".join(
                str(value or "").lower()
                for value in (
                    item.get("provider"),
                    item.get("language"),
                    item.get("set_id"),
                )
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        self.discovery_path.write_text(
            json.dumps(deduped, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._lock:
            self._status.update({
                "sets_discovered": len(deduped),
                "updated_at": time.time(),
                "errors": errors[-100:],
            })
        self._save_progress()

        return {
            "ok": True,
            "sets": deduped,
            "count": len(deduped),
            "errors": errors,
        }

    def start_world_build(
        self,
        *,
        languages: list[str] | None = None,
        provider_ids: list[str] | None = None,
        resume: bool = True,
        max_sets: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get("busy"):
                return {
                    "ok": False,
                    "error": "Pokémon Master Database build is already running.",
                }

        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._world_build_worker,
            kwargs={
                "languages": languages,
                "provider_ids": provider_ids,
                "resume": resume,
                "max_sets": max_sets,
            },
            daemon=True,
            name="rareiq-pokemon-master-builder",
        )
        self._worker.start()
        return {"ok": True, "status": self.status()}

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        with self._lock:
            self._status.update({
                "phase": "CANCELING",
                "updated_at": time.time(),
            })
        self._save_progress()
        return {"ok": True}

    def _completed_keys(self) -> set[str]:
        completed: set[str] = set()
        for manifest_path in self.catalog_engine.sets_dir.glob("*/manifest.json"):
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8")
                )
                provider = str(manifest.get("provider") or "").lower()
                language = str(manifest.get("language") or "")
                set_id = str(manifest.get("set_id") or "")
                completed.add(
                    f"{provider}|{language}|{set_id}".lower()
                )
            except Exception:
                continue
        return completed

    def _world_build_worker(
        self,
        *,
        languages: list[str] | None,
        provider_ids: list[str] | None,
        resume: bool,
        max_sets: int | None,
    ) -> None:
        started_at = time.time()
        with self._lock:
            self._status.update({
                "busy": True,
                "phase": "DISCOVERING",
                "started_at": started_at,
                "updated_at": started_at,
                "sets_completed": 0,
                "sets_failed": 0,
                "errors": [],
            })
        self._save_progress()

        try:
            discovery = self.discover_all(languages)
            sets = list(discovery.get("sets") or [])

            selected_providers = set(
                provider_ids or self.providers.keys()
            )
            sets = [
                item for item in sets
                if item.get("provider") in selected_providers
            ]
            if max_sets:
                sets = sets[:max_sets]

            completed_keys = self._completed_keys() if resume else set()

            for item in sets:
                if self._cancel.is_set():
                    break

                provider_id = str(item.get("provider"))
                language = str(item.get("language"))
                set_id = str(item.get("set_id"))
                set_name = str(item.get("set_name") or set_id)
                key = f"{provider_id}|{language}|{set_id}".lower()

                if resume and key in completed_keys:
                    continue

                with self._lock:
                    self._status.update({
                        "phase": "IMPORTING",
                        "provider": provider_id,
                        "language": language,
                        "set_id": set_id,
                        "set_name": set_name,
                        "updated_at": time.time(),
                    })
                self._save_progress()

                try:
                    if provider_id == "tcgdex":
                        result = self.catalog_engine.import_tcgdex_set(
                            set_id,
                            language,
                            None,
                        )
                    elif provider_id == "pokemontcg":
                        result = self._import_pokemontcg_set(
                            set_id,
                            language,
                        )
                    elif provider_id == "simplifiedtcg":
                        result = self._import_simplifiedtcg_set(
                            set_id,
                            language,
                        )
                    else:
                        raise RuntimeError(
                            f"Unsupported provider: {provider_id}"
                        )

                    with self._lock:
                        if result.get("ok"):
                            self._status["sets_completed"] += 1
                        else:
                            self._status["sets_failed"] += 1
                            self._status["errors"].append(
                                f"{provider_id}/{language}/{set_id}: "
                                f"{result.get('error')}"
                            )

                        catalog_status = self.catalog_engine.status()
                        self._status["cards"] = catalog_status.get("cards", 0)
                        self._status["images"] = catalog_status.get("images", 0)
                        self._status["coverage_percent"] = (
                            catalog_status.get("coverage_percent", 0.0)
                        )
                        self._status["updated_at"] = time.time()
                    self._save_progress()
                except Exception as exc:
                    with self._lock:
                        self._status["sets_failed"] += 1
                        self._status["errors"].append(
                            f"{provider_id}/{language}/{set_id}: {exc}"
                        )
                        self._status["updated_at"] = time.time()
                    self._save_progress()

            with self._lock:
                self._status.update({
                    "busy": False,
                    "phase": (
                        "CANCELED"
                        if self._cancel.is_set()
                        else "COMPLETE"
                    ),
                    "provider": None,
                    "language": None,
                    "set_id": None,
                    "set_name": None,
                    "updated_at": time.time(),
                })
            self._save_progress()
        except Exception as exc:
            with self._lock:
                self._status.update({
                    "busy": False,
                    "phase": "FAILED",
                    "errors": self._status.get("errors", []) + [str(exc)],
                    "updated_at": time.time(),
                })
            self._save_progress()

    def _import_pokemontcg_set(
        self,
        set_id: str,
        language: str,
        *,
        progress_callback: Any | None = None,
        defer_indexes: bool = False,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        provider = self.providers["pokemontcg"]
        payload = provider.fetch_set(language, set_id)
        cards = payload.get("cards") or []

        set_dir = self.catalog_engine.sets_dir / f"en_{set_id}"
        images_dir = (
            storage.get_path("image_path")
            / "pokemon"
            / "en"
            / set_id
        )
        set_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        normalized: list[dict[str, Any]] = []
        errors: list[str] = []
        import httpx

        def process_card(card: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            image_error: str | None = None
            images = card.get("images") or {}
            image_url = images.get("large") or images.get("small")
            image_path = images_dir / f"{card.get('id')}.png"

            if image_url and not image_path.exists():
                try:
                    with httpx.Client(
                        timeout=httpx.Timeout(35.0, connect=10.0),
                        follow_redirects=True,
                    ) as client:
                        response = client.get(image_url)
                        response.raise_for_status()
                        image_path.write_bytes(response.content)
                except Exception as exc:
                    image_error = f"{card.get('id')}: image {exc}"

            number = str(card.get("number") or "")
            printed_total = (
                (card.get("set") or {}).get("printedTotal")
                or payload.get("printedTotal")
                or payload.get("total")
            )
            collector_number = (
                f"{number}/{printed_total}"
                if printed_total else number
            )
            image_exists = image_path.exists()
            return ({
                "game_id": "pokemon",
                "id": card.get("id"),
                "name": card.get("name"),
                "printed_name": card.get("name"),
                "english_name": card.get("name"),
                "language": "English",
                "language_code": "en",
                "set_id": set_id,
                "set_name": payload.get("name"),
                "collector_number": collector_number,
                "local_id": number,
                "rarity": self.catalog_engine.infer_rarity(
                    card.get("rarity"),
                    collector_number,
                    card.get("name"),
                ),
                "raw_rarity": card.get("rarity"),
                "category": card.get("supertype"),
                "hp": card.get("hp"),
                "types": card.get("types") or [],
                "illustrator": card.get("artist"),
                "regulation_mark": card.get("regulationMark"),
                "image_url": image_url,
                "reference_image_url": (
                    f"/api/catalog-engine/image/en_{set_id}/"
                    f"{image_path.name}"
                    if image_exists else image_url
                ),
                "local_image": str(image_path) if image_exists else None,
                "source": "Pokémon TCG API",
            }, image_error)

        workers = max(1, min(16, int(max_workers)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_card, card) for card in cards]
            for future in as_completed(futures):
                record, image_error = future.result()
                normalized.append(record)
                if image_error:
                    errors.append(image_error)
                if progress_callback:
                    progress_callback({
                        "provider": "pokemontcg",
                        "language": "English",
                        "set_id": set_id,
                        "set_name": payload.get("name"),
                        "processed": len(normalized),
                        "total": len(cards),
                        "cards": len(normalized),
                        "images": sum(
                            1 for item in normalized
                            if item.get("local_image")
                        ),
                    })

        normalized.sort(key=lambda item: str(item.get("local_id") or ""))

        (set_dir / "cards.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = {
            "catalog_format": "RareIQ Master Catalog v1",
            "game_id": "pokemon",
            "provider": "pokemontcg",
            "set_id": set_id,
            "set_name": payload.get("name"),
            "language": "English",
            "language_code": "en",
            "cards": len(normalized),
            "images": sum(1 for item in normalized if item.get("local_image")),
            "coverage_percent": (
                round(
                    sum(1 for item in normalized if item.get("local_image"))
                    / len(normalized) * 100,
                    2,
                ) if normalized else 0.0
            ),
            "imported_at": time.time(),
            "errors": errors,
            "download_complete": True,
        }
        (set_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        index_status: dict[str, Any] = {"deferred": True}
        if not defer_indexes:
            self.catalog_engine.rebuild_master_index()
            index_status = self.catalog_engine.artwork_index.rebuild()

        return {
            "ok": True,
            "set_id": set_id,
            "set_name": payload.get("name"),
            "language": "English",
            "cards": len(normalized),
            "images": manifest["images"],
            "coverage_percent": manifest["coverage_percent"],
            "index_status": index_status,
        }

    def _import_simplifiedtcg_set(
        self,
        set_id: str,
        language: str,
        *,
        progress_callback: Any | None = None,
        defer_indexes: bool = False,
        max_workers: int = 8,
    ) -> dict[str, Any]:
        """Import an authentic mainland zh-cn set and its localized artwork."""
        provider = self.providers["simplifiedtcg"]
        payload = provider.fetch_set(language, set_id)
        cards = list(payload.get("cards") or [])
        set_name = str(payload.get("name") or set_id)
        safe_set = self.catalog_engine._safe(set_id)
        set_dir = self.catalog_engine.sets_dir / f"zh-cn_{safe_set}"
        images_dir = storage.get_path("image_path") / "pokemon" / "zh-cn" / safe_set
        set_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        normalized: list[dict[str, Any]] = []
        errors: list[str] = []
        import httpx

        def process_card(card: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            card_id = str(card.get("id") or "")
            image_url = str(card.get("image_url") or "")
            image_path = images_dir / f"{self.catalog_engine._safe(card_id)}.png"
            image_error: str | None = None
            if image_url and not image_path.exists():
                try:
                    with httpx.Client(timeout=35.0, follow_redirects=True) as client:
                        response = client.get(image_url)
                        response.raise_for_status()
                        image_path.write_bytes(response.content)
                except Exception as exc:
                    image_error = f"{card_id}: image {exc}"
            exists = image_path.exists()
            number = str(card.get("card_number") or "")
            return ({
                "game_id": "pokemon",
                "id": f"simplifiedtcg-{set_id}-{card_id}",
                "name": card.get("local_name") or card.get("name"),
                "printed_name": card.get("local_name"),
                "english_name": card.get("name"),
                "language": "Simplified Chinese",
                "language_code": "zh-cn",
                "set_id": set_id,
                "set_name": set_name,
                "collector_number": number,
                "local_id": number,
                "rarity": self.catalog_engine.infer_rarity(
                    card.get("rarity_label"), number, card.get("name")
                ),
                "raw_rarity": card.get("rarity_label"),
                "category": "Pokemon" if card.get("pokedex_no") else None,
                "pokedex_no": card.get("pokedex_no"),
                "variant_type": card.get("variant_type"),
                "variant_group_id": card.get("variant_group_id"),
                "image_url": image_url,
                "reference_image_url": (
                    f"/api/catalog-engine/image/zh-cn_{safe_set}/{image_path.name}"
                    if exists else image_url
                ),
                "local_image": str(image_path) if exists else None,
                "dhash": self.catalog_engine._dhash(image_path) if exists else None,
                "sha256": self.catalog_engine._sha256(image_path) if exists else None,
                "source": "SimplifiedTCG",
            }, image_error)

        workers = max(1, min(16, int(max_workers)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_card, card) for card in cards]
            for future in as_completed(futures):
                record, image_error = future.result()
                normalized.append(record)
                if image_error:
                    errors.append(image_error)
                if progress_callback:
                    progress_callback({
                        "provider": "simplifiedtcg",
                        "language": "Simplified Chinese",
                        "set_id": set_id,
                        "set_name": set_name,
                        "processed": len(normalized),
                        "total": len(cards),
                        "cards": len(normalized),
                        "images": sum(1 for item in normalized if item.get("local_image")),
                    })

        normalized.sort(key=lambda item: str(item.get("local_id") or ""))
        (set_dir / "cards.json").write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        images = sum(1 for item in normalized if item.get("local_image"))
        manifest = {
            "catalog_format": "RareIQ Master Catalog v1",
            "game_id": "pokemon",
            "provider": "simplifiedtcg",
            "set_id": set_id,
            "set_name": set_name,
            "language": "Simplified Chinese",
            "language_code": "zh-cn",
            "cards": len(normalized),
            "images": images,
            "coverage_percent": round(images / len(normalized) * 100, 2) if normalized else 0.0,
            "imported_at": time.time(),
            "errors": errors,
            "download_complete": True,
        }
        (set_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        index_status: dict[str, Any] = {"deferred": True}
        if not defer_indexes:
            self.catalog_engine.rebuild_master_index()
            index_status = self.catalog_engine.artwork_index.rebuild()
        return {
            "ok": True, "set_id": set_id, "set_name": set_name,
            "language": "Simplified Chinese", "cards": len(normalized),
            "images": images, "coverage_percent": manifest["coverage_percent"],
            "errors": errors, "index_status": index_status,
        }
