from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


@dataclass(frozen=True)
class BroadcastPlatform:
    platform_id: str
    name: str
    transport: str
    setup_method: str
    capabilities: tuple[str, ...]
    connector_phase: str
    note: str
    requirements: tuple[str, ...]
    next_action: str
    verification_method: str


class BroadcastConnectorStatusProvider(Protocol):
    """Non-blocking provider for cached, platform-confirmed connector state."""

    platform_id: str

    def cached_status(self) -> dict[str, Any]: ...


class BroadcastDestinationService:
    """Truthful capability registry for future broadcast connectors.

    The service never accepts credentials and never infers that a platform is
    live from encoder state alone. Connector adapters may provide cached
    platform evidence; this service validates freshness, route correlation,
    and state dependencies before exposing any positive claim.
    """

    CONNECTOR_EVIDENCE_TTL_SECONDS = 90.0
    CONNECTOR_FUTURE_TOLERANCE_SECONDS = 5.0
    _SOURCE_PATTERN = re.compile(r"^[a-z0-9_.-]{1,64}$")

    PLATFORMS = (
        BroadcastPlatform(
            "twitch",
            "Twitch",
            "OBS / RTMP",
            "OAuth application",
            ("channel metadata", "chat", "events", "stream health"),
            "first",
            "OAuth and EventSub connector not configured.",
            ("Twitch developer application", "Authorized channel account", "OBS RTMP destination"),
            "Create and authorize the Twitch connector.",
            "Twitch account authorization plus EventSub and stream-status confirmation.",
        ),
        BroadcastPlatform(
            "youtube",
            "YouTube",
            "OBS / RTMP",
            "Google OAuth application",
            ("schedule", "broadcast control", "live chat", "stream health"),
            "first",
            "YouTube Live API connector not configured.",
            ("Google Cloud OAuth application", "YouTube channel with Live enabled", "OBS RTMP destination"),
            "Create and authorize the YouTube Live connector.",
            "YouTube Live API broadcast and stream-status confirmation.",
        ),
        BroadcastPlatform(
            "kick",
            "Kick",
            "OBS / RTMPS",
            "Kick OAuth application",
            ("channel metadata", "chat", "events", "stream health"),
            "second",
            "Kick API connector not configured.",
            ("Kick developer application", "Authorized channel account", "OBS RTMPS destination"),
            "Create and authorize the Kick connector.",
            "Kick account authorization plus channel and stream-status confirmation.",
        ),
        BroadcastPlatform(
            "rumble",
            "Rumble",
            "OBS / RTMP",
            "Static stream key and Live Stream API URL",
            ("chat", "followers", "rants", "stream activity"),
            "second",
            "Rumble stream key and API URL not configured.",
            ("Rumble Live Stream API URL", "Rumble stream key in OBS", "Channel access"),
            "Configure the Rumble destination and read-only activity connector.",
            "Rumble API response plus encoder destination confirmation.",
        ),
        BroadcastPlatform(
            "facebook",
            "Facebook",
            "OBS / RTMPS",
            "Meta application and Page authorization",
            ("page broadcast", "comments", "stream health"),
            "conditional",
            "Requires eligible Page access and Meta permissions.",
            ("Meta developer application", "Eligible Facebook Page", "Page authorization and Live permissions"),
            "Verify Page eligibility before authorizing the Meta connector.",
            "Meta Page authorization and live-video status confirmation.",
        ),
        BroadcastPlatform(
            "tiktok",
            "TikTok",
            "LIVE Studio / stream key",
            "Eligible LIVE account",
            ("encoder destination",),
            "conditional",
            "Public posting APIs do not provide general LIVE control.",
            ("TikTok account eligible for LIVE", "LIVE Studio or stream-key access", "Encoder destination configured outside RareIQ"),
            "Confirm LIVE eligibility and configure the encoder destination.",
            "Platform-side LIVE status; RareIQ has no general public LIVE-control connector.",
        ),
        BroadcastPlatform(
            "x",
            "X",
            "Media Studio Producer / RTMP",
            "Media Studio Producer access",
            ("encoder destination", "broadcast monitoring"),
            "conditional",
            "Requires Media Studio Producer access for the account.",
            ("X Media Studio Producer access", "RTMP source configured in Producer", "Eligible account"),
            "Confirm Media Studio Producer access and configure its RTMP source.",
            "Producer-side broadcast status; no RareIQ account connector is configured.",
        ),
        BroadcastPlatform(
            "instagram",
            "Instagram",
            "Live Producer / RTMP",
            "Eligible professional account",
            ("encoder destination",),
            "conditional",
            "Live Producer availability depends on account eligibility.",
            ("Eligible professional Instagram account", "Live Producer access", "RTMP destination configured outside RareIQ"),
            "Confirm Live Producer eligibility and configure the encoder destination.",
            "Live Producer status; RareIQ has no general account connector configured.",
        ),
    )

    def __init__(
        self,
        *,
        connectors: Mapping[str, BroadcastConnectorStatusProvider] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._connectors = dict(connectors or {})
        self._clock = clock

    def snapshot(self, *, obs_status: dict[str, Any] | None = None) -> dict[str, Any]:
        obs = obs_status or {}
        encoder_connected = bool(obs.get("connected"))
        encoder_streaming = bool(obs.get("streaming"))
        destinations = [
            self._destination(
                platform,
                encoder_connected=encoder_connected,
                encoder_streaming=encoder_streaming,
            )
            for platform in self.PLATFORMS
        ]
        connected_count = sum(1 for item in destinations if item["connected"])
        ready_count = sum(1 for item in destinations if item["ready"])
        live_count = sum(1 for item in destinations if item["live"])
        return {
            "version": 2,
            "routing": {
                "mode": "external_encoder",
                "encoder": "OBS",
                "connected": encoder_connected,
                "streaming": encoder_streaming,
                "platform_live_verified": live_count > 0,
                "detail": (
                    f"{live_count} platform destination{'s' if live_count != 1 else ''} verified live."
                    if live_count
                    else "OBS is sending output, but no platform destination is verified."
                    if encoder_streaming
                    else "Connect OBS and configure platform destinations before going live."
                ),
            },
            "summary": {
                "total": len(destinations),
                "connected": connected_count,
                "ready": ready_count,
                "live": live_count,
                "needs_setup": sum(1 for item in destinations if not item["ready"]),
            },
            "destinations": destinations,
        }

    def _destination(
        self,
        platform: BroadcastPlatform,
        *,
        encoder_connected: bool,
        encoder_streaming: bool,
    ) -> dict[str, Any]:
        destination = self._unconfigured(
            platform,
            encoder_connected=encoder_connected,
            encoder_streaming=encoder_streaming,
        )
        connector = self._connectors.get(platform.platform_id)
        if connector is None:
            return destination
        if getattr(connector, "platform_id", None) != platform.platform_id:
            return self._connector_failure(destination, "Connector identity mismatch")
        try:
            evidence = connector.cached_status()
        except Exception:
            return self._connector_failure(destination, "Connector status unavailable")
        return self._apply_connector_evidence(
            destination,
            platform,
            evidence,
            encoder_streaming=encoder_streaming,
        )

    @staticmethod
    def _connector_failure(destination: dict[str, Any], detail: str) -> dict[str, Any]:
        destination.update(
            {
                "state": "connector_error",
                "state_label": "Status unavailable",
                "connector_detail": detail,
                "connector": {
                    "registered": True,
                    "fresh": False,
                    "verification_source": None,
                    "route_verified": False,
                    "age_seconds": None,
                },
            }
        )
        destination["setup"] = {
            **destination["setup"],
            "status": "error",
            "status_label": "Status unavailable",
        }
        return destination

    def _apply_connector_evidence(
        self,
        destination: dict[str, Any],
        platform: BroadcastPlatform,
        evidence: dict[str, Any] | Any,
        *,
        encoder_streaming: bool,
    ) -> dict[str, Any]:
        if not isinstance(evidence, dict) or evidence.get("platform_id") != platform.platform_id:
            return self._connector_failure(destination, "Connector evidence identity mismatch")
        source = str(evidence.get("verification_source") or "")
        verified_at = evidence.get("verified_at")
        if not evidence.get("verified") or not self._SOURCE_PATTERN.fullmatch(source):
            return self._connector_failure(destination, "Connector evidence is unverified")
        try:
            verified_timestamp = float(verified_at)
            if not math.isfinite(verified_timestamp):
                raise ValueError("non-finite connector timestamp")
            age_seconds = self._clock() - verified_timestamp
        except (TypeError, ValueError):
            return self._connector_failure(destination, "Connector evidence has no valid timestamp")
        fresh = (
            -self.CONNECTOR_FUTURE_TOLERANCE_SECONDS
            <= age_seconds
            <= self.CONNECTOR_EVIDENCE_TTL_SECONDS
        )
        if not fresh:
            destination.update(
                {
                    "state": "stale",
                    "state_label": "Status stale",
                    "verified_at": verified_timestamp,
                    "connector_detail": "Refresh the platform connector before relying on this destination.",
                    "connector": {
                        "registered": True,
                        "fresh": False,
                        "verification_source": source,
                        "route_verified": False,
                        "age_seconds": round(max(0.0, age_seconds), 1),
                    },
                }
            )
            destination["setup"] = {
                **destination["setup"],
                "status": "stale",
                "status_label": "Refresh required",
            }
            return destination

        configured = bool(evidence.get("configured"))
        connected = configured and bool(evidence.get("connected"))
        route_verified = connected and bool(evidence.get("route_verified"))
        ready = route_verified and bool(evidence.get("destination_ready"))
        live = ready and encoder_streaming and bool(evidence.get("platform_live"))
        state = "live" if live else "ready" if ready else "connected" if connected else "configured" if configured else "not_configured"
        state_label = "Live verified" if live else "Ready" if ready else "Connected" if connected else "Configured" if configured else "Not configured"
        destination.update(
            {
                "state": state,
                "state_label": state_label,
                "connected": connected,
                "ready": ready,
                "live": live,
                "verified_at": verified_timestamp,
                "connector_detail": (
                    "Platform and encoder route verified live."
                    if live
                    else "Platform destination and encoder route verified ready."
                    if ready
                    else "Platform account connected; destination route is not verified."
                    if connected
                    else "Connector configured; platform authorization is not verified."
                    if configured
                    else platform.note
                ),
                "connector": {
                    "registered": True,
                    "fresh": True,
                    "verification_source": source,
                    "route_verified": route_verified,
                    "age_seconds": round(max(0.0, age_seconds), 1),
                },
            }
        )
        destination["setup"] = {
            **destination["setup"],
            "status": "complete" if ready else "configured" if configured else "required",
            "status_label": "Ready" if ready else "Configuration incomplete" if configured else "Setup required",
        }
        return destination

    @staticmethod
    def _unconfigured(
        platform: BroadcastPlatform,
        *,
        encoder_connected: bool,
        encoder_streaming: bool,
    ) -> dict[str, Any]:
        return {
            "id": platform.platform_id,
            "name": platform.name,
            "state": "not_configured",
            "state_label": "Not configured",
            "connected": False,
            "ready": False,
            "live": False,
            "verified_at": None,
            "transport": platform.transport,
            "setup_method": platform.setup_method,
            "capabilities": list(platform.capabilities),
            "connector_phase": platform.connector_phase,
            "note": platform.note,
            "connector_detail": platform.note,
            "connector": {
                "registered": False,
                "fresh": False,
                "verification_source": None,
                "route_verified": False,
                "age_seconds": None,
            },
            "read_only": True,
            "encoder": {
                "connected": encoder_connected,
                "streaming": encoder_streaming,
                "state": "streaming_unverified" if encoder_streaming else "ready" if encoder_connected else "offline",
                "state_label": "OBS sending · unverified" if encoder_streaming else "OBS ready" if encoder_connected else "OBS offline",
            },
            "setup": {
                "status": "required",
                "status_label": "Setup required",
                "requirements": list(platform.requirements),
                "next_action": platform.next_action,
                "verification_method": platform.verification_method,
                "credentials_collected": False,
                "can_connect": False,
            },
        }
