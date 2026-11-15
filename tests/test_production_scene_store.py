from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from rareiq.services.production_scene_store import ProductionSceneStore


@pytest.fixture
def store(tmp_path):
    legacy = tmp_path / "production_scenes.json"
    legacy.write_text(json.dumps([{"id": "one", "name": "Original", "program_slot": 1}]))
    return ProductionSceneStore(tmp_path / "scenes.sqlite3", legacy, [])


def edit(store, request_id="first", revision=0, **kwargs):
    return store.edit(action="save", target="one", scene={"name": "Changed", "program_slot": 2},
                      expected_revision=revision, request_id=request_id, actor_kind="local_operator", **kwargs)


def test_restart_migration_and_retries_do_not_duplicate_success(store):
    original = store.legacy_path.read_bytes()
    first = edit(store)
    assert first["revision"] == 1
    restarted = ProductionSceneStore(store.path, store.legacy_path, [])
    assert edit(restarted) == first
    assert restarted.snapshot()["scenes"][0]["program_slot"] == 2
    assert len(restarted.history()["events"]) == 1
    assert store.legacy_path.read_bytes() == original


def test_two_writers_cannot_overwrite_the_same_revision(store):
    store.snapshot()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda key: edit(store, request_id=key), ["alice-device", "bob-device"]))
    assert sum(result["ok"] for result in results) == 1
    assert {row["outcome"] for row in store.history()["events"]} == {"succeeded", "scene_revision_conflict"}
    assert store.snapshot()["revision"] == 1


def test_request_id_reuse_with_different_parameters_is_rejected(store):
    edit(store)
    result = edit(store, revision=1)
    assert result["reason"] == "scene_request_conflict"
    assert store.snapshot()["revision"] == 1


def test_history_failure_rolls_back_scene_and_request(store):
    before = store.snapshot()
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER reject_activity BEFORE INSERT ON scene_activity BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    with pytest.raises(sqlite3.IntegrityError):
        edit(store)
    assert store.snapshot() == before
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM scene_requests").fetchone()[0] == 0


def test_activity_is_append_only_and_does_not_copy_free_text(store):
    edit(store)
    event = store.history()["events"][0]
    assert event["identity_verified"] is False
    assert event["changes"]["program_slot"] == {"before": 1, "after": 2}
    assert event["changes"]["name"] == {"changed": True}
    assert "Changed" not in json.dumps(event)
    with sqlite3.connect(store.path) as db:
        for sql in ["DELETE FROM scene_activity", "UPDATE scene_activity SET actor_kind='someone-else'"]:
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                db.execute(sql)


def test_delete_conflict_retry_and_history_pagination(store):
    edit(store)
    args = dict(action="delete", target="one", scene=None, actor_kind="paired_lan_operator")
    assert store.edit(**args, expected_revision=0, request_id="stale")["reason"] == "scene_revision_conflict"
    success = store.edit(**args, expected_revision=1, request_id="delete")
    assert success["ok"] and store.snapshot()["scenes"] == []
    assert store.edit(**args, expected_revision=1, request_id="delete") == success
    page = store.history(limit=2)
    older = store.history(before_id=page["next_before_id"], limit=2)
    assert len(page["events"]) == 2 and len(older["events"]) == 1
    assert not older["next_before_id"]


def test_corrupt_migration_is_not_silently_replaced_with_defaults(store):
    store.legacy_path.write_text("not json")
    with pytest.raises(ValueError):
        store.snapshot()


def test_request_receipts_do_not_archive_scene_free_text(store):
    edit(store)
    with sqlite3.connect(store.path) as db:
        receipt = db.execute("SELECT result FROM scene_requests").fetchone()[0]
    assert "Original" not in receipt and "Changed" not in receipt and "scenes" not in receipt


def test_routes_require_revision_and_reject_forged_actor(store, monkeypatch):
    from rareiq.web import server
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server, "PRODUCTION_SCENES", [])
    client = TestClient(server.app, client=("127.0.0.1", 50000))
    try:
        assert client.post('/api/production/scenes', json={"name": "No revision"}).status_code == 422
        assert client.delete('/api/production/scenes/one').status_code == 422
        payload = {"id": "one", "name": "Updated", "expected_revision": 0, "request_id": "http-save"}
        assert client.post('/api/production/scenes', json=payload | {"actor": "owner"}).status_code == 422
        assert client.post('/api/production/scenes', json=payload).status_code == 200
        assert client.post('/api/production/scenes', json=payload | {"request_id": "stale-http"}).status_code == 409
        events = client.get('/api/production/scenes/activity').json()["events"]
        assert len(events) == 2
        assert all(e["actor_kind"] == "local_operator" and not e["identity_verified"] for e in events)
        assert client.get('/api/production/scenes/activity?limit=999').status_code == 400
    finally:
        client.close()


def test_unpaired_remote_cannot_read_history(store, monkeypatch):
    from rareiq.web import server
    from rareiq.web.remote_access import RemoteAccessPolicy
    monkeypatch.setattr(server, "production_scene_store", store)
    monkeypatch.setattr(server, "REMOTE_ACCESS", RemoteAccessPolicy(False, "fixture", ""))
    client = TestClient(server.app, client=("192.0.2.1", 50000))
    try:
        assert client.get('/api/production/scenes/activity').status_code == 401
    finally:
        client.close()
