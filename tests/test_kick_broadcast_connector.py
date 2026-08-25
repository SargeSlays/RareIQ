from __future__ import annotations

import httpx

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.kick_broadcast_connector import KickBroadcastConnector
from rareiq.services.obs_service import ObsStreamRouteProbe


CLIENT_ID = "kick-client-id"
CLIENT_SECRET = "kick-client-secret"
REFRESH_TOKEN = "kick-refresh-token"
ROTATED_REFRESH_TOKEN = "kick-rotated-refresh-token"
ACCESS_TOKEN = "kick-access-token"
CHANNEL_SLUG = "rareiq-live"
USER_ID = 481516
STREAM_KEY = "kick-private-stream-key"
STREAM_URL = "rtmps://fa723fc1b171.global-contribute.live-video.net:443/app"


def connector_with(handler, *, clock=lambda: 1_000.0) -> KickBroadcastConnector:
    return KickBroadcastConnector(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        channel_slug=CHANNEL_SLUG,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def obs_route(
    *,
    stream_key: str = STREAM_KEY,
    stream_url: str = STREAM_URL,
    provider: str | None = "kick",
) -> ObsStreamRouteProbe:
    return ObsStreamRouteProbe(
        inspected=True,
        connected=True,
        verified_at=1_000.0,
        service_type="rtmp_custom",
        provider=provider,
        key_configured=True,
        _stream_key=stream_key,
        _server_url=stream_url,
    )


def kick_response(
    request: httpx.Request,
    *,
    live: bool = False,
    channel_slug: str = CHANNEL_SLUG,
    scopes: str = "user:read channel:read streamkey:read",
) -> httpx.Response:
    if request.url == httpx.URL(KickBroadcastConnector.TOKEN_URL):
        assert request.method == "POST"
        body = request.content.decode("utf-8")
        assert f"client_id={CLIENT_ID}" in body
        assert f"client_secret={CLIENT_SECRET}" in body
        assert f"refresh_token={REFRESH_TOKEN}" in body
        assert "grant_type=refresh_token" in body
        return httpx.Response(
            200,
            json={
                "access_token": ACCESS_TOKEN,
                "refresh_token": ROTATED_REFRESH_TOKEN,
                "expires_in": 3_600,
                "token_type": "Bearer",
            },
        )

    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    if request.url == httpx.URL(KickBroadcastConnector.INTROSPECT_URL):
        assert request.method == "POST"
        return httpx.Response(
            200,
            json={
                "data": {
                    "active": True,
                    "client_id": CLIENT_ID,
                    "token_type": "user",
                    "scope": scopes,
                    "exp": 4_600,
                },
                "message": "OK",
            },
        )
    if request.url == httpx.URL(KickBroadcastConnector.USERS_URL):
        assert not request.url.params
        return httpx.Response(
            200,
            json={"data": [{"user_id": USER_ID, "name": "RareIQ"}]},
        )
    if request.url == httpx.URL(KickBroadcastConnector.CHANNELS_URL):
        assert not request.url.params
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "broadcaster_user_id": USER_ID,
                        "slug": channel_slug,
                        "stream": {
                            "is_live": live,
                            "key": STREAM_KEY,
                            "url": STREAM_URL,
                        },
                    }
                ]
            },
        )
    raise AssertionError(f"Unexpected Kick request: {request.method} {request.url}")


def test_environment_factory_requires_complete_valid_configuration() -> None:
    assert KickBroadcastConnector.from_environment({}) is None
    assert KickBroadcastConnector.from_environment(
        {
            "RAREIQ_KICK_CLIENT_ID": CLIENT_ID,
            "RAREIQ_KICK_CLIENT_SECRET": CLIENT_SECRET,
            "RAREIQ_KICK_REFRESH_TOKEN": REFRESH_TOKEN,
        }
    ) is None
    assert KickBroadcastConnector.from_environment(
        {
            "RAREIQ_KICK_CLIENT_ID": CLIENT_ID,
            "RAREIQ_KICK_CLIENT_SECRET": CLIENT_SECRET,
            "RAREIQ_KICK_REFRESH_TOKEN": REFRESH_TOKEN,
            "RAREIQ_KICK_CHANNEL_SLUG": "Invalid Channel!",
        }
    ) is None


def test_cached_status_never_performs_network_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("cached_status must not call Kick")

    status = connector_with(handler).cached_status()

    assert requests == []
    assert status["verified"] is False
    assert status["connected"] is False


def test_authorized_channel_without_matching_obs_route_stays_connected() -> None:
    connector = connector_with(kick_response)

    status = connector.refresh(obs_route=obs_route(provider=None, stream_url=""))
    kick = BroadcastDestinationService(
        connectors={"kick": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": False})["destinations"][2]

    assert status["verified"] is True
    assert status["connected"] is True
    assert status["route_verified"] is False
    assert kick["state"] == "connected"
    assert kick["ready"] is False


def test_exact_server_and_key_make_destination_ready_without_secret_exposure() -> None:
    connector = connector_with(kick_response)
    connector.refresh(obs_route=obs_route())
    payload = BroadcastDestinationService(
        connectors={"kick": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": False})
    kick = payload["destinations"][2]
    serialized = repr(payload)

    assert kick["state"] == "ready"
    assert kick["ready"] is True
    assert kick["connector"]["route_verified"] is True
    for secret in (
        CLIENT_SECRET,
        REFRESH_TOKEN,
        ROTATED_REFRESH_TOKEN,
        ACCESS_TOKEN,
        STREAM_KEY,
        STREAM_URL,
    ):
        assert secret not in serialized


def test_partial_obs_route_matches_fail_closed() -> None:
    for route in (
        obs_route(stream_key="wrong-key"),
        obs_route(stream_url="rtmps://example.invalid/app"),
        obs_route(provider="youtube"),
    ):
        status = connector_with(kick_response).refresh(obs_route=route)
        assert status["connected"] is True
        assert status["route_verified"] is False


def test_live_requires_matching_route_and_obs_streaming() -> None:
    connector = connector_with(lambda request: kick_response(request, live=True))
    connector.refresh(obs_route=obs_route())
    service = BroadcastDestinationService(
        connectors={"kick": connector},
        clock=lambda: 1_005.0,
    )

    ready = service.snapshot(obs_status={"connected": True, "streaming": False})
    live = service.snapshot(obs_status={"connected": True, "streaming": True})

    assert ready["destinations"][2]["state"] == "ready"
    assert live["destinations"][2]["state"] == "live"
    assert live["routing"]["platform_live_verified"] is True


def test_channel_identity_mismatch_fails_before_route_verification() -> None:
    connector = connector_with(
        lambda request: kick_response(request, channel_slug="different-channel")
    )

    status = connector.refresh(obs_route=obs_route())

    assert status["verified"] is True
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["error_code"] == "channel_identity_mismatch"


def test_missing_streamkey_scope_fails_closed() -> None:
    connector = connector_with(
        lambda request: kick_response(request, scopes="user:read channel:read")
    )

    status = connector.refresh(obs_route=obs_route())

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False


def test_oauth_failure_fails_closed_without_secret_leakage() -> None:
    connector = connector_with(
        lambda request: httpx.Response(401, json={"error": "invalid_grant"})
    )
    status = connector.refresh(obs_route=obs_route())
    serialized = repr(status)

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    for secret in (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN, STREAM_KEY):
        assert secret not in serialized


def test_access_token_and_introspection_are_reused_until_expiry() -> None:
    now = [1_000.0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return kick_response(request)

    connector = connector_with(handler, clock=lambda: now[0])
    connector.refresh()
    now[0] += 30.0
    connector.refresh()

    assert sum(
        request.url == httpx.URL(KickBroadcastConnector.TOKEN_URL)
        for request in requests
    ) == 1
    assert sum(
        request.url == httpx.URL(KickBroadcastConnector.INTROSPECT_URL)
        for request in requests
    ) == 1


def test_malformed_api_payload_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(KickBroadcastConnector.CHANNELS_URL):
            return httpx.Response(200, json={"data": {"slug": CHANNEL_SLUG}})
        return kick_response(request)

    status = connector_with(handler).refresh(obs_route=obs_route())

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
