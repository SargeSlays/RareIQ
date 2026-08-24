from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_inventory_cards_live_in_a_named_bounded_browser_surface():
    assert 'class="inventory-stock-browser"' in CONTROL
    assert 'id="inventoryBrowserTitle"' in CONTROL
    assert 'id="inventoryItemCount"' in CONTROL
    assert 'id="inventoryItems" role="list"' in CONTROL
    assert ".inventory-stock-browser .inventory-items{max-height:clamp(420px,56vh,760px);overflow:auto" in STYLES
    assert "overscroll-behavior:contain" in STYLES


def test_inventory_browser_preserves_item_actions_and_accessibility():
    assert 'row.setAttribute("role","listitem")' in SCRIPT
    assert 'select.setAttribute("aria-label",`Select ${item.item_id} for batch actions`)' in SCRIPT
    for label in ("Profile", "Print Label", "Set Alert", "Mark Listed", "Sell"):
        assert label in SCRIPT


def test_inventory_browser_reports_the_complete_rendered_count():
    assert '$("inventoryItemCount").textContent=`${items.length.toLocaleString()} ${items.length===1?"item":"items"}`' in SCRIPT
    assert 'boxes:[".inventory-manager"' in SCRIPT
    assert '".inventory-stock-browser"' in SCRIPT


def test_inventory_browser_has_truthful_empty_and_mobile_states():
    assert 'content:"No physical inventory cards yet."' in STYLES
    assert ".inventory-stock-browser .inventory-items{max-height:clamp(340px,52vh,520px)" in STYLES
