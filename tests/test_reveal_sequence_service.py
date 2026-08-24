from rareiq.services.reveal_sequence_service import RevealSequenceService


def card(rarity="COMMON", name="Card"):
    return {"card_name": name, "rarity": rarity, "collector_number": "1"}


def test_reveal_sequence_builds_suspense_and_reacts_at_rare_slot(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    service.configure({"expected_cards": 6, "rare_slot": 6})
    for index in range(5):
        state = service.advance(card(name=f"Card {index+1}"))
    assert state["phase"] == "build"
    assert state["suspense_percent"] == 83
    final = service.advance(card("RARE", "Rare Card"))
    assert final["phase"] == "reaction"
    assert final["reaction_tier"] == "low"
    assert final["reaction_copy"] == "Nice pull!"


def test_medium_and_grail_hits_trigger_early_reaction_and_custom_preset(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    service.configure({"custom_grail_preset": "user-john-cena-style", "reaction_copy": {"grail": "OH MY GOD!"}})
    medium = service.advance(card("DOUBLE RARE", "Hit"))
    grail = service.next_pack() and service.advance(card("GRAIL", "Grail"))
    assert medium["phase"] == "reaction" and medium["reaction_tier"] == "medium"
    assert grail["reaction_copy"] == "OH MY GOD!"
    assert grail["custom_grail_preset"] == "user-john-cena-style"
    assert grail["audio_enabled"] is False


def test_reveal_config_persists_but_pack_sequence_resets(tmp_path):
    path = tmp_path / "reveal.json"
    service = RevealSequenceService(path)
    service.configure({"expected_cards": 8, "rare_slot": 7})
    service.advance(card())
    restored = RevealSequenceService(path)
    assert restored.snapshot()["expected_cards"] == 8
    assert restored.snapshot()["position"] == 0

def test_verified_rare_tiers_get_distinct_animation_presets(tmp_path):
    service=RevealSequenceService(tmp_path/"reveal.json")
    service.configure({"minimum_animation_tier":"low","animation_intensity":88,"animation_duration_ms":4800})
    low=service.advance(card("RARE","Rare"))
    service.next_pack(); medium=service.advance(card("DOUBLE RARE","Medium"))
    service.next_pack(); grail=service.advance(card("GRAIL","Grail"))
    assert low["animation"]["preset"]=="low" and low["animation"]["active"]
    assert medium["animation"]["preset"]=="medium"
    assert grail["animation"]["preset"]=="grail"
    assert grail["animation"]["intensity"]==88 and grail["animation"]["duration_ms"]==4800

def test_provisional_cards_cannot_fire_animation(tmp_path):
    service=RevealSequenceService(tmp_path/"reveal.json")
    result=service.advance(card("GRAIL","Wrong")|{"provisional":True})
    assert result["animation_blocked"] is True
    assert result["animation_block_reason"]=="verified_identity_required"
    assert result["position"]==0


def test_verified_market_value_can_promote_hit_tier(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    medium = service.advance(card("COMMON", "Valuable Card") | {"market_price": 42.0})
    service.next_pack()
    grail = service.advance(card("RARE", "Huge Card") | {"pricing": {"market": 225.0}})
    assert medium["reaction_tier"] == "medium"
    assert medium["current_card"]["hit_reason"] == "verified_market_value"
    assert medium["current_card"]["market_value"] == 42.0
    assert grail["reaction_tier"] == "grail"
    assert grail["animation"]["preset"] == "grail"


def test_incomplete_market_data_falls_back_to_catalog_rarity(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    result = service.advance(card("ILLUSTRATION RARE", "Catalog Hit") | {"market_price": None})
    assert result["reaction_tier"] == "medium"
    assert result["current_card"]["hit_reason"] == "catalog_rarity"


def test_custom_value_thresholds_drive_classification_and_stay_ordered(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    configured = service.configure({"medium_value_threshold": 10, "grail_value_threshold": 8})
    assert configured["config"]["medium_value_threshold"] == 10
    assert configured["config"]["grail_value_threshold"] == 10
    result = service.advance(card("COMMON", "Threshold Hit") | {"market_price": 10})
    assert result["reaction_tier"] == "grail"


def test_animation_arms_and_can_be_released_or_cancelled(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    service.configure({"arming_delay_ms": 5000})
    armed = service.advance(card("GRAIL", "Armed Grail"))
    assert armed["arming"]["active"] is True
    assert armed["animation"]["active"] is False
    released = service.release_animation()
    assert released["arming"]["active"] is False
    assert released["animation"]["active"] is True
    service.next_pack()
    service.advance(card("GRAIL", "Cancelled Grail"))
    cancelled = service.cancel_animation()
    assert cancelled["arming"]["cancelled"] is True
    assert cancelled["animation"]["active"] is False


def test_reveal_history_replays_without_advancing_pack(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    first = service.advance(card("GRAIL", "Historic Grail") | {"market_price": 200})
    reveal_id = first["history"][0]["reveal_id"]
    position = first["position"]
    replay = service.replay_animation(reveal_id)
    assert replay["is_replay"] is True
    assert replay["current_card"]["card_name"] == "Historic Grail"
    assert replay["position"] == position
    assert len(replay["history"]) == 1
    assert replay["animation"]["active"] is True


def test_unknown_reveal_replay_is_safe(tmp_path):
    service = RevealSequenceService(tmp_path / "reveal.json")
    result = service.replay_animation("missing")
    assert result["replay_error"] == "reveal_not_found"
    assert result["position"] == 0


def test_reveal_history_persists_while_active_pack_resets(tmp_path):
    path = tmp_path / "reveal.json"
    service = RevealSequenceService(path)
    revealed = service.advance(card("GRAIL", "Durable Grail") | {"market_price": 250})
    reveal_id = revealed["history"][0]["reveal_id"]
    restored = RevealSequenceService(path)
    snapshot = restored.snapshot()
    assert snapshot["position"] == 0
    assert len(snapshot["history"]) == 1
    assert snapshot["history"][0]["card_name"] == "Durable Grail"
    assert restored.replay_animation(reveal_id)["current_card"]["card_name"] == "Durable Grail"


def test_legacy_config_file_still_loads(tmp_path):
    path = tmp_path / "reveal.json"
    path.write_text('{"expected_cards": 9, "rare_slot": 8}', encoding="utf-8")
    restored = RevealSequenceService(path).snapshot()
    assert restored["expected_cards"] == 9
    assert restored["rare_slot"] == 8
    assert restored["history"] == []


def test_persisted_history_is_bounded_and_sanitized(tmp_path):
    path = tmp_path / "reveal.json"
    service = RevealSequenceService(path)
    for index in range(24):
        service.next_pack()
        service.advance(card("RARE", f"Hit {index}"))
    restored = RevealSequenceService(path).snapshot()
    assert len(restored["history"]) == 20
    assert restored["history"][0]["card_name"] == "Hit 23"
    assert all("unexpected" not in item for item in restored["history"])
