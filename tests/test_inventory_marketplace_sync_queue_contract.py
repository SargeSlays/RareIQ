from pathlib import Path

from rareiq.services.inventory_service import InventoryService


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_listing_changes_queue_behind_approval_and_retry_safely(tmp_path):
    state = tmp_path / "inventory.json"
    service = InventoryService(state)
    item_id = service.create_many({"english_name": "Card"}, quantity=1)["items"][0]["item_id"]
    service.update_listing(item_id, action="activate", channel="ebay", listing_id="E-1", asking_price=10)
    queue = service.marketplace_sync_queue()
    job = queue["jobs"][0]
    assert job["status"] == "pending_approval"
    assert queue["external_writes_enabled"] is False

    assert service.update_marketplace_sync_job(job["job_id"], "approve")["job"]["status"] == "ready"
    failed = service.update_marketplace_sync_job(job["job_id"], "simulate", simulated_outcome="failure")
    assert failed["job"]["status"] == "failed"
    assert failed["job"]["attempts"] == 1
    assert service.update_marketplace_sync_job(job["job_id"], "retry")["job"]["status"] == "ready"
    assert service.update_marketplace_sync_job(job["job_id"], "simulate")["job"]["status"] == "succeeded"

    restored = InventoryService(state).marketplace_sync_queue()["jobs"][0]
    assert restored["status"] == "succeeded"
    assert restored["attempts"] == 2


def test_marketplace_sync_ui_api_and_safety_are_wired():
    assert '@app.get("/api/inventory/marketplace-sync")' in SERVER
    assert '@app.post("/api/inventory/marketplace-sync/{job_id}")' in SERVER
    assert 'id="inventorySyncJobs"' in HTML
    assert 'id="inventorySyncSafety"' in HTML
    assert "renderInventoryMarketplaceSync" in JS
    assert "updateInventoryMarketplaceSync" in JS
    assert "Safe simulation · external writes off" in HTML
    assert "6.8.8-provisional-identity" in HTML
