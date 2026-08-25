from rareiq.web.server import _broadcast_go_live_readiness


def test_connected_obs_without_verified_destination_is_not_broadcast_ready() -> None:
    result = _broadcast_go_live_readiness(
        {"summary": {"ready": 0, "live": 0}},
        {"connected": True, "streaming": True},
    )

    assert result["ready"] is False
    assert result["encoder_connected"] is True
    assert result["connector_ready"] is False
    assert result["platform_live_verified"] is False
    assert "no platform destination is verified" in result["detail"]


def test_verified_connector_and_obs_are_broadcast_ready_without_claiming_live() -> None:
    result = _broadcast_go_live_readiness(
        {
            "summary": {"ready": 1, "live": 0},
            "destinations": [{"id": "twitch", "name": "Twitch", "ready": True, "live": False}],
        },
        {"connected": True, "streaming": False},
    )

    assert result["ready"] is True
    assert result["connector_ready"] is True
    assert result["platform_live_verified"] is False
    assert result["ready_destinations"] == ["Twitch"]
    assert "Twitch" in result["detail"]
    assert result["action"] == ""


def test_platform_live_requires_platform_confirmed_live_count() -> None:
    result = _broadcast_go_live_readiness(
        {
            "summary": {"ready": 1, "live": 1},
            "destinations": [{"id": "youtube", "name": "YouTube Live", "ready": True, "live": True}],
        },
        {"connected": True, "streaming": True},
    )

    assert result["ready"] is True
    assert result["platform_live_verified"] is True
    assert result["live_destinations"] == ["YouTube Live"]


def test_verified_connector_without_obs_is_not_broadcast_ready() -> None:
    result = _broadcast_go_live_readiness(
        {"summary": {"ready": 1, "live": 0}},
        {"connected": False, "streaming": False},
    )

    assert result["ready"] is False
    assert result["encoder_connected"] is False
    assert "OBS is not connected" in result["detail"]
