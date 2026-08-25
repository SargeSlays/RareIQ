from __future__ import annotations

import httpx
import pytest

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.facebook_broadcast_connector import FacebookBroadcastConnector
from rareiq.services.obs_service import ObsStreamRouteProbe


PAGE_ID = "123456789012345"
PAGE_TOKEN = "facebook-page-access-token"
INGEST_URL = "rtmps://live-api-s.facebook.com:443/rtmp"
STREAM_KEY = "facebook-private-stream-key"


def connector_with(handler, *, clock=lambda: 1_000.0) -> FacebookBroadcastConnector:
    return FacebookBroadcastConnector(
        page_id=PAGE_ID,
        page_access_token=PAGE_TOKEN,
        ingest_url=INGEST_URL,
        stream_key=STREAM_KEY,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )


def obs_route(
    *,
    stream_key: str = STREAM_KEY,
    ingest_url: str = INGEST_URL,
    provider: str | None = "facebook",
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


def page_payload(*, page_id: str = PAGE_ID) -> dict[str, str]:
    return {"id": page_id, "name": "RareIQ Live"}


def test_environment_factory_requires_complete_valid_configuration() -> None:
    complete = {
        "RAREIQ_FACEBOOK_PAGE_ID": PAGE_ID,
        "RAREIQ_FACEBOOK_PAGE_ACCESS_TOKEN": PAGE_TOKEN,
        "RAREIQ_FACEBOOK_INGEST_URL": INGEST_URL,
        "RAREIQ_FACEBOOK_STREAM_KEY": STREAM_KEY,
    }
    assert FacebookBroadcastConnector.from_environment({}) is None
    for key in complete:
        partial = dict(complete)
        partial.pop(key)
        assert FacebookBroadcastConnector.from_environment(partial) is None
    assert FacebookBroadcastConnector.from_environment(complete) is not None


@pytest.mark.parametrize(
    ("page_id", "ingest_url"),
    (
        ("page-name", INGEST_URL),
        (PAGE_ID, "http://live-api-s.facebook.com/rtmp"),
        (PAGE_ID, "rtmps://example.com/rtmp"),
        (PAGE_ID, "rtmps://live-api-s.facebook.com:8443/rtmp"),
        (PAGE_ID, "rtmps://user:pass@live-api-s.facebook.com/rtmp"),
        (PAGE_ID, "rtmps://live-api-s.facebook.com"),
        (PAGE_ID, "rtmps://live-api-s.facebook.com/rtmp?key=secret"),
        (PAGE_ID, "rtmps://live-api-s.facebook.com/rtmp#fragment"),
    ),
)
def test_configuration_validation_fails_closed(page_id: str, ingest_url: str) -> None:
    with pytest.raises(ValueError):
        FacebookBroadcastConnector(
            page_id=page_id,
            page_access_token=PAGE_TOKEN,
            ingest_url=ingest_url,
            stream_key=STREAM_KEY,
        )


def test_cached_status_never_performs_network_io() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("cached_status must not call Meta")

    status = connector_with(handler).cached_status()

    assert requests == []
    assert status["verified"] is False
    assert status["connected"] is False


def test_page_identity_and_exact_obs_route_become_ready_without_live_claim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.facebook.com"
        assert request.url.path == f"/v26.0/{PAGE_ID}"
        assert request.url.params["fields"] == "id,name"
        assert request.headers["Authorization"] == f"Bearer {PAGE_TOKEN}"
        return httpx.Response(200, json=page_payload())

    connector = connector_with(handler)
    status = connector.refresh(obs_route=obs_route())
    service = BroadcastDestinationService(
        connectors={"facebook": connector},
        clock=lambda: 1_005.0,
    )
    ready = service.snapshot(obs_status={"connected": True, "streaming": False})
    sending = service.snapshot(obs_status={"connected": True, "streaming": True})
    facebook = ready["destinations"][4]

    assert status["verified"] is True
    assert status["connected"] is True
    assert status["route_verified"] is True
    assert status["platform_live"] is False
    assert status["platform_live_supported"] is False
    assert facebook["state"] == "ready"
    assert facebook["ready"] is True
    assert facebook["live"] is False
    assert "live-status readback is unavailable" in facebook["connector_detail"]
    assert sending["destinations"][4]["state"] == "ready"
    assert sending["routing"]["platform_live_verified"] is False


def test_page_identity_can_connect_without_claiming_a_wrong_route() -> None:
    connector = connector_with(
        lambda request: httpx.Response(200, json=page_payload())
    )
    status = connector.refresh(obs_route=obs_route(stream_key="wrong-key"))
    facebook = BroadcastDestinationService(
        connectors={"facebook": connector},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": True})["destinations"][4]

    assert status["connected"] is True
    assert status["route_verified"] is False
    assert facebook["state"] == "connected"
    assert facebook["ready"] is False
    assert facebook["live"] is False


@pytest.mark.parametrize(
    "route",
    (
        obs_route(stream_key="wrong-key"),
        obs_route(ingest_url="rtmps://live-api-s.facebook.com/other"),
        obs_route(provider="youtube"),
    ),
)
def test_partial_or_wrong_platform_obs_routes_fail_closed(route) -> None:
    status = connector_with(
        lambda request: httpx.Response(200, json=page_payload())
    ).refresh(obs_route=route)

    assert status["connected"] is True
    assert status["route_verified"] is False
    assert status["platform_live"] is False


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {},
        {"id": PAGE_ID},
        {"id": "999", "name": "Wrong Page"},
        [page_payload()],
    ),
)
def test_malformed_or_wrong_page_identity_fails_closed(payload) -> None:
    status = connector_with(
        lambda request: httpx.Response(200, json=payload)
    ).refresh(obs_route=obs_route())

    assert status["verified"] is False
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False


def test_oversized_or_failed_graph_response_fails_closed_without_secret_leakage() -> None:
    oversized = b"x" * (FacebookBroadcastConnector.MAX_RESPONSE_BYTES + 1)
    statuses = (
        connector_with(
            lambda request: httpx.Response(200, content=oversized)
        ).refresh(obs_route=obs_route()),
        connector_with(
            lambda request: httpx.Response(503, json={"error": "offline"})
        ).refresh(obs_route=obs_route()),
    )

    for status in statuses:
        assert status["verified"] is False
        assert status["connected"] is False
        serialized = repr(status)
        for secret in (PAGE_TOKEN, STREAM_KEY, INGEST_URL):
            assert secret not in serialized
