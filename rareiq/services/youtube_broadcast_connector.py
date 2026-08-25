from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable

import httpx


class YouTubeBroadcastConnector:
    """Read-only YouTube Live monitor with exact, private OBS route matching."""

    platform_id = "youtube"

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
    BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
    STREAMS_URL = "https://www.googleapis.com/youtube/v3/liveStreams"
    READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

    TOKEN_EXPIRY_SKEW_SECONDS = 60.0
    MAX_LIST_PAGES = 4
    _CHANNEL_ID_PATTERN = re.compile(r"^UC[A-Za-z0-9_-]{20,30}$")

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_id: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._refresh_token = refresh_token.strip()
        self._channel_id = channel_id.strip()
        if not self._client_id or not self._client_secret or not self._refresh_token:
            raise ValueError("YouTube OAuth configuration is incomplete.")
        if not self._CHANNEL_ID_PATTERN.fullmatch(self._channel_id):
            raise ValueError("YouTube channel ID is invalid.")

        self._client = client or httpx.Client(
            timeout=httpx.Timeout(6.0, connect=3.0),
            follow_redirects=False,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._status = self._unverified_status("not_refreshed")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> YouTubeBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        client_id = str(values.get("RAREIQ_YOUTUBE_CLIENT_ID") or "").strip()
        client_secret = str(values.get("RAREIQ_YOUTUBE_CLIENT_SECRET") or "").strip()
        refresh_token = str(values.get("RAREIQ_YOUTUBE_REFRESH_TOKEN") or "").strip()
        channel_id = str(values.get("RAREIQ_YOUTUBE_CHANNEL_ID") or "").strip()
        if not (client_id and client_secret and refresh_token and channel_id):
            return None
        try:
            return cls(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                channel_id=channel_id,
                **kwargs,
            )
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without performing network I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self, *, obs_route: Any = None) -> dict[str, Any]:
        """Refresh channel, active-broadcast, and optional route evidence."""
        with self._lock:
            now = self._clock()
            try:
                token = self._valid_access_token(now)
                headers = {"Authorization": f"Bearer {token}"}
                channels = self._list_pages(
                    self.CHANNELS_URL,
                    params={"part": "id", "mine": "true", "maxResults": 50},
                    headers=headers,
                    max_pages=1,
                )
                channel_verified = any(
                    str(item.get("id") or "") == self._channel_id
                    for item in channels
                )
                if not channel_verified:
                    self._status = self._verified_status(
                        now=now,
                        connected=False,
                        platform_live=False,
                        route_verified=False,
                        error_code="channel_identity_mismatch",
                    )
                    return dict(self._status)

                active_broadcasts = self._broadcasts(
                    headers=headers,
                    broadcast_status="active",
                )
                active_live_stream_ids = {
                    str((item.get("contentDetails") or {}).get("boundStreamId") or "")
                    for item in active_broadcasts
                    if str(
                        (item.get("status") or {}).get("lifeCycleStatus") or ""
                    ).lower()
                    == "live"
                }
                active_live_stream_ids.discard("")
                route_verified, matched_route_live = self._verify_obs_route(
                    obs_route=obs_route,
                    headers=headers,
                    active_broadcasts=active_broadcasts,
                    active_live_stream_ids=active_live_stream_ids,
                )
                self._status = self._verified_status(
                    now=now,
                    connected=True,
                    platform_live=(
                        matched_route_live
                        if route_verified
                        else bool(active_live_stream_ids)
                    ),
                    route_verified=route_verified,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                self._clear_access_token()
                self._status = self._unverified_status(
                    "youtube_api_unavailable",
                    now=now,
                )
            return dict(self._status)

    def _valid_access_token(self, now: float) -> str:
        if (
            not self._access_token
            or now >= self._access_token_expires_at - self.TOKEN_EXPIRY_SKEW_SECONDS
        ):
            response = self._client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload.get("access_token") or "").strip()
            expires_in = float(payload.get("expires_in") or 0.0)
            granted_scope = str(payload.get("scope") or "").split()
            if (
                not token
                or expires_in <= self.TOKEN_EXPIRY_SKEW_SECONDS
                or (
                    granted_scope
                    and self.READONLY_SCOPE not in granted_scope
                )
            ):
                raise ValueError("YouTube returned an unusable access token.")
            self._access_token = token
            self._access_token_expires_at = now + expires_in
        return self._access_token

    def _broadcasts(
        self,
        *,
        headers: dict[str, str],
        broadcast_status: str,
    ) -> list[dict[str, Any]]:
        return self._list_pages(
            self.BROADCASTS_URL,
            params={
                "part": "id,contentDetails,status",
                "mine": "true",
                "broadcastStatus": broadcast_status,
                "broadcastType": "all",
                "maxResults": 50,
            },
            headers=headers,
        )

    def _verify_obs_route(
        self,
        *,
        obs_route: Any,
        headers: dict[str, str],
        active_broadcasts: list[dict[str, Any]],
        active_live_stream_ids: set[str],
    ) -> tuple[bool, bool]:
        if (
            obs_route is None
            or getattr(obs_route, "provider", None) != self.platform_id
            or not bool(getattr(obs_route, "key_configured", False))
            or not callable(getattr(obs_route, "matches_stream_key", None))
        ):
            return False, False

        streams = self._list_pages(
            self.STREAMS_URL,
            params={"part": "id,cdn,status", "mine": "true", "maxResults": 50},
            headers=headers,
        )
        upcoming_broadcasts = self._broadcasts(
            headers=headers,
            broadcast_status="upcoming",
        )
        bound_stream_ids = {
            str((item.get("contentDetails") or {}).get("boundStreamId") or "")
            for item in [*active_broadcasts, *upcoming_broadcasts]
        }
        bound_stream_ids.discard("")
        returned_ids = {str(item.get("id") or "") for item in streams}
        missing_ids = sorted(bound_stream_ids - returned_ids)
        if missing_ids:
            streams.extend(
                self._list_pages(
                    self.STREAMS_URL,
                    params={
                        "part": "id,cdn,status",
                        "id": ",".join(missing_ids[:50]),
                        "maxResults": 50,
                    },
                    headers=headers,
                    max_pages=1,
                )
            )

        route_verified = False
        matched_route_live = False
        for stream in streams:
            ingestion = (stream.get("cdn") or {}).get("ingestionInfo") or {}
            stream_name = str(ingestion.get("streamName") or "")
            if stream_name and obs_route.matches_stream_key(
                stream_name,
                provider=self.platform_id,
            ):
                route_verified = True
                matched_route_live = (
                    matched_route_live
                    or str(stream.get("id") or "") in active_live_stream_ids
                )
        return route_verified, matched_route_live

    def _list_pages(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(max_pages or self.MAX_LIST_PAGES):
            request_params = dict(params)
            if page_token:
                request_params["pageToken"] = page_token
            response = self._client.get(url, params=request_params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            page_items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(page_items, list) or not all(
                isinstance(item, dict) for item in page_items
            ):
                raise ValueError("YouTube API response is malformed.")
            items.extend(page_items)
            page_token = str(payload.get("nextPageToken") or "") or None
            if not page_token:
                break
        return items

    def _verified_status(
        self,
        *,
        now: float,
        connected: bool,
        platform_live: bool,
        route_verified: bool,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": True,
            "verified_at": now,
            "verification_source": "youtube.live_api",
            "configured": True,
            "connected": connected,
            "route_verified": route_verified,
            "destination_ready": connected,
            "platform_live": platform_live,
            "error_code": error_code,
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
            "verification_source": "youtube.live_api",
            "configured": True,
            "connected": False,
            "route_verified": False,
            "destination_ready": False,
            "platform_live": False,
            "error_code": error_code,
        }

    def _clear_access_token(self) -> None:
        self._access_token = None
        self._access_token_expires_at = 0.0
