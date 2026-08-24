from pathlib import Path
import time

from rareiq.services.catalog_service import CatalogService

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def _item(number: str, group: str = "box:pack-1") -> dict:
    return {
        "item_id": f"RIQ-{number}", "status": "in_stock", "set_code": "me05",
        "collector_number": number, "language": "English", "finish": "normal",
        "cost_basis": 2, "currency": "USD", "allocation_group": group,
    }


def test_inventory_excludes_stale_and_unverified_quotes_without_zeroing_them(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        now = time.time()
        cards = [
            (_item("1/84"), {"market": 10, "currency": "USD", "source": "A", "updated_at": now, "verified": True, "valuation_eligible": True, "verification_state": "verified"}),
            (_item("2/84"), {"market": 20, "currency": "USD", "source": "A", "updated_at": now - 8 * 86400, "verified": False, "valuation_eligible": False, "verification_state": "stale", "verification_reason": "Quote is older than 7 days"}),
            (_item("3/84"), {"market": 30, "currency": "USD", "source": "B", "updated_at": now, "verified": False, "valuation_eligible": False, "verification_state": "unverified", "verification_reason": "Quote confidence is not strong enough"}),
        ]
        for item, pricing in cards:
            service._record_price({**item, "pricing": pricing})
        result = service.inventory_valuation([item for item, _pricing in cards])
        assert result["verified_value"] == 10
        assert result["priced"] == 1 and result["unpriced"] == 2
        assert result["excluded_quotes"] == 2
        assert result["stale_excluded"] == 1 and result["unverified_excluded"] == 1
        excluded = [row for row in result["items"] if not row["priced"]]
        assert sorted(row["market"] for row in excluded) == [20, 30]
        assert all(row["unrealized_profit"] is None for row in excluded)
    finally:
        service.shutdown()


def test_pack_roi_and_strongest_pull_use_only_eligible_quotes(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        now = time.time()
        eligible, stale = _item("1/84"), _item("2/84")
        service._record_price({**eligible, "english_name": "Eligible", "pricing": {"market": 8, "currency": "USD", "source": "A", "updated_at": now, "valuation_eligible": True, "verified": True}})
        service._record_price({**stale, "english_name": "Stale", "pricing": {"market": 100, "currency": "USD", "source": "A", "updated_at": now - 8 * 86400, "valuation_eligible": False, "verified": False, "verification_state": "stale"}})
        result = service.inventory_break_performance([{**eligible, "english_name": "Eligible"}, {**stale, "english_name": "Stale"}])
        pack = result["packs"][0]
        assert pack["verified_value"] == 8
        assert pack["strongest_pull"]["card_name"] == "Eligible"
        assert pack["priced"] == 1 and pack["coverage_percent"] == 50
    finally:
        service.shutdown()


def test_inventory_ui_explains_market_quote_exclusions():
    assert "data.stale_excluded" in JS
    assert "data.unverified_excluded" in JS
    assert "excluded from verified totals" in JS
    assert "6.8.8-provisional-identity" in HTML
