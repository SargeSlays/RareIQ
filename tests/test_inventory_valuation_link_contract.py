from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "rareiq/services/inventory_service.py").read_text(encoding="utf-8")


def test_inventory_valuation_provenance_contract_is_visible_and_exportable():
    assert '"acquisition_valuation"' in SERVICE
    assert '"pricing_resolution_id"' in SERVICE
    assert '"acquisition_market_provider"' in SERVICE
    assert '"pricing_resolution_id", "acquisition_market"' in SERVER
    assert "item.acquisition_valuation||{}" in JS
    assert "acquired at" in JS
    assert "6.8.8-provisional-identity" in HTML
