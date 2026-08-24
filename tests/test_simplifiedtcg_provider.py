from rareiq.catalog_providers.simplifiedtcg_provider import SimplifiedTCGProvider
from rareiq.services.pokemon_master_database_service import PokemonMasterDatabaseService


def test_extracts_embedded_simplified_chinese_records():
    document = (
        '<script>self.__next_f.push([1,"'
        r'{\"id\":\"CBB6C\",\"local_name\":\"宝石包 VOL.6\",'
        r'\"name\":\"Gem Pack Vol 6\",\"n_cards\":196,'
        r'\"release_date\":\"2026-08-07\"}'
        '"])</script>'
    )
    records = SimplifiedTCGProvider._embedded_objects(document)
    assert records == [{
        "id": "CBB6C",
        "local_name": "宝石包 VOL.6",
        "name": "Gem Pack Vol 6",
        "n_cards": 196,
        "release_date": "2026-08-07",
    }]


def test_simplified_chinese_is_a_first_class_world_language():
    assert "Simplified Chinese" in PokemonMasterDatabaseService.DEFAULT_LANGUAGES


def test_simplified_provider_is_not_a_traditional_chinese_alias():
    provider = SimplifiedTCGProvider()
    assert provider.languages == ("Simplified Chinese",)
    assert provider.provider_id == "simplifiedtcg"
