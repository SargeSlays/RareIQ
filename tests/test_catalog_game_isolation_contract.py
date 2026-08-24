from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pokemon_importers_stamp_game_identity() -> None:
    catalog = (ROOT / "rareiq/services/catalog_intelligence_service.py").read_text(encoding="utf-8")
    pokemon = (ROOT / "rareiq/services/pokemon_master_database_service.py").read_text(encoding="utf-8")
    assert catalog.count('"game_id": "pokemon"') >= 2
    assert pokemon.count('"game_id": "pokemon"') >= 4


def test_legacy_cards_default_to_pokemon_and_visual_records_keep_game_id() -> None:
    catalog = (ROOT / "rareiq/services/catalog_intelligence_service.py").read_text(encoding="utf-8")
    visual = (ROOT / "rareiq/services/global_visual_index_service.py").read_text(encoding="utf-8")
    assert 'card.setdefault("game_id", "pokemon")' in catalog
    assert 'item.setdefault("game_id", "pokemon")' in visual
    assert '"game_id": card.get("game_id") or "pokemon"' in visual


def test_catalog_resolution_rejects_cross_game_candidates() -> None:
    catalog = (ROOT / "rareiq/services/catalog_intelligence_service.py").read_text(encoding="utf-8")
    assert 'wanted_game = str(recognition.get("game_id") or "pokemon").casefold()' in catalog
    assert 'str(card.get("game_id") or "pokemon").casefold() == wanted_game' in catalog
