from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_api_exposes_durable_trends():
    assert "orchestrator.collection.dashboard(references)" in SERVER
    service = Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")
    assert "trends = self.trends()" in service
    assert '"trends": trends' in service


def test_collection_ui_shows_trends_activity_and_baseline_disclosure():
    assert 'id="collectionAcquisitionChart"' in CONTROL
    assert 'id="collectionValueChart"' in CONTROL
    assert 'id="collectionSetGrowth"' in CONTROL
    assert 'id="collectionActivity"' in CONTROL
    assert "historical dates were not invented" in CONTROL
    assert "function renderCollectionTrends(trends)" in STUDIO
