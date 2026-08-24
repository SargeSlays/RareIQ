from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_bulk_listing_endpoint_builds_traceable_non_destructive_drafts():
    assert "class InventoryListingDraftRequest" in SERVER
    assert '@app.post("/api/inventory/listing-drafts")' in SERVER
    for field in ("status", "sku", "title", "description", "price", "expected_profit", "profile_url"):
        assert f'"{field}"' in SERVER
    assert '"status": "draft"' in SERVER
    assert 'item.get("status") != "in_stock"' in SERVER
    assert "orchestrator.inventory.sell(" not in SERVER[SERVER.index('async def inventory_listing_drafts'):SERVER.index('return {"ok": True, "channel"', SERVER.index('async def inventory_listing_drafts'))]

def test_selected_inventory_exports_channel_ready_csv():
    assert 'id="inventoryListingChannel"' in HTML
    assert 'id="inventoryPrepareListings"' in HTML
    assert "prepareInventoryListings" in JS
    assert 'api("/api/inventory/listing-drafts"' in JS
    assert "inventoryCsvCell" in JS
    assert "listing-drafts-" in JS
    assert "6.8.8-provisional-identity" in HTML
