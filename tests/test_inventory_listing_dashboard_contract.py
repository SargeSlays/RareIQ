from pathlib import Path
import time

from rareiq.services.inventory_service import InventoryService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_listing_dashboard_counts_exposure_stale_and_unlisted(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    created = service.create_many({"english_name": "Card", "set_code": "set", "collector_number": "1/10", "currency": "USD"}, quantity=3)
    first, second, _third = [item["item_id"] for item in created["items"]]
    service.update_listing(first, action="activate", channel="ebay", listing_id="E-1", asking_price=10)
    service.update_listing(second, action="activate", channel="shopify", listing_id="S-1", asking_price=20)
    service._items[first]["listings"][-1]["listed_at"] = time.time() - 40 * 86400
    dashboard = service.listing_dashboard(30)
    assert dashboard["active"] == 2
    assert dashboard["stale"] == 1
    assert dashboard["unlisted"] == 1
    assert dashboard["asking_exposure"] == 30
    assert dashboard["listings"][0]["item_id"] == first
    assert {row["channel"] for row in dashboard["channels"]} == {"ebay", "shopify"}

def test_listing_dashboard_is_visible_and_refreshable():
    assert '@app.get("/api/inventory/listing-dashboard")' in SERVER
    assert 'id="inventoryListingStaleDays"' in HTML
    assert 'id="inventoryListingRows"' in HTML
    assert "renderInventoryListingDashboard" in JS
    assert 'api(`/api/inventory/listing-dashboard?stale_days=${staleDays}`)' in JS
    assert "6.8.8-provisional-identity" in HTML
