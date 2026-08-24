from pathlib import Path
import time
from datetime import datetime

from rareiq.services.catalog_service import CatalogService
from rareiq.services.inventory_service import InventoryService


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_market_widget_has_real_refresh_action():
    assert 'id="marketRefreshButton"' in HTML
    assert "async function refreshCurrentMarket()" in JS
    assert 'api("/api/catalog/refresh-current",{method:"POST"})' in JS
    assert 'tab==="business"){refreshCurrentMarket()}' in JS


def test_backend_exposes_current_verified_card_refresh():
    assert '@app.post("/api/catalog/refresh-current")' in SERVER
    assert "orchestrator.catalog.refresh(card)" in SERVER


def test_force_refresh_removes_cached_exact_number(tmp_path, monkeypatch):
    service = CatalogService(lambda event: None, tmp_path)
    cache = service._cache_path("en", "023/084")
    cache.write_text("{}", encoding="utf-8")
    submitted = []
    monkeypatch.setattr(service, "submit", lambda card, force=False: submitted.append((card, force)))

    result = service.refresh({
        "collector_number": "023/084",
        "language": "English",
        "name": "Electrike",
    })

    assert result["ok"] is True
    assert not cache.exists()
    assert submitted[0][1] is True


def test_manual_verified_price_is_persisted_and_labeled(tmp_path):
    events = []
    service = CatalogService(events.append, tmp_path)
    result = service.set_manual_price(
        {"set_id": "me05", "collector_number": "023/084", "name": "Electrike"},
        {"market": 1.25, "low": 0.9, "high": 1.8, "currency": "USD", "note": "Local sold comp"},
    )

    assert result["ok"] is True
    assert result["pricing"]["source"] == "Manual verified"
    assert result["pricing"]["manual"] is True
    assert service._manual_price_path.exists()
    assert service._apply_manual_price({
        "set_id": "me05", "collector_number": "023/084"
    })["pricing"]["market"] == 1.25
    assert events[-1]["type"] == "catalog_update"


def test_manual_price_form_is_exact_card_scoped_and_wired():
    assert 'id="manualPriceForm"' in HTML
    assert 'id="manualPriceMarket"' in HTML
    assert 'id="manualPriceNote"' in HTML
    assert 'api("/api/catalog/manual-price"' in JS
    assert "Manual prices are labeled and timestamped" in HTML
    assert '@app.post("/api/catalog/manual-price")' in SERVER


def test_public_price_preserves_provider_quotes_and_confidence(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    result = service._extract_price({"pricing": {
        "tcgplayer": {"unit": "USD", "normal": {"marketPrice": 3.5, "lowPrice": 3.0}},
        "cardmarket": {"unit": "EUR", "trend": 3.2, "low": 2.8},
    }})
    assert result["source"] == "TCGPlayer"
    assert result["provider_count"] == 2
    assert result["confidence"] == "high"
    assert result["verified"] is True
    assert {quote["source"] for quote in result["quotes"]} == {"TCGPlayer", "Cardmarket"}


def test_market_ui_exposes_provenance_freshness_and_currency():
    assert 'id="pricingConfidence"' in HTML
    assert 'id="pricingFreshness"' in HTML
    assert 'id="pricingProviderCount"' in HTML
    assert 'function cardMoney(value,currency="USD")' in JS


def test_price_history_deduplicates_and_calculates_movement(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    card = {"set_id": "me05", "collector_number": "013/084", "pricing": {
        "source": "TCGPlayer", "market": 10.0, "unit": "USD"
    }}
    first = service._record_price(card)
    service._record_price(card)
    assert first["pricing"]["history_count"] == 1
    higher = dict(card)
    higher["pricing"] = {**card["pricing"], "market": 12.0}
    result = service._record_price(higher)
    assert result["pricing"]["history_count"] == 2
    assert len(result["pricing"]["history"]) == 2
    assert result["pricing"]["trend"] == "rising"
    assert result["pricing"]["change_percent"] == 20.0


def test_market_ui_exposes_price_movement():
    assert 'id="pricingMovement"' in HTML
    assert 'pricing.historyCount?"Baseline captured"' in JS
    assert 'id="priceHistoryChart"' in HTML
    assert 'id="priceHistoryLedger"' in HTML
    assert "function renderPriceHistory(history=[]" in JS


def test_price_alert_is_exact_card_scoped_and_evaluated(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    card = {"set_id": "me05", "collector_number": "013/084", "pricing": {
        "source": "TCGPlayer", "market": 12.0, "unit": "USD"
    }}
    saved = service.set_price_alert(card, {"direction": "above", "target": 10, "currency": "USD"})
    assert saved["ok"] is True
    evaluated = service._attach_price_history(card)
    assert evaluated["pricing"]["alert"]["triggered"] is True
    assert service._price_alert_path.exists()


def test_price_alert_ui_and_endpoint_are_wired():
    assert 'id="priceAlertForm"' in HTML
    assert 'id="priceAlertClear"' in HTML
    assert 'api("/api/catalog/price-alert"' in JS
    assert '@app.post("/api/catalog/price-alert")' in SERVER


def test_price_alert_dashboard_reports_triggered_first(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    card = {"set_id": "me05", "collector_number": "013/084", "name": "Goldeen", "set_name": "Pitch Black", "pricing": {"source": "TCGPlayer", "market": 12.0, "unit": "USD"}}
    service._record_price(card)
    service.set_price_alert(card, {"direction": "above", "target": 10, "currency": "USD"})
    dashboard = service.price_alert_dashboard()
    assert dashboard["total"] == 1
    assert dashboard["triggered"] == 1
    assert dashboard["alerts"][0]["card_name"] == "Goldeen"


def test_central_price_watchlist_is_wired():
    assert 'id="priceWatchlist"' in HTML
    assert 'id="priceWatchlistSummary"' in HTML
    assert 'api("/api/catalog/price-alerts")' in JS
    assert '@app.get("/api/catalog/price-alerts")' in SERVER


def test_price_alert_notification_channels_are_opt_in_and_deduplicated():
    assert 'id="priceAlertDesktop"' in HTML
    assert 'id="priceAlertSound"' in HTML
    assert "Notification.requestPermission()" in JS
    assert "sessionStorage.getItem(storageKey)" in JS
    assert "playSoundboardPad(pad)" in JS


def test_watchlist_scheduler_status_and_manual_refresh_are_wired(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        status = service.watch_status()
        assert status["next_run_at"] is not None
        assert status["busy"] is False
    finally:
        service.shutdown()
    assert 'id="priceWatchRefresh"' in HTML
    assert 'id="priceWatchSchedule"' in HTML
    assert 'api("/api/catalog/price-alerts/refresh"' in JS
    assert '@app.post("/api/catalog/price-alerts/refresh")' in SERVER


def test_inventory_valuation_excludes_unpriced_and_calculates_profit(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        card = {"set_code": "me05", "collector_number": "013/084", "pricing": {"source": "TCGPlayer", "market": 12.0, "unit": "USD"}}
        service._record_price(card)
        result = service.inventory_valuation([
            {"item_id": "RIQ-1", "status": "in_stock", "set_code": "me05", "collector_number": "013/084", "cost_basis": 8, "currency": "USD"},
            {"item_id": "RIQ-2", "status": "in_stock", "set_code": "missing", "collector_number": "1/1", "cost_basis": 2, "currency": "USD"},
        ])
        assert result["verified_value"] == 12.0
        assert result["unrealized_profit"] == 4.0
        assert result["priced"] == 1 and result["unpriced"] == 1
        assert result["coverage_percent"] == 50.0
    finally:
        service.shutdown()


def test_inventory_valuation_ui_and_endpoint_are_wired():
    assert 'id="inventoryVerifiedValue"' in HTML
    assert 'id="inventoryUnrealized"' in HTML
    assert 'api("/api/inventory/valuation")' in JS
    assert '@app.get("/api/inventory/valuation")' in SERVER


def test_approved_scan_inventory_intake_is_optional_and_duplicate_safe():
    assert 'id="approvedInventoryAuto"' in HTML
    assert 'id="approvedInventoryAdd"' in HTML
    assert 'id="approvedInventoryLabel"' in HTML
    assert "if(!result?.card||result.duplicate_suppressed)return" in JS
    assert 'api("/api/inventory/items"' in JS
    assert "if(approvedInventoryPrefs().auto)" in JS


def test_approved_inventory_supports_pack_and_box_cost_allocation():
    assert 'id="approvedInventoryCostMode"' in HTML
    assert 'value="pack_share"' in HTML
    assert 'id="approvedInventoryCardsPerPack"' in HTML
    assert 'api("/api/production/session/pack-economics")' in JS
    assert "packCost/cards" in JS
    assert "currency:allocation.currency" in JS


def test_rarity_weighted_inventory_rebalances_to_exact_pack_total(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    common = {"english_name": "Common", "set_code": "me05", "collector_number": "1/84"}
    rare = {"english_name": "Rare", "set_code": "me05", "collector_number": "2/84"}
    first = service.create(common, allocation_group="session:pack-1", allocation_weight=1)
    second = service.create(rare, allocation_group="session:pack-1", allocation_weight=3)
    result = service.rebalance_allocation("session:pack-1", 12, "USD")
    costs = {item["item_id"]: item["cost_basis"] for item in result["items"]}
    assert result["rebalanced"] is True
    assert costs[first["item"]["item_id"]] == 3
    assert costs[second["item"]["item_id"]] == 9
    assert sum(costs.values()) == 12


def test_rarity_weighted_inventory_ui_and_endpoint_are_wired():
    assert 'value="rarity_weighted"' in HTML
    assert "approvedInventoryRarityWeight" in JS
    assert 'api("/api/inventory/allocations/rebalance"' in JS
    assert '@app.post("/api/inventory/allocations/rebalance")' in SERVER


def test_inventory_valuation_groups_pack_profitability(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        service._record_price({"set_code": "me05", "collector_number": "1/84", "pricing": {"market": 9, "currency": "USD", "source": "test"}})
        result = service.inventory_valuation([{"item_id": "RIQ-1", "status": "in_stock", "set_code": "me05", "collector_number": "1/84", "english_name": "Card", "cost_basis": 3, "currency": "USD", "allocation_group": "session:pack-1", "allocation_weight": 2}])
        group = result["allocation_groups"][0]
        assert group["cards"] == 1 and group["cost_basis"] == 3
        assert group["verified_value"] == 9 and group["unrealized_profit"] == 6
        assert group["roi_percent"] == 200
        assert group["complete"] is True
        assert group["strongest_pull"]["card_name"] == "Card"
    finally:
        service.shutdown()


def test_pack_profitability_dashboard_is_wired():
    assert 'id="inventoryPackLedgers"' in HTML
    assert 'id="inventoryPackLedgerSummary"' in HTML
    assert "renderInventoryPackLedgers" in JS
    assert 'document.createElement("details")' in JS
    assert "Strongest pull" in JS and "ROI" in JS


def test_completed_pack_allocation_is_immutable(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    card = {"english_name": "Card", "set_code": "me05", "collector_number": "1/84"}
    service.create(card, allocation_group="session:pack-1", allocation_weight=1)
    assert service.lock_allocation("session:pack-1")["locked"] is True
    assert service.rebalance_allocation("session:pack-1", 9)["reason"] == "allocation_group_locked"
    assert service.create(card, allocation_group="session:pack-1")["reason"] == "allocation_group_locked"
    reloaded = InventoryService(tmp_path / "inventory.json")
    assert reloaded.rebalance_allocation("session:pack-1", 9)["reason"] == "allocation_group_locked"


def test_pack_locking_and_rollover_are_wired():
    assert '@app.post("/api/inventory/allocations/lock")' in SERVER
    assert 'api("/api/inventory/allocations/lock"' in JS
    assert "_inventoryAllocationComplete" in JS
    assert "activeInventoryAllocationGroup" in JS


def test_pack_report_snapshot_preserves_lock_and_items(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    card = {"english_name": "Card", "set_code": "me05", "collector_number": "1/84"}
    created = service.create(card, allocation_group="session:pack-1", allocation_weight=2)
    service.lock_allocation("session:pack-1")
    snapshot = service.allocation_snapshot("session:pack-1")
    assert snapshot["locked"] is True
    assert snapshot["items"][0]["item_id"] == created["item"]["item_id"]


def test_pack_reports_and_csv_exports_are_wired():
    assert '@app.get("/api/inventory/allocations/{group}/report")' in SERVER
    assert '@app.get("/api/inventory/allocations/{group}/report.csv")' in SERVER
    assert "Print / Save PDF" in SERVER
    assert "Open Pack Report" in JS and "Download CSV" in JS


def test_break_performance_combines_verified_value_and_realized_sales(tmp_path):
    service = CatalogService(lambda event: None, tmp_path)
    try:
        service._record_price({"set_code": "me05", "collector_number": "1/84", "pricing": {"market": 8, "currency": "USD", "source": "test"}})
        items = [
            {"item_id": "RIQ-1", "status": "in_stock", "english_name": "Live Card", "set_code": "me05", "collector_number": "1/84", "cost_basis": 2, "currency": "USD", "allocation_group": "box-a:pack-1", "allocation_weight": 1},
            {"item_id": "RIQ-2", "status": "sold", "english_name": "Sold Hit", "set_code": "me05", "collector_number": "2/84", "cost_basis": 3, "currency": "USD", "allocation_group": "box-a:pack-1", "allocation_weight": 4, "sale": {"gross": 12, "net_proceeds": 10}},
        ]
        result = service.inventory_break_performance(items)
        pack = result["packs"][0]
        assert pack["verified_value"] == 8 and pack["realized_sales"] == 10
        assert pack["total_return"] == 18 and pack["profit"] == 13
        assert pack["roi_percent"] == 260 and pack["hit_rate"] == 50
        assert result["boxes"][0]["total_return"] == 18
    finally:
        service.shutdown()


def test_break_performance_dashboard_is_wired():
    assert 'id="breakPerformanceRows"' in HTML
    assert 'id="breakBestPack"' in HTML and 'id="breakBestBox"' in HTML
    assert 'api(`/api/inventory/break-performance?${performanceQuery}`)' in JS
    assert '@app.get("/api/inventory/break-performance")' in SERVER


def test_break_performance_business_filters_and_export_are_wired():
    assert 'id="breakPerformancePeriod"' in HTML
    assert 'id="breakPerformanceSet"' in HTML
    assert 'id="breakPerformanceApply"' in HTML
    assert 'id="breakPerformanceExport"' in HTML
    assert "function breakPerformanceQuery()" in JS
    assert 'period=${encodeURIComponent(period)}&set_filter=${encodeURIComponent(setFilter)}' in JS
    assert '@app.get("/api/inventory/break-performance.csv")' in SERVER
    assert 'Literal["daily", "weekly", "monthly", "lifetime"]' in SERVER


def test_expense_ledger_persists_and_reduces_operating_net(tmp_path):
    path = tmp_path / "inventory.json"
    service = InventoryService(path)
    card = {"english_name": "Card", "set_code": "me05", "collector_number": "1/84"}
    item = service.create(card, cost_basis=5)["item"]
    service.sell(item["item_id"], sale_price=10)
    expense = service.add_expense("supplies", 2, note="Sleeves")["expense"]
    trends = service.business_trends(7)
    assert trends["totals"] == {"revenue": 10.0, "card_profit": 5.0, "expenses": 2.0, "operating_net": 3.0}
    reloaded = InventoryService(path)
    assert reloaded.business_trends(7)["expenses"][0]["expense_id"] == expense["expense_id"]
    assert reloaded.remove_expense(expense["expense_id"])["removed"] is True


def test_business_trends_and_expense_tools_are_wired():
    assert 'id="businessTrendChart"' in HTML
    assert 'id="inventoryExpenseForm"' in HTML
    assert 'id="businessTrendDays"' in HTML
    assert 'api("/api/inventory/expenses"' in JS
    assert 'api(`/api/inventory/business-trends?days=${trendDays}`)' in JS
    assert '@app.get("/api/inventory/business-trends")' in SERVER
    assert '@app.post("/api/inventory/expenses")' in SERVER
    assert '@app.delete("/api/inventory/expenses/{expense_id}")' in SERVER


def test_receipts_recurring_expenses_and_tax_summary(tmp_path):
    path = tmp_path / "inventory.json"; service = InventoryService(path)
    card = {"english_name": "Card", "set_code": "me05", "collector_number": "1/84"}
    item = service.create(card, cost_basis=4)["item"]
    service.sell(item["item_id"], sale_price=12, fees=1, shipping_cost=2)
    expense = service.add_expense("supplies", 2, recurrence="monthly", receipt_name="receipt.png", receipt_data_url="data:image/png;base64,iVBORw0KGgo=")["expense"]
    assert expense["receipt_url"] and service.expense_receipt(expense["expense_id"]).is_file()
    trends = service.business_trends(31)
    assert trends["expenses"][0]["recurrence"] == "monthly"
    summary = service.tax_summary(time.localtime().tm_year)
    assert summary["totals"]["revenue"] == 12
    assert summary["totals"]["fees"] == 1 and summary["totals"]["shipping"] == 2
    assert summary["totals"]["card_cost"] == 4
    assert summary["totals"]["operating_expenses"] >= 2


def test_tax_expense_exports_and_receipts_are_wired():
    assert 'id="inventoryExpenseRecurrence"' in HTML
    assert 'id="inventoryExpenseReceipt"' in HTML
    assert 'id="inventoryTaxExport"' in HTML
    assert "expenseReceiptData" in JS
    assert '@app.get("/api/inventory/expenses.csv")' in SERVER
    assert '@app.get("/api/inventory/tax-summary.csv")' in SERVER
    assert '@app.get("/api/inventory/expenses/{expense_id}/receipt")' in SERVER


def test_calendar_recurrence_expense_editing_and_tax_comparison(tmp_path):
    service = InventoryService(tmp_path / "inventory.json")
    january = datetime(2026, 1, 31, 12).timestamp(); march = datetime(2026, 3, 31, 23).timestamp()
    occurrences = service._expense_occurrences({"incurred_at": january, "recurrence": "monthly"}, january, march)
    dates = [datetime.fromtimestamp(value).strftime("%Y-%m-%d") for value in occurrences]
    assert dates == ["2026-01-31", "2026-02-28", "2026-03-31"]
    expense = service.add_expense("fees", 10, recurrence="monthly")["expense"]
    assert expense["tax_category"] == "Commissions and fees"
    updated = service.update_expense(expense["expense_id"], amount=12, category="supplies", note="Updated")
    assert updated["expense"]["amount"] == 12
    assert updated["expense"]["tax_category"] == "Office expense and supplies"
    comparison = service.tax_comparison(time.localtime().tm_year)
    assert "current" in comparison and "previous" in comparison and "change_percent" in comparison


def test_expense_editing_tax_mapping_and_yoy_ui_are_wired():
    assert 'id="taxComparisonRevenue"' in HTML
    assert 'id="taxComparisonDeductions"' in HTML
    assert 'id="taxComparisonNet"' in HTML
    assert "editInventoryExpense" in JS and "renderTaxComparison" in JS
    assert '@app.patch("/api/inventory/expenses/{expense_id}")' in SERVER
    assert '@app.get("/api/inventory/tax-comparison")' in SERVER
