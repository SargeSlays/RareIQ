"""Read-only full-app boundary checks; no lifespan, credentials or provider calls."""
from fastapi.testclient import TestClient

from rareiq.services.audience_service import AudienceService
from rareiq.web import server
from rareiq.web.greenroom import PUBLIC_GUEST_PATHS


def test_combined_status_never_activates_credentials_or_public_receiver(monkeypatch, tmp_path):
    def forbidden():
        raise AssertionError("Status read accessed host authorization")
    for connector in (server.twitch_audience_connector, server.youtube_audience_connector,
                      server.kick_audience_connector):
        monkeypatch.setattr(connector, "_credentials_provider", forbidden)
    # The route holds its own service object; replace its read method without touching local data.
    isolated = AudienceService(tmp_path / "audience.sqlite3")
    monkeypatch.setattr(server.audience_service, "status", isolated.status)
    client = TestClient(server.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234))
    response = client.get("/api/production/audience")
    assert response.status_code == 200
    sources = response.json()["sources"]
    assert {row["platform"] for row in sources} == {"twitch", "youtube", "kick"}
    assert all(row["implemented"] and not row["connected"] and not row["available_events"] for row in sources)
    for platform in ("twitch", "youtube", "kick"):
        assert client.get("/api/production/audience/" + platform).status_code == 200
        assert client.post("/api/production/audience/" + platform + "/connect", json={}).status_code == 403
    path = server.kick_audience_connector.CALLBACK_PATH
    assert path not in PUBLIC_GUEST_PATHS
    assert all(getattr(route, "path", None) != path for route in server.app.routes)
    assert client.post(path, json={}).status_code == 404


def test_kick_connection_stays_inactive_without_registration(monkeypatch):
    def forbidden():
        raise AssertionError("Unapproved registration accessed credentials")
    monkeypatch.setattr(server.kick_audience_connector, "_credentials_provider", forbidden)
    client = TestClient(server.app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1234))
    response = client.post("/api/production/audience/kick/connect", json={}, headers={"Origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert not response.json()["connected"]
    assert response.json()["reason"] == "dashboard_registration_approval_required"
