from rareiq.models.session import BreakSession
from rareiq.services.backend_test_service import BackendTestService


def test_normalized_card_contract():
    service = object.__new__(BackendTestService)
    service.orchestrator = None

    card = service.normalize_current_card(
        recognition={
            "database_match": {
                "id": "card-1",
                "name": "Test Card",
                "number": "12/100",
                "set": "Test Set",
                "language": "English",
                "rarity": "Rare",
                "price": 5.25,
            },
            "overall_confidence": 0.95,
            "verification_state": "VERIFIED",
            "candidates": [],
        },
        state={},
    )

    assert card["card_name"] == "Test Card"
    assert card["collector_number"] == "12/100"
    assert card["raw_value"] == 5.25
    assert card["confidence"] == 0.95


def test_normalized_card_keeps_missing_market_value_unavailable():
    service = object.__new__(BackendTestService)
    service.orchestrator = None

    card = service.normalize_current_card(
        recognition={
            "database_match": {
                "id": "card-1",
                "name": "Unpriced Card",
                "number": "12/100",
                "language": "English",
            },
            "verification_state": "VERIFIED",
            "candidates": [],
        },
        state={},
    )

    assert card["raw_value"] is None


def test_authoritative_card_requires_local_reference_evidence():
    service = object.__new__(BackendTestService)
    service.orchestrator = None
    recognition = {
        "database_match": {
            "id": "card-1",
            "name": "Test Card",
            "number": "12/100",
            "set": "Test Set",
            "language": "English",
        },
        "recognition_locked": True,
        "verification_state": "VERIFIED",
    }
    safe_state = {
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "identity_consistent": True,
        "result_current": True,
        "has_reference_evidence": True,
    }

    assert service.authoritative_current_card(recognition, safe_state) is not None
    assert service.authoritative_current_card(
        recognition,
        {**safe_state, "has_reference_evidence": False},
    ) is None


def test_session_round_trip():
    original = BreakSession.create(
        customer="Jon",
        order_number="TEST-1",
        product_name="Test Box",
        boxes_total=1,
        packs_per_box=2,
    )
    restored = BreakSession.from_public(original.public())

    assert restored.customer == "Jon"
    assert restored.order_number == "TEST-1"
    assert restored.boxes_total == 1
    assert restored.packs_per_box == 2
