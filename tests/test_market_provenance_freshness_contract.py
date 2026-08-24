from pathlib import Path
import time

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_only_strong_current_quotes_are_verified():
    now = time.time()
    fresh = CatalogService._decorate_price({"market": 10, "source": "A", "updated_at": now}, confidence="high")
    weak = CatalogService._decorate_price({"market": 10, "source": "A", "updated_at": now}, confidence="medium")
    stale = CatalogService._decorate_price({"market": 10, "source": "A", "updated_at": now - 8 * 86400}, confidence="high")
    assert fresh["verified"] is True and fresh["valuation_eligible"] is True
    assert fresh["freshness_status"] == "fresh"
    assert weak["verified"] is False and weak["verification_state"] == "unverified"
    assert stale["verified"] is False and stale["valuation_eligible"] is False
    assert stale["freshness_status"] == "stale"
    assert stale["verification_reason"] == "Quote is older than 7 days"


def test_quote_provenance_is_structured_and_preserved():
    price = CatalogService._decorate_price({
        "market": 4, "source": "TCGPlayer", "provider_count": 2,
        "selection_reason": "Preferred USD market quote", "variant": "holofoil", "unit": "USD",
    }, confidence="high")
    assert price["provenance"] == {
        "source": "TCGPlayer", "provider_count": 2,
        "selection_reason": "Preferred USD market quote", "variant": "holofoil", "currency": "USD",
        "consensus": None,
    }


def test_market_ui_distinguishes_stale_and_unverified_quotes():
    assert 'pricing.freshnessStatus==="stale"' in JS
    assert 'hasValue&&!pricing.verified' in JS
    assert 'state==="stale"' in JS and 'state==="unverified"' in JS
    assert 'pricing.verified?"VERIFIED":"NOT VERIFIED"' in JS
    assert '[data-market-state="stale"]' in CSS
    assert '[data-market-state="unverified"]' in CSS
    assert "6.8.8-provisional-identity" in HTML
