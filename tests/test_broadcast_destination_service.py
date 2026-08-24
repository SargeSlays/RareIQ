from rareiq.services.broadcast_destination_service import BroadcastDestinationService


def test_destination_registry_exposes_all_requested_platforms() -> None:
    payload = BroadcastDestinationService().snapshot(obs_status={})

    assert [item["id"] for item in payload["destinations"]] == [
        "twitch",
        "youtube",
        "kick",
        "rumble",
        "facebook",
        "tiktok",
        "x",
        "instagram",
    ]
    assert payload["summary"] == {
        "total": 8,
        "connected": 0,
        "ready": 0,
        "live": 0,
        "needs_setup": 8,
    }


def test_encoder_output_never_fabricates_platform_live_state() -> None:
    payload = BroadcastDestinationService().snapshot(
        obs_status={"connected": True, "streaming": True}
    )

    assert payload["routing"]["connected"] is True
    assert payload["routing"]["streaming"] is True
    assert payload["routing"]["platform_live_verified"] is False
    assert all(item["connected"] is False for item in payload["destinations"])
    assert all(item["live"] is False for item in payload["destinations"])


def test_foundation_payload_contains_no_credentials_or_secret_values() -> None:
    payload = BroadcastDestinationService().snapshot(obs_status={})
    serialized = repr(payload).lower()

    for forbidden in ("client_secret", "access_token", "refresh_token", "stream_key"):
        assert forbidden not in serialized
    assert all(item["state"] == "not_configured" for item in payload["destinations"])
    assert all(item["verified_at"] is None for item in payload["destinations"])
