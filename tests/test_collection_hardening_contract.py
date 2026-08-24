from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")


def test_collection_dashboard_is_one_consistent_service_snapshot():
    assert "orchestrator.collection.dashboard(references)" in SERVER
    assert "def dashboard(self, reference_cards" in SERVICE


def test_collection_mutations_return_non_200_error_responses():
    assert "def _collection_mutation_response" in SERVER
    assert "JSONResponse(status_code=status" in SERVER
    assert "status = 404" in SERVER and "else 409" in SERVER and "else 422" in SERVER


def test_collection_history_has_explicit_bounds_and_migration():
    assert "MAX_ACTIVITY = 10000" in SERVICE
    assert "MAX_CORRECTIONS = 5000" in SERVICE
    assert "MAX_ARCHIVED_GOALS = 1000" in SERVICE
    assert "def _migrate_loaded_state" in SERVICE
