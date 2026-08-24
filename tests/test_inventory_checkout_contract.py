from pathlib import Path

SERVER=Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")

def test_inventory_checkout_has_modal_export_and_reversible_sale_routes():
    assert 'id="inventoryCheckoutForm"' in CONTROL
    assert 'id="inventoryNetPreview"' in CONTROL
    assert 'href="/api/inventory/sales.csv"' in CONTROL
    assert '@app.post("/api/inventory/items/{item_id}/void-sale")' in SERVER
    assert '@app.get("/api/inventory/sales.csv")' in SERVER
    assert "function completeInventoryCheckout(event)" in STUDIO
    assert "function voidInventorySale(item)" in STUDIO

def test_checkout_no_longer_uses_prompts():
    checkout=STUDIO[STUDIO.index("function checkoutInventoryItem"):STUDIO.index("async function voidInventorySale")]
    assert "window.prompt" not in checkout
