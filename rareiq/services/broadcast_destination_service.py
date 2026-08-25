from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


class BroadcastDestinationService:
    """Truthful capability registry for future broadcast connectors.

    This first phase intentionally does not accept credentials or infer that a
    platform is live from the encoder state. Platform-specific adapters can
    replace ``not_configured`` with verified account and live states later.
    """

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

    def snapshot(self, *, obs_status: dict[str, Any] | None = None) -> dict[str, Any]:
        obs = obs_status or {}
        encoder_connected = bool(obs.get("connected"))
        encoder_streaming = bool(obs.get("streaming"))
        destinations = [
            self._unconfigured(platform, encoder_connected=encoder_connected, encoder_streaming=encoder_streaming)
            for platform in self.PLATFORMS
        ]
        return {
            "version": 1,
            "routing": {
                "mode": "external_encoder",
                "encoder": "OBS",
                "connected": encoder_connected,
                "streaming": encoder_streaming,
                "platform_live_verified": False,
                "detail": (
                    "OBS is sending output, but no platform destination is verified."
                    if encoder_streaming
                    else "Connect OBS and configure platform destinations before going live."
                ),
            },
            "summary": {
                "total": len(destinations),
                "connected": 0,
                "ready": 0,
                "live": 0,
                "needs_setup": len(destinations),
            },
            "destinations": destinations,
        }

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
