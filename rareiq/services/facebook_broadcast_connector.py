from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


class FacebookBroadcastConnector:
    """Read-only Facebook Page identity and private OBS-route verifier.

    Meta's current Page ``live_videos`` edge does not support reads. This
    connector therefore verifies only claims that can be proved without
    creating or mutating a broadcast: Page identity and the locally supplied
    Facebook ingest route configured in OBS.
    """

    platform_id = "facebook"

    GRAPH_API_VERSION = "v26.0"
    GRAPH_API_ORIGIN = "https://graph.facebook.com"
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024
    _INGEST_HOSTS = frozenset(("live-api-s.facebook.com",))

    def __init__(
        self,
        *,
        page_id: str,
        page_access_token: str,
        ingest_url: str,
        stream_key: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._page_id = self._validated_page_id(page_id)
        self._page_access_token = self._validated_secret(
            page_access_token,
            label="Facebook Page access token",
        )
        self._ingest_url = self._validated_ingest_url(ingest_url)
        self._stream_key = self._validated_secret(
            stream_key,
            label="Facebook stream key",
        )
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
    ) -> FacebookBroadcastConnector | None:
        values = environment if environment is not None else os.environ
        configuration = {
            "page_id": str(values.get("RAREIQ_FACEBOOK_PAGE_ID") or "").strip(),
            "page_access_token": str(
                values.get("RAREIQ_FACEBOOK_PAGE_ACCESS_TOKEN") or ""
            ).strip(),
            "ingest_url": str(
                values.get("RAREIQ_FACEBOOK_INGEST_URL") or ""
            ).strip(),
            "stream_key": str(
                values.get("RAREIQ_FACEBOOK_STREAM_KEY") or ""
            ).strip(),
        }
        if not all(configuration.values()):
            return None
        try:
            return cls(**configuration, **kwargs)
        except ValueError:
            return None

    def cached_status(self) -> dict[str, Any]:
        """Return cached evidence without performing network I/O."""
        with self._lock:
            return dict(self._status)

    def refresh(self, *, obs_route: Any = None) -> dict[str, Any]:
        """Verify the Page and exact encoder route without mutating Meta."""
        with self._lock:
            now = self._clock()
            try:
                response = self._client.get(
                    f"{self.GRAPH_API_ORIGIN}/{self.GRAPH_API_VERSION}/{self._page_id}",
                    params={"fields": "id,name"},
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {self._page_access_token}",
                    },
                )
                response.raise_for_status()
                if len(response.content) > self.MAX_RESPONSE_BYTES:
                    raise ValueError("Meta Graph response exceeds the safety limit.")
                self._validate_page(response.json())
                route_verified = self._matches_obs_route(obs_route)
                self._status = self._verified_status(
                    now=now,
                    route_verified=route_verified,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                self._status = self._unverified_status(
                    "meta_graph_unavailable",
                    now=now,
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

    def _validate_page(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Meta Graph response is malformed.")
        if str(payload.get("id") or "").strip() != self._page_id:
            raise ValueError("Meta Page identity does not match configuration.")
        if not str(payload.get("name") or "").strip():
            raise ValueError("Meta Graph response has no Page name.")

    @staticmethod
    def _validated_page_id(value: str) -> str:
        page_id = str(value or "").strip()
        if not page_id.isdecimal() or len(page_id) > 32:
            raise ValueError("Facebook Page ID is invalid.")
        return page_id

    @staticmethod
    def _validated_secret(value: str, *, label: str) -> str:
        secret = str(value or "").strip()
        if not secret or len(secret) > 4096 or any(character.isspace() for character in secret):
            raise ValueError(f"{label} is invalid.")
        return secret

    @classmethod
    def _validated_ingest_url(cls, value: str) -> str:
        raw = str(value or "").strip()
        parsed = urlparse(raw)
        host = str(parsed.hostname or "").lower().rstrip(".")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Facebook ingest URL is invalid.") from exc
        if (
            parsed.scheme.lower() != "rtmps"
            or host not in cls._INGEST_HOSTS
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.strip("/")
            or parsed.query
        ):
            raise ValueError("Facebook ingest URL is invalid.")
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
            "verification_source": "meta.graph_page",
            "configured": True,
            "connected": True,
            "route_verified": route_verified,
            "destination_ready": True,
            # Meta Graph v26.0 does not expose a read operation on the Page
            # live_videos edge, so a platform-live claim would be fabricated.
            "platform_live": False,
            "platform_live_supported": False,
            "connector_detail": (
                "Facebook Page identity and exact OBS route verified; "
                "Meta live-status readback is unavailable."
                if route_verified
                else "Facebook Page identity verified; the exact OBS route is not verified."
            ),
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
            "verification_source": "meta.graph_page",
            "configured": True,
            "connected": False,
            "route_verified": False,
            "destination_ready": False,
            "platform_live": False,
            "platform_live_supported": False,
            "connector_detail": "Facebook Page authorization could not be verified.",
            "error_code": error_code,
        }
