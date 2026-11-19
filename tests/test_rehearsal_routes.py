"""Actual HTTP contract and private operator boundaries; no live output."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.rehearsal_service import RehearsalService
from rareiq.web.rehearsal import create_rehearsal_router


BASE = "http://127.0.0.1:8765"
HEADERS = {"Origin": BASE}
ROOT = "/api/production/rehearsal"


def fixture(tmp_path, *, host="127.0.0.1", operator=True):
    room = RehearsalService(tmp_path / "state.json", idle_provider=lambda: {"ready": True})
    app = FastAPI()
    app.include_router(create_rehearsal_router(room, lambda _: operator))
    return TestClient(app, base_url=BASE, client=(host, 12345)), room


def test_actual_http_enter_mark_exit_and_guest_privacy(tmp_path):
    client, room = fixture(tmp_path)
    state = client.get(ROOT).json()["room"]
    entered = client.post(ROOT + "/enter", json={"request_id": "enter-1", "expected_revision": state["revision"]}, headers=HEADERS)
    assert entered.status_code == 200
    state = entered.json()["room"]
    public = client.get("/api/guest/rehearsal").json()
    assert set(public) == {"active", "label", "mode", "generation"}
    assert public["active"] and public["label"] == "Rehearsal"
    payload = {"request_id": "mark-1", "expected_revision": state["revision"], "generation": state["generation"], "check_id": "video", "status": "passed"}
    marked = client.post(ROOT + "/mark", json=payload, headers=HEADERS)
    assert marked.status_code == 200
    assert client.post(ROOT + "/mark", json=payload, headers=HEADERS).json() == marked.json()
    state = marked.json()["room"]
    exited = client.post(ROOT + "/exit", json={"request_id": "exit-1", "expected_revision": state["revision"], "generation": state["generation"]}, headers=HEADERS)
    assert exited.status_code == 200 and room.publishing_allowed()
    assert client.get("/api/guest/rehearsal").json()["label"] == "Production"


@pytest.mark.parametrize("case", ["remote", "host", "operator", "origin", "foreign_origin", "duplicate_origin", "duplicate_host", "fetch_site"])
def test_private_commands_reject_untrusted_boundary_before_mutation(tmp_path, case):
    client, room = fixture(tmp_path, host="10.1.2.3" if case == "remote" else "127.0.0.1", operator=case != "operator")
    headers = list(HEADERS.items())
    if case == "origin":
        headers = []
    if case == "foreign_origin":
        headers = [("Origin", "https://foreign.invalid")]
    if case == "duplicate_origin":
        headers.append(("Origin", BASE))
    if case == "host":
        headers.append(("Host", "foreign.invalid"))
    if case == "duplicate_host":
        headers.extend([("Host", "127.0.0.1:8765"), ("Host", "127.0.0.1:8765")])
    if case == "fetch_site":
        headers.append(("Sec-Fetch-Site", "cross-site"))
    result = client.post(ROOT + "/enter", json={"request_id": "enter-1", "expected_revision": 0}, headers=headers)
    assert result.status_code == 403
    assert room.snapshot()["revision"] == 0 and not room.path.exists()
    assert client.get("/api/guest/rehearsal").status_code == 200


@pytest.mark.parametrize("case", ["content_type", "oversized", "extra", "duplicate", "boolean_revision", "missing", "array", "nan"])
def test_commands_require_strict_bounded_json(tmp_path, case):
    client, room = fixture(tmp_path)
    headers = {**HEADERS, "Content-Type": "application/json"}
    value = '{"request_id":"enter-1","expected_revision":0}'
    if case == "content_type":
        headers["Content-Type"] = "text/plain"
    elif case == "oversized":
        value = " " * 1025
    elif case == "extra":
        value = '{"request_id":"enter-1","expected_revision":0,"private_note":"not accepted"}'
    elif case == "duplicate":
        value = '{"request_id":"enter-1","request_id":"enter-2","expected_revision":0}'
    elif case == "boolean_revision":
        value = '{"request_id":"enter-1","expected_revision":false}'
    elif case == "missing":
        value = '{"request_id":"enter-1"}'
    elif case == "array":
        value = "[]"
    elif case == "nan":
        value = '{"request_id":"enter-1","expected_revision":NaN}'
    assert client.post(ROOT + "/enter", content=value, headers=headers).status_code == 400
    assert room.snapshot()["revision"] == 0


def test_recover_requires_explicit_true_confirmation_and_preserves_file(tmp_path):
    client, room = fixture(tmp_path)
    room.path.write_bytes(b"broken original")
    state = client.get(ROOT).json()["room"]
    assert state["mode"] == "recovery_required"
    payload = {"request_id": "recover-1", "expected_revision": state["revision"], "generation": state["generation"]}
    for confirmation in (None, False, "true", 1):
        command = dict(payload)
        if confirmation is not None:
            command["confirm_recovery"] = confirmation
        assert client.post(ROOT + "/recover", json=command, headers=HEADERS).status_code == 400
        assert room.path.read_bytes() == b"broken original"
    result = client.post(ROOT + "/recover", json={**payload, "confirm_recovery": True}, headers=HEADERS)
    assert result.status_code == 200 and result.json()["room"]["publishing_allowed"]
    assert list(tmp_path.glob(".rehearsal-state-corrupt-*"))[0].read_bytes() == b"broken original"


def test_private_status_requires_operator_and_public_failure_stays_marked(tmp_path):
    client, room = fixture(tmp_path, operator=False)
    assert client.get(ROOT).status_code == 403
    def fail():
        raise RuntimeError("private machine details")
    room.snapshot = fail
    result = client.get("/api/guest/rehearsal")
    assert result.status_code == 503 and result.json() == {"active": True, "label": "Rehearsal", "mode": "recovery_required", "generation": None}
