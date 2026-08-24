from rareiq.services.collection_service import CollectionService


def card(**overrides):
    payload = {
        "card_name": "Crocalor",
        "set_name": "Gem Pack Vol 5",
        "set_code": "GEM_PACK_VOL_5",
        "collector_number": "160/??",
        "language": "zh-CN",
        "rarity": "Common",
        "reference_image_url": "/card/160.jpg",
    }
    payload.update(overrides)
    return payload


def test_collection_tracks_exact_versions_and_duplicates(tmp_path):
    service = CollectionService(tmp_path / "collection.json")

    assert service.record(card(), "pull-1")["recorded"] is True
    assert service.record(card(), "pull-2")["recorded"] is True
    assert service.record(card(collector_number="161/??"), "pull-3")["recorded"] is True

    snapshot = service.snapshot()
    assert snapshot["total_cards"] == 3
    assert snapshot["unique_cards"] == 2
    assert snapshot["duplicate_copies"] == 1
    assert sorted(item["quantity"] for item in snapshot["cards"]) == [1, 2]


def test_collection_event_is_idempotent_and_persists(tmp_path):
    path = tmp_path / "collection.json"
    service = CollectionService(path)
    service.record(card(), "pull-1")

    duplicate = service.record(card(), "pull-1")
    restored = CollectionService(path).snapshot()

    assert duplicate["recorded"] is False
    assert duplicate["reason"] == "duplicate_event"
    assert restored["total_cards"] == 1


def test_collection_rejects_provisional_and_supports_undo(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    rejected = service.record(card(provisional=True), "pull-provisional")
    service.record(card(), "pull-verified")
    removed = service.remove_event("pull-verified")

    assert rejected == {"recorded": False, "reason": "verified_card_required"}
    assert removed["removed"] is True
    assert service.snapshot()["total_cards"] == 0


def test_collection_quantity_corrections_are_audited_and_reversible(tmp_path):
    path = tmp_path / "collection.json"
    service = CollectionService(path)
    service.record(card(), "pull-1")

    adjustment = service.adjust_quantity(
        service.version_key(card()), 2, "counted two offline copies"
    )
    assert adjustment["adjusted"] is True
    assert service.snapshot()["total_cards"] == 3
    assert service.snapshot()["corrections"][0]["reason"] == "counted two offline copies"

    undone = service.undo_correction(adjustment["correction"]["id"])
    restored = CollectionService(path).snapshot()
    assert undone["undone"] is True
    assert restored["total_cards"] == 1
    assert restored["corrections"][0]["undone_at"] is not None


def test_collection_correction_never_allows_negative_quantity(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(), "pull-1")

    result = service.adjust_quantity(service.version_key(card()), -2, "bad count")

    assert result == {"adjusted": False, "reason": "quantity_below_zero"}
    assert service.snapshot()["total_cards"] == 1


def test_collection_set_progress_uses_catalog_checklist_without_inventing_totals(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(collector_number="160"), "pull-1")
    service.record(card(collector_number="160"), "pull-2")
    references = [
        card(collector_number="159", card_name="Crocalor A"),
        card(collector_number="160", card_name="Crocalor B"),
        card(collector_number="161", card_name="Crocalor C"),
    ]

    progress = service.set_progress(references)["sets"][0]

    assert progress["owned_versions"] == 1
    assert progress["total_copies"] == 2
    assert progress["duplicate_copies"] == 1
    assert progress["catalog_total"] == 3
    assert progress["catalog_owned"] == 1
    assert progress["completion_percent"] == 33.3
    assert [item["collector_number"] for item in progress["missing_cards"]] == ["159", "161"]


def test_collection_set_progress_marks_missing_catalog_as_unavailable(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(set_code="LOCAL_SET", set_name="Local Set"), "pull-1")

    progress = service.set_progress([])["sets"][0]

    assert progress["checklist_status"] == "unavailable"
    assert progress["catalog_total"] is None
    assert progress["completion_percent"] is None
    assert progress["missing_cards"] == []


def test_collection_valuation_counts_only_sourced_prices(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(market_price=12.50, pricing_source="TCG market"), "pull-1")
    service.record(card(market_price=12.50, pricing_source="TCG market"), "pull-2")
    service.record(card(collector_number="161", market_price=99, pricing_source=None), "pull-3")

    valuation = service.valuation()

    assert valuation["portfolio_value"] == 25.0
    assert valuation["priced_copies"] == 2
    assert valuation["unpriced_copies"] == 1
    assert valuation["pricing_coverage_percent"] == 66.7
    assert valuation["biggest_hits"][0]["unit_price"] == 12.5
    assert valuation["set_values"][0]["value"] == 25.0


def test_collection_valuation_excludes_test_and_zero_prices(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(market_price=50, pricing_source="demo"), "pull-1")
    service.record(card(collector_number="161", market_price=0, pricing_source="TCG market"), "pull-2")

    valuation = service.valuation()

    assert valuation["portfolio_value"] == 0
    assert valuation["priced_copies"] == 0
    assert valuation["unpriced_copies"] == 2


def test_collection_trends_record_acquisitions_corrections_and_undos(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(market_price=10, pricing_source="market"), "pull-1")
    correction = service.adjust_quantity(service.version_key(card()), 2, "offline copies")
    service.undo_correction(correction["correction"]["id"])

    trends = service.trends()

    assert [item["type"] for item in trends["recent_activity"][:3]] == ["correction_undo", "correction", "acquired"]
    assert sum(item["cards_delta"] for item in trends["daily"]) == 1
    assert sum(item["verified_value_delta"] for item in trends["daily"]) == 10


def test_legacy_collection_gets_one_honest_baseline_event(tmp_path):
    path = tmp_path / "collection.json"
    service = CollectionService(path)
    service.record(card(), "pull-1")
    payload = __import__("json").loads(path.read_text(encoding="utf-8"))
    payload.pop("activity")
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    trends = CollectionService(path).trends()

    assert trends["has_legacy_baseline"] is True
    assert trends["recent_activity"][0]["label"] == "Existing collection baseline"


def test_collection_card_goal_tracks_exact_number_and_quantity(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(collector_number="160"), "pull-1")
    created = service.add_goal(target_type="card", set_name="Gem Pack Vol 5", collector_number="160", target_quantity=2, priority="high")
    goal = service.goals([card(collector_number="160", card_name="Crocalor")])["goals"][0]
    assert created["created"] is True
    assert goal["current_quantity"] == 1
    assert goal["progress_percent"] == 50.0
    assert goal["complete"] is False
    assert goal["identity_status"] == "catalog_resolved"


def test_collection_set_goal_and_archive_are_persistent(tmp_path):
    path = tmp_path / "collection.json"
    service = CollectionService(path)
    service.record(card(collector_number="160"), "pull-1")
    created = service.add_goal(target_type="set", set_name="Gem Pack Vol 5", target_quantity=2)
    assert service.goals([])["goals"][0]["current_quantity"] == 1
    assert service.archive_goal(created["goal"]["id"])["archived"] is True
    assert CollectionService(path).goals([])["active_goals"] == 0


def test_duplicate_disposition_tracks_trade_sell_and_keep(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    for index in range(4):
        service.record(card(), f"pull-{index}")
    key = service.version_key(card())
    result = service.set_disposition(key, trade=2, sell=1)
    queue = service.disposition_queue()
    assert result["updated"] is True
    assert queue["trade_copies"] == 2
    assert queue["sell_copies"] == 1
    assert queue["disposition_cards"][0]["keep_quantity"] == 1


def test_disposition_rejects_overallocation_and_clamps_after_quantity_drop(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.record(card(), "pull-1")
    service.record(card(), "pull-2")
    key = service.version_key(card())
    assert service.set_disposition(key, trade=2, sell=1)["reason"] == "allocation_exceeds_quantity"
    service.set_disposition(key, trade=1, sell=1)
    service.adjust_quantity(key, -1, "count correction")
    row = service.snapshot()["cards"][0]
    assert row["disposition"] == {"trade": 1, "sell": 0}


def test_collection_backup_preview_and_merge_preserve_higher_quantity(tmp_path):
    local = CollectionService(tmp_path / "local.json")
    remote = CollectionService(tmp_path / "remote.json")
    local.record(card(), "local-1")
    remote.record(card(), "remote-1")
    remote.record(card(), "remote-2")
    remote.record(card(collector_number="161"), "remote-3")

    preview = local.preview_import(remote.backup())
    merged = local.merge_backup(remote.backup())

    assert preview["new_versions"] == 1
    assert preview["conflict_count"] == 1
    assert preview["conflicts"][0]["resolved_quantity"] == 2
    assert merged["merged"] is True
    assert local.snapshot()["total_cards"] == 3
    assert set(local.backup()["events"]) == {"local-1", "remote-1", "remote-2", "remote-3"}


def test_collection_import_rejects_report_json_and_malformed_backup(tmp_path):
    service = CollectionService(tmp_path / "collection.json")

    assert service.preview_import(service.snapshot())["reason"] == "unsupported_backup_format"
    assert service.preview_import({"format": "rareiq_collection_backup", "cards": []})["reason"] == "invalid_backup_structure"


def test_legacy_schema_migrates_disposition_and_version_key(tmp_path):
    path = tmp_path / "collection.json"
    key = CollectionService.version_key(card())
    path.write_text(__import__("json").dumps({
        "schema_version": 1, "cards": {key: {**card(), "quantity": 2, "first_seen_at": 1}},
        "events": {},
    }), encoding="utf-8")

    restored = CollectionService(path)
    item = restored.snapshot()["cards"][0]
    assert item["version_key"] == key
    assert item["disposition"] == {"trade": 0, "sell": 0}
    assert restored.trends()["has_legacy_baseline"] is True


def test_collection_history_is_bounded_before_persistence(tmp_path):
    service = CollectionService(tmp_path / "collection.json")
    service.MAX_ACTIVITY = 3
    for index in range(5):
        service.record(card(collector_number=str(index)), f"pull-{index}")
    assert len(service.backup()["activity"]) == 3
