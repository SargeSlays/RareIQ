from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_api_joins_catalog_reference_checklist():
    assert "collection_reference_cards()" in SERVER
    assert "orchestrator.collection.dashboard(references)" in SERVER
    assert "progress = self.set_progress(reference_cards)" in Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")


def test_collection_ui_distinguishes_known_and_unknown_completion():
    assert 'id="collectionSetGrid"' in CONTROL
    assert "function renderCollectionSets(sets)" in STUDIO
    assert 'set.checklist_status==="available"' in STUDIO
    assert "Reference checklist not loaded" in STUDIO
    assert "missing cards" in STUDIO
