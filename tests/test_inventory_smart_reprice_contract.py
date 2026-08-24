from pathlib import Path

from rareiq.services.inventory_service import InventoryService


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_smart_price_targets_apply_individually_and_preserve_listing_identity(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    items = service.create_many({"english_name": "Card", "currency": "USD"}, quantity=2)["items"]
    first, second = [item["item_id"] for item in items]
    service.update_listing(first, action="activate", channel="ebay", listing_id="E-1", listing_url="https://example.test/E-1", asking_price=10)
    service.update_listing(second, action="activate", channel="shopify", listing_id="S-1", asking_price=20)

    result = service.apply_listing_price_targets([
        {"item_id": first, "asking_price": 12.34},
        {"item_id": second, "asking_price": 27.89},
    ])

    assert result["updated"] == 2
    assert service.get(first)["active_listing"]["asking_price"] == 12.34
    assert service.get(first)["active_listing"]["listing_id"] == "E-1"
    assert service.get(first)["active_listing"]["listing_url"] == "https://example.test/E-1"
    assert service.get(second)["active_listing"]["reprice_source"] == "smart_reprice"


def test_smart_reprice_has_preview_apply_and_profit_guards():
    assert 'class InventorySmartRepriceRequest(BaseModel)' in SERVER
    assert '@app.post("/api/inventory/listings/smart-reprice")' in SERVER
    assert 'minimum_profit' in SERVER
    assert 'profit_floor_price' in SERVER
    assert 'if req.apply else None' in SERVER
    assert 'id="inventoryListingSmartReprice"' in HTML
    assert "SMART REPRICE PREVIEW" in JS
    assert "inventorySmartRepriceProfiles" in JS
    assert "6.8.8-provisional-identity" in HTML
