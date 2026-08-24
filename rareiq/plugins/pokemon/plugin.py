from __future__ import annotations

from typing import Any

from rareiq.plugins.base import CollectiblePlugin


class PokemonPlugin(CollectiblePlugin):
    plugin_id = "pokemon"
    display_name = "Pokémon Trading Card Game"
    version = "1.0.0"

    def provider_ids(self) -> tuple[str, ...]:
        return ("tcgdex", "pokemontcg")

    def normalize_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "game": self.plugin_id,
            "id": payload.get("id"),
            "name": payload.get("name"),
            "set_id": payload.get("set_id"),
            "set_name": payload.get("set_name"),
            "language": payload.get("language"),
            "collector_number": payload.get("collector_number"),
            "rarity": payload.get("rarity"),
            "image_url": payload.get("image_url"),
            "local_image": payload.get("local_image"),
            "source": payload.get("source"),
        }

    def recognition_signals(self) -> tuple[str, ...]:
        return (
            "visual_similarity",
            "collector_number",
            "ocr_name",
            "language",
            "layout",
            "color_profile",
            "rarity_hint",
        )
