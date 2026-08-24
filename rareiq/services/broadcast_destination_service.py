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
        ),
        BroadcastPlatform(
            "youtube",
            "YouTube",
            "OBS / RTMP",
            "Google OAuth application",
            ("schedule", "broadcast control", "live chat", "stream health"),
            "first",
            "YouTube Live API connector not configured.",
        ),
        BroadcastPlatform(
            "kick",
            "Kick",
            "OBS / RTMPS",
            "Kick OAuth application",
            ("channel metadata", "chat", "events", "stream health"),
            "second",
            "Kick API connector not configured.",
        ),
        BroadcastPlatform(
            "rumble",
            "Rumble",
            "OBS / RTMP",
            "Static stream key and Live Stream API URL",
            ("chat", "followers", "rants", "stream activity"),
            "second",
            "Rumble stream key and API URL not configured.",
        ),
        BroadcastPlatform(
            "facebook",
            "Facebook",
            "OBS / RTMPS",
            "Meta application and Page authorization",
            ("page broadcast", "comments", "stream health"),
            "conditional",
            "Requires eligible Page access and Meta permissions.",
        ),
        BroadcastPlatform(
            "tiktok",
            "TikTok",
            "LIVE Studio / stream key",
            "Eligible LIVE account",
            ("encoder destination",),
            "conditional",
            "Public posting APIs do not provide general LIVE control.",
        ),
        BroadcastPlatform(
            "x",
            "X",
            "Media Studio Producer / RTMP",
            "Media Studio Producer access",
            ("encoder destination", "broadcast monitoring"),
            "conditional",
            "Requires Media Studio Producer access for the account.",
        ),
        BroadcastPlatform(
            "instagram",
            "Instagram",
            "Live Producer / RTMP",
            "Eligible professional account",
            ("encoder destination",),
            "conditional",
            "Live Producer availability depends on account eligibility.",
        ),
    )

    def snapshot(self, *, obs_status: dict[str, Any] | None = None) -> dict[str, Any]:
        obs = obs_status or {}
        encoder_connected = bool(obs.get("connected"))
        encoder_streaming = bool(obs.get("streaming"))
        destinations = [self._unconfigured(platform) for platform in self.PLATFORMS]
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
    def _unconfigured(platform: BroadcastPlatform) -> dict[str, Any]:
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
        }
