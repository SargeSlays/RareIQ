from rareiq.services.catalog_intelligence_service import CatalogIntelligenceService


def test_tcgdex_resource_ids_are_safe_path_segments() -> None:
    assert CatalogIntelligenceService._tcgdex_url("ja", "sets", "SM1+").endswith(
        "/ja/sets/SM1%2B"
    )
    assert CatalogIntelligenceService._tcgdex_url("ja", "sets", "sm2+").endswith(
        "/ja/sets/sm2%2B"
    )


def test_tcgdex_card_ids_cannot_change_url_path_shape() -> None:
    url = CatalogIntelligenceService._tcgdex_url("en", "cards", "set/card + 1")
    assert url.endswith("/en/cards/set%2Fcard%20%2B%201")
