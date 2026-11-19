"""Opt-in, broadcaster-owned Twitch chat observation; never sends chat or starts a show.

EventSub contracts: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
https://dev.twitch.tv/docs/eventsub/reference/chat#channel-chat-message
https://dev.twitch.tv/docs/authentication/validate-tokens/
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from datetime import datetime
import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import connect as websocket_connect

from rareiq.services.audience_service import TrustedAudienceEvent
from rareiq.services.viewer_chat_service import deliver_viewer_chat


class _ProviderError(Exception):
    """Only constant, non-sensitive reason codes cross the adapter boundary."""


class _NoRedirectConnect(websocket_connect):
    def process_redirect(self, exc):
        return exc


_QUIET_LOGGER = logging.Logger("rareiq.twitch_audience.transport")
_QUIET_LOGGER.disabled = True  # WebSocket debug logs otherwise include private chat frames.


async def _open_websocket(url):
    return await _NoRedirectConnect(url, open_timeout=8, close_timeout=2,
                                   max_size=65536, max_queue=16, compression=None,
                                   ping_interval=None, logger=_QUIET_LOGGER)


class TwitchAudienceConnector:
    """All I/O starts at explicit connect(); credentials come only from the host.

    credentials_provider returns client_id, channel_login, user_access_token.
    This first version intentionally supports the broadcaster's own token only.
    Cached status contains neither credential fragments nor channel/user identity.
    """

    CLOSE_TIMEOUT_SECONDS = 2
    SOCKET_URL = "wss://eventsub.wss.twitch.tv/ws"
    VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    SUBSCRIPTIONS_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"
    TYPE = "channel.chat.message"
    MAX_BYTES = 65536
    _ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
    _USER = re.compile(r"^[0-9]{1,24}$")
    _LOGIN = re.compile(r"^[a-z0-9_]{1,25}$")

    def __init__(self, audience_service, credentials_provider, *, http_factory=None,
                 websocket_factory=None, clock=time.time, transcript_sink=None):
        self._audience, self._credentials_provider = audience_service, credentials_provider
        self._transcript_sink = transcript_sink
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=3), follow_redirects=False))
        self._websocket_factory = websocket_factory or _open_websocket
        self._clock, self._lock = clock, asyncio.Lock()
        self._http = self._socket = self._task = None
        self._token = self._client_id = self._login = self._user_id = self._session_id = None
        self._owned = set()
        self._seen = OrderedDict()
        self._rate = deque()
        self._history = deque(maxlen=20)
        self._validated_until = self._expires_at = 0
        self._keepalive = 10
        self._state, self._reason = "not_connected", "explicit_connection_required"
        self._authorized = False
        self._received = self._rejected = 0
        self._last_attempt = float("-inf")
        self._cleanup_incomplete = False

    def cached_status(self):
        connected = self._state == "connected" and self._clock() < self._expires_at
        return {"platform": "twitch", "implemented": True, "state": self._state,
                "connected": connected, "authorized": self._authorized and connected,
                "verified": connected, "reason": self._reason,
                "events": ["first_chat", "featured_chat"],
                "available_events": ["first_chat", "featured_chat"] if connected else [],
                "viewer_join_supported": False, "received": self._received,
                "rejected": self._rejected, "cleanup_incomplete": self._cleanup_incomplete,
                "history": [dict(item) for item in self._history]}

    def _state_change(self, state, reason):
        self._state, self._reason = state, reason
        actor = "local_operator" if reason in ("validating_authorization", "disconnected_by_operator") else "twitch_provider"
        self._history.append({"at": self._clock(), "state": state, "reason": reason, "actor_kind": actor})

    @staticmethod
    def _identifier(value, pattern):
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise _ProviderError("invalid_provider_payload")
        return value

    async def connect(self):
        async with self._lock:
            if self._task and not self._task.done():
                return self.cached_status()
            if self._clock() - self._last_attempt < 5:
                return {**self.cached_status(), "reason": "connection_retry_limited"}
            self._last_attempt = self._clock()
            self._state_change("connecting", "validating_authorization")
            try:
                values = self._credentials_provider()
                if not isinstance(values, dict) or not all(values.get(k) for k in ("client_id", "channel_login", "user_access_token")):
                    raise _ProviderError("credentials_required")
                self._client_id = self._identifier(values.get("client_id"), self._ID)
                self._login = self._identifier(values.get("channel_login"), self._LOGIN)
                self._token = self._identifier(values.get("user_access_token"), self._ID)
                self._seen.clear()
                self._cleanup_incomplete = False
                self._http = self._http_factory()
                await self._validate()
                self._socket, self._session_id, self._keepalive = await self._open(self.SOCKET_URL)
                await self._subscribe()
                self._state_change("connected", "observing_chat")
                self._task = asyncio.create_task(self._run(), name="twitch-audience-observer")
            except asyncio.CancelledError:
                await self._cleanup()
                self._state_change("not_connected", "connection_cancelled")
                raise
            except Exception as exc:
                await self._cleanup()
                self._state_change("not_connected", self._safe_reason(exc))
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
    def _safe_reason(exc):
        return str(exc) if isinstance(exc, _ProviderError) else "provider_unavailable"

    async def _request(self, method, url, *, expected, **kwargs):
        async with self._http.stream(method, url, **kwargs) as response:
            if response.status_code != expected:
                if response.status_code in (401, 403):
                    raise _ProviderError("authorization_rejected")
                if response.status_code == 429:
                    raise _ProviderError("provider_rate_limited")
                raise _ProviderError("provider_request_failed")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > self.MAX_BYTES:
                    raise _ProviderError("provider_payload_too_large")
                data.extend(chunk)
            if expected == 204:
                return None
            value = json.loads(data)
            if not isinstance(value, dict):
                raise _ProviderError("invalid_provider_payload")
            return value

    async def _validate(self):
        value = await self._request("GET", self.VALIDATE_URL, expected=200,
                                    headers={"Authorization": "OAuth " + self._token})
        user_id = self._identifier(value.get("user_id"), self._USER)
        scopes, expires = value.get("scopes"), value.get("expires_in")
        if value.get("client_id") != self._client_id or value.get("login") != self._login:
            raise _ProviderError("token_channel_or_client_mismatch")
        if self._user_id is not None and self._user_id != user_id:
            raise _ProviderError("token_channel_or_client_mismatch")
        if not isinstance(scopes, list) or len(scopes) > 200 or "user:read:chat" not in scopes:
            raise _ProviderError("chat_scope_required")
        if type(expires) is not int or expires < 60:
            raise _ProviderError("token_expiring")
        self._user_id, self._authorized = user_id, True
        self._expires_at = self._clock() + expires
        self._validated_until = self._clock() + min(3600, expires - 30)

    def _headers(self):
        return {"Authorization": "Bearer " + self._token, "Client-Id": self._client_id}

    async def _subscribe(self):
        body = {"type": self.TYPE, "version": "1", "condition": {
            "broadcaster_user_id": self._user_id, "user_id": self._user_id},
            "transport": {"method": "websocket", "session_id": self._session_id}}
        value = await self._request("POST", self.SUBSCRIPTIONS_URL, expected=202,
                                    headers=self._headers(), json=body)
        records = value.get("data")
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise _ProviderError("invalid_subscription_response")
        record = records[0]
        subscription_id = self._identifier(record.get("id"), self._ID)
        # Remember only the ID returned by our own create request, even on a malformed response.
        self._owned.add(subscription_id)
        if (any(record.get(key) != body[key] for key in ("type", "version", "condition"))
                or not isinstance(record.get("transport"), dict)
                or any(record["transport"].get(key) != expected for key, expected in body["transport"].items())
                or record.get("status") != "enabled"):
            raise _ProviderError("invalid_subscription_response")

    def _parse(self, raw):
        if not isinstance(raw, str) or len(raw) > self.MAX_BYTES or len(raw.encode("utf-8")) > self.MAX_BYTES:
            raise _ProviderError("provider_payload_too_large")
        try:
            value = json.loads(raw)
            meta, payload = value["metadata"], value["payload"]
            if not isinstance(meta, dict) or not isinstance(payload, dict):
                raise ValueError()
            self._identifier(meta.get("message_id"), self._ID)
            stamp = meta["message_timestamp"]
            if not isinstance(stamp, str) or len(stamp) > 40 or not stamp.endswith("Z"):
                raise ValueError()
            occurred = datetime.fromisoformat(stamp[:-1] + "+00:00").timestamp()
            if not self._clock() - 120 <= occurred <= self._clock() + 5:
                raise ValueError()
        except (KeyError, TypeError, ValueError, RecursionError):
            raise _ProviderError("invalid_provider_payload") from None
        return meta, payload, occurred

    async def _open(self, url):
        socket = await self._websocket_factory(url)
        try:
            meta, payload, _ = self._parse(await asyncio.wait_for(socket.recv(), 8))
            session = payload.get("session", {})
            keepalive = session.get("keepalive_timeout_seconds")
            if meta.get("message_type") != "session_welcome" or session.get("status") != "connected":
                raise _ProviderError("invalid_provider_welcome")
            if type(keepalive) is not int or not 10 <= keepalive <= 600:
                raise _ProviderError("invalid_provider_welcome")
            return socket, self._identifier(session.get("id"), self._ID), keepalive
        except BaseException:
            await socket.close()
            raise

    @staticmethod
    def _reconnect_url(value):
        if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
            raise _ProviderError("invalid_reconnect_destination")
        parsed = urlsplit(value)
        if (parsed.scheme != "wss" or parsed.hostname != "eventsub.wss.twitch.tv"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.fragment or parsed.path not in ("", "/", "/ws")):
            raise _ProviderError("invalid_reconnect_destination")
        return value

    def _notification(self, meta, payload, occurred):
        sub, event = payload.get("subscription"), payload.get("event")
        if not isinstance(sub, dict) or not isinstance(event, dict):
            raise _ProviderError("invalid_provider_payload")
        transport = sub.get("transport", {})
        if (meta.get("subscription_type") != self.TYPE or meta.get("subscription_version") != "1"
                or sub.get("id") not in self._owned or sub.get("type") != self.TYPE
                or sub.get("version") != "1" or sub.get("status") != "enabled"
                or sub.get("condition") != {"broadcaster_user_id": self._user_id, "user_id": self._user_id}
                or not isinstance(transport, dict) or transport.get("method") != "websocket"
                or transport.get("session_id") != self._session_id
                or event.get("broadcaster_user_id") != self._user_id
                or event.get("source_broadcaster_user_id") not in (None, self._user_id)):
            raise _ProviderError("unexpected_subscription_event")
        event_id = self._identifier(event.get("message_id"), self._ID)
        subject = self._identifier(event.get("chatter_user_id"), self._USER)
        name = event.get("chatter_user_name")
        if not isinstance(name, str) or not 1 <= len(name) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            raise _ProviderError("invalid_provider_payload")
        if event_id in self._seen:
            return
        if self._transcript_sink is not None:
            message = event.get("message")
            deliver_viewer_chat(self._transcript_sink, "twitch", self._user_id,
                               event_id, subject, name,
                               message.get("text") if isinstance(message, dict) else None, occurred)
        # The optional volatile transcript never enters audience storage.
        accepted = self._audience.accept(TrustedAudienceEvent("twitch", self._user_id,
            event_id, subject, name, "chat", occurred))
        if accepted.get("ok"):
            self._seen[event_id] = None
            if len(self._seen) > 4096:
                self._seen.popitem(last=False)
            self._received += int(not accepted.get("duplicate"))
        else:
            self._rejected += 1

    def _handle(self, raw, *, migrating=False):
        now = self._clock()
        while self._rate and self._rate[0] <= now - 1:
            self._rate.popleft()
        if len(self._rate) >= 200:
            raise _ProviderError("provider_event_rate_exceeded")
        self._rate.append(now)
        try:
            meta, payload, occurred = self._parse(raw)
            kind = meta.get("message_type")
            if kind == "notification":
                self._notification(meta, payload, occurred)
            elif kind == "session_keepalive" and payload == {}:
                pass
            elif kind == "revocation":
                sub = payload.get("subscription", {})
                if sub.get("id") in self._owned:
                    raise _ProviderError("subscription_revoked")
                raise _ProviderError("unexpected_subscription_event")
            elif kind == "session_reconnect" and not migrating:
                session = payload.get("session", {})
                if session.get("id") != self._session_id or session.get("status") != "reconnecting":
                    raise _ProviderError("invalid_provider_payload")
                return self._reconnect_url(session.get("reconnect_url"))
            else:
                raise _ProviderError("unexpected_provider_event")
        except _ProviderError:
            self._rejected += 1
            raise
        return None

    async def _migrate(self, url):
        old = self._socket
        opening = asyncio.create_task(self._open(url))
        receiving = asyncio.create_task(old.recv())
        try:
            while not opening.done():
                done, _ = await asyncio.wait((opening, receiving), return_when=asyncio.FIRST_COMPLETED)
                if receiving in done:
                    try:
                        raw = receiving.result()
                    except Exception:
                        # Twitch can close the old connection as the replacement welcomes us.
                        await opening
                        break
                    self._handle(raw, migrating=True)
                    receiving = asyncio.create_task(old.recv())
            new_socket, session_id, keepalive = opening.result()
            # Drain the old transport's bounded queue before switching session IDs. The
            # replacement already buffers new events; delivery IDs suppress overlap.
            for _ in range(17):
                try:
                    raw = await asyncio.wait_for(receiving, .005)
                except (TimeoutError, ConnectionError):
                    break
                except Exception:
                    break
                self._handle(raw, migrating=True)
                receiving = asyncio.create_task(old.recv())
            self._socket, self._session_id, self._keepalive = new_socket, session_id, keepalive
            self._state_change("connected", "observing_chat")
        finally:
            receiving.cancel()
            opening.cancel()
            await asyncio.gather(receiving, opening, return_exceptions=True)
            if opening.done() and not opening.cancelled() and opening.exception() is None:
                replacement = opening.result()[0]
                if replacement is not self._socket:
                    await replacement.close()
            await old.close()

    async def _run(self):
        try:
            retries = 0
            while True:
                if self._clock() >= self._validated_until:
                    await self._validate()
                try:
                    timeout = max(.05, min(self._keepalive, self._validated_until - self._clock()))
                    raw = await asyncio.wait_for(self._socket.recv(), timeout)
                except Exception:
                    if self._clock() >= self._validated_until:
                        await self._validate()
                        continue
                    retries += 1
                    if retries > 3:
                        raise _ProviderError("connection_lost") from None
                    self._state_change("reconnecting", "connection_lost")
                    await self._delete_owned()
                    await self._socket.close()
                    await asyncio.sleep(.5 * retries)
                    self._socket, self._session_id, self._keepalive = await self._open(self.SOCKET_URL)
                    await self._subscribe()
                    self._state_change("connected", "observing_chat")
                    continue
                url = self._handle(raw)
                if url:
                    self._state_change("reconnecting", "provider_reconnect")
                    await self._migrate(url)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._state_change("not_connected", self._safe_reason(exc))
        finally:
            await self._cleanup()

    async def _delete_owned(self):
        owned, self._owned = self._owned, set()
        for subscription_id in owned:
            try:
                await self._request("DELETE", self.SUBSCRIPTIONS_URL, expected=204,
                                    headers=self._headers(), params={"id": subscription_id})
            except Exception:
                self._cleanup_incomplete = True

    async def _cleanup(self):
        try:
            if self._http:
                try:
                    await asyncio.wait_for(self._delete_owned(), 8)
                except Exception:
                    self._cleanup_incomplete = True
            if self._socket:
                try:
                    await asyncio.wait_for(self._socket.close(), self.CLOSE_TIMEOUT_SECONDS)
                except Exception:
                    self._cleanup_incomplete = True
            if self._http:
                try:
                    await asyncio.wait_for(self._http.aclose(), self.CLOSE_TIMEOUT_SECONDS)
                except Exception:
                    self._cleanup_incomplete = True
        finally:
            self._http = self._socket = None
            self._token = self._client_id = self._login = self._user_id = self._session_id = None
            self._authorized = False
            self._rate.clear()
