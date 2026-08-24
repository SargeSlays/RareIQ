from rareiq.services.catalog_intelligence_service import CatalogIntelligenceService


def test_locked_set_resolve_reconciles_provider_total_by_local_number() -> None:
    service = CatalogIntelligenceService.__new__(CatalogIntelligenceService)
    english = {
        "id": "me05-023",
        "name": "Electrike",
        "printed_name": "Electrike",
        "english_name": "Electrike",
        "language": "English",
        "set_id": "me05",
        "set_name": "Pitch Black",
        "collector_number": "023/120",
        "local_id": "023",
        "reference_image_url": "/api/catalog-engine/image/en_me05/me05-023.webp",
        "local_image": "F:/RareIQ/images/pokemon/en/me05/me05-023.webp",
    }
    german = {**english, "language": "German", "printed_name": "Frizelbliz"}
    service._by_number = {"023/120": [german, english]}
    service._by_set_local = {("me05", "23"): [german, english]}

    match = service.resolve({
        "collector_number": "023/084",
        "language": "English",
        "active_set": {
            "set_id": "me05",
            "name": "Pitch Black",
            "language": "English",
        },
    })

    assert match is not None
    assert match["id"] == "me05-023"
    assert match["printed_name"] == "Electrike"
    assert match["collector_number"] == "023/120"
    assert match["set_locked_catalog_lookup"] is True
    assert match["source"] == "rareiq_master_catalog"


def test_locked_set_resolve_prefers_requested_language_over_local_image() -> None:
    service = CatalogIntelligenceService.__new__(CatalogIntelligenceService)
    italian = {
        "id": "it-me05-029", "name": "Slowpoke", "printed_name": "Slowpoke",
        "language": "Italian", "language_code": "it", "set_id": "me05",
        "collector_number": "029/084", "local_image": "italian.webp",
        "reference_image_url": "/italian.webp",
    }
    english = {
        **italian, "id": "en-me05-029", "language": "English",
        "language_code": "en", "local_image": None,
        "reference_image_url": "/english.webp",
    }
    service._by_number = {"029/084": [italian, english]}
    service._by_set_local = {("me05", "29"): [italian, english]}

    match = service.resolve({
        "collector_number": "029/084", "language": "English",
        "active_set": {"set_id": "me05", "language": "English"},
    })

    assert match["id"] == "en-me05-029"
    assert match["reference_image_url"] == "/english.webp"
