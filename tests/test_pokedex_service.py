from rareiq.services.pokedex_service import PokedexService


def test_pokedex_resolves_and_caches_species(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("/crocalor"):
            return {
                "id": 910,
                "name": "crocalor",
                "height": 10,
                "weight": 307,
                "base_experience": 144,
                "species": {"url": "https://pokeapi.co/api/v2/pokemon-species/910/"},
                "types": [{"type": {"name": "fire"}}],
                "abilities": [{"ability": {"name": "blaze"}}],
                "sprites": {"other": {"official-artwork": {"front_default": "https://img/crocalor.png"}}},
            }
        return {
            "base_happiness": 50,
            "capture_rate": 45,
            "habitat": None,
            "generation": {"name": "generation-ix"},
            "genera": [{"language": {"name": "en"}, "genus": "Fire Croc Pokémon"}],
            "flavor_text_entries": [{"language": {"name": "en"}, "flavor_text": "Its fire burns hotter."}],
        }

    service = PokedexService(tmp_path, fetcher=fetch)
    first = service.resolve({"english_name": "Crocalor"})
    second = service.resolve({"english_name": "Crocalor"})

    assert first["pokemon"]["id"] == 910
    assert first["pokemon"]["types"] == ["fire"]
    assert first["pokemon"]["genus"] == "Fire Croc Pokémon"
    assert second["cached"] is True
    assert len(calls) == 2


def test_pokedex_gracefully_falls_back_to_verified_card_identity(tmp_path):
    def fail(_url):
        raise OSError("offline")

    result = PokedexService(tmp_path, fetcher=fail).resolve(
        {"english_name": "Crocalor", "types": ["Fire"]}
    )

    assert result["status"] == "partial"
    assert result["pokemon"]["name"] == "Crocalor"
    assert result["pokemon"]["types"] == ["Fire"]
