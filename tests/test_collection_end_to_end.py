from rareiq.services.collection_service import CollectionService
from rareiq.services.inventory_service import InventoryService


def verified_card(number="160"):
    return {
        "card_name": "Crocalor", "english_name": "Crocalor",
        "set_name": "Gem Pack Vol 5", "set_code": "GEM_PACK_VOL_5",
        "collector_number": number, "language": "zh-cn", "rarity": "C",
        "market_price": 12.5, "pricing_source": "verified market", "currency": "USD",
    }


def test_complete_collection_workflow_survives_backup_recovery(tmp_path):
    source = CollectionService(tmp_path / "source.json")
    source.record(verified_card(), "scan-1")
    source.record(verified_card(), "scan-2")
    source.add_goal(target_type="card", set_name="Gem Pack Vol 5", collector_number="160", target_quantity=2, priority="high")
    source.set_disposition(source.version_key(verified_card()), trade=1, sell=0)

    reference = [verified_card("159"), verified_card("160"), verified_card("161")]
    dashboard = source.dashboard(reference)
    assert dashboard["total_cards"] == 2
    assert dashboard["valuation"]["portfolio_value"] == 25.0
    assert dashboard["goals"][0]["complete"] is True
    assert dashboard["trade_copies"] == 1
    assert dashboard["sets"][0]["completion_percent"] == 33.3

    restored = CollectionService(tmp_path / "restored.json")
    assert restored.preview_import(source.backup())["valid"] is True
    assert restored.merge_backup(source.backup())["merged"] is True
    recovered = restored.dashboard(reference)
    assert recovered["total_cards"] == 2
    assert recovered["valuation"]["portfolio_value"] == 25.0
    assert recovered["goals"][0]["complete"] is True
    assert recovered["trade_copies"] == 1


def test_one_approved_event_updates_collection_and_inventory_exactly_once(tmp_path):
    collection = CollectionService(tmp_path / "collection.json")
    inventory = InventoryService(tmp_path / "inventory.json")
    card = verified_card()

    assert collection.record(card, "approval-1")["recorded"] is True
    assert collection.record(card, "approval-1")["reason"] == "duplicate_event"
    assert inventory.create(card, source_event_id="approval-1")["duplicate_suppressed"] is False
    assert inventory.create(card, source_event_id="approval-1")["duplicate_suppressed"] is True

    assert collection.snapshot()["total_cards"] == 1
    assert inventory.dashboard()["in_stock"] == 1
