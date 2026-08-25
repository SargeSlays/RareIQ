from rareiq.services.broadcast_destination_service import BroadcastDestinationService


class FakeConnector:
    def __init__(self, platform_id: str, evidence: dict | None = None, error: Exception | None = None):
        self.platform_id = platform_id
        self.evidence = evidence or {}
        self.error = error

    def cached_status(self) -> dict:
        if self.error is not None:
            raise self.error
        return dict(self.evidence)


def connector_evidence(**overrides) -> dict:
    return {
        "platform_id": "twitch",
        "verified": True,
        "verified_at": 1_000.0,
        "verification_source": "twitch.api",
        "configured": True,
        "connected": True,
        "route_verified": True,
        "destination_ready": True,
        "platform_live": False,
        **overrides,
    }


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
    assert payload["version"] == 2


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
    assert all(item["read_only"] is True for item in payload["destinations"])
    assert all(item["setup"]["credentials_collected"] is False for item in payload["destinations"])
    assert all(item["setup"]["can_connect"] is False for item in payload["destinations"])


def test_destination_readiness_explains_requirements_without_claiming_connection() -> None:
    payload = BroadcastDestinationService().snapshot(
        obs_status={"connected": True, "streaming": False}
    )

    for destination in payload["destinations"]:
        assert destination["encoder"] == {
            "connected": True,
            "streaming": False,
            "state": "ready",
            "state_label": "OBS ready",
        }
        assert destination["setup"]["status"] == "required"
        assert destination["setup"]["status_label"] == "Setup required"
        assert len(destination["setup"]["requirements"]) >= 3
        assert destination["setup"]["next_action"]
        assert destination["setup"]["verification_method"]
        assert destination["connected"] is False
        assert destination["ready"] is False


def test_streaming_encoder_is_explicitly_unverified_for_every_destination() -> None:
    payload = BroadcastDestinationService().snapshot(
        obs_status={"connected": True, "streaming": True}
    )

    assert all(item["encoder"]["state"] == "streaming_unverified" for item in payload["destinations"])
    assert all(item["encoder"]["state_label"] == "OBS sending · unverified" for item in payload["destinations"])
    assert payload["summary"]["live"] == 0


def test_fresh_verified_connector_can_mark_one_destination_ready() -> None:
    service = BroadcastDestinationService(
        connectors={"twitch": FakeConnector("twitch", connector_evidence())},
        clock=lambda: 1_020.0,
    )
    payload = service.snapshot(obs_status={"connected": True, "streaming": False})
    twitch = payload["destinations"][0]

    assert twitch["state"] == "ready"
    assert twitch["connected"] is True
    assert twitch["ready"] is True
    assert twitch["live"] is False
    assert twitch["connector"] == {
        "registered": True,
        "fresh": True,
        "verification_source": "twitch.api",
        "route_verified": True,
        "age_seconds": 20.0,
    }
    assert payload["summary"] == {
        "total": 8,
        "connected": 1,
        "ready": 1,
        "live": 0,
        "needs_setup": 7,
    }


def test_live_requires_fresh_platform_evidence_route_and_streaming_encoder() -> None:
    service = BroadcastDestinationService(
        connectors={
            "twitch": FakeConnector(
                "twitch",
                connector_evidence(platform_live=True),
            )
        },
        clock=lambda: 1_010.0,
    )

    idle = service.snapshot(obs_status={"connected": True, "streaming": False})
    live = service.snapshot(obs_status={"connected": True, "streaming": True})

    assert idle["destinations"][0]["live"] is False
    assert idle["routing"]["platform_live_verified"] is False
    assert live["destinations"][0]["live"] is True
    assert live["destinations"][0]["state"] == "live"
    assert live["routing"]["platform_live_verified"] is True


def test_connected_account_without_verified_route_cannot_be_ready() -> None:
    service = BroadcastDestinationService(
        connectors={
            "twitch": FakeConnector(
                "twitch",
                connector_evidence(route_verified=False, platform_live=True),
            )
        },
        clock=lambda: 1_010.0,
    )
    twitch = service.snapshot(
        obs_status={"connected": True, "streaming": True}
    )["destinations"][0]

    assert twitch["state"] == "connected"
    assert twitch["connected"] is True
    assert twitch["ready"] is False
    assert twitch["live"] is False
    assert twitch["connector"]["route_verified"] is False


def test_stale_connector_evidence_cannot_claim_connected_ready_or_live() -> None:
    service = BroadcastDestinationService(
        connectors={
            "twitch": FakeConnector(
                "twitch",
                connector_evidence(platform_live=True),
            )
        },
        clock=lambda: 1_100.0,
    )
    twitch = service.snapshot(
        obs_status={"connected": True, "streaming": True}
    )["destinations"][0]

    assert twitch["state"] == "stale"
    assert twitch["connected"] is False
    assert twitch["ready"] is False
    assert twitch["live"] is False
    assert twitch["connector"]["fresh"] is False


def test_malformed_mismatched_and_failed_connectors_fail_closed() -> None:
    cases = [
        FakeConnector("youtube", connector_evidence()),
        FakeConnector("twitch", connector_evidence(verified=False)),
        FakeConnector("twitch", connector_evidence(verification_source="secret value")),
        FakeConnector("twitch", connector_evidence(platform_id="youtube")),
        FakeConnector("twitch", connector_evidence(verified_at=float("nan"))),
        FakeConnector("twitch", error=RuntimeError("provider failed")),
    ]

    for connector in cases:
        twitch = BroadcastDestinationService(
            connectors={"twitch": connector},
            clock=lambda: 1_010.0,
        ).snapshot(obs_status={"connected": True, "streaming": True})["destinations"][0]
        assert twitch["state"] == "connector_error"
        assert twitch["connected"] is False
        assert twitch["ready"] is False
        assert twitch["live"] is False
        assert twitch["connector"]["verification_source"] is None
