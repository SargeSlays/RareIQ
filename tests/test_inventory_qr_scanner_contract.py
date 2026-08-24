from pathlib import Path

CONTROL=Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")

def test_inventory_has_live_qr_scanner_with_manual_fallback():
    assert 'id="inventoryStartScanner"' in CONTROL
    assert 'id="inventoryScannerView"' in CONTROL
    assert 'id="inventoryLookup"' in CONTROL
    assert "navigator.mediaDevices.getUserMedia" in STUDIO
    assert 'new BarcodeDetector({formats:["qr_code"]})' in STUDIO
    assert 'document.createElement("video")' in STUDIO
    assert "/^RIQ-[A-F0-9]{12}$/" in STUDIO

def test_scanner_stops_tracks_and_debounces_codes():
    assert "getTracks().forEach(track=>track.stop())" in STUDIO
    assert "now-inventoryScannerLastAt<3000" in STUDIO
    assert "stopInventoryScanner();if(result.item.status" in STUDIO
