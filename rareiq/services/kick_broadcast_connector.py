from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable

import httpx


class KickBroadcastConnector:
    """Read-only Kick monitor with exact, private OBS route verification."""

    platform_id = "kick"

    TOKEN_URL = "https://id.kick.com/oauth/token"
    INTROSPECT_URL = "https://api.kick.com/public/v1/token/introspect"
    USERS_URL = "https://api.kick.com/public/v1/users"
    CHANNELS_URL = "https://api.kick.com/public/v1/channels"

    REQUIRED_SCOPES = frozenset(("user:read", "channel:read", "streamkey:read"))
    TOKEN_EXPIRY_SKEW_SECONDS = 60.0
    _SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,24}$")

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        channel_slug: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._refresh_token = refresh_token.strip()
        self._channel_slug = channel_slug.strip().lower()
        if not self._client_id or not self._client_secret or not self._refresh_token:
            raise ValueError("Kick OAuth configuration is incomplete.")
        if not self._SLUG_PATTERN.fullmatch(self._channel_slug):
            raise ValueError("Kick channel slug is invalid.")

        self._client = client or httpx.Client(
            timeout=httpx.Timeout(6.0, connect=3.0),
            follow_redirects=False,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._token_verified = False
        self._status = self._unverified_status("not_refreshed")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> KickBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        client_id = str(values.get("RAREIQ_KICK_CLIENT_ID") or "").strip()
        client_secret = str(values.get("RAREIQ_KICK_CLIENT_SECRET") or "").strip()
        refresh_token = str(values.get("RAREIQ_KICK_REFRESH_TOKEN") or "").strip()
        channel_slug = str(values.get("RAREIQ_KICK_CHANNEL_SLUG") or "").strip()
        if not (client_id and client_secret and refresh_token and channel_slug):
            return None
        try:
            return cls(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                channel_slug=channel_slug,
                **kwargs,
            )
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without performing network I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self, *, obs_route: Any = None) -> dict[str, Any]:
        """Refresh the authorized account, channel, route, and live evidence."""
        with self._lock:
            now = self._clock()
            try:
                token = self._valid_access_token(now)
                headers = {"Authorization": f"Bearer {token}"}
                users = self._data_list(self._client.get(self.USERS_URL, headers=headers))
                channels = self._data_list(
                    self._client.get(self.CHANNELS_URL, headers=headers)
                )
                user_ids = {
                    str(item.get("user_id") or "").strip()
                    for item in users
                    if str(item.get("user_id") or "").strip()
                }
                channel = next(
                    (
                        item
                        for item in channels
                        if str(item.get("slug") or "").strip().lower()
                        == self._channel_slug
                        and str(item.get("broadcaster_user_id") or "").strip()
                        in user_ids
                    ),
                    None,
                )
                if channel is None:
                    self._status = self._verified_status(
                        now=now,
                        connected=False,
                        platform_live=False,
                        route_verified=False,
                        error_code="channel_identity_mismatch",
                    )
                    return dict(self._status)

                stream = channel.get("stream")
                if not isinstance(stream, dict):
                    stream = {}
                route_verified = self._verify_obs_route(
                    obs_route=obs_route,
                    stream=stream,
                )
                self._status = self._verified_status(
                    now=now,
                    connected=True,
                    platform_live=bool(stream.get("is_live")),
                    route_verified=route_verified,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                self._clear_access_token()
                self._status = self._unverified_status(
                    "kick_api_unavailable",
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
            if not isinstance(payload, dict):
                raise ValueError("Kick token response is malformed.")
            token = str(payload.get("access_token") or "").strip()
            expires_in = float(payload.get("expires_in") or 0.0)
            if not token or expires_in <= self.TOKEN_EXPIRY_SKEW_SECONDS:
                raise ValueError("Kick returned an unusable access token.")
            rotated_refresh = str(payload.get("refresh_token") or "").strip()
            if rotated_refresh:
                self._refresh_token = rotated_refresh
            self._access_token = token
            self._access_token_expires_at = now + expires_in
            self._token_verified = False
        if not self._token_verified:
            self._verify_token(now)
        if not self._access_token:
            raise ValueError("Kick access token is unavailable.")
        return self._access_token

    def _verify_token(self, now: float) -> None:
        if not self._access_token:
            raise ValueError("Kick access token is unavailable.")
        response = self._client.post(
            self.INTROSPECT_URL,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        response.raise_for_status()
        payload = self._data_object(response)
        scopes = set(str(payload.get("scope") or "").split())
        expires_at = float(payload.get("exp") or 0.0)
        if (
            not bool(payload.get("active"))
            or str(payload.get("client_id") or "") != self._client_id
            or str(payload.get("token_type") or "").lower() != "user"
            or not self.REQUIRED_SCOPES.issubset(scopes)
            or expires_at <= now + self.TOKEN_EXPIRY_SKEW_SECONDS
        ):
            raise ValueError("Kick token cannot verify the configured channel route.")
        self._access_token_expires_at = min(self._access_token_expires_at, expires_at)
        self._token_verified = True

    def _verify_obs_route(self, *, obs_route: Any, stream: dict[str, Any]) -> bool:
        expected_key = str(stream.get("key") or "").strip()
        expected_server = str(stream.get("url") or "").strip()
        matcher = getattr(obs_route, "matches_stream_route", None)
        if (
            obs_route is None
            or not expected_key
            or not expected_server
            or not bool(getattr(obs_route, "key_configured", False))
            or not callable(matcher)
        ):
            return False
        return bool(
            matcher(
                expected_key,
                expected_server,
                provider=self.platform_id,
            )
        )

    @staticmethod
    def _data_list(response: httpx.Response) -> list[dict[str, Any]]:
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("Kick API response is malformed.")
        return data

    @staticmethod
    def _data_object(response: httpx.Response) -> dict[str, Any]:
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("Kick API response is malformed.")
        return data

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
            "verification_source": "kick.public_api",
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
            "verification_source": "kick.public_api",
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
        self._token_verified = False
