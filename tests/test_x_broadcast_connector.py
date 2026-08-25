from __future__ import annotations

import pytest

from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.services.obs_service import ObsStreamRouteProbe
from rareiq.services.x_broadcast_connector import XBroadcastConnector


INGEST_URL = "rtmps://va.pscp.tv:443/x"
STREAM_KEY = "x-media-studio-private-key"


def connector(*, clock=lambda: 1_000.0) -> XBroadcastConnector:
    return XBroadcastConnector(
        ingest_url=INGEST_URL,
        stream_key=STREAM_KEY,
        clock=clock,
    )


def obs_route(
    *,
    stream_key: str = STREAM_KEY,
    ingest_url: str = INGEST_URL,
    provider: str | None = "x",
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


def test_environment_factory_requires_both_valid_route_values() -> None:
    assert XBroadcastConnector.from_environment({}) is None
    assert XBroadcastConnector.from_environment(
        {"RAREIQ_X_INGEST_URL": INGEST_URL}
    ) is None
    assert XBroadcastConnector.from_environment(
        {"RAREIQ_X_STREAM_KEY": STREAM_KEY}
    ) is None
    assert XBroadcastConnector.from_environment(
        {
            "RAREIQ_X_INGEST_URL": INGEST_URL,
            "RAREIQ_X_STREAM_KEY": STREAM_KEY,
        }
    ) is not None


@pytest.mark.parametrize(
    "ingest_url",
    (
        "https://va.pscp.tv/x",
        "rtmps://",
        "rtmps://user:pass@va.pscp.tv/x",
        "rtmps://va.pscp.tv",
        "rtmps://va.pscp.tv/x?key=secret",
        "rtmps://va.pscp.tv/x#fragment",
        "rtmps://va.pscp.tv:99999/x",
    ),
)
def test_ingest_url_validation_rejects_unsafe_or_non_encoder_urls(
    ingest_url: str,
) -> None:
    with pytest.raises(ValueError):
        XBroadcastConnector(ingest_url=ingest_url, stream_key=STREAM_KEY)


def test_cached_status_does_not_assume_route_or_platform_state() -> None:
    status = connector().cached_status()

    assert status["verified"] is False
    assert status["configured"] is True
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False


def test_exact_obs_route_becomes_ready_without_live_claim() -> None:
    adapter = connector()
    status = adapter.refresh(obs_route=obs_route())
    service = BroadcastDestinationService(
        connectors={"x": adapter},
        clock=lambda: 1_005.0,
    )
    ready = service.snapshot(obs_status={"connected": True, "streaming": False})
    sending = service.snapshot(obs_status={"connected": True, "streaming": True})
    x_destination = ready["destinations"][6]
    serialized = repr(ready)

    assert status["verified"] is True
    assert status["route_verified"] is True
    assert status["platform_live"] is False
    assert x_destination["state"] == "ready"
    assert x_destination["ready"] is True
    assert x_destination["live"] is False
    assert "live-status readback is unavailable" in x_destination["connector_detail"]
    assert sending["destinations"][6]["state"] == "ready"
    assert sending["routing"]["platform_live_verified"] is False
    assert INGEST_URL not in serialized
    assert STREAM_KEY not in serialized


@pytest.mark.parametrize(
    "route",
    (
        None,
        obs_route(stream_key="wrong-key"),
        obs_route(ingest_url="rtmps://other.pscp.tv/x"),
        obs_route(provider="youtube"),
    ),
)
def test_missing_partial_or_conflicting_obs_route_remains_configured(route) -> None:
    adapter = connector()
    status = adapter.refresh(obs_route=route)
    x_destination = BroadcastDestinationService(
        connectors={"x": adapter},
        clock=lambda: 1_005.0,
    ).snapshot(obs_status={"connected": True, "streaming": True})["destinations"][6]

    assert status["verified"] is True
    assert status["connected"] is False
    assert status["route_verified"] is False
    assert status["platform_live"] is False
    assert x_destination["state"] == "configured"
    assert x_destination["ready"] is False
    assert x_destination["live"] is False


def test_default_ports_and_trailing_slashes_normalize_for_exact_match() -> None:
    status = connector().refresh(
        obs_route=obs_route(ingest_url="rtmps://va.pscp.tv/x/")
    )

    assert status["route_verified"] is True


def test_stream_key_never_appears_in_status_or_connector_repr() -> None:
    adapter = connector()
    status = adapter.refresh(obs_route=obs_route())

    assert STREAM_KEY not in repr(status)
    assert STREAM_KEY not in repr(adapter)
