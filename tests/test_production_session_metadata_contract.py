from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_production_metadata_is_persisted_and_archived():
    assert "class ProductionSessionMetadataRequest(BaseModel)" in SERVER
    assert '@app.post("/api/production/session/metadata")' in SERVER
    assert 'PRODUCTION_SESSION["metadata"] = request.model_dump()' in SERVER
    assert 'snapshot["metadata"] = metadata' in SERVER

def test_production_metadata_operator_form_contract():
    for element_id in ("productionSessionMetadata", "productionSessionName", "productionSessionCustomer", "productionSessionBreakId", "productionSessionNotes"):
        assert f'id="{element_id}"' in HTML
    assert "function productionMetadataPayload" in JS
    assert "async function saveProductionSessionMetadata" in JS
    assert ".production-session-metadata" in CSS
