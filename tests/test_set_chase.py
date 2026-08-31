import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading

from fastapi import FastAPI
import httpx
import pytest

from rareiq.services.set_chase_service import SetChaseService, RevisionConflict, image_path, theme_for, validate_config
from rareiq.services.global_visual_index_service import GlobalVisualIndexService
from rareiq.services.catalog_rarity import rarity_sort_key
from rareiq.web.set_chase import create_set_chase_router


def card(identifier="one"):
    return {"id": identifier, "name": "Sample card", "set_id": "sample", "language": "English",
            "collector_number": "001/100", "image_url": "/api/catalog-engine/image/en_sample/one.png"}


def config():
    return {"set_id": "sample", "set_name": "Sample Set", "language": "English", "theme": "auto",
            "cards_per_page": 4, "seconds_per_page": 8, "case_hits": [card()], "top_hits": [card("two")]}


def test_draft_is_separate_from_program_and_hide_preserves_content(tmp_path):
    service = SetChaseService(tmp_path / "chase.json", clock=lambda: 100)
    service.change("draft", 0, config())
    assert not service.snapshot()["visible"]
    assert service.snapshot(preview=True)["config"]["set_name"] == "Sample Set"
    service.change("take", 1)
    changed = config(); changed["set_name"] = "New draft"
    service.change("draft", 2, changed)
    assert service.snapshot()["config"]["set_name"] == "Sample Set"
    assert service.snapshot()["started_at_ms"] == 100_000
    service.change("hide", 3)
    assert not service.snapshot()["visible"]
    assert service.settings()["draft"]["set_name"] == "New draft"
    assert service.settings()["program"]["set_name"] == "Sample Set"


def test_restart_restores_lists_but_stays_off_air(tmp_path):
    path = tmp_path / "chase.json"; service = SetChaseService(path)
    service.change("draft", 0, config()); service.change("take", 1)
    restored = SetChaseService(path)
    assert restored.settings()["draft"] == service.settings()["draft"]
    assert restored.settings()["revision"] == 2
    assert not restored.snapshot()["visible"]


def test_stale_editor_and_concurrent_publish_are_rejected(tmp_path):
    service = SetChaseService(tmp_path / "chase.json"); service.change("draft", 0, config())
    results = []
    def publish():
        try: results.append(service.change("take", 1)["revision"])
        except RevisionConflict: results.append("conflict")
    threads = [threading.Thread(target=publish) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sorted(map(str, results)) == ["2", "conflict"]
    with pytest.raises(RevisionConflict): service.change("draft", 0, config())


def test_failed_persistence_leaves_both_states_and_revision_unchanged(tmp_path, monkeypatch):
    service = SetChaseService(tmp_path / "chase.json")
    before = service.settings()
    def fail(*args): raise OSError("disk unavailable")
    monkeypatch.setattr("rareiq.services.set_chase_service.atomic_json", fail)
    with pytest.raises(OSError): service.change("draft", 0, config())
    assert service.settings() == before


def test_corrupt_settings_are_visible_and_never_overwritten(tmp_path):
    path = tmp_path / "chase.json"; path.write_text("not json")
    service = SetChaseService(path)
    assert not service.settings()["ok"] and not service.snapshot()["visible"]
    with pytest.raises(ValueError): service.change("draft", 0, config())
    assert path.read_text() == "not json"


@pytest.mark.parametrize("mutation", [
    {"cards_per_page": 2}, {"cards_per_page": True}, {"seconds_per_page": 3}, {"seconds_per_page": 31},
    {"seconds_per_page": 4.5}, {"theme": "made-up"}, {"theme": {}}, {"accent": "red;display:none"},
    {"set_name": ""}, {"language": None}, {"secret": "not supported"}, {"case_hits": [card()] * 33},
    {"top_hits": [card()]}, {"case_hits": [{**card(), "set_id": "wrong"}]},
    {"top_hits": [{**card("two"), "language": "Japanese"}]},
])
def test_invalid_config_cannot_change_live_output(tmp_path, mutation):
    service = SetChaseService(tmp_path / "chase.json")
    service.change("draft", 0, config()); service.change("take", 1); before = service.settings()
    with pytest.raises(ValueError): service.change("draft", 2, {**config(), **mutation})
    assert service.settings() == before


@pytest.mark.parametrize("path", ["https://example.test/image.png", "//example.test/card", "javascript:alert(1)",
    "/api/catalog-engine/image/en/../secret", "/api/catalog-engine/image/en/%2e%2e", "/api/catalog-engine/image/en/%252e%252e",
    "/api/catalog-engine/image/en/a.png?token=private", "/static/anything.svg", "/api/catalog-engine/image/en/a\\b"])
def test_images_are_local_catalog_only(path):
    with pytest.raises(ValueError): image_path(path)


def test_empty_draft_can_preview_but_cannot_publish(tmp_path):
    service = SetChaseService(tmp_path / "chase.json")
    service.change("draft", 0, {**config(), "case_hits": [], "top_hits": []})
    with pytest.raises(ValueError, match="at least one"): service.change("take", 1)


def test_theme_and_snapshots_are_bounded_and_copied(tmp_path):
    current = validate_config({**config(), "set_name": "Pitch Black", "accent": "#AaBBcc"})
    assert theme_for(current)["key"] == "midnight"
    assert theme_for(current)["accent"] == "#aabbcc"
    service = SetChaseService(tmp_path / "chase.json"); service.change("draft", 0, current)
    snapshot = service.snapshot(preview=True); snapshot["config"]["case_hits"].clear()
    assert len(service.settings()["draft"]["case_hits"]) == 1


def test_scoped_catalog_search_filters_before_limiting_and_preserves_unfiltered_search():
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{"id": str(i), "name": "Pikachu", "set_id": "other", "language": "English"} for i in range(120)]
    index._records += [{"id": "right", "name": "Pikachu", "set_id": "sample", "language": "English"},
                       {"id": "jp", "name": "Pikachu", "set_id": "sample", "language": "Japanese"}]
    result = index.text_search("Pikachu", set_id="sample", language="English", limit=1)
    assert [c["id"] for c in result] == ["right"]
    assert len(index.text_search("Pikachu", limit=100)) == 100
    assert [c["id"] for c in index.text_search("P", set_id="sample", language="English")] == ["right"]
    assert index.text_search("P") == []


def test_set_options_come_from_searchable_cards_not_other_catalog_manifests():
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [
        {"id": "en1", "set_id": "me5", "set_name": "Pitch Black", "language": "English"},
        {"id": "en2", "set_id": "me5", "set_name": "Pitch Black", "language": "English"},
        {"id": "ja1", "set_id": "M5", "set_name": "Japanese Set", "language": "Japanese"},
        {"id": "incomplete", "set_id": "unknown"},
    ]
    options = index.set_options()
    assert options[0] == {"set_id": "me5", "set_name": "Pitch Black", "language": "English", "cards": 2}
    assert len(options) == 2
    options[0]["set_name"] = "Mutated"
    assert index.set_options()[0]["set_name"] == "Pitch Black"


def test_rarity_filter_and_counts_cover_the_whole_set_before_result_limit():
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{**card(str(i)), "rarity": "C"} for i in range(130)]
    index._records += [{**card("chase"), "rarity": " SAR ", "name": "Chase Card"},
                       {**card("rare"), "rarity": "R"}, {**card("double"), "rarity": "RR"},
                       {**card("unlisted"), "rarity": None},
                       {**card("other-language"), "rarity": "SAR", "language": "Japanese"},
                       {**card("other-set"), "rarity": "SAR", "set_id": "other"}]
    all_cards = index.catalog_search("", set_id="sample", language="English", limit=100)
    assert len(all_cards["results"]) == 100 and all_cards["total"] == 134
    assert all_cards["set_total"] == 134
    assert {facet["value"]: facet["count"] for facet in all_cards["rarities"]} == {"C": 130, "SAR": 1, "R": 1, "RR": 1, "": 1}
    hit = index.catalog_search("Chase", set_id="sample", language="English", rarity="sar")
    assert [row["id"] for row in hit["results"]] == ["chase"]
    assert hit["total"] == 1 and hit["rarities"] == all_cards["rarities"]
    exact = index.catalog_search("", set_id="sample", language="English", rarity="R")
    assert [row["id"] for row in exact["results"]] == ["rare"]
    unlisted = index.catalog_search("", set_id="sample", language="English", rarity="")
    assert [row["id"] for row in unlisted["results"]] == ["unlisted"]
    missing = index.catalog_search("nothing", set_id="sample", language="English", rarity="SAR")
    assert missing["total"] == 0 and missing["rarities"] == hit["rarities"]


def test_rarity_endpoint_combines_filters_without_mutating_saved_rotation(tmp_path):
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{**card("rare"), "rarity": "R", "name": "Rare Sample"},
                       {**card("unlisted"), "rarity": ""}]
    service = SetChaseService(tmp_path / "state.json")
    service.change("draft", 0, config()); service.change("take", 1)
    before = service.settings()
    async def read(request): return await request.json()
    app = FastAPI(); app.include_router(create_set_chase_router(service, index, read, Path("rareiq/web/static")))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/creator/set-chase/cards"
            filters = {"set_id": "sample", "language": "English", "rarity": "R", "q": "Rare"}
            result = (await client.get(path, params=filters)).json()
            assert result["total"] == 1 and result["results"][0]["id"] == "rare"
            assert result["rarities"] == [{"value": "R", "count": 1}, {"value": "", "count": 1}]
            unlisted = (await client.get(path, params={**filters, "rarity": "", "q": ""})).json()
            assert unlisted["results"][0]["id"] == "unlisted"
            assert (await client.get(path, params={**filters, "rarity": "R" * 121})).status_code == 422
            assert service.settings() == before
    asyncio.run(run())


def test_rarity_order_is_highest_first_and_preserves_catalog_labels():
    labels = ["", "U", "C", "R", "RR", "AR", "UR", "SAR", "Hyper Rare", "MUR", "Promo"]
    assert sorted(labels, key=lambda label: rarity_sort_key(label, "English")) == [
        "MUR", "Hyper Rare", "SAR", "UR", "AR", "RR", "R", "U", "C", "Promo", ""]
    assert sorted(["SAR", "UR", "SR"], key=lambda label: rarity_sort_key(label, "Japanese")) == ["UR", "SAR", "SR"]
    full = ["Common", "Rare Ultra", "Special Illustration Rare", "Uncommon", "Illustration Rare", "Double Rare"]
    assert sorted(full, key=rarity_sort_key) == ["Special Illustration Rare", "Rare Ultra", "Illustration Rare", "Double Rare", "Uncommon", "Common"]


def test_multi_rarity_filter_orders_before_limit_without_changing_recognition_order():
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{**card(str(i)), "name": "Exact", "rarity": "C"} for i in range(130)]
    index._records += [{**card("sar"), "name": "Exact chase", "rarity": "SAR"},
                       {**card("rr"), "name": "Exact double", "rarity": "RR"},
                       {**card("r"), "name": "Exact rare", "rarity": "R"}]
    scope = {"set_id": "sample", "language": "English"}
    first = index.catalog_search("Exact", **scope, rarity_first=True, limit=1)
    assert first["results"][0]["id"] == "sar" and first["total"] == 133
    assert [item["value"] for item in first["rarities"]] == ["SAR", "RR", "R", "C"]
    union = index.catalog_search("Exact", **scope, rarity=["sar", " rr ", "SAR"], rarity_first=True)
    assert [row["id"] for row in union["results"]] == ["sar", "rr"]
    assert union["total"] == 2 and union["rarities"] == first["rarities"]
    assert index.catalog_search("", **scope, rarity=[])["results"] == []
    assert index.text_search("Exact", **scope, limit=1)[0]["rarity"] == "C"


def test_highest_rarity_selection_is_set_wide_even_when_query_has_no_matches():
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{**card("top"), "rarity": "SAR", "name": "Chase"},
                      {**card("base"), "rarity": "C", "name": "Common"},
                      {**card("other"), "rarity": "MUR", "set_id": "other"}]
    scope = {"set_id": "sample", "language": "English", "highest_rarity_only": True, "rarity_first": True}
    top = index.catalog_search("", **scope)
    assert top["selected_rarities"] == ["SAR"] and top["results"][0]["id"] == "top"
    empty = index.catalog_search("Common", **scope)
    assert empty["selected_rarities"] == ["SAR"] and empty["total"] == 0
    assert empty["rarities"] == top["rarities"]
    assert index.catalog_search("", **{**scope, "set_id": "empty"})["selected_rarities"] == []


def test_rarity_route_accepts_multiple_levels_and_validates_filter_bounds(tmp_path):
    index = object.__new__(GlobalVisualIndexService); index._lock = threading.RLock()
    index._records = [{**card("common"), "rarity": "C"}, {**card("double"), "rarity": "RR"},
                      {**card("top"), "rarity": "SAR"}, {**card("unlisted"), "rarity": ""}]
    service = SetChaseService(tmp_path / "state.json")
    async def read(request): return await request.json()
    app = FastAPI(); app.include_router(create_set_chase_router(service, index, read, Path("rareiq/web/static")))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = "/api/creator/set-chase/cards?set_id=sample&language=English"
            result = (await client.get(path + "&rarity=SAR&rarity=RR")).json()
            assert [row["id"] for row in result["results"]] == ["top", "double"]
            assert result["selected_rarities"] == ["SAR", "RR"]
            top = (await client.get(path + "&highest=true")).json()
            assert [row["id"] for row in top["results"]] == ["top"]
            assert top["selected_rarities"] == ["SAR"]
            union = (await client.get(path + "&rarity=RR&rarity=")).json()
            assert [row["id"] for row in union["results"]] == ["double", "unlisted"]
            assert (await client.get(path + "&highest=true&rarity=R")).status_code == 422
            assert (await client.get(path + "&rarity=R" * 65)).status_code == 422
            assert (await client.get(path + "&rarity=" + "R" * 121)).status_code == 422
            assert service.settings()["revision"] == 0
    asyncio.run(run())


def test_router_state_actions_and_public_card_projection(tmp_path):
    class Index:
        def set_options(self):
            return [{"set_id": "sample", "set_name": "Sample Set", "language": "English", "cards": 1}]

        def catalog_search(self, query, **kwargs):
            assert kwargs["set_id"] == "sample" and kwargs["language"] == "English"
            return {"results": [{**card(), "reference_image_url": card()["image_url"], "local_image": "private/path", "private_note": "secret"}],
                    "total": 1, "set_total": 1, "rarities": [{"value": "R", "count": 1}]}
    async def read(request): return await request.json()
    service = SetChaseService(tmp_path / "state.json"); app = FastAPI()
    app.include_router(create_set_chase_router(service, Index(), read, Path("rareiq/web/static")))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for page in ("/overlay/set-chase", "/creator/set-chase"):
                response = await client.get(page)
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store, max-age=0"
            assert (await client.get("/api/creator/set-chase/sets")).json()["sets"][0]["set_id"] == "sample"
            assert not (await client.get("/api/creator/set-chase/status")).json()["visible"]
            response = await client.post("/api/creator/set-chase/draft", json={"revision": 0, "config": config()})
            assert response.status_code == 200
            assert (await client.post("/api/creator/set-chase/take", json={"revision": 0})).status_code == 409
            assert (await client.post("/api/creator/set-chase/take", json={"revision": 1})).status_code == 200
            assert (await client.get("/api/creator/set-chase/status")).json()["visible"]
            rows = (await client.get("/api/creator/set-chase/cards?set_id=sample&language=English")).json()["results"]
            assert "local_image" not in rows[0] and "private_note" not in rows[0]
            assert (await client.post("/api/creator/set-chase/hide", json={"revision": 2})).status_code == 200
    asyncio.run(run())


def test_creator_integration_and_bounded_mutations():
    server = Path("rareiq/web/server.py").read_text(encoding="utf-8")
    control = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
    assert 'path.startswith("/api/creator/set-chase/")' in server
    assert 'create_set_chase_router(set_chase' in server
    assert 'data-creator-view="chase"' in control and 'data-src="/creator/set-chase?embed=creator"' in control
