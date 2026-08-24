from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_disposition_api_and_exports_exist():
    assert '@app.post("/api/collection/disposition")' in SERVER
    assert '@app.get("/api/collection/trade-list.csv")' in SERVER
    assert '@app.get("/api/collection/sell-list.csv")' in SERVER
    assert "allocation_exceeds_quantity" in Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")


def test_duplicate_queue_supports_keep_trade_sell_allocations():
    assert 'id="collectionDuplicateGrid"' in CONTROL
    assert "Export Trades" in CONTROL and "Export Sales" in CONTROL
    assert "function dispositionControls(card)" in STUDIO
    assert "function renderDuplicateQueue(cards,summary={})" in STUDIO
    assert "function updateCollectionDisposition(versionKey,trade,sell)" in STUDIO
