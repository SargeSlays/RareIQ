from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_exports_are_downloadable_and_authoritative():
    assert '@app.get("/api/collection/export.json")' in SERVER
    assert '@app.get("/api/collection/export.csv")' in SERVER
    assert 'filename="rareiq_collection.json"' in SERVER
    assert 'filename="rareiq_collection.csv"' in SERVER
    assert 'writer.writerows(orchestrator.collection.snapshot()["cards"])' in SERVER
    assert '"collector_number"' in SERVER
    assert '"quantity"' in SERVER
    assert '"version_key"' in SERVER


def test_collection_toolbar_exposes_search_filters_sort_and_exports():
    for control_id in (
        "collectionSearch",
        "collectionSetFilter",
        "collectionLanguageFilter",
        "collectionSort",
        "collectionDuplicatesOnly",
    ):
        assert f'id="{control_id}"' in CONTROL
        assert control_id in STUDIO
    assert 'href="/api/collection/export.csv"' in CONTROL
    assert 'href="/api/collection/export.json"' in CONTROL
    assert "function renderCollectionRows()" in STUDIO
    assert 'Number(card.quantity||0)>1' in STUDIO
