from pathlib import Path

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_like_currency_quotes_receive_consensus_classification():
    aligned = CatalogService._quote_consensus([
        {"source": "A", "market": 10, "unit": "USD"},
        {"source": "B", "market": 10.5, "unit": "USD"},
        {"source": "C", "market": 9, "unit": "EUR"},
    ], "USD")
    divergent = CatalogService._quote_consensus([
        {"source": "A", "market": 10, "unit": "USD"},
        {"source": "B", "market": 20, "unit": "USD"},
    ], "USD")
    assert aligned["status"] == "aligned" and aligned["comparable_providers"] == 2
    assert aligned["spread_percent"] < 10
    assert divergent["status"] == "divergent" and divergent["spread_percent"] > 25


def test_divergent_providers_block_verification_and_valuation():
    quote = CatalogService._decorate_price({
        "market": 10, "source": "A", "unit": "USD",
        "quote_consensus": {"status": "divergent", "comparable_providers": 2, "spread_percent": 50},
    }, confidence="high")
    assert quote["verified"] is False
    assert quote["valuation_eligible"] is False
    assert quote["verification_reason"] == "Comparable providers materially disagree"
    assert quote["provenance"]["consensus"]["status"] == "divergent"


def test_market_ui_exposes_provider_conflicts_before_valuation():
    assert 'id="pricingConsensus"' in HTML
    assert 'pricing.consensusStatus==="divergent"' in JS
    assert 'key:"conflict"' in JS
    assert "Provider conflict · review comparable quotes" in JS
    assert 'data-market-state="conflict"' in CSS
    assert "6.8.8-provisional-identity" in HTML
