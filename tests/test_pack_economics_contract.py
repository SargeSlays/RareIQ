from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_pack_economics_api_and_persistence_contract():
    assert 'class PackEconomicsRequest(BaseModel)' in SERVER
    assert '@app.get("/api/production/session/pack-economics")' in SERVER
    assert '@app.post("/api/production/session/pack-economics")' in SERVER
    assert 'PRODUCTION_SESSION["pack_economics"] = settings' in SERVER
    assert "_save_production_session()" in SERVER


def test_pack_economics_keeps_unknowns_and_unrelated_sales_explicit():
    assert '"unresolved_cards"' in SERVER
    assert '"minimum_verified" if unresolved' in SERVER
    assert '"inventory_realized_all_time"' in SERVER
    assert '"inventory_profit_all_time"' in SERVER
    assert "if value > 0: values.append(value)" in SERVER


def test_pack_economics_operator_ui_contract():
    for element_id in (
        "packEconomicsForm", "packEconomicsPackCost", "packEconomicsBoxCost",
        "packEconomicsPacksPerBox", "economicsVerifiedReturn", "economicsBreakEven",
        "economicsMargin", "economicsUnresolved", "economicsPackRows",
    ):
        assert f'id="{element_id}"' in HTML
    assert "function renderPackEconomics" in JS
    assert "async function loadPackEconomics" in JS
    assert "async function savePackEconomics" in JS
    assert ".pack-economics" in CSS
    assert 'html[data-theme="light"] .pack-economics{' in CSS
    assert 'html[data-theme="light"] .pack-economics-summary article' in CSS
    assert "@media(max-width:760px)" in CSS
