from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlparse


class XBroadcastConnector:
    """Private X Media Studio route verifier with no platform-state claims."""

    platform_id = "x"

    def __init__(
        self,
        *,
        ingest_url: str,
        stream_key: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ingest_url = self._validated_ingest_url(ingest_url)
        self._stream_key = self._validated_secret(stream_key)
        self._clock = clock
        self._lock = threading.RLock()
        self._status = self._unverified_status("not_refreshed")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> XBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        ingest_url = str(values.get("RAREIQ_X_INGEST_URL") or "").strip()
        stream_key = str(values.get("RAREIQ_X_STREAM_KEY") or "").strip()
        if not ingest_url or not stream_key:
            return None
        try:
            return cls(
                ingest_url=ingest_url,
                stream_key=stream_key,
                **kwargs,
            )
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without reading OBS or performing I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self, *, obs_route: Any = None) -> dict[str, Any]:
        """Compare the configured X source with OBS entirely in memory."""
        with self._lock:
            route_verified = self._matches_obs_route(obs_route)
            self._status = self._verified_status(
                now=self._clock(),
                route_verified=route_verified,
            )
            return dict(self._status)

    def _matches_obs_route(self, obs_route: Any) -> bool:
        matcher = getattr(obs_route, "matches_stream_route", None)
        if (
            obs_route is None
            or not bool(getattr(obs_route, "key_configured", False))
            or not callable(matcher)
        ):
            return False
        return bool(
            matcher(
                self._stream_key,
                self._ingest_url,
                provider=self.platform_id,
            )
        )

    @staticmethod
    def _validated_secret(value: str) -> str:
        secret = str(value or "").strip()
        if (
            not secret
            or len(secret) > 4096
            or any(character.isspace() for character in secret)
        ):
            raise ValueError("X stream key is invalid.")
        return secret

    @staticmethod
    def _validated_ingest_url(value: str) -> str:
        raw = str(value or "").strip()
        parsed = urlparse(raw)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("X Media Studio ingest URL is invalid.") from exc
        if (
            parsed.scheme.lower() not in {"rtmp", "rtmps"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.query
            or not parsed.path.strip("/")
        ):
            raise ValueError("X Media Studio ingest URL is invalid.")
        return raw

    def _verified_status(
        self,
        *,
        now: float,
        route_verified: bool,
    ) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": True,
            "verified_at": now,
            "verification_source": "x.media_studio_route",
            "configured": True,
            "connected": route_verified,
            "route_verified": route_verified,
            "destination_ready": route_verified,
            # X does not publish a general read-only Producer status API.
            "platform_live": False,
            "platform_live_supported": False,
            "connector_detail": (
                "Exact X Media Studio source and OBS route verified; "
                "platform live-status readback is unavailable."
                if route_verified
                else "X Media Studio source configured; the exact OBS route is not verified."
            ),
            "error_code": None,
        }

    def _unverified_status(self, error_code: str) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": False,
            "verified_at": self._clock(),
            "verification_source": "x.media_studio_route",
            "configured": True,
            "connected": False,
            "route_verified": False,
            "destination_ready": False,
            "platform_live": False,
            "platform_live_supported": False,
            "connector_detail": "X Media Studio route has not been checked against OBS.",
            "error_code": error_code,
        }
