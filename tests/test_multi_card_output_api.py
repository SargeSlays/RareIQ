"""Output mutations must reject malformed and unverified selections without side effects."""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rareiq.web import server


def test_status_does_not_wait_for_reconciliation_on_the_event_loop(monkeypatch):
    caller_thread = threading.get_ident()
    worker_threads = []

    def status():
        worker_threads.append(threading.get_ident())
        return {"status": "complete", "verified_count": 3}

    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        multi_card_recognition=SimpleNamespace(status=status)))
    response = asyncio.run(server.multi_card_status())
    assert response == {"ok": True, "status": "complete", "verified_count": 3}
    assert len(worker_threads) == 1 and worker_threads[0] != caller_thread


@pytest.mark.parametrize("payload", [{}, {"slots": "1"}, {"slots": None}])
def test_invalid_selection_body_does_not_clear_existing_output(monkeypatch, payload):
    select = Mock()
    monkeypatch.setattr(server, "_read_bounded_json", AsyncMock(return_value=payload))
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        multi_card_recognition=SimpleNamespace(select_slots=select)))
    response = asyncio.run(server.multi_card_select(SimpleNamespace()))
    assert response.status_code == 400
    assert json.loads(response.body)["reason"] == "invalid_slots"
    select.assert_not_called()


def test_unverified_selection_returns_conflict_without_species_lookup(monkeypatch):
    state = {"ok": False, "reason": "cards_need_verification", "blocked_slots": [2], "selected_slots": [1]}
    select = Mock(return_value=state)
    lookup = AsyncMock()
    monkeypatch.setattr(server, "_read_bounded_json", AsyncMock(return_value={"slots": [1, 2]}))
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        multi_card_recognition=SimpleNamespace(select_slots=select)))
    monkeypatch.setattr(server, "current_pokedex_entry", lookup)
    response = asyncio.run(server.multi_card_select(SimpleNamespace()))
    assert response.status_code == 409
    assert json.loads(response.body) == state
    lookup.assert_not_awaited()


def test_valid_selection_refreshes_species_profile(monkeypatch):
    select = Mock(return_value={"ok": True, "selected_slots": [1]})
    lookup = AsyncMock(return_value={"pokemon": {"name": "Nickit"}})
    monkeypatch.setattr(server, "_read_bounded_json", AsyncMock(return_value={"slots": [1]}))
    monkeypatch.setattr(server, "orchestrator", SimpleNamespace(
        multi_card_recognition=SimpleNamespace(select_slots=select)))
    monkeypatch.setattr(server, "current_pokedex_entry", lookup)
    response = asyncio.run(server.multi_card_select(SimpleNamespace()))
    assert response["selected_slots"] == [1]
    assert response["rare_intelligence"]["pokemon"]["name"] == "Nickit"
    select.assert_called_once_with([1])
    lookup.assert_awaited_once()
