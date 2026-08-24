from io import BytesIO
from pathlib import Path
import time
from PIL import Image
from rareiq.services.inventory_service import InventoryService

CARD={"version_key":"gem|160|zh-cn|crocalor","english_name":"Crocalor","set_name":"Gem Pack Vol 5","set_code":"GEM_PACK_VOL_5","collector_number":"160","language":"zh-cn"}

def test_inventory_item_qr_sale_and_profit_are_persistent(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    result=service.create(CARD,cost_basis=10,asking_price=30,condition="near_mint",location="Box A")
    item_id=result["item"]["item_id"]
    assert result["created"] and item_id.startswith("RIQ-")
    assert Image.open(BytesIO(service.qr_png(item_id))).format=="PNG"
    assert service.sell(item_id,sale_price=30,fees=3,shipping_cost=2)["item"]["sale"]["profit"]==15
    assert not service.sell(item_id,sale_price=40)["sold"]
    dashboard=InventoryService(tmp_path/"inventory.json").dashboard()
    assert dashboard["in_stock"]==0 and dashboard["sold_count"]==1 and dashboard["net_profit"]==15

def test_void_sale_restores_stock_but_preserves_sale_history(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    item_id=service.create(CARD,cost_basis=10)["item"]["item_id"]
    service.sell(item_id,sale_price=25,fees=2,channel="ebay",order_reference="ORDER-1")
    result=service.void_sale(item_id,"customer_return")
    assert result["voided"] and result["item"]["status"]=="in_stock"
    assert result["item"]["sale"] is None
    assert result["item"]["sale_history"][0]["order_reference"]=="ORDER-1"
    assert service.dashboard()["net_profit"]==0

def test_sales_export_rows_include_financial_and_order_fields(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    item_id=service.create(CARD,cost_basis=7)["item"]["item_id"]
    service.sell(item_id,sale_price=20,fees=2,shipping_cost=3,channel="in_person",order_reference="SHOW-9")
    row=service.sales_rows()[0]
    assert row["profit"]==8 and row["net_proceeds"]==15
    assert row["channel"]=="in_person" and row["order_reference"]=="SHOW-9"

def test_inventory_preserves_pricing_resolution_through_sale(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    priced={**CARD,"pricing":{"market":18.5,"currency":"USD","source":"Provider B","variant":"normal","resolution_id":"price-resolution-123","resolution_reason":"variant-match","resolution_note":"Exact normal finish","updated_at":123.0,"verified":True,"valuation_eligible":True}}
    created=service.create(priced,cost_basis=7)["item"]
    assert created["pricing_resolution_id"]=="price-resolution-123"
    assert created["acquisition_valuation"]["market"]==18.5
    assert created["acquisition_valuation"]["provider"]=="Provider B"
    sold=service.sell(created["item_id"],sale_price=25)["item"]
    assert sold["sale"]["pricing_resolution_id"]=="price-resolution-123"
    assert sold["sale"]["acquisition_market"]==18.5
    restored=InventoryService(tmp_path/"inventory.json").get(created["item_id"])
    assert restored["acquisition_valuation"]["resolution_note"]=="Exact normal finish"
    row=service.sales_rows()[0]
    assert row["pricing_resolution_id"]=="price-resolution-123"
    assert row["acquisition_market_provider"]=="Provider B"

def test_inventory_requires_identity_and_unknown_codes_do_not_resolve(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    assert service.create({})["reason"]=="card_identity_required"
    assert service.get("RIQ-NOTREAL") is None
    assert service.qr_png("RIQ-NOTREAL") is None

def test_bulk_intake_creates_unique_copy_records_in_one_persisted_batch(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    result=service.create_many(CARD,quantity=3,cost_basis=4.5,asking_price=12,location="Case B")
    assert result["created"] and result["quantity"]==3
    assert len({item["item_id"] for item in result["items"]})==3
    assert {item["batch_id"] for item in result["items"]}=={result["batch_id"]}
    assert [item["batch_copy_number"] for item in result["items"]]==[1,2,3]
    dashboard=InventoryService(tmp_path/"inventory.json").dashboard()
    assert dashboard["in_stock"]==3 and dashboard["inventory_cost"]==13.5

def test_bulk_intake_rejects_quantities_outside_print_batch_limit(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    assert service.create_many(CARD,quantity=0)["reason"]=="invalid_quantity"
    assert service.create_many(CARD,quantity=101)["reason"]=="invalid_quantity"
    assert service.dashboard()["in_stock"]==0

def test_business_profile_audit_log_and_daily_backup_are_persistent(tmp_path):
    state_path=tmp_path/"inventory.json"
    service=InventoryService(state_path)
    created=service.create(CARD,cost_basis=8)
    service.update_business_profile(company_name="Rare Intelligence Cards",currency="CAD",fiscal_year_start=4,reporting_basis="accrual")
    restored=InventoryService(state_path)
    assert restored.business_profile()=={"company_name":"Rare Intelligence Cards","currency":"CAD","fiscal_year_start":4,"reporting_basis":"accrual"}
    log=restored.audit_log(20)
    assert log["total"]==2
    assert [row["action"] for row in log["entries"]]==["business_profile.updated","inventory.created"]
    assert log["entries"][1]["entity_id"]==created["item"]["batch_id"]
    backup=restored.backup_status()
    assert backup["automatic"] and backup["count"]==1
    assert Path(backup["latest"]).is_file()

def test_allocation_changes_are_in_the_immutable_accounting_history(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    service.create_many(CARD,quantity=2,allocation_group="PACK-1")
    assert service.rebalance_allocation("PACK-1",12)["rebalanced"]
    assert service.lock_allocation("PACK-1")["locked"]
    actions=[row["action"] for row in service.audit_log()["entries"]]
    assert actions[:3]==["allocation.locked","allocation.rebalanced","inventory.created"]

def test_monthly_profit_loss_close_locks_historical_expenses(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    incurred=time.mktime((2025,5,12,12,0,0,0,1,-1))
    expense=service.add_expense("supplies",25,incurred_at=incurred)["expense"]
    report=service.profit_and_loss(2025,5)
    assert report["period"]=="2025-05" and report["statement"]["operating_expenses"]==25
    assert report["statement"]["net_income"]==-25 and not report["closed"]
    assert service.close_period(2025,5)["closed"]
    assert service.profit_and_loss(2025,5)["closed"]
    assert service.update_expense(expense["expense_id"],amount=30)["reason"]=="accounting_period_closed"
    assert service.remove_expense(expense["expense_id"])["reason"]=="accounting_period_closed"
    assert service.add_expense("other",10,incurred_at=incurred)["reason"]=="accounting_period_closed"
    assert InventoryService(tmp_path/"inventory.json").period_closes()["periods"][0]["period"]=="2025-05"

def test_current_month_cannot_be_closed(tmp_path):
    service=InventoryService(tmp_path/"inventory.json")
    now=time.localtime()
    assert service.close_period(now.tm_year,now.tm_mon)["reason"]=="period_not_finished"
