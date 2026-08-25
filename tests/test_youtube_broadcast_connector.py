from __future__ import annotations

import httpx

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.obs_service import ObsStreamRouteProbe
from rareiq.services.youtube_broadcast_connector import YouTubeBroadcastConnector


CLIENT_ID = "youtube-client-id"
CLIENT_SECRET = "youtube-client-secret"
REFRESH_TOKEN = "youtube-refresh-token"
ACCESS_TOKEN = "youtube-access-token"
CHANNEL_ID = "UC1234567890123456789012"
STREAM_NAME = "abcd-efgh-ijkl-mnop"


def connector_with(handler, *, clock=lambda: 1_000.0) -> YouTubeBroadcastConnector:
    return YouTubeBroadcastConnector(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        channel_id=CHANNEL_ID,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def obs_route(
    stream_name: str = STREAM_NAME,
    *,
    provider: str | None = "youtube",
) -> ObsStreamRouteProbe:
    return ObsStreamRouteProbe(
        inspected=True,
        connected=True,
        verified_at=1_000.0,
        service_type="rtmp_common",
        provider=provider,
        key_configured=True,
        _stream_key=stream_name,
    )


def youtube_response(
    request: httpx.Request,
    *,
    live: bool = False,
    channel_id: str = CHANNEL_ID,
    reusable_stream: bool = True,
) -> httpx.Response:
    if request.url == httpx.URL(YouTubeBroadcastConnector.TOKEN_URL):
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
                "expires_in": 3_600,
                "scope": YouTubeBroadcastConnector.READONLY_SCOPE,
                "token_type": "Bearer",
            },
        )

    assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    if request.url.path == "/youtube/v3/channels":
        assert request.url.params["mine"] == "true"
        return httpx.Response(200, json={"items": [{"id": channel_id}]})

    if request.url.path == "/youtube/v3/liveBroadcasts":
        assert request.url.params["mine"] == "true"
        status = request.url.params["broadcastStatus"]
        if status == "active":
            return httpx.Response(
                200,
                json={
                    "items": (
                        [
                            {
                                "id": "broadcast-live",
                                "contentDetails": {"boundStreamId": "stream-live"},
                                "status": {"lifeCycleStatus": "live"},
                            }
                        ]
                        if live
                        else []
                    )
                },
            )
        assert status == "upcoming"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "broadcast-upcoming",
                        "contentDetails": {"boundStreamId": "stream-reusable"},
                        "status": {"lifeCycleStatus": "ready"},
                    }
                ]
            },
        )

    if request.url.path == "/youtube/v3/liveStreams":
        if request.url.params.get("mine") == "true":
            return httpx.Response(
                200,
                json={
                    "items": (
                        [
                            {
                                "id": "stream-reusable",
                                "cdn": {"ingestionInfo": {"streamName": STREAM_NAME}},
                                "status": {"streamStatus": "ready"},
                            }
                        ]
                        if reusable_stream
                        else []
                    )
                },
            )
        assert request.url.params["id"]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": request.url.params["id"].split(",")[0],
                        "cdn": {"ingestionInfo": {"streamName": STREAM_NAME}},
                        "status": {"streamStatus": "ready"},
                    }
                ]
            },
        )
    raise AssertionError(f"Unexpected YouTube request: {request.url}")


def test_environment_factory_requires_complete_valid_configuration() -> None:
    assert YouTubeBroadcastConnector.from_environment({}) is None
    assert YouTubeBroadcastConnector.from_environment(
        {
            "RAREIQ_YOUTUBE_CLIENT_ID": CLIENT_ID,
            "RAREIQ_YOUTUBE_CLIENT_SECRET": CLIENT_SECRET,
            "RAREIQ_YOUTUBE_REFRESH_TOKEN": REFRESH_TOKEN,
        }
    ) is None
    assert YouTubeBroadcastConnector.from_environment(
        {
            "RAREIQ_YOUTUBE_CLIENT_ID": CLIENT_ID,
            "RAREIQ_YOUTUBE_CLIENT_SECRET": CLIENT_SECRET,
            "RAREIQ_YOUTUBE_REFRESH_TOKEN": REFRESH_TOKEN,
            "RAREIQ_YOUTUBE_CHANNEL_ID": "not-a-channel",
        }
    ) is None


def test_cached_status_never_performs_network_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("cached_status must not call YouTube")

    status = connector_with(handler).cached_status()

    assert requests == []
    assert status["verified"] is False
    assert status["connected"] is False


def test_verified_channel_without_youtube_obs_route_stays_connected() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return youtube_response(request)

    status = connector_with(handler).refresh(obs_route=obs_route(provider=None))

    assert status["verified"] is True
    assert status["connected"] is True
    assert status["route_verified"] is False
    assert status["platform_live"] is False
    assert len(requests) == 3
    assert not any(request.url.path == "/youtube/v3/liveStreams" for request in requests)


def test_matching_owned_stream_verifies_exact_obs_route_without_exposure() -> None:
    connector = connector_with(youtube_response)
    connector.refresh(obs_route=obs_route())
    payload = BroadcastDestinationService(
        connectors={"youtube": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": False})
    youtube = payload["destinations"][1]
    serialized = repr(payload)

    assert youtube["state"] == "ready"
    assert youtube["ready"] is True
    assert youtube["connector"]["route_verified"] is True
    for secret in (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN, STREAM_NAME):
        assert secret not in serialized


def test_wrong_obs_key_cannot_become_ready() -> None:
    connector = connector_with(youtube_response)
    connector.refresh(obs_route=obs_route("wrong-stream-name"))
    youtube = BroadcastDestinationService(
        connectors={"youtube": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True})["destinations"][1]

    assert youtube["state"] == "connected"
    assert youtube["connected"] is True
    assert youtube["ready"] is False


def test_non_reusable_bound_stream_is_recovered_by_id() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return youtube_response(request, reusable_stream=False)

    status = connector_with(handler).refresh(obs_route=obs_route())

    assert status["route_verified"] is True
    assert any(
        request.url.path == "/youtube/v3/liveStreams"
        and request.url.params.get("id") == "stream-reusable"
        for request in requests
    )


def test_channel_identity_mismatch_fails_connection_before_broadcast_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return youtube_response(request, channel_id="UC9999999999999999999999")

    status = connector_with(handler).refresh(obs_route=obs_route())

    assert status["verified"] is True
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["error_code"] == "channel_identity_mismatch"
    assert not any(request.url.path == "/youtube/v3/liveBroadcasts" for request in requests)


def test_verified_route_and_active_broadcast_require_obs_streaming_for_live() -> None:
    connector = connector_with(lambda request: youtube_response(request, live=True))
    connector.refresh(obs_route=obs_route())
    service = BroadcastDestinationService(
        connectors={"youtube": connector},
        clock=lambda: 1_005.0,
    )

    ready = service.snapshot(obs_status={"connected": True, "streaming": False})
    live = service.snapshot(obs_status={"connected": True, "streaming": True})

    assert ready["destinations"][1]["state"] == "ready"
    assert ready["routing"]["platform_live_verified"] is False
    assert live["destinations"][1]["state"] == "live"
    assert live["routing"]["platform_live_verified"] is True


def test_unrelated_active_broadcast_cannot_make_a_different_obs_route_live() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if (
            request.url.path == "/youtube/v3/liveStreams"
            and request.url.params.get("id") == "stream-live"
        ):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "stream-live",
                            "cdn": {"ingestionInfo": {"streamName": "other-live-key"}},
                        }
                    ]
                },
            )
        return youtube_response(request, live=True)

    connector = connector_with(handler)
    status = connector.refresh(obs_route=obs_route())
    live = BroadcastDestinationService(
        connectors={"youtube": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": True})

    assert status["route_verified"] is True
    assert status["platform_live"] is False
    assert live["destinations"][1]["state"] == "ready"
    assert live["routing"]["platform_live_verified"] is False


def test_oauth_failure_fails_closed_without_secret_leakage() -> None:
    connector = connector_with(
        lambda request: httpx.Response(401, json={"error": "invalid_grant"})
    )
    status = connector.refresh(obs_route=obs_route())
    serialized = repr(status)

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False
    for secret in (CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN, STREAM_NAME):
        assert secret not in serialized


def test_access_token_is_reused_until_expiry() -> None:
    now = [1_000.0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return youtube_response(request)

    connector = connector_with(handler, clock=lambda: now[0])
    connector.refresh()
    now[0] += 30.0
    connector.refresh()

    assert sum(
        request.url == httpx.URL(YouTubeBroadcastConnector.TOKEN_URL)
        for request in requests
    ) == 1
