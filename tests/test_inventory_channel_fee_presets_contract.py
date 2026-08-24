from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")

def test_checkout_has_editable_channel_fee_presets():
    for channel in ("in_person", "ebay", "tcgplayer", "whatnot", "shopify", "other"):
        assert f"{channel}:" in JS
    assert "applyInventoryChannelPreset" in JS
    assert "saveInventoryChannelPreset" in JS
    assert "INVENTORY_FEE_PRESET_KEY" in JS
    assert 'localStorage.setItem(INVENTORY_FEE_PRESET_KEY' in JS
    assert 'id="inventoryFeePresetNote"' in HTML
    assert "Channel fee presets are editable estimates" in HTML
    assert "6.8.8-provisional-identity" in HTML

def test_channel_changes_recalculate_and_fee_edits_persist():
    assert '$("inventorySaleChannel")?.addEventListener("change"' in JS
    assert '$("inventoryFeePercent")?.addEventListener("change"' in JS
    assert "return updateInventorySellRecommendation()" in JS
