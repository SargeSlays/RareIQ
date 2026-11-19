"""Local operator boundaries and redaction for the volatile viewer transcript."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from rareiq.services.viewer_chat_service import MAX_CURSOR, ViewerChatService
from rareiq.web.viewer_chat import create_viewer_chat_router


ORIGIN = "http://127.0.0.1:8765"


def fixture(*, host="127.0.0.1", origin=ORIGIN, authorized=True, sources=None):
    service = ViewerChatService()
    app = FastAPI()
    app.include_router(create_viewer_chat_router(service, lambda request: authorized,
                                                sources_provider=sources))
    return service, TestClient(app, base_url=origin, client=(host, 1234))


@pytest.mark.parametrize("options", [
    {"host": "198.51.100.4"}, {"origin": "http://evil.example:8765"}, {"authorized": False},
])
def test_both_routes_require_local_client_local_host_and_operator(options):
    service, client = fixture(**options)
    assert client.get("/api/production/viewer-chat").status_code == 403
    assert client.post("/api/production/viewer-chat/listening", json={"enabled": True},
                       headers={"Origin": ORIGIN}).status_code == 403
    assert not service.active


def test_status_is_read_only_redacts_sources_and_exposes_no_provider_history():
    calls = []
    def sources():
        calls.append(True)
        return [{"platform": "twitch", "state": "connected", "reason": "observing_chat",
                 "connected": True, "authorized": True, "verified": True, "implemented": True,
                 "channel_id": "private-channel", "token": "private-token", "history": ["private-text"]},
                {"platform": "youtube", "state": "reconnecting", "reason": "private-provider-error",
                 "poll_interval_seconds": 15, "retry_after_seconds": 60},
                {"platform": "kick", "state": "not_connected", "reason": "dashboard_registration_approval_required",
                 "dashboard_registration_approved": False}]
    service, client = fixture(sources=sources)
    response = client.get("/api/production/viewer-chat")
    data = response.json()
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert not service.active and len(calls) == 1
    assert data["sources"][0]["connected"]
    assert data["sources"][1]["reason"] == "source_status_unavailable"
    assert data["sources"][1]["poll_interval_seconds"] == 15
    assert data["sources"][2]["state"] == "not_connected"
    assert data["sources"][2]["dashboard_registration_approved"] is False
    assert "private" not in json.dumps(data)
    enabled = client.post("/api/production/viewer-chat/listening", json={"enabled": True},
                          headers={"Origin": ORIGIN}).json()
    assert enabled["active"] and enabled["session_id"] != data["session_id"]
    assert client.get("/api/production/viewer-chat", params={"after": enabled["cursor"],
                       "session_id": enabled["session_id"]}).json()["reset"] is False


@pytest.mark.parametrize("query", [
    "after=-1", "after=true", "after=1.2", f"after={MAX_CURSOR + 1}", "after=0&after=1",
    "after=" + "1" * 500, "session_id=bad", "secret=private",
])
def test_malformed_or_ambiguous_query_has_bounded_safe_error(query):
    _, client = fixture()
    response = client.get("/api/production/viewer-chat?" + query)
    assert response.status_code == 400 and "private" not in response.text


@pytest.mark.parametrize("headers", [{}, {"Origin": "http://evil.example"},
    {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    {"Origin": ORIGIN, "Content-Type": "text/plain"}])
def test_listening_requires_same_origin_json(headers):
    service, client = fixture()
    assert client.post("/api/production/viewer-chat/listening", json={"enabled": True},
                       headers=headers).status_code == 403
    assert not service.active


@pytest.mark.parametrize("body", [{}, {"enabled": 1}, {"enabled": "true"},
    {"enabled": True, "token": "private"}, [True], "x" * 200])
def test_listening_rejects_nonboolean_extra_or_oversized_data(body):
    service, client = fixture()
    response = client.post("/api/production/viewer-chat/listening", json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 400 and not service.active
    assert "private" not in response.text


def test_source_faults_fail_closed_without_losing_transcript_controls():
    def failed():
        raise RuntimeError("private exception")
    service, client = fixture(sources=failed)
    response = client.post("/api/production/viewer-chat/listening", json={"enabled": True},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200 and service.active
    assert all(source["state"] == "unavailable" for source in response.json()["sources"])
    assert "private" not in response.text


def test_activity_history_failure_prevents_listening_change():
    service = ViewerChatService()
    app = FastAPI()
    def blocked(**entry):
        raise RuntimeError("private database failure")
    app.include_router(create_viewer_chat_router(service, lambda request: True, audit=blocked))
    client = TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 1234))
    response = client.post("/api/production/viewer-chat/listening", json={"enabled": True}, headers={"Origin": ORIGIN})
    assert response.status_code == 503 and not service.active
    assert response.json()["reason"] == "activity_history_unavailable"
    assert "private" not in response.text
