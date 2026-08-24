from pathlib import Path

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def _item(item_id: str) -> dict:
    return {"item_id": item_id, "set_code": "me05", "set_name": "Pitch Black", "collector_number": "001/084", "language": "English", "finish": "normal", "english_name": "Tropius", "currency": "USD"}

def test_multiple_physical_copies_keep_independent_targets(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    first, second = _item("RIQ-ONE"), _item("RIQ-TWO")
    try:
        service._record_price({**first, "pricing": {"market": 12, "currency": "USD", "source": "Verified", "verified": True, "valuation_eligible": True}})
        assert service.set_inventory_price_alert(first, {"direction": "above", "target": 10, "currency": "USD", "enabled": True})["ok"]
        assert service.set_inventory_price_alert(second, {"direction": "below", "target": 8, "currency": "USD", "enabled": True})["ok"]
        rows = service.price_alert_dashboard()["alerts"]
        assert {row["inventory_item_id"] for row in rows} == {"RIQ-ONE", "RIQ-TWO"}
        assert next(row for row in rows if row["inventory_item_id"] == "RIQ-ONE")["triggered"] is True
        assert next(row for row in rows if row["inventory_item_id"] == "RIQ-TWO")["triggered"] is False
        service.set_inventory_price_alert(first, {"direction": "above", "target": 10, "currency": "USD", "enabled": False})
        assert [row["inventory_item_id"] for row in service.price_alert_dashboard()["alerts"]] == ["RIQ-TWO"]
    finally:
        service.shutdown()

def test_inventory_alert_controls_are_exposed():
    assert '@app.post("/api/inventory/items/{item_id}/price-alert")' in SERVER
    assert "setInventoryPriceAlert(item)" in JS
    assert 'alertAction.textContent="Set Alert"' in JS
    assert "inventory_item_id" in JS
    assert "6.8.8-provisional-identity" in HTML
