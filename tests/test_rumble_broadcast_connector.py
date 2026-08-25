from __future__ import annotations

import httpx
import pytest

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.obs_service import ObsStreamRouteProbe
from rareiq.services.rumble_broadcast_connector import RumbleBroadcastConnector


API_SECRET = "rumble-api-secret"
API_URL = f"https://rumble.com/-livestream-api/get-data?key={API_SECRET}"
INGEST_URL = "rtmps://live.rumble.example/live"
STREAM_KEY = "rumble-private-stream-key"


def connector_with(handler, *, clock=lambda: 1_000.0) -> RumbleBroadcastConnector:
    return RumbleBroadcastConnector(
        api_url=API_URL,
        ingest_url=INGEST_URL,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def obs_route(
    *,
    stream_key: str = STREAM_KEY,
    ingest_url: str = INGEST_URL,
    provider: str | None = None,
) -> ObsStreamRouteProbe:
    return ObsStreamRouteProbe(
        inspected=True,
        connected=True,
        verified_at=1_000.0,
        service_type="rtmp_custom",
        provider=provider,
        key_configured=True,
        _stream_key=stream_key,
        _server_url=ingest_url,
    )


def rumble_payload(
    *,
    live: bool = False,
    stream_key: str = STREAM_KEY,
    entity_type: str = "user",
) -> dict:
    return {
        "now": 1_000,
        "type": entity_type,
        "user_id": "user-123" if entity_type == "user" else None,
        "channel_id": "channel-456" if entity_type == "channel" else None,
        "livestreams": (
            [
                {
                    "id": "stream-789",
                    "title": "RareIQ Live",
                    "is_live": True,
                    "stream_key": stream_key,
                    "watching_now": 42,
                }
            ]
            if live
            else []
        ),
    }


def test_environment_factory_requires_both_valid_urls() -> None:
    assert RumbleBroadcastConnector.from_environment({}) is None
    assert RumbleBroadcastConnector.from_environment(
        {"RAREIQ_RUMBLE_LIVE_STREAM_API_URL": API_URL}
    ) is None
    assert RumbleBroadcastConnector.from_environment(
        {
            "RAREIQ_RUMBLE_LIVE_STREAM_API_URL": "https://example.com/api?key=x",
            "RAREIQ_RUMBLE_INGEST_URL": INGEST_URL,
        }
    ) is None
    assert RumbleBroadcastConnector.from_environment(
        {
            "RAREIQ_RUMBLE_LIVE_STREAM_API_URL": API_URL,
            "RAREIQ_RUMBLE_INGEST_URL": "https://not-an-ingest.example",
        }
    ) is None


@pytest.mark.parametrize(
    "api_url",
    (
        "http://rumble.com/api?key=x",
        "https://example.com/api?key=x",
        "https://rumble.com:8443/api?key=x",
        "https://user:pass@rumble.com/api?key=x",
        "https://rumble.com/api",
        "https://rumble.com/api?key=x#fragment",
    ),
)
def test_api_url_validation_blocks_untrusted_or_non_secret_urls(api_url: str) -> None:
    with pytest.raises(ValueError):
        RumbleBroadcastConnector(api_url=api_url, ingest_url=INGEST_URL)


def test_cached_status_never_performs_network_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("cached_status must not call Rumble")

    status = connector_with(handler).cached_status()

    assert requests == []
    assert status["verified"] is False
    assert status["connected"] is False


def test_offline_creator_api_is_connected_but_not_route_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == API_URL
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=rumble_payload())

    connector = connector_with(handler)
    status = connector.refresh(obs_route=obs_route())
    rumble = BroadcastDestinationService(
        connectors={"rumble": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": False})["destinations"][3]

    assert status["verified"] is True
    assert status["connected"] is True
    assert status["platform_live"] is False
    assert status["route_verified"] is False
    assert rumble["state"] == "connected"
    assert rumble["ready"] is False


def test_active_stream_exact_key_and_ingest_make_route_ready() -> None:
    connector = connector_with(
        lambda request: httpx.Response(200, json=rumble_payload(live=True))
    )
    connector.refresh(obs_route=obs_route())
    payload = BroadcastDestinationService(
        connectors={"rumble": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": False})
    rumble = payload["destinations"][3]
    serialized = repr(payload)

    assert rumble["state"] == "ready"
    assert rumble["ready"] is True
    assert rumble["connector"]["route_verified"] is True
    for secret in (API_SECRET, API_URL, STREAM_KEY, INGEST_URL):
        assert secret not in serialized


def test_active_route_requires_obs_streaming_before_live_verified() -> None:
    connector = connector_with(
        lambda request: httpx.Response(200, json=rumble_payload(live=True))
    )
    connector.refresh(obs_route=obs_route())
    service = BroadcastDestinationService(
        connectors={"rumble": connector},
        clock=lambda: 1_005.0,
    )

    ready = service.snapshot(obs_status={"connected": True, "streaming": False})
    live = service.snapshot(obs_status={"connected": True, "streaming": True})

    assert ready["destinations"][3]["state"] == "ready"
    assert ready["routing"]["platform_live_verified"] is False
    assert live["destinations"][3]["state"] == "live"
    assert live["routing"]["platform_live_verified"] is True


def test_partial_or_wrong_platform_obs_routes_fail_closed() -> None:
    for route in (
        obs_route(stream_key="wrong-key"),
        obs_route(ingest_url="rtmps://wrong.example/live"),
        obs_route(provider="youtube"),
    ):
        status = connector_with(
            lambda request: httpx.Response(200, json=rumble_payload(live=True))
        ).refresh(obs_route=route)
        assert status["connected"] is True
        assert status["platform_live"] is True
        assert status["route_verified"] is False


def test_non_live_record_cannot_verify_route() -> None:
    payload = rumble_payload()
    payload["livestreams"] = [
        {"id": "stale", "is_live": False, "stream_key": STREAM_KEY}
    ]
    status = connector_with(
        lambda request: httpx.Response(200, json=payload)
    ).refresh(obs_route=obs_route())

    assert status["connected"] is True
    assert status["platform_live"] is False
    assert status["route_verified"] is False


def test_channel_scoped_creator_api_is_supported() -> None:
    status = connector_with(
        lambda request: httpx.Response(
            200,
            json=rumble_payload(entity_type="channel"),
        )
    ).refresh()

    assert status["verified"] is True
    assert status["connected"] is True


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {},
        {"type": "unknown", "user_id": "1", "livestreams": []},
        {"type": "user", "user_id": None, "livestreams": []},
        {"type": "channel", "channel_id": "1", "livestreams": {}},
        {"type": "user", "user_id": "1", "livestreams": ["bad"]},
    ),
)
def test_malformed_creator_api_payloads_fail_closed(payload) -> None:
    status = connector_with(
        lambda request: httpx.Response(200, json=payload)
    ).refresh(obs_route=obs_route())

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False


def test_oversized_response_fails_before_json_parsing() -> None:
    body = b"x" * (RumbleBroadcastConnector.MAX_RESPONSE_BYTES + 1)
    status = connector_with(
        lambda request: httpx.Response(200, content=body)
    ).refresh(obs_route=obs_route())

    assert status["verified"] is False
    assert status["connected"] is False


def test_transport_failure_fails_closed_without_secret_leakage() -> None:
    connector = connector_with(
        lambda request: httpx.Response(503, json={"error": "offline"})
    )
    status = connector.refresh(obs_route=obs_route())
    serialized = repr(status)

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    for secret in (API_SECRET, API_URL, STREAM_KEY, INGEST_URL):
        assert secret not in serialized
