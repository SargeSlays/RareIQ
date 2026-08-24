from pathlib import Path

from rareiq.services.inventory_service import InventoryService


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_reprice_history_rolls_back_only_latest_effective_price(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    item_id = service.create_many({"english_name": "Card", "currency": "USD"}, quantity=1)["items"][0]["item_id"]
    service.update_listing(item_id, action="activate", channel="ebay", listing_id="E-1", asking_price=10)
    service.apply_listing_price_targets([{"item_id": item_id, "asking_price": 12, "expected_profit": 5, "profit_delta": 2}])
    first = service.listing_reprice_history()["entries"][0]
    assert first["rollback_available"] is True
    assert first["detail"]["profit_delta"] == 2

    rolled_back = service.rollback_listing_reprice(first["audit_id"])
    assert rolled_back["rolled_back"] is True
    assert service.get(item_id)["active_listing"]["asking_price"] == 10
    assert service.rollback_listing_reprice(first["audit_id"])["reason"] == "already_rolled_back"


def test_older_reprice_cannot_overwrite_a_newer_price(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    item_id = service.create_many({"english_name": "Card"}, quantity=1)["items"][0]["item_id"]
    service.update_listing(item_id, action="activate", asking_price=10)
    service.apply_listing_price_targets([{"item_id": item_id, "asking_price": 11}])
    old_event = service.listing_reprice_history()["entries"][0]
    service.apply_listing_price_targets([{"item_id": item_id, "asking_price": 13}])
    assert service.rollback_listing_reprice(old_event["audit_id"])["reason"] == "newer_price_exists"


def test_reprice_history_ui_api_and_sync_state_are_wired():
    assert '@app.get("/api/inventory/listings/reprice-history")' in SERVER
    assert '@app.post("/api/inventory/listings/reprice-rollback")' in SERVER
    assert 'id="inventoryRepriceHistory"' in HTML
    assert "renderInventoryRepriceHistory" in JS
    assert "rollbackInventoryReprice" in JS
    assert 'sync_status": "local_only"' in (ROOT / "rareiq/services/inventory_service.py").read_text(encoding="utf-8")
    assert "6.8.8-provisional-identity" in HTML
