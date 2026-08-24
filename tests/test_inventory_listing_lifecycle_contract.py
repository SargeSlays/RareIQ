from pathlib import Path

from rareiq.services.inventory_service import InventoryService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def _service_item(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    created = service.create({"english_name": "Tropius", "set_code": "me05", "collector_number": "001/084"}, cost_basis=2)
    return service, created["item"]["item_id"]

def test_listing_lifecycle_preserves_history_and_active_pointer(tmp_path):
    service, item_id = _service_item(tmp_path)
    first = service.update_listing(item_id, action="activate", channel="ebay", listing_id="A-1", listing_url="https://example.test/a", asking_price=10)
    assert first["updated"] and first["item"]["active_listing"]["listing_id"] == "A-1"
    second = service.update_listing(item_id, action="activate", channel="ebay", listing_id="A-2", asking_price=12)
    assert second["item"]["listings"][0]["status"] == "ended"
    assert second["item"]["listings"][0]["end_reason"] == "replaced"
    ended = service.update_listing(item_id, action="end", listing_id="A-2")
    assert ended["updated"] and ended["item"]["active_listing"] is None

def test_sale_automatically_closes_active_listing(tmp_path):
    service, item_id = _service_item(tmp_path)
    service.update_listing(item_id, action="activate", channel="tcgplayer", listing_id="TCG-9", asking_price=8)
    sold = service.sell(item_id, sale_price=8)
    assert sold["item"]["active_listing"] is None
    assert sold["item"]["listings"][0]["status"] == "sold"
    assert sold["item"]["listings"][0]["end_reason"] == "inventory_sold"

def test_listing_controls_and_api_are_exposed():
    assert "class InventoryListingStatusRequest" in SERVER
    assert '@app.post("/api/inventory/items/{item_id}/listing")' in SERVER
    assert "activateInventoryListing" in JS and "endInventoryListing" in JS
    assert 'listingAction.textContent=listing?"End Listing":"Mark Listed"' in JS
    assert "6.8.8-provisional-identity" in HTML
