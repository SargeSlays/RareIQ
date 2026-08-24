from __future__ import annotations

from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

from rareiq.web import server
from rareiq.web.remote_access import (
    REMOTE_ACCESS_COOKIE,
    RemoteAccessConfigurationError,
    RemoteAccessPolicy,
    validate_server_binding,
)


TOKEN = "mobile-pairing-token-with-ample-entropy"


def _enabled_policy(session_id: str = "session-one") -> RemoteAccessPolicy:
    return RemoteAccessPolicy.from_environment(
        session_id,
        environment={
            "RAREIQ_REMOTE_ACCESS": "1",
            "RAREIQ_REMOTE_ACCESS_TOKEN": TOKEN,
        },
    )


def test_remote_access_is_disabled_and_loopback_only_by_default() -> None:
    policy = RemoteAccessPolicy.from_environment("session", environment={})

    assert policy.enabled is False
    assert policy.authorizes("192.168.1.20", None) is False
    assert validate_server_binding("127.0.0.1", policy) == "127.0.0.1"
    with pytest.raises(RemoteAccessConfigurationError, match="explicit authenticated"):
        validate_server_binding("0.0.0.0", policy)


def test_remote_access_requires_a_long_secret_token() -> None:
    with pytest.raises(RemoteAccessConfigurationError, match="at least 24"):
        RemoteAccessPolicy.from_environment(
            "session",
            environment={
                "RAREIQ_REMOTE_ACCESS": "1",
                "RAREIQ_REMOTE_ACCESS_TOKEN": "too-short",
            },
        )


def test_pairing_cookie_is_constant_time_verified_and_process_scoped() -> None:
    first = _enabled_policy("session-one")
    second = _enabled_policy("session-two")

    assert first.verify_pairing_token(TOKEN) is True
    assert first.verify_pairing_token("wrong-token") is False
    assert first.authorizes("192.168.1.20", None) is False
    assert first.authorizes("192.168.1.20", first.cookie_value) is True
    assert first.authorizes("127.0.0.1", None) is True
    assert first.cookie_value != second.cookie_value
    assert second.authorizes("192.168.1.20", first.cookie_value) is False


def test_remote_browser_must_pair_before_control_access(monkeypatch) -> None:
    policy = _enabled_policy()
    monkeypatch.setattr(server, "REMOTE_ACCESS", policy)
    client = TestClient(
        server.app,
        raise_server_exceptions=False,
        client=("192.168.1.20", 50000),
    )

    blocked = client.get("/control", headers={"Accept": "text/html"}, follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/remote-access"

    login = client.get("/remote-access")
    assert login.status_code == 200
    assert "Pair this device" in login.text
    assert TOKEN not in login.text

    rejected = client.post(
        "/remote-access",
        data={"token": "wrong-token"},
        follow_redirects=False,
    )
    assert rejected.status_code == 401
    assert REMOTE_ACCESS_COOKIE not in rejected.cookies

    paired = client.post(
        "/remote-access",
        data={"token": TOKEN},
        follow_redirects=False,
    )
    assert paired.status_code == 303
    assert paired.headers["location"] == "/control"
    assert paired.cookies.get(REMOTE_ACCESS_COOKIE) == policy.cookie_value
    assert "HttpOnly" in paired.headers["set-cookie"]
    assert "SameSite=strict" in paired.headers["set-cookie"]

    status = client.get("/api/remote-access/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True
    assert status.json()["paired"] is True


def test_direct_asgi_remote_exposure_still_fails_closed_when_feature_is_disabled(monkeypatch) -> None:
    policy = RemoteAccessPolicy.from_environment("session", environment={})
    monkeypatch.setattr(server, "REMOTE_ACCESS", policy)
    client = TestClient(
        server.app,
        raise_server_exceptions=False,
        client=("192.168.1.20", 50000),
    )

    response = client.get("/api/remote-access/status")

    assert response.status_code == 401
    assert response.json()["reason"] == "remote_pairing_required"


def test_query_tokens_cannot_authorize_remote_api_or_websocket(monkeypatch) -> None:
    policy = _enabled_policy()
    monkeypatch.setattr(server, "REMOTE_ACCESS", policy)
    client = TestClient(
        server.app,
        raise_server_exceptions=False,
        client=("192.168.1.20", 50000),
    )

    response = client.get(f"/api/remote-access/status?token={TOKEN}")

    assert response.status_code == 401
    assert response.json()["reason"] == "remote_pairing_required"
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect(f"/ws?token={TOKEN}"):
            pass
    assert disconnected.value.code == 4401
