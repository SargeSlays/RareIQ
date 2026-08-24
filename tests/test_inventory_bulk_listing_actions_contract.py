from pathlib import Path

from rareiq.services.inventory_service import InventoryService


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_bulk_listing_reprice_and_end_are_independent(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    items = service.create_many({"english_name": "Card", "currency": "USD"}, quantity=2)["items"]
    first, second = [item["item_id"] for item in items]
    service.update_listing(first, action="activate", channel="ebay", listing_id="E-1", asking_price=10)
    service.update_listing(second, action="activate", channel="shopify", listing_id="S-1", asking_price=20)

    repriced = service.bulk_update_listings([first, second, "RIQ-NOT-FOUND"], action="reprice", price_adjustment_percent=-10)
    assert repriced["updated"] == 2
    assert repriced["failed"] == 1
    assert service.get(first)["active_listing"]["asking_price"] == 9
    assert service.get(second)["active_listing"]["asking_price"] == 18

    ended = service.bulk_update_listings([first, second], action="end")
    assert ended["updated"] == 2
    assert service.get(first)["status"] == "in_stock"
    assert service.get(first)["active_listing"] is None


def test_bulk_listing_controls_and_endpoint_are_wired():
    assert 'class InventoryBulkListingRequest(BaseModel)' in SERVER
    assert '@app.post("/api/inventory/listings/bulk")' in SERVER
    assert 'id="inventoryListingSelectStale"' in HTML
    assert 'id="inventoryListingReprice"' in HTML
    assert 'id="inventoryListingEnd"' in HTML
    assert 'bulkUpdateInventoryListings' in JS
    assert 'api("/api/inventory/listings/bulk"' in JS
    assert "6.8.8-provisional-identity" in HTML
