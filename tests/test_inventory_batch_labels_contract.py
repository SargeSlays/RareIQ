from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")


def test_inventory_supports_selectable_batch_label_printing():
    for marker in (
        'id="inventoryBatchCount"',
        'id="inventorySelectAll"',
        'id="inventoryClearSelection"',
        'id="inventoryPrintSelected"',
    ):
        assert marker in CONTROL
    assert "selectedInventoryLabelIds" in STUDIO
    assert "selectAllInventoryLabels" in STUDIO
    assert "/api/inventory/labels/print?item_ids=" in STUDIO


def test_inventory_label_sheet_is_bounded_and_print_ready():
    assert '@app.get("/api/inventory/labels/print")' in SERVER
    assert "[:100]" in SERVER
    assert "window.print()" in SERVER
    assert "break-inside:avoid" in SERVER
    assert "/label.png" in SERVER


def test_inventory_bulk_intake_creates_and_prints_unique_copy_labels():
    assert 'id="inventoryQuantity"' in CONTROL
    assert 'max="100"' in CONTROL
    assert 'Create &amp; Print QR Labels' in CONTROL
    assert '@app.post("/api/inventory/items/batch")' in SERVER
    assert '"/api/inventory/items/batch"' in STUDIO
    assert "result.items" in STUDIO
    assert "ids.join" in STUDIO
