from __future__ import annotations

import httpx

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.twitch_broadcast_connector import TwitchBroadcastConnector


CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
CHANNEL_LOGIN = "rareiqchannel"
TOKEN = "test-access-token"


def connector_with(handler, *, clock=lambda: 1_000.0) -> TwitchBroadcastConnector:
    return TwitchBroadcastConnector(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        channel_login=CHANNEL_LOGIN,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def twitch_response(request: httpx.Request, *, live: bool = False) -> httpx.Response:
    if request.url == httpx.URL(TwitchBroadcastConnector.TOKEN_URL):
        assert request.method == "POST"
        body = request.content.decode("utf-8")
        assert "grant_type=client_credentials" in body
        assert f"client_id={CLIENT_ID}" in body
        assert f"client_secret={CLIENT_SECRET}" in body
        return httpx.Response(
            200,
            json={"access_token": TOKEN, "expires_in": 7_200, "token_type": "bearer"},
        )
    if request.url == httpx.URL(TwitchBroadcastConnector.VALIDATE_URL):
        assert request.headers["Authorization"] == f"OAuth {TOKEN}"
        return httpx.Response(200, json={"client_id": CLIENT_ID, "expires_in": 7_200})
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["Client-Id"] == CLIENT_ID
    if request.url.path == "/helix/users":
        assert request.url.params["login"] == CHANNEL_LOGIN
        return httpx.Response(
            200,
            json={"data": [{"id": "123", "login": CHANNEL_LOGIN}]},
        )
    if request.url.path == "/helix/streams":
        assert request.url.params["user_id"] == "123"
        return httpx.Response(
            200,
            json={
                "data": (
                    [{"id": "stream-1", "user_id": "123", "type": "live"}]
                    if live
                    else []
                )
            },
        )
    raise AssertionError(f"Unexpected Twitch request: {request.url}")


def test_environment_factory_requires_complete_valid_configuration() -> None:
    assert TwitchBroadcastConnector.from_environment({}) is None
    assert TwitchBroadcastConnector.from_environment(
        {"RAREIQ_TWITCH_CLIENT_ID": CLIENT_ID}
    ) is None
    assert TwitchBroadcastConnector.from_environment(
        {
            "RAREIQ_TWITCH_CLIENT_ID": CLIENT_ID,
            "RAREIQ_TWITCH_CLIENT_SECRET": CLIENT_SECRET,
            "RAREIQ_TWITCH_CHANNEL_LOGIN": "invalid channel name",
        }
    ) is None


def test_cached_status_never_performs_network_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("cached_status must not call Twitch")

    connector = connector_with(handler)
    status = connector.cached_status()

    assert requests == []
    assert status["verified"] is False
    assert status["connected"] is False


def test_offline_channel_is_connected_but_never_route_verified() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return twitch_response(request, live=False)

    connector = connector_with(handler)
    status = connector.refresh()

    assert status == {
        "platform_id": "twitch",
        "verified": True,
        "verified_at": 1_000.0,
        "verification_source": "twitch.helix",
        "configured": True,
        "connected": True,
        "route_verified": False,
        "destination_ready": True,
        "platform_live": False,
        "error_code": None,
    }
    assert len(requests) == 4


def test_live_channel_does_not_claim_rareiq_route_or_live_output() -> None:
    connector = connector_with(lambda request: twitch_response(request, live=True))
    connector.refresh()
    payload = BroadcastDestinationService(
        connectors={"twitch": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": True})
    twitch = payload["destinations"][0]

    assert twitch["state"] == "connected"
    assert twitch["connected"] is True
    assert twitch["ready"] is False
    assert twitch["live"] is False
    assert twitch["connector"]["route_verified"] is False
    assert payload["routing"]["platform_live_verified"] is False


def test_token_is_reused_and_validated_hourly() -> None:
    now = [1_000.0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return twitch_response(request)

    connector = connector_with(handler, clock=lambda: now[0])
    connector.refresh()
    now[0] += 30.0
    connector.refresh()
    assert sum(request.url == httpx.URL(connector.TOKEN_URL) for request in requests) == 1
    assert sum(request.url == httpx.URL(connector.VALIDATE_URL) for request in requests) == 1

    now[0] += connector.TOKEN_VALIDATION_INTERVAL_SECONDS
    connector.refresh()
    assert sum(request.url == httpx.URL(connector.TOKEN_URL) for request in requests) == 1
    assert sum(request.url == httpx.URL(connector.VALIDATE_URL) for request in requests) == 2


def test_api_failure_fails_closed_and_does_not_expose_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(TwitchBroadcastConnector.TOKEN_URL):
            return httpx.Response(401, json={"message": "invalid client"})
        raise AssertionError("No Helix call should follow failed authentication")

    connector = connector_with(handler)
    status = connector.refresh()
    serialized = repr(status)

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False
    assert CLIENT_ID not in serialized
    assert CLIENT_SECRET not in serialized
    assert TOKEN not in serialized
    assert "client_secret" not in serialized.lower()
    assert "access_token" not in serialized.lower()


def test_missing_channel_is_a_verified_non_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/helix/users":
            return httpx.Response(200, json={"data": []})
        return twitch_response(request)

    status = connector_with(handler).refresh()

    assert status["verified"] is True
    assert status["connected"] is False
    assert status["platform_live"] is False
    assert status["error_code"] == "channel_not_found"


def test_connector_refresh_is_explicit_and_snapshot_remains_cached() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return twitch_response(request)

    connector = connector_with(handler)
    service = BroadcastDestinationService(
        connectors={"twitch": connector},
        clock=lambda: 1_005.0,
    )

    before = service.snapshot(obs_status={})
    assert requests == []
    assert before["destinations"][0]["state"] == "connector_error"

    assert service.refresh_connectors() == {"twitch": True}
    after = service.snapshot(obs_status={})
    assert len(requests) == 4
    assert after["destinations"][0]["state"] == "connected"
