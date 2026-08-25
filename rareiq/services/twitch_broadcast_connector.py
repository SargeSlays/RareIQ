from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable

import httpx


class TwitchBroadcastConnector:
    """Read-only Twitch channel monitor with fail-closed cached evidence."""

    platform_id = "twitch"

    TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    USERS_URL = "https://api.twitch.tv/helix/users"
    STREAMS_URL = "https://api.twitch.tv/helix/streams"

    TOKEN_EXPIRY_SKEW_SECONDS = 60.0
    TOKEN_VALIDATION_INTERVAL_SECONDS = 60.0 * 60.0
    _LOGIN_PATTERN = re.compile(r"^[a-z0-9_]{1,25}$")

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        channel_login: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._channel_login = channel_login.strip().lower()
        if not self._client_id or not self._client_secret:
            raise ValueError("Twitch client configuration is incomplete.")
        if not self._LOGIN_PATTERN.fullmatch(self._channel_login):
            raise ValueError("Twitch channel login is invalid.")

        self._client = client or httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
        )
        self._clock = clock
        self._lock = threading.RLock()
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_validated_at = 0.0
        self._status = self._unverified_status("not_refreshed")

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> TwitchBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        client_id = str(values.get("RAREIQ_TWITCH_CLIENT_ID") or "").strip()
        client_secret = str(values.get("RAREIQ_TWITCH_CLIENT_SECRET") or "").strip()
        channel_login = str(values.get("RAREIQ_TWITCH_CHANNEL_LOGIN") or "").strip()
        if not (client_id and client_secret and channel_login):
            return None
        try:
            return cls(
                client_id=client_id,
                client_secret=client_secret,
                channel_login=channel_login,
                **kwargs,
            )
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without performing network I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self) -> dict[str, Any]:
        """Refresh public Twitch channel evidence with bounded network calls."""
        with self._lock:
            now = self._clock()
            try:
                token = self._valid_token(now)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Client-Id": self._client_id,
                }
                user_response = self._client.get(
                    self.USERS_URL,
                    params={"login": self._channel_login},
                    headers=headers,
                )
                user_response.raise_for_status()
                users = self._data_list(user_response)
                user = next(
                    (
                        item
                        for item in users
                        if str(item.get("login") or "").lower() == self._channel_login
                    ),
                    None,
                )
                if user is None or not str(user.get("id") or "").strip():
                    self._status = self._verified_status(
                        now=now,
                        connected=False,
                        platform_live=False,
                        error_code="channel_not_found",
                    )
                    return dict(self._status)

                user_id = str(user["id"]).strip()
                stream_response = self._client.get(
                    self.STREAMS_URL,
                    params={"user_id": user_id},
                    headers=headers,
                )
                stream_response.raise_for_status()
                streams = self._data_list(stream_response)
                platform_live = any(
                    str(item.get("user_id") or "") == user_id
                    and str(item.get("type") or "").lower() == "live"
                    for item in streams
                )
                self._status = self._verified_status(
                    now=now,
                    connected=True,
                    platform_live=platform_live,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                self._status = self._unverified_status("twitch_api_unavailable", now=now)
                self._discard_token_after_unauthorized()
            return dict(self._status)

    def _valid_token(self, now: float) -> str:
        if (
            not self._token
            or now >= self._token_expires_at - self.TOKEN_EXPIRY_SKEW_SECONDS
        ):
            self._request_token(now)
        elif now - self._token_validated_at >= self.TOKEN_VALIDATION_INTERVAL_SECONDS:
            self._validate_token(now)
        if not self._token:
            raise ValueError("Twitch token is unavailable.")
        return self._token

    def _request_token(self, now: float) -> None:
        response = self._client.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "").strip()
        expires_in = float(payload.get("expires_in") or 0.0)
        if not token or expires_in <= self.TOKEN_EXPIRY_SKEW_SECONDS:
            raise ValueError("Twitch returned an unusable token.")
        self._token = token
        self._token_expires_at = now + expires_in
        self._token_validated_at = 0.0
        self._validate_token(now)

    def _validate_token(self, now: float) -> None:
        if not self._token:
            raise ValueError("Twitch token is unavailable.")
        response = self._client.get(
            self.VALIDATE_URL,
            headers={"Authorization": f"OAuth {self._token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("client_id") or "") != self._client_id:
            self._clear_token()
            raise ValueError("Twitch token client identity mismatch.")
        expires_in = float(payload.get("expires_in") or 0.0)
        if expires_in <= self.TOKEN_EXPIRY_SKEW_SECONDS:
            self._clear_token()
            raise ValueError("Twitch token is too close to expiry.")
        self._token_expires_at = min(self._token_expires_at, now + expires_in)
        self._token_validated_at = now

    @staticmethod
    def _data_list(response: httpx.Response) -> list[dict[str, Any]]:
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("Twitch API response is malformed.")
        return data

    def _discard_token_after_unauthorized(self) -> None:
        # A failed request may be an expired or revoked token. Clearing all token
        # state makes the next explicit status refresh re-authenticate safely.
        self._clear_token()

    def _clear_token(self) -> None:
        self._token = None
        self._token_expires_at = 0.0
        self._token_validated_at = 0.0

    def _verified_status(
        self,
        *,
        now: float,
        connected: bool,
        platform_live: bool,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "verified": True,
            "verified_at": now,
            "verification_source": "twitch.helix",
            "configured": True,
            "connected": connected,
            # Public channel status cannot prove which destination OBS uses.
            "route_verified": False,
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
            "verification_source": "twitch.helix",
            "configured": True,
            "connected": False,
            "route_verified": False,
            "destination_ready": False,
            "platform_live": False,
            "error_code": error_code,
        }
