from pathlib import Path

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")


def conflicted_card():
    quotes = [
        {"source": "Provider A", "variant": "normal", "market": 10.0, "unit": "USD", "updated_at": 2_000_000_000},
        {"source": "Provider B", "variant": "normal", "market": 20.0, "unit": "USD", "updated_at": 2_000_000_000},
    ]
    return {"set_code": "me05", "collector_number": "013/084", "language": "English", "variant": "normal",
            "pricing": {**quotes[0], "quotes": quotes, "provider_count": 2,
                        "quote_consensus": {"status": "divergent", "spread_percent": 66.67}}}


def test_operator_can_select_an_exact_provider_quote(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        result = service.select_price_quote(conflicted_card(), {
            "source": "Provider B", "variant": "normal", "currency": "USD",
            "reason": "recent-sale", "note": "Verified sale at the stream table"
        })
        pricing = result["pricing"]
        assert result["ok"] is True
        assert pricing["market"] == 20.0
        assert pricing["verified"] is True and pricing["valuation_eligible"] is True
        assert pricing["operator_selected"] is True
        assert pricing["quote_consensus"]["status"] == "operator-resolved"
        assert pricing["selection_reason"] == "Operator selected provider quote"
        assert pricing["resolution_reason"] == "recent-sale"
        assert pricing["resolution_note"] == "Verified sale at the stream table"
        assert len(pricing["quotes"]) == 2
        assert service._read_manual_prices()
        assert service.price_resolution_history(conflicted_card())[0]["reason"] == "recent-sale"
    finally:
        service.shutdown()


def test_quote_selection_rejects_stale_or_inexact_choices(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        result = service.select_price_quote(conflicted_card(), {
            "source": "Provider C", "variant": "normal", "currency": "USD"
        })
        assert result["ok"] is False
        assert "no longer available" in result["error"]
        assert service._read_manual_prices() == {}
    finally:
        service.shutdown()


def test_operator_can_undo_selection_and_restore_conflict(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        card = conflicted_card()
        selected = service.select_price_quote(card, {
            "source": "Provider B", "variant": "normal", "currency": "USD"
        })
        undone = service.undo_price_quote_selection(selected["match"])
        assert undone["ok"] is True
        assert undone["pricing"]["quote_consensus"]["status"] == "divergent"
        assert undone["pricing"]["valuation_eligible"] is False
        assert service._read_manual_prices() == {}
        history = service.price_resolution_history(card)
        assert len(history) == 1 and history[0]["undone_at"] is not None
        assert service.undo_price_quote_selection(card)["ok"] is False
    finally:
        service.shutdown()


def test_pricing_audit_report_is_accounting_safe(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        service.select_price_quote(conflicted_card(), {
            "source": "Provider B", "variant": "normal", "currency": "USD",
            "reason": "variant-match", "note": "Exact normal finish"
        })
        report = service.price_resolution_report()
        assert report["schema"] == "rareiq-price-resolution-v1"
        assert report["decision_count"] == 1
        row = report["decisions"][0]
        assert row["set_code"] == "me05" and row["collector_number"] == "13/84"
        assert row["reason"] == "variant-match" and row["status"] == "active"
        assert "before" not in row and "previous_override" not in row
    finally:
        service.shutdown()


def test_conflict_resolution_is_explicit_in_api_and_ui():
    assert '@app.post("/api/catalog/select-quote")' in SERVER
    assert '@app.post("/api/catalog/select-quote/undo")' in SERVER
    assert '@app.get("/api/catalog/quote-resolution-history")' in SERVER
    assert '@app.get("/api/catalog/quote-resolution-history/export")' in SERVER
    assert 'data-market-quote-select' in JS
    assert 'data-market-quote-undo' in JS
    assert 'id="marketResolutionHistoryRows"' in HTML
    assert 'id="marketResolutionReason"' in HTML
    assert 'id="marketResolutionNote"' in HTML
    assert 'data-resolution-export="csv"' in HTML
    assert 'data-resolution-export="json"' in HTML
    assert 'function exportMarketResolutionHistory' in JS
    assert 'async function loadMarketResolutionHistory' in JS
    assert 'event.currentTarget.open' in JS
    assert '.market-resolution-history article[data-status=undone]' in CSS
    assert '.market-resolution-context' in CSS
    assert 'async function selectMarketProviderQuote' in JS
    assert 'Operator selected provider quote' in (ROOT / "rareiq/services/catalog_service.py").read_text(encoding="utf-8")
    assert '#marketProviderComparisonRows article>button' in CSS
    assert "6.8.8-provisional-identity" in HTML
