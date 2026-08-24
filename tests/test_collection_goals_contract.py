from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_goal_api_creates_and_archives_targets():
    assert '@app.post("/api/collection/goals")' in SERVER
    assert '@app.post("/api/collection/goals/{goal_id}/archive")' in SERVER
    assert "orchestrator.collection.dashboard(references)" in SERVER
    assert "goals = self.goals(reference_cards)" in Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")


def test_collection_goal_ui_supports_cards_sets_priority_and_progress():
    assert 'id="collectionGoalForm"' in CONTROL
    assert 'id="collectionGoalType"' in CONTROL
    assert 'id="collectionGoalPriority"' in CONTROL
    assert 'id="collectionGoalGrid"' in CONTROL
    assert "function renderCollectionGoals(goals,summary={})" in STUDIO
    assert "function createCollectionGoal(event)" in STUDIO
    assert "progress_percent" in STUDIO
