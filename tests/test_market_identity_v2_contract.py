from pathlib import Path

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_price_identity_is_language_variant_and_zero_format_safe():
    english = {"set_code": "ME05", "collector_number": "023/084", "language": "English", "variant": "normal"}
    japanese = {**english, "language": "Japanese"}
    reverse = {**english, "variant": "reverse_holo"}
    normalized = {**english, "collector_number": "23/84"}
    assert CatalogService._price_identity(english) == "me05|23/84|en|normal"
    assert CatalogService._price_identity(normalized) == CatalogService._price_identity(english)
    assert CatalogService._price_identity(japanese) != CatalogService._price_identity(english)
    assert CatalogService._price_identity(reverse).endswith("|reverse-holo")


def test_language_and_finish_prices_cannot_contaminate_each_other(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        base = {"set_code": "me05", "collector_number": "13/84"}
        service._record_price({**base, "language": "English", "finish": "normal", "pricing": {"market": 4, "currency": "USD", "source": "test"}})
        service._record_price({**base, "language": "Japanese", "finish": "normal", "pricing": {"market": 8, "currency": "USD", "source": "test"}})
        service._record_price({**base, "language": "English", "finish": "reverse-holofoil", "pricing": {"market": 12, "currency": "USD", "source": "test"}})
        saved = service._read_price_history()
        assert len(saved) == 3
        assert sorted(rows[-1]["market"] for rows in saved.values()) == [4, 8, 12]
    finally:
        service.shutdown()


def test_legacy_price_records_remain_readable(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        card = {"set_code": "me05", "collector_number": "013/084", "language": "English"}
        legacy = service._legacy_price_identity(card)
        service._manual_price_path.write_text('{"%s":{"market":6,"source":"Legacy"}}' % legacy, encoding="utf-8")
        assert service._apply_manual_price(card)["pricing"]["market"] == 6
    finally:
        service.shutdown()


def test_market_identity_v2_build_is_current():
    assert "6.8.8-provisional-identity" in HTML
