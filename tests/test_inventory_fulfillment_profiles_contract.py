from pathlib import Path

from rareiq.services.inventory_service import InventoryService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_packaging_and_postage_are_included_in_recommendation():
    result = InventoryService.sell_recommendation({"cost_basis": 10, "currency": "USD"}, None, fee_percent=10, shipping_cost=4, packaging_cost=1, desired_profit_percent=20)
    assert result["fulfillment_cost"] == 5
    assert result["break_even_price"] == 16.67
    assert result["target_price"] == 18.89
    assert result["expected_profit"] == 2

def test_sale_ledger_keeps_packaging_separate(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    created = service.create({"english_name": "Card", "set_code": "set", "collector_number": "1/10"}, cost_basis=5)
    item_id = created["item"]["item_id"]
    sold = service.sell(item_id, sale_price=20, fees=2, shipping_cost=3, packaging_cost=1, channel="ebay")
    assert sold["item"]["sale"]["packaging_cost"] == 1
    assert sold["item"]["sale"]["net_proceeds"] == 14
    assert sold["item"]["sale"]["profit"] == 9
    assert service.sales_rows()[0]["packaging_cost"] == 1

def test_channel_fulfillment_profiles_are_wired():
    assert "INVENTORY_FULFILLMENT_PRESET_KEY" in JS
    assert "saveInventoryFulfillmentPreset" in JS
    assert "packaging_cost:String(packaging)" in JS
    assert 'id="inventoryPackagingCost"' in HTML
    assert '"packaging_cost"' in SERVER
    assert "6.8.8-provisional-identity" in HTML
