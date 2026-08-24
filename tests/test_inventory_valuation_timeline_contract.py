from pathlib import Path

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_item_timeline_connects_acquisition_current_value_and_sale(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    item = {"item_id": "RIQ-ABC123", "status": "sold", "set_code": "me05", "collector_number": "001/084", "language": "English", "finish": "normal", "cost_basis": 4, "currency": "USD", "created_at": 10, "acquisition_valuation": {"captured_at": 10, "market": 6, "currency": "USD", "provider": "Provider A", "resolution_id": "resolution-1"}, "sale": {"sold_at": 30, "gross": 12, "net_proceeds": 10, "profit": 6, "channel": "Live"}}
    try:
        service._record_price({**item, "pricing": {"market": 9, "currency": "USD", "source": "Provider B", "verified": True, "valuation_eligible": True}})
        result = service.inventory_item_timeline(item)
        assert [event["kind"] for event in result["events"]] == ["acquisition", "sale", "market"]
        assert result["acquisition_market"] == 6 and result["current_market"] == 9
        assert result["market_change"] == 3 and result["market_change_percent"] == 50
        assert result["market_low"] == 9 and result["market_high"] == 9
        assert result["checkpoint_count"] == 1
        assert result["realized_profit"] == 6 and result["realized_roi_percent"] == 150
    finally:
        service.shutdown()

def test_inventory_profile_and_history_are_operator_accessible():
    assert '@app.get("/inventory/item/{item_id}")' in SERVER
    assert '@app.get("/api/inventory/items/{item_id}/valuation-history")' in SERVER
    assert "Permanent item history" in SERVER
    assert 'href="${item.profile_url}"' in JS and ">Profile</a>" in JS
    assert "automatic checkpoints" in SERVER
    assert "6.8.8-provisional-identity" in HTML
