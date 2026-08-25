from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


class RumbleBroadcastConnector:
    """Read-only Rumble Live Stream API monitor with private route matching."""

    platform_id = "rumble"

    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    _API_HOSTS = frozenset(("rumble.com", "www.rumble.com"))
    _ENTITY_TYPES = frozenset(("user", "channel"))

    def __init__(
        self,
        *,
        api_url: str,
        ingest_url: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._api_url = self._validated_api_url(api_url)
        self._ingest_url = self._validated_ingest_url(ingest_url)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(6.0, connect=3.0),
            follow_redirects=False,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._status = self._unverified_status("not_refreshed")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> RumbleBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        api_url = str(
            values.get("RAREIQ_RUMBLE_LIVE_STREAM_API_URL") or ""
        ).strip()
        ingest_url = str(values.get("RAREIQ_RUMBLE_INGEST_URL") or "").strip()
        if not api_url or not ingest_url:
            return None
        try:
            return cls(api_url=api_url, ingest_url=ingest_url, **kwargs)
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without performing network I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self, *, obs_route: Any = None) -> dict[str, Any]:
        """Refresh creator-owned API evidence without exposing its secret URL."""
        with self._lock:
            now = self._clock()
            try:
                response = self._client.get(
                    self._api_url,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                if len(response.content) > self.MAX_RESPONSE_BYTES:
                    raise ValueError("Rumble API response exceeds the safety limit.")
                payload = response.json()
                livestreams = self._validated_payload(payload)
                active_streams = [
                    item for item in livestreams if item.get("is_live") is True
                ]
                route_verified = any(
                    self._matches_obs_route(obs_route=obs_route, stream=item)
                    for item in active_streams
                )
                self._status = self._verified_status(
                    now=now,
                    connected=True,
                    platform_live=bool(active_streams),
                    route_verified=route_verified,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                self._status = self._unverified_status(
                    "rumble_api_unavailable",
                    now=now,
                )
            return dict(self._status)

    def _matches_obs_route(self, *, obs_route: Any, stream: dict[str, Any]) -> bool:
        expected_key = str(stream.get("stream_key") or "").strip()
        matcher = getattr(obs_route, "matches_stream_route", None)
        if (
            obs_route is None
            or not expected_key
            or not bool(getattr(obs_route, "key_configured", False))
            or not callable(matcher)
        ):
            return False
        return bool(
            matcher(
                expected_key,
                self._ingest_url,
                provider=self.platform_id,
            )
        )

    @classmethod
    def _validated_api_url(cls, value: str) -> str:
        raw = value.strip()
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Rumble Live Stream API URL is invalid.") from exc
        if (
            parsed.scheme.lower() != "https"
            or host not in cls._API_HOSTS
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.strip("/")
            or not parsed.query
        ):
            raise ValueError("Rumble Live Stream API URL is invalid.")
        return raw

    @staticmethod
    def _validated_ingest_url(value: str) -> str:
        raw = value.strip()
        parsed = urlparse(raw)
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("Rumble ingest URL is invalid.") from exc
        if (
            parsed.scheme.lower() not in {"rtmp", "rtmps"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("Rumble ingest URL is invalid.")
        return raw

    @classmethod
    def _validated_payload(cls, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("Rumble API response is malformed.")
        entity_type = str(payload.get("type") or "").strip().lower()
        if entity_type not in cls._ENTITY_TYPES:
            raise ValueError("Rumble API response has no valid entity type.")
        identity_key = "user_id" if entity_type == "user" else "channel_id"
        if not str(payload.get(identity_key) or "").strip():
            raise ValueError("Rumble API response has no creator identity.")
        livestreams = payload.get("livestreams")
        if not isinstance(livestreams, list) or not all(
            isinstance(item, dict) for item in livestreams
        ):
            raise ValueError("Rumble API response has invalid livestream data.")
        return livestreams

    def _verified_status(
        self,
        *,
        now: float,
        connected: bool,
        platform_live: bool,
        route_verified: bool,
    ) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": True,
            "verified_at": now,
            "verification_source": "rumble.live_stream_api",
            "configured": True,
            "connected": connected,
            "route_verified": route_verified,
            "destination_ready": connected,
            "platform_live": platform_live,
            "error_code": None,
        }

    def _unverified_status(
        self,
        error_code: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": False,
            "verified_at": self._clock() if now is None else now,
            "verification_source": "rumble.live_stream_api",
            "configured": True,
            "connected": False,
            "route_verified": False,
            "destination_ready": False,
            "platform_live": False,
            "error_code": error_code,
        }
