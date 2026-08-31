import asyncio
from pathlib import Path

from rareiq.services.broadcast_source_catalog import broadcast_sources
from rareiq.services.obs_service import ObsService
from rareiq.web import server


def test_source_catalog_has_unique_clean_urls_names_and_keys():
    sources = broadcast_sources()
    assert len(sources) == 14
    for field in ("key", "path", "scene", "source"):
        assert len({item[field] for item in sources}) == len(sources)
    assert not ({item["scene"] for item in sources} & {item["source"] for item in sources})
    assert all(item["path"].startswith("/") and "?" not in item["path"] for item in sources)
    assert [item["key"] for item in sources if item["audio"]] == ["soundboard"]
    assert all(item["width"] > 0 and item["height"] > 0 for item in sources)


def test_obs_plan_and_operator_guide_share_metadata_without_changing_catalog(monkeypatch):
    class Recording:
        def settings(self): return {}
        def status(self): return {}
        def capabilities(self): return {}
    monkeypatch.setattr(server, "recording", Recording())
    guide = asyncio.run(server.recording_settings())
    plan = ObsService.bootstrap_plan("http://127.0.0.1:9040/")
    assert guide["browser_source_details"] == broadcast_sources()
    assert guide["browser_sources"] == {item["key"]: item["path"] for item in plan}
    for item, detail in zip(plan, guide["browser_source_details"]):
        assert item == {**detail, "url": "http://127.0.0.1:9040" + detail["path"]}
    plan[0]["source"] = "changed name"
    guide["browser_source_details"][0]["width"] = 1
    assert broadcast_sources()[0]["width"] == 1920
    assert broadcast_sources()[0]["source"] == "RareIQ Program Browser"


def test_all_source_routes_are_registered_including_the_chase_strip():
    paths = {route.path for route in server.app.routes}
    # Camera routes are parameterized, the remaining routes are concrete.
    for item in broadcast_sources():
        if not item["path"].startswith("/output/camera/"):
            assert item["path"] in paths
    html = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
    assert 'href="/creator/set-chase"' in html
    assert "Browser source library" in html


def test_copy_notifications_do_not_depend_on_retired_brand_styles():
    css = Path("rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")
    styles = css[css.index("/* Notification foundations"):]
    assert "body.studiox-command-deck #notificationStack {" in styles
    assert "position: fixed;" in styles and "pointer-events: none;" in styles
    assert "background: var(--sx-surface-raised);" in styles
    assert "overflow-wrap: anywhere;" in styles
    assert "notification-dismiss:focus-visible" in styles
