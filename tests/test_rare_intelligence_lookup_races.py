from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from rareiq.services.overlay_state_service import OverlayStateService
from rareiq.web import server


@pytest.fixture
def lookup(tmp_path, monkeypatch):
    card = {"id": "card-a", "name": "Nickit", "collector_number": "53/84"}
    current = {
        "generation": 1, "card_present": True, "recognition_locked": True,
        "verification_state": "VERIFIED", "identity_consistent": True,
        "result_current": True, "has_reference_evidence": True,
        "primary_candidate": card,
    }
    multi = {"job_id": 0, "selected_slots": [], "slots": []}
    overlay = OverlayStateService(tmp_path / "overlay.json")
    overlay.update({"pokedex_on_air": True})
    resolved = []
    state = SimpleNamespace(current=current, multi=multi, overlay=overlay, during_resolve=lambda: None)

    def resolve(candidate):
        resolved.append(deepcopy(candidate))
        state.during_resolve()
        return {"pokemon": {"name": candidate["name"]}}

    fake = SimpleNamespace(
        recognition_state=SimpleNamespace(snapshot=lambda: deepcopy(current)),
        recognition=SimpleNamespace(status=lambda: {}),
        backend_test=SimpleNamespace(normalize_current_card=lambda _raw, snapshot: {
            **snapshot["primary_candidate"], "card_id": snapshot["primary_candidate"]["id"],
            "card_name": snapshot["primary_candidate"]["name"],
        }),
        multi_card_recognition=SimpleNamespace(status=lambda: deepcopy(multi)),
        overlay_state=overlay,
        pokedex=SimpleNamespace(resolve=resolve, pokemon_name=lambda candidate: (candidate or {}).get("name")),
        experiences=SimpleNamespace(for_card=lambda _card: {}),
    )
    monkeypatch.setattr(server, "orchestrator", fake)
    state.run = lambda: asyncio.run(server.current_pokedex_entry())
    return state


def test_slow_lookup_obeys_latest_on_air_and_theme(lookup):
    def turn_off():
        lookup.overlay.update({"pokedex_on_air": False, "rare_intelligence_theme": {"accent": "mint"}})
    lookup.during_resolve = turn_off
    response = lookup.run()
    assert response["pokemon"]["name"] == "Nickit"
    assert response["on_air"] is False
    assert response["theme"] == {"accent": "mint"}
    assert lookup.overlay.get()["pokedex_current"]["on_air"] is False


@pytest.mark.parametrize("change", ["generation", "candidate", "verification", "removed", "selection", "slot_card", "job"])
def test_slow_lookup_cannot_publish_or_persist_stale_identity(lookup, change):
    if change in {"slot_card", "job"}:
        lookup.multi.update({"job_id": 1, "selected_slots": [1], "slots": [
            {"slot": 1, "verified": True, "card": {"id": "slot-a", "name": "Nickit"}},
        ]})
    newer = {"pokemon": {"name": "Slowpoke"}, "identity": {"verified": True}, "provisional": False}

    def replace_context():
        if change == "generation":
            lookup.current["generation"] += 1
        elif change == "candidate":
            lookup.current["primary_candidate"] = {"id": "card-b", "name": "Slowpoke"}
        elif change == "verification":
            lookup.current["verification_state"] = "REVIEW_NEEDED"
        elif change == "removed":
            lookup.current.update({"card_present": False, "recognition_locked": False})
        elif change == "selection":
            lookup.multi["selected_slots"] = [2]
        elif change == "slot_card":
            lookup.multi["slots"][0]["card"] = {"id": "slot-b", "name": "Slowpoke"}
        else:
            lookup.multi["job_id"] += 1
        lookup.overlay.update({"pokedex_current": newer})

    lookup.during_resolve = replace_context
    response = lookup.run()
    assert response["pokemon"] is None
    assert response["on_air"] is False
    assert response["broadcast_eligible"] is False
    assert response["reason"] == "recognition_context_changed"
    assert lookup.overlay.get()["pokedex_current"] == newer


def test_same_card_confidence_and_frame_updates_do_not_discard_profile(lookup):
    def next_frame():
        lookup.current.update({"confidence": .96, "frame_id": 200, "revision": 25})
        lookup.current["primary_candidate"]["score"] = .99
    lookup.during_resolve = next_frame
    response = lookup.run()
    assert response["pokemon"]["name"] == "Nickit"
    assert response["on_air"] is True
    assert response["broadcast_eligible"] is True
