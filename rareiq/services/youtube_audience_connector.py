"""Explicitly connected, owner-authorized YouTube chat observer. No broadcast writes.

https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list
https://developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts/list
https://developers.google.com/identity/protocols/oauth2/web-server
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
import inspect
import math
import re
import time

import httpx

from rareiq.services.audience_service import TrustedAudienceEvent
from rareiq.services.viewer_chat_service import deliver_viewer_chat


class _ProviderError(Exception):
    def __init__(self, reason, *, retry_after=0):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


class YouTubeAudienceConnector:
    """Reuses the host's existing OAuth configuration; constructor/status do no I/O.

    credentials_provider returns client_id, client_secret, refresh_token, channel_id.
    The refresh grant binds this app; channels.list(mine=true) binds channel ownership.
    Optional authorization_provider supplies a service-owned access token instead;
    only an explicit None selects the legacy refresh path. Both modes recheck
    ownership, and a running observer cannot silently change its channel.
    No access/refresh tokens, chat bodies, names or account IDs appear in cached status.
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
    BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
    MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"
    READ_SCOPES = {"https://www.googleapis.com/auth/youtube.readonly",
                   "https://www.googleapis.com/auth/youtube",
                   "https://www.googleapis.com/auth/youtube.force-ssl"}
    MAX_BYTES, MAX_ITEMS = 262144, 200
    MIN_POLL_SECONDS = 10
    CLOSE_TIMEOUT_SECONDS = 2
    _CHANNEL = re.compile(r"^UC[A-Za-z0-9_-]{20,30}$")
    _ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")

    def __init__(self, audience_service, credentials_provider, *, http_factory=None,
                 clock=time.time, sleep=asyncio.sleep, transcript_sink=None, authorization_provider=None):
        self._audience, self._credentials_provider = audience_service, credentials_provider
        self._transcript_sink = transcript_sink
        self._authorization_provider = authorization_provider
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(6, connect=3), follow_redirects=False))
        self._clock, self._sleep, self._lock = clock, sleep, asyncio.Lock()
        self._http = self._task = self._credentials = self._access_token = None
        self._channel_id = self._broadcast_id = self._chat_id = self._page_token = None
        self._expires_at = self._event_floor = self._last_observed = 0
        self._poll_seconds = self.MIN_POLL_SECONDS
        self._retry_not_before = self._last_attempt = float("-inf")
        self._seen, self._history = OrderedDict(), deque(maxlen=20)
        self._state, self._reason = "not_connected", "explicit_connection_required"
        self._authorized, self._cleanup_incomplete = False, False
        self._received = self._rejected = 0

    def cached_chat_reply_target(self):
        status = self.cached_status()
        return {"channel_id": self._channel_id, "live_chat_id": self._chat_id} if status["connected"] and status["verified"] else None

    def cached_status(self):
        connected = (self._state == "connected" and self._authorized and self._clock() < self._expires_at
                     and self._clock() - self._last_observed <= max(30, self._poll_seconds + 15))
        return {"platform": "youtube", "implemented": True, "state": self._state,
                "connected": connected, "authorized": connected, "verified": connected,
                "reason": self._reason, "events": ["first_chat", "featured_chat"],
                "available_events": ["first_chat", "featured_chat"] if connected else [],
                "viewer_join_supported": False, "received": self._received, "rejected": self._rejected,
                "poll_interval_seconds": self._poll_seconds,
                "retry_after_seconds": max(0, round(self._retry_not_before - self._clock())) if self._retry_not_before > self._clock() else 0,
                "cleanup_incomplete": self._cleanup_incomplete,
                "history": [dict(row) for row in self._history]}

    def _state_change(self, state, reason):
        self._state, self._reason = state, reason
        self._history.append({"at": self._clock(), "state": state, "reason": reason,
            "actor_kind": "local_operator" if reason in ("validating_authorization", "disconnected_by_operator") else "youtube_provider"})

    @staticmethod
    def _text(value, limit):
        if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise _ProviderError("invalid_provider_payload")
        return value

    @classmethod
    def _identifier(cls, value, *, channel=False):
        if not isinstance(value, str) or not (cls._CHANNEL if channel else cls._ID).fullmatch(value):
            raise _ProviderError("invalid_provider_payload")
        return value

    async def connect(self):
        async with self._lock:
            if self._task and not self._task.done():
                return self.cached_status()
            if self._clock() < self._retry_not_before or self._clock() - self._last_attempt < 5:
                return {**self.cached_status(), "reason": "connection_retry_limited"}
            self._last_attempt = self._clock()
            self._state_change("connecting", "validating_authorization")
            try:
                if self._authorization_provider is None:
                    self._load_legacy_credentials()
                self._http, self._cleanup_incomplete = self._http_factory(), False
                self._seen.clear()
                await self._authorize()
                await self._select_chat()
                # Initial list responses contain history. Seed the cursor only, even
                # when that history happens to be recent enough for normal intake.
                self._page(await self._messages(), seed=True)
                self._state_change("connected", "observing_chat")
                self._task = asyncio.create_task(self._run(), name="youtube-audience-observer")
            except asyncio.CancelledError:
                await self._cleanup()
                self._state_change("not_connected", "connection_cancelled")
                raise
            except Exception as exc:
                await self._cleanup()
                self._state_change("not_connected", self._reason_for(exc))
            return self.cached_status()

    async def disconnect(self):
        async with self._lock:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
            await self._cleanup()
            self._state_change("not_connected", "disconnected_by_operator")
            return self.cached_status()

    async def close(self):
        await self.disconnect()

    @staticmethod
    def _reason_for(exc):
        return exc.reason if isinstance(exc, _ProviderError) else "provider_unavailable"

    async def _request(self, method, url, **kwargs):
        async with self._http.stream(method, url, **kwargs) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > self.MAX_BYTES:
                    raise _ProviderError("provider_payload_too_large")
                raw.extend(chunk)
            if response.status_code != 200:
                reason = None
                try:
                    body = json.loads(raw)
                    error = body.get("error", {})
                    reason = error if isinstance(error, str) else error.get("errors", [{}])[0].get("reason")
                except (ValueError, TypeError, AttributeError, IndexError):
                    pass
                if reason in ("liveChatEnded", "liveChatDisabled", "liveChatNotFound"):
                    raise _ProviderError({"liveChatEnded": "chat_ended", "liveChatDisabled": "chat_disabled", "liveChatNotFound": "chat_unavailable"}[reason])
                if reason in ("quotaExceeded", "dailyLimitExceeded"):
                    raise _ProviderError("provider_quota_exhausted")
                if response.status_code == 429 or reason in ("rateLimitExceeded", "userRateLimitExceeded"):
                    header = response.headers.get("retry-after", "60")[:128]
                    if header.isdigit() and len(header) <= 10:
                        retry = int(header)
                    else:
                        try:
                            retry = int(parsedate_to_datetime(header).timestamp() - self._clock()) + 1
                        except (ValueError, TypeError, OverflowError):
                            retry = 60
                    retry = max(60, retry)
                    self._retry_not_before = self._clock() + retry
                    # Long provider cooldowns end this connection instead of keeping
                    # a background task alive or retrying earlier than requested.
                    raise _ProviderError("provider_rate_limited", retry_after=retry if retry <= 3600 else 0)
                if response.status_code in (400, 401, 403):
                    raise _ProviderError("authorization_rejected")
                if response.status_code >= 500:
                    raise _ProviderError("provider_unavailable", retry_after=10)
                raise _ProviderError("provider_request_failed")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise _ProviderError("invalid_provider_payload")
            return value

    def _headers(self):
        return {"Authorization": "Bearer " + self._access_token}

    def _load_legacy_credentials(self):
        raw = self._credentials_provider()
        fields = ("client_id", "client_secret", "refresh_token", "channel_id")
        if not isinstance(raw, dict) or not all(raw.get(key) for key in fields):
            raise _ProviderError("credentials_required")
        values = {key: self._text(raw[key], 4096) for key in fields}
        channel = self._identifier(values["channel_id"], channel=True)
        if self._channel_id is not None and self._channel_id != channel:
            raise _ProviderError("channel_identity_mismatch")
        self._credentials, self._channel_id = values, channel

    async def _authorize(self):
        authorization = None
        if self._authorization_provider is not None:
            try:
                authorization = self._authorization_provider()
                if inspect.isawaitable(authorization):
                    authorization = await authorization
            except asyncio.CancelledError:
                raise
            except Exception:
                raise _ProviderError("authorization_refresh_required") from None
        if authorization is None:
            # None is an explicit legacy-mode selection, never an error fallback.
            if self._credentials is None:
                self._load_legacy_credentials()
            token = await self._request("POST", self.TOKEN_URL, data={
                key: self._credentials[key] for key in ("client_id", "client_secret", "refresh_token")
            } | {"grant_type": "refresh_token"})
            expires, scopes = token.get("expires_in"), token.get("scope")
            if type(expires) is not int or not 60 < expires <= 86400 or token.get("token_type", "").lower() != "bearer":
                raise _ProviderError("invalid_access_token")
            if not isinstance(scopes, str) or len(scopes) > 8192 or not self.READ_SCOPES.intersection(scopes.split()):
                raise _ProviderError("chat_scope_required")
            self._access_token = self._text(token.get("access_token"), 8192)
            self._expires_at = self._clock() + expires
        else:
            if not isinstance(authorization, dict) or set(authorization) != {"access_token", "channel_id", "expires_at", "scopes"}:
                raise _ProviderError("invalid_access_token")
            channel = self._identifier(authorization["channel_id"], channel=True)
            if self._channel_id is not None and self._channel_id != channel:
                raise _ProviderError("channel_identity_mismatch")
            expires, scopes = authorization["expires_at"], authorization["scopes"]
            if (type(expires) not in (int, float) or not math.isfinite(expires)
                    or not self._clock() < expires <= self._clock() + 86400):
                raise _ProviderError("invalid_access_token")
            if (not isinstance(scopes, list) or not 0 < len(scopes) <= 32
                    or any(not isinstance(scope, str) or not 0 < len(scope) <= 128
                           or any(not 33 <= ord(char) <= 126 for char in scope) for scope in scopes)
                    or not self.READ_SCOPES.intersection(scopes)):
                raise _ProviderError("chat_scope_required")
            self._authorized = False
            self._channel_id, self._credentials = channel, None
            self._access_token = self._text(authorization["access_token"], 8192)
            self._expires_at = expires
        value = await self._request("GET", self.CHANNELS_URL, headers=self._headers(),
            params={"part": "id", "mine": "true", "maxResults": 50, "fields": "items(id),nextPageToken"})
        items = self._items(value, 50)
        if value.get("nextPageToken") or not any(item.get("id") == self._channel_id for item in items):
            raise _ProviderError("channel_identity_mismatch")
        self._authorized = True

    @staticmethod
    def _items(value, limit):
        items = value.get("items")
        if not isinstance(items, list) or len(items) > limit or not all(isinstance(item, dict) for item in items):
            raise _ProviderError("invalid_provider_payload")
        return items

    async def _select_chat(self):
        candidates, page, visited = [], None, set()
        for _ in range(4):
            params = {"part": "id,snippet,status", "broadcastStatus": "active", "broadcastType": "all", "maxResults": 50,
                      "fields": "nextPageToken,items(id,snippet(channelId,liveChatId),status(lifeCycleStatus))"}
            if page:
                params["pageToken"] = page
            value = await self._request("GET", self.BROADCASTS_URL, headers=self._headers(), params=params)
            for item in self._items(value, 50):
                snippet, status = item.get("snippet", {}), item.get("status", {})
                if not isinstance(snippet, dict) or not isinstance(status, dict):
                    raise _ProviderError("invalid_provider_payload")
                if snippet.get("channelId") == self._channel_id and status.get("lifeCycleStatus") == "live" and snippet.get("liveChatId"):
                    candidates.append((self._identifier(item.get("id")), self._text(snippet["liveChatId"], 512)))
            page = value.get("nextPageToken")
            if not page:
                break
            page = self._text(page, 2048)
            if page in visited:
                raise _ProviderError("invalid_provider_pagination")
            visited.add(page)
        if page:
            raise _ProviderError("broadcast_selection_limit")
        if len(candidates) != 1:
            raise _ProviderError("multiple_active_chats" if candidates else "no_active_chat")
        self._broadcast_id, self._chat_id = candidates[0]

    async def _verify_chat(self):
        value = await self._request("GET", self.BROADCASTS_URL, headers=self._headers(),
            params={"part": "id,snippet,status", "id": self._broadcast_id,
                    "fields": "items(id,snippet(channelId,liveChatId),status(lifeCycleStatus))"})
        items = self._items(value, 1)
        if len(items) != 1 or items[0].get("id") != self._broadcast_id:
            raise _ProviderError("chat_unavailable")
        item = items[0]
        if (item.get("snippet", {}).get("channelId") != self._channel_id
                or item.get("snippet", {}).get("liveChatId") != self._chat_id):
            raise _ProviderError("channel_identity_mismatch")
        if item.get("status", {}).get("lifeCycleStatus") != "live":
            raise _ProviderError("chat_ended")

    async def _messages(self):
        text_field = ",displayMessage" if self._transcript_sink is not None else ""
        params = {"part": "id,snippet,authorDetails", "liveChatId": self._chat_id, "maxResults": self.MAX_ITEMS,
                  # Preserve the identity-only request unless a transcript sink is installed.
                  "fields": "nextPageToken,pollingIntervalMillis,offlineAt,items(id,snippet(type,liveChatId,authorChannelId,publishedAt"
                            + text_field + "),authorDetails(channelId,displayName))"}
        if self._page_token:
            params["pageToken"] = self._page_token
        return await self._request("GET", self.MESSAGES_URL, headers=self._headers(), params=params)

    def _remember(self, event_id):
        self._seen[event_id] = None
        if len(self._seen) > 4096:
            self._seen.popitem(last=False)

    def _page(self, value, *, seed=False):
        if value.get("offlineAt"):
            raise _ProviderError("chat_ended")
        interval = value.get("pollingIntervalMillis")
        if type(interval) is not int or not 0 <= interval <= 3600000:
            raise _ProviderError("invalid_provider_poll_interval")
        page = self._text(value.get("nextPageToken"), 2048)
        items = self._items(value, self.MAX_ITEMS)
        self._poll_seconds = max(self.MIN_POLL_SECONDS, interval / 1000)
        now = self._clock()
        for item in items:
            try:
                event_id = self._identifier(item.get("id"))
                snippet = item.get("snippet")
                if not isinstance(snippet, dict) or snippet.get("liveChatId") != self._chat_id:
                    raise _ProviderError("unexpected_chat_event")
                if event_id in self._seen:
                    continue
                if seed or snippet.get("type") != "textMessageEvent":
                    self._remember(event_id)
                    continue
                author = item.get("authorDetails", {})
                subject = self._identifier(snippet.get("authorChannelId"), channel=True)
                if not isinstance(author, dict) or author.get("channelId") != subject:
                    raise _ProviderError("unexpected_chat_author")
                name = author.get("displayName")
                if not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in name):
                    raise _ProviderError("invalid_provider_payload")
                stamp = snippet.get("publishedAt")
                if not isinstance(stamp, str) or len(stamp) > 40 or not stamp.endswith("Z"):
                    raise _ProviderError("invalid_provider_timestamp")
                occurred = datetime.fromisoformat(stamp[:-1] + "+00:00").timestamp()
                self._remember(event_id)
                if not max(self._event_floor, now - 120) < occurred <= now + 5:
                    self._rejected += 1
                    continue
                if self._transcript_sink is not None:
                    deliver_viewer_chat(self._transcript_sink, "youtube", self._channel_id,
                                       event_id, subject, name, snippet.get("displayMessage"), occurred)
                accepted = self._audience.accept(TrustedAudienceEvent("youtube", self._channel_id,
                    event_id, subject, name, "chat", occurred))
                if accepted.get("ok"):
                    self._received += int(not accepted.get("duplicate"))
                else:
                    self._rejected += 1
            except (ValueError, TypeError, OverflowError):
                self._rejected += 1
        self._page_token, self._last_observed = page, now
        if seed:
            self._event_floor = now

    async def _run(self):
        failures, delay = 0, self._poll_seconds
        try:
            while True:
                await self._sleep(delay)
                try:
                    if self._clock() >= self._expires_at - 60:
                        await self._authorize()
                        await self._verify_chat()
                    self._page(await self._messages(), seed=failures > 0)
                    failures = 0
                    if self._state != "connected":
                        self._state_change("connected", "observing_chat")
                    delay = self._poll_seconds
                except (httpx.TransportError, _ProviderError) as exc:
                    retry = exc.retry_after if isinstance(exc, _ProviderError) else 10
                    if not retry or failures >= 3:
                        raise
                    failures += 1
                    delay = max(self._poll_seconds, retry, failures * 10)
                    self._state_change("reconnecting", self._reason_for(exc))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state_change("not_connected", self._reason_for(exc))
        finally:
            await self._cleanup()

    async def _cleanup(self):
        try:
            if self._http:
                await asyncio.wait_for(self._http.aclose(), self.CLOSE_TIMEOUT_SECONDS)
        except Exception:
            self._cleanup_incomplete = True
        finally:
            self._http = self._credentials = self._access_token = None
            self._channel_id = self._broadcast_id = self._chat_id = self._page_token = None
            self._authorized = False
