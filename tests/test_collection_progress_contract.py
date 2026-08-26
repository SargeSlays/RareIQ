from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
DECK = Path("rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


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


def test_collection_set_catalog_defaults_to_started_sets_and_bounded_rendering():
    assert 'id="collectionSetSearch"' in CONTROL
    assert 'id="collectionSetMode"' in CONTROL
    assert '<option value="started">Started sets</option>' in CONTROL
    assert 'id="collectionSetMore"' in CONTROL
    assert "function collectionSetStarted(set)" in STUDIO
    assert 'const mode=$("collectionSetMode")?.value||"started"' in STUDIO
    assert "const visible=filtered.slice(0,collectionSetVisibleLimit)" in STUDIO
    assert "collectionSetVisibleLimit+=48" in STUDIO
    assert "max-height: min(720px, 62vh)" in DECK


def test_recent_collection_flow_prioritizes_exact_inventory():
    recent_rule = '.workspace[data-workspace="collection"][data-collection-view="recent"] .collection-exact-inventory { order: 2; }'
    trends_rule = '.workspace[data-workspace="collection"][data-collection-view="recent"] .collection-trends { order: 3; }'
    sync_rule = '.workspace[data-workspace="collection"][data-collection-view="recent"] #librarySyncPanel { order: 4; }'
    assert recent_rule in DECK
    assert trends_rule in DECK
    assert sync_rule in DECK
