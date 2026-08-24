from pathlib import Path

from rareiq.services.inventory_service import InventoryService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_recommendation_covers_cost_fees_shipping_profit_and_market():
    item = {"cost_basis": 10, "currency": "USD"}
    result = InventoryService.sell_recommendation(item, 25, fee_percent=10, shipping_cost=5, desired_profit_percent=20)
    assert result["break_even_price"] == 16.67
    assert result["target_price"] == 18.89
    assert result["recommended_price"] == 25
    assert result["expected_fees"] == 2.5
    assert result["expected_net"] == 17.5
    assert result["expected_profit"] == 7.5

def test_recommendation_uses_profit_target_when_market_is_unavailable():
    result = InventoryService.sell_recommendation({"cost_basis": 8, "currency": "USD"}, None, fee_percent=0, shipping_cost=2, desired_profit_percent=25)
    assert result["recommended_price"] == 12
    assert result["market_premium"] is None

def test_smart_sell_price_is_wired_into_checkout():
    assert '@app.get("/api/inventory/items/{item_id}/sell-recommendation")' in SERVER
    assert "updateInventorySellRecommendation" in JS
    assert "applyInventorySellRecommendation" in JS
    assert 'id="inventoryApplyRecommendation"' in HTML
    assert "6.8.8-provisional-identity" in HTML
