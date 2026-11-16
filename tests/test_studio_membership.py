"""Isolated account-mode contracts; no real identity provider or hardware."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from rareiq.services.production_scene_store import ProductionSceneStore
from rareiq.web.shared_scene_access import SharedScenePolicy, VerifiedPrincipal


def account(subject):
    return VerifiedPrincipal("fixture-provider", "fixture-studio", subject)


OWNER, EDITOR, VIEWER, STRANGER = map(account, ("owner", "editor", "viewer", "stranger"))


@pytest.fixture
def store(tmp_path):
    result = ProductionSceneStore(tmp_path / "scenes.sqlite3", tmp_path / "legacy.json", [])
    result.bootstrap_owner(OWNER)
    result.set_member(OWNER, EDITOR, "editor", 1)
    result.set_member(OWNER, VIEWER, "viewer", 2)
    return result


def save(store, actor=EDITOR, request_id="save", revision=0):
    return store.edit(action="save", target="scene-one", scene={"name": "Private name", "program_slot": 2},
                      expected_revision=revision, request_id=request_id,
                      actor_kind="local_operator", principal=actor)


def test_permissions_and_scoped_retry_receipts(store):
    for person in (VIEWER, STRANGER):
        with pytest.raises(PermissionError):
            save(store, person)
    first = save(store)
    assert save(store) == first
    # Another editor using the same ID gets a real conflict, never the first receipt.
    assert save(store, OWNER)["reason"] == "scene_revision_conflict"
    event = next(e for e in store.history(principal=VIEWER)["events"] if e["outcome"] == "succeeded" and e["action"] == "scene.save")
    assert event["actor_identity"] == [EDITOR.provider, EDITOR.app_id, EDITOR.subject]
    assert event["identity_verified"] and event["actor_kind"] == "verified_account"
    assert "Private name" not in json.dumps(event)
    for read in (store.snapshot, store.history):
        with pytest.raises(PermissionError):
            read(principal=STRANGER)


@pytest.mark.parametrize("new_role", ["viewer", None])
def test_current_membership_checked_before_receipt_replay(store, new_role):
    save(store)
    store.set_member(OWNER, EDITOR, new_role, 3)
    with pytest.raises(PermissionError):
        save(store)
    assert store.snapshot()["revision"] == 1


def test_owner_administration_is_revisioned_and_protects_last_owner(store):
    with pytest.raises(PermissionError):
        store.set_member(EDITOR, STRANGER, "owner", 3)
    with pytest.raises(ValueError, match="last_studio_owner"):
        store.set_member(OWNER, OWNER, None, 3)
    with pytest.raises(ValueError, match="revision_conflict"):
        store.set_member(OWNER, STRANGER, "editor", 2)
    with pytest.raises(ValueError, match="app_mismatch"):
        store.set_member(OWNER, VerifiedPrincipal("fixture-provider", "other-app", "owner"), "owner", 3)
    with pytest.raises(ValueError, match="already_initialized"):
        store.bootstrap_owner(STRANGER)
    assert store.membership(OWNER)["revision"] == 3
    assert store.set_member(OWNER, EDITOR, "editor", 3)["revision"] == 3


def test_membership_and_activity_rollback_together(store):
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER reject_membership BEFORE INSERT ON scene_activity BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.set_member(OWNER, EDITOR, None, 3)
    assert store.membership(OWNER)["revision"] == 3
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT role FROM studio_members WHERE identity=?", (store._identity(EDITOR),)).fetchone()[0] == "editor"


def test_concurrent_verified_writers_have_separate_authoritative_history(store):
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda actor: save(store, actor), (OWNER, EDITOR)))
    assert sum(r["ok"] for r in results) == 1
    events = [e for e in store.history(principal=OWNER)["events"] if e["action"] == "scene.save"]
    assert {e["actor_identity"][2] for e in events} == {"owner", "editor"}


def test_legacy_history_and_receipts_survive_identity_schema_migration(tmp_path):
    store = ProductionSceneStore(tmp_path / "old.sqlite3", tmp_path / "legacy.json", [])
    args = dict(action="save", target="old", scene={"name": "Old"}, expected_revision=0,
                request_id="old-save", actor_kind="local_operator")
    first = store.edit(**args)
    with sqlite3.connect(store.path) as db:
        db.execute("ALTER TABLE scene_activity DROP COLUMN actor_identity")
    restarted = ProductionSceneStore(store.path, store.legacy_path, [])
    assert restarted.edit(**args) == first
    assert restarted.history()["events"][0]["identity_verified"] is False
    assert restarted.history()["events"][0]["actor_identity"] is None


@pytest.fixture
def client(store, monkeypatch):
    from rareiq.web import server
    calls = []

    async def verify(token):
        calls.append(token)
        if token == "unavailable":
            raise RuntimeError("private provider detail")
        return {"owner": OWNER, "editor": EDITOR, "viewer": VIEWER, "stranger": STRANGER}.get(token)

    monkeypatch.setattr(server, "SHARED_SCENE_ACCESS", SharedScenePolicy(True, verify))
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [])
    # No context manager: deliberately do not start app lifespan/hardware.
    result = TestClient(server.app, client=("127.0.0.1", 51000))
    yield result, calls
    result.close()


def auth(person):
    return {"Authorization": "Bearer " + person}


def test_real_routes_enforce_identity_membership_and_revalidation(client, store):
    http, calls = client
    url = "/api/production/scenes"
    payload = {"id": "scene-one", "name": "Shared", "expected_revision": 0, "request_id": "route-save"}
    assert http.get(url).status_code == 401
    assert http.get(url, headers=auth("stranger")).status_code == 403
    assert http.get(url, headers=auth("viewer")).status_code == 200
    assert http.post(url, headers=auth("viewer"), json=payload).status_code == 403
    assert http.post(url, headers=auth("editor"), json=payload | {"actor": "owner"}).status_code == 422
    assert http.post(url, headers=auth("editor"), json=payload).status_code == 200
    assert http.post(url, headers=auth("editor"), json=payload).status_code == 200
    store.set_member(OWNER, EDITOR, "viewer", 3)
    assert http.post(url, headers=auth("editor"), json=payload).status_code == 403
    assert http.get(url, headers=auth("unavailable")).status_code == 503
    assert http.get(url, headers=auth("invalid")).status_code == 401
    history = http.get(url + "/activity", headers=auth("owner"))
    assert history.headers["cache-control"] == "no-store"
    assert any(e["identity_verified"] and e["actor_identity"][2] == "editor" for e in history.json()["events"])
    assert calls.count("editor") == 4


def test_policy_change_during_verification_does_not_drop_member_permissions(client, monkeypatch):
    from rareiq.web import server
    http, _ = client

    async def verify_and_disable(token):
        monkeypatch.setattr(server, "SHARED_SCENE_ACCESS", SharedScenePolicy())
        return VIEWER

    monkeypatch.setattr(server, "SHARED_SCENE_ACCESS", SharedScenePolicy(True, verify_and_disable))
    response = http.post("/api/production/scenes", headers=auth("viewer"),
                         json={"name": "Forbidden", "expected_revision": 0, "request_id": "policy-change"})
    assert response.status_code == 403


def test_remote_verified_member_needs_no_shared_pairing_cookie(client):
    from rareiq.web import server
    remote = TestClient(server.app, client=("192.0.2.10", 51000))
    try:
        assert remote.get("/api/production/scenes", headers=auth("viewer")).status_code == 200
        assert remote.delete("/api/production/scenes/scene-one?expected_revision=0&request_id=delete",
                             headers=auth("viewer")).status_code == 403
    finally:
        remote.close()


@pytest.mark.parametrize("method,path", [
    ("get", "/control"), ("get", "/static/control.html"), ("get", "/remote-access"),
    ("get", "/api/production/session"), ("post", "/api/production/switcher/take"),
    ("post", "/api/production/scenes/scene-one/take"), ("post", "/api/production/session/start"),
    ("get", "/api/boot/ping"), ("get", "/docs"), ("get", "/openapi.json"),
])
def test_legacy_routes_never_reach_handlers_in_account_mode(client, method, path):
    http, calls = client
    assert getattr(http, method)(path, headers=auth("owner")).status_code == 403
    assert calls == []


@pytest.mark.parametrize("path", ["/ws", "/ws/output/camera/1"])
def test_real_socket_routes_are_closed_before_hardware(client, path):
    http, _ = client
    with pytest.raises(WebSocketDisconnect) as error:
        with http.websocket_connect(path, headers=auth("owner")):
            pytest.fail("socket accepted")
    assert error.value.code == 1008


def test_stackthis_adapter_to_real_routes_uses_membership_not_purchase_source(tmp_path, monkeypatch):
    from rareiq.web import server
    from rareiq.services.stackthis_identity import StackThisSessionVerifier
    owner = VerifiedPrincipal("stackthis", "producer-please", "fixture-owner")
    viewer = VerifiedPrincipal("stackthis", "producer-please", "fixture-viewer")
    store = ProductionSceneStore(tmp_path / "integrated.sqlite3", tmp_path / "legacy.json", [])
    store.bootstrap_owner(owner)
    store.set_member(owner, viewer, "viewer", 1)
    revoked = False

    class Body(httpx.AsyncByteStream):
        def __init__(self, payload):
            self.payload = payload

        async def __aiter__(self):
            yield json.dumps(self.payload).encode()

    def provider(request):
        subject = owner.subject if request.headers["authorization"] == "Bearer " + "a" * 64 else viewer.subject
        payload = {"allowed": True, "appId": "producer-please", "subject": subject,
                   "source": "purchase", "checkedAt": datetime.now(timezone.utc).isoformat()}
        return httpx.Response(401 if revoked else 200, headers={"content-type": "application/json"}, stream=Body(payload))

    verifier = StackThisSessionVerifier(transport=httpx.MockTransport(provider))
    monkeypatch.setattr(server, "SHARED_SCENE_ACCESS", SharedScenePolicy(True, verifier))
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [])
    http = TestClient(server.app, client=("192.0.2.10", 51000))
    try:
        payload = {"name": "Fixture scene", "expected_revision": 0, "request_id": "integrated"}
        assert http.post("/api/production/scenes", headers=auth("b" * 64), json=payload).status_code == 403
        assert http.post("/api/production/scenes", headers=auth("a" * 64), json=payload).status_code == 200
        event = store.history(principal=owner)["events"][0]
        assert event["identity_verified"] and event["actor_identity"][2] == owner.subject
        revoked = True
        assert http.post("/api/production/scenes", headers=auth("a" * 64), json=payload).status_code == 401
        assert store.snapshot()["revision"] == 1
    finally:
        http.close()
