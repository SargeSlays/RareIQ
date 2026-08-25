import pytest
from fastapi import HTTPException

from rareiq.web.server import (
    _bind_card_graphic_identity,
    _compose_broadcast_overlay_state,
    _sanitize_card_graphic,
)


def _snapshot(**overrides):
    return {
        "state_id": "verified-state-1",
        "generation": 7,
        "verification_state": "VERIFIED",
        "identity_consistent": True,
        "recognition_locked": True,
        "result_current": True,
        "has_reference_evidence": True,
        **overrides,
    }


def _card():
    return {
        "card_id": "card-1",
        "card_name": "Verified Card",
        "english_name": "Verified Card",
        "set_name": "Verified Set",
        "collector_number": "12/100",
        "reference_image_url": "/reference/card-1.webp",
    }


def test_overlay_replaces_mutable_stale_card_with_authoritative_state():
    state = _compose_broadcast_overlay_state(
        {"current_card": {"card_name": "Stale Wrong Card"}},
        None,
        _snapshot(
            verification_state="REFERENCE_MISSING",
            identity_consistent=False,
            recognition_locked=False,
            has_reference_evidence=False,
        ),
    )

    assert state["current_card"] is None
    assert state["current_card_status"] == "reference_missing"
    assert state["current_card_state_id"] is None


def test_card_graphic_rejects_missing_reference_identity():
    with pytest.raises(HTTPException) as error:
        _bind_card_graphic_identity(
            {"kind": "card", "title": "Wrong Candidate"},
            None,
            _snapshot(
                verification_state="REFERENCE_MISSING",
                identity_consistent=False,
                recognition_locked=False,
                has_reference_evidence=False,
            ),
        )

    assert error.value.status_code == 409


def test_card_graphic_uses_backend_card_and_binds_live_state():
    graphic = _bind_card_graphic_identity(
        {
            "kind": "card",
            "title": "Caller Supplied Wrong Name",
            "subtitle": "Caller Supplied Wrong Set",
            "image_url": "/wrong.png",
        },
        _card(),
        _snapshot(),
    )

    assert graphic["title"] == "Verified Card"
    assert graphic["subtitle"] == "Verified Set · 12/100"
    assert graphic["image_url"] == "/reference/card-1.webp"
    assert graphic["identity_verified"] is True
    assert graphic["identity_state_id"] == "verified-state-1"
    assert graphic["identity_generation"] == 7


def test_visible_card_graphic_is_hidden_when_identity_generation_changes():
    graphic = _bind_card_graphic_identity(
        {"kind": "card"},
        _card(),
        _snapshot(),
    ) | {"visible": True, "preview": False}

    safe = _sanitize_card_graphic(
        graphic,
        None,
        _snapshot(
            state_id="new-state",
            generation=8,
            verification_state="REFERENCE_MISSING",
            identity_consistent=False,
            recognition_locked=False,
            has_reference_evidence=False,
        ),
    )

    assert safe["visible"] is False
    assert safe["preview"] is False
    assert safe["safety_status"] == "blocked"
    assert safe["suppression_reason"] == "verified_current_card_required"


def test_operator_lower_third_remains_independent_of_card_identity():
    graphic = {"kind": "lower-third", "title": "Guest Host", "visible": True}

    assert _bind_card_graphic_identity(graphic, None, {}) == graphic
    assert _sanitize_card_graphic(graphic, None, {}) == graphic
