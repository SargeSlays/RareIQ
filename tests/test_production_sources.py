"""Local media definitions, retry durability and complete-output launch guards."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from rareiq.services.production_composition import validate_sources
from rareiq.services.production_source_store import ProductionSourceStore, ProductionSourceError
from rareiq.services.reaction_asset_service import ReactionAssetService
from rareiq.web import server
from rareiq.web.greenroom import GreenroomHub, Peer


MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42" + b"fixture"
WEBM = b"\x1a\x45\xdf\xa3\x8b\x42\x82\x84webm" + b"fixture"


@pytest.fixture
def library(tmp_path, monkeypatch):
    assets = ReactionAssetService(tmp_path / "assets", tmp_path / "assets.json")
    store = ProductionSourceStore(tmp_path / "sources.sqlite3")
    monkeypatch.setattr(server.orchestrator, "reaction_assets", assets)
    monkeypatch.setattr(server, "production_source_store", store)
    return assets, store


def test_video_import_is_bounded_kind_safe_and_retry_durable(library):
    assets, _ = library
    for name, mime, data in [("clip.mp4", "video/mp4", MP4), ("clip.webm", "video/webm", WEBM)]:
        result = assets.add(name, mime, data, request_id=name, actor_kind="local_operator")
        # Request identifiers deliberately forbid punctuation.
        assert result["reason"] == "invalid_asset_request_id"
        key = name.replace(".", "_")
        first = assets.add(name, mime, data, request_id=key, actor_kind="local_operator")["asset"]
        assert first["kind"] == "video" and "path" not in first and "import_actor_kind" not in first
        restored = ReactionAssetService(assets.root, assets.state_path)
        retry = restored.add(name, mime, data, request_id=key, actor_kind="local_operator")
        assert retry["replayed"] and retry["asset"]["id"] == first["id"]
        assert restored.add("changed", mime, data, request_id=key, actor_kind="local_operator")["reason"] == "asset_request_conflict"
        assert assets.map_tier("standard", "visual", first["id"])["reason"] == "asset_kind_mismatch"
        assert assets.add(name, mime, b"not media")["reason"] == "file_signature_mismatch"
        assert assets.ALLOWED[mime][2] == 64 * 1024 * 1024
    assert len(assets.snapshot()["assets"]) == 2
    assert assets.add("bad.mp4", "video/mp4", b"\xff\xff\xff\xffftypisom" + b"x" * 64)["reason"] == "file_signature_mismatch"


def test_text_definition_is_immutable_literal_and_concurrent_retry_safe(library):
    _, store = library
    payload = dict(name="Title", text="<script>literal</script>\nSecond line", position="lower-third", request_id="same", actor_kind="local_operator")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.create_text(**payload), range(4)))
    assert sum(not result["replayed"] for result in results) == 1
    source = results[0]["source"]
    assert source["text"] == payload["text"] and validate_sources([source["id"]])
    reopened = ProductionSourceStore(store.path)
    assert reopened.create_text(**payload)["source"] == source
    with pytest.raises(ProductionSourceError, match="source_request_conflict"):
        reopened.create_text(**{**payload, "text": "changed"})
    catalog = reopened.catalog()
    assert len(catalog) == 1 and "text" not in catalog[0] and "request_id" not in catalog[0]
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT actor_kind,request_id FROM production_sources").fetchall() == [("local_operator", "same")]


@pytest.mark.parametrize("change", [{"text": " "}, {"text": "x" * 1001}, {"text": "bad\x00"}, {"name": " "}, {"name": "x" * 81}, {"position": "arbitrary"}, {"request_id": "../bad"}, {"actor_kind": "guest"}])
def test_invalid_text_cannot_create_source(library, change):
    _, store = library
    with pytest.raises(ProductionSourceError):
        store.create_text(**{**dict(name="Title", text="Hello", position="top", request_id="request", actor_kind="local_operator"), **change})
    assert store.catalog() == []


@pytest.mark.parametrize("separator", ["\n", "\x85", "\u2028", "\u2029"])
def test_text_rejects_more_than_eight_lines_without_writing(library, separator):
    _, store = library
    payload = dict(name="Title", position="top", request_id="lines", actor_kind="local_operator")
    for text in [separator.join(["Line"] * 9), separator.join(["Line"] * 8) + separator]:
        with pytest.raises(ProductionSourceError, match="invalid_source_text_lines"):
            store.create_text(**payload, text=text)
        assert store.catalog() == []
    accepted = separator.join(["Line"] * 8)
    assert store.create_text(**payload, text=accepted)["source"]["text"] == accepted


def test_video_text_require_one_fresh_output_and_never_change_program_on_import(library, monkeypatch):
    assets, store = library
    video = "video:" + assets.add("clip.mp4", "video/mp4", MP4)["asset"]["id"]
    text = store.create_text(name="Title", text="Hello", position="center", request_id="text", actor_kind="local_operator")["source"]["id"]
    state = dict(program_slot=1, preview_slot=2, generation=0, transition="fade", duration_ms=500, program_sources=[], preview_sources=[video, text])
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server.vision_controller, "manual_override", lambda: None)
    service = SimpleNamespace(source_available=lambda source: False, record_production_event=lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "greenroom_service", service)
    hub = GreenroomHub(service, authorize_operator=lambda request: True, switcher=lambda: deepcopy(state), static_dir=Path("."), source_available=server._production_source_available)
    monkeypatch.setattr(server, "greenroom_hub", hub)
    assert {row["kind"] for row in server._production_sources()} == {"text", "video"}
    assert server._production_source_problem([video, text]) is None
    assert server._take_program_action({})["reason"] == "video_output_not_ready" and state["program_sources"] == []
    one, two = Peer(None, "output", subscriptions=(video, text)), Peer(None, "output", subscriptions=(video, text))
    hub.peers = {"one": one, "two": two}
    for key, peer, sources in [("one", one, [video]), ("two", two, [text])]:
        asyncio.run(hub._message(key, peer, {"type": "ready", "sources": sources}))
    assert not hub.composition_ready([video, text])
    assert not server._take_program_action({})["ok"]
    asyncio.run(hub._message("one", one, {"type": "ready", "sources": [video, text]}))
    assert server._take_program_action({})["ok"]
    assert state["program_sources"] == [video, text]
    assert not server._program_composition_readiness([], 1)["ready"]
    asyncio.run(hub._message("one", one, {"type": "ready", "sources": [video, text], "playback": {"generation": 1, "audio_blocked": False, "rendered": True}}))
    asyncio.run(hub._message("one", one, {"type": "rendered", "generation": 1}))
    assert server._program_composition_readiness([], 1)["ready"]
    one.ready[video] = time.monotonic() - 7
    assert server._production_source_problem([video], require_output=True)["reason"] == "video_output_not_ready"
    assert not server._production_source_available(video.replace("video:", "image:"))
    assert not server._production_source_available(text.replace("text:", "video:"))


def test_source_routes_are_bounded_retryable_and_keep_text_out_of_catalog(library):
    assets, _ = library
    client = TestClient(server.app, client=("127.0.0.1", 50000))
    body = dict(name="Caption", text="<b>literal</b>", position="top", request_id="caption")
    first = client.post("/api/production/sources/text", json=body)
    assert first.status_code == 200
    source = first.json()["source"]
    assert client.post("/api/production/sources/text", json=body).json()["replayed"]
    assert client.get(source["url"]).json()["source"]["text"] == body["text"]
    assert "text" not in client.get("/api/production/sources/text").json()["sources"][0]
    assert client.post("/api/production/sources/text", json={**body, "text": "changed"}).status_code == 409
    assert client.post("/api/production/sources/text", content=b"x", headers={"content-length": "16385"}).status_code == 413
    upload = {"content-type": "video/mp4", "x-rareiq-filename": "clip.mp4", "x-rareiq-request-id": "upload"}
    video = client.post("/api/creator/assets", content=MP4, headers=upload).json()
    assert video["ok"] and video["asset"]["kind"] == "video"
    assert client.post("/api/creator/assets", content=MP4, headers=upload).json()["replayed"]
    assert client.get(video["asset"]["url"]).content == MP4
    assert client.post("/api/creator/assets", content=b"x", headers={**upload, "content-length": str(64 * 1024 * 1024 + 1)}).status_code == 413
    assert len(assets.snapshot()["assets"]) == 1
    assert "local_operator" in assets.state_path.read_text()


@pytest.mark.parametrize("url", ["http://example.com", "https://user:password@example.com", "https://@example.com", "https://example.com:8443", "https://127.0.0.1", "https://[::1]", "https://2130706433", "https://0x7f000001", "https://127.1", "https://localhost", "https://x.local", "https://x.internal", "https://x.home", "https://x.lan", "https://x.test", "https://x.invalid", "https://x.onion", "https://x.arpa", "https://studio.example.com", "https://example.com\\@evil.com", "https://example.com\n", "https://%65xample.com", "https://example.com."])
def test_browser_initial_url_rejects_private_ambiguous_or_studio_addresses(library, url):
    _, store = library
    with pytest.raises(ProductionSourceError):
        store.create_browser(name="Page", target_url=url, request_id="browser", actor_kind="local_operator", studio_hostname="studio.example.com")
    assert store.catalog() == []


def test_browser_routes_preserve_definition_retry_and_catalog_privacy(library):
    _, store = library
    client = TestClient(server.app, base_url="http://studio.example.com", client=("127.0.0.1", 50000))
    payload = dict(name="Web page", target_url="https://EXAMPLE.com:443/widget?key=private#panel", request_id="browser")
    result = client.post("/api/production/sources/browser", json=payload)
    assert result.status_code == 200
    source = result.json()["source"]
    assert source["kind"] == "browser" and validate_sources([source["id"]])
    assert source["target_url"] == "https://example.com/widget?key=private#panel"
    assert client.post("/api/production/sources/browser", json=payload).json()["replayed"]
    assert client.get(source["url"]).json()["source"] == source
    assert "target_url" not in client.get("/api/production/sources/browser").json()["sources"][0]
    assert client.post("/api/production/sources/browser", json={**payload, "target_url": "https://other.example.com"}).status_code == 409
    assert client.post("/api/production/sources/browser", json={**payload, "target_url": "https://studio.example.com"}).json()["reason"] == "browser_studio_url_forbidden"
    assert ProductionSourceStore(store.path).get("browser", source["id"].split(":")[1]) == source
    assert server._production_source_available(source["id"])


def test_browser_take_requires_fresh_review_on_every_connected_output(library, monkeypatch):
    _, store = library
    source = store.create_browser(name="Page", target_url="https://example.com", request_id="browser", actor_kind="local_operator", studio_hostname="localhost")["source"]["id"]
    state = dict(program_slot=1, preview_slot=2, generation=0, transition="fade", duration_ms=500, program_sources=[], preview_sources=[source])
    monkeypatch.setattr(server, "PRODUCTION_SWITCHER_STATE", state)
    monkeypatch.setattr(server.orchestrator.camera_manager, "camera_slots", lambda: [])
    monkeypatch.setattr(server.vision_controller, "manual_override", lambda: None)
    service = SimpleNamespace(source_available=lambda source: False, record_production_event=lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "greenroom_service", service)
    hub = GreenroomHub(service, authorize_operator=lambda request: True, switcher=lambda: deepcopy(state), static_dir=Path("."), source_available=server._production_source_available)
    monkeypatch.setattr(server, "greenroom_hub", hub)
    one, two = Peer(None, "output", subscriptions=(source,)), Peer(None, "output", subscriptions=(source,))
    hub.peers = {"one": one, "two": two}
    assert not hub.source_ready(source)
    asyncio.run(hub._message("one", one, {"type": "ready", "sources": [source]}))
    assert not hub.source_ready(source) and not hub.composition_ready([source])
    assert server._take_program_action({})["reason"] == "browser_output_not_ready" and state["program_sources"] == []
    asyncio.run(hub._message("two", two, {"type": "ready", "sources": [source]}))
    assert hub.source_ready(source) and hub.composition_ready([source])
    assert server._take_program_action({})["ok"]
    two.ready[source] = time.monotonic() - 7
    assert not hub.source_ready(source) and not hub.composition_ready([source])
    del hub.peers["two"]
    assert hub.source_ready(source) and hub.composition_ready([source])
