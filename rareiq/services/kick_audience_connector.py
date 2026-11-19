"""Inactive-by-default Kick chat webhook receiver; never registers or deploys a webhook.

Contracts: https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md
https://github.com/KickEngineering/KickDevDocs/blob/main/events/event-types.md
https://api.kick.com/swagger/doc.yaml
The dashboard callback cannot be read back through the documented subscription API.
An approved host registration is therefore a separate prerequisite, never inferred.
"""
from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
import hashlib
import ipaddress
import json
import math
import re
import time
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import httpx

from rareiq.services.audience_service import TrustedAudienceEvent
from rareiq.services.viewer_chat_service import deliver_viewer_chat


class KickAudienceError(Exception):
    """Constant reason codes only; provider response text never crosses the boundary."""


@dataclass(frozen=True)
class KickWebhookRegistration:
    url: str
    app_id: str
    subscription_id: str
    dashboard_approved: bool = False


class KickAudienceConnector:
    """Only explicit connect() uses host credentials; no OAuth refresh/credential edits.

    credentials_provider supplies client_id, channel_slug, user_access_token from the
    existing host credential owner. It must serialize refreshes with that owner.
    It is not called until the host-approved callback registration is supplied.
    This slice attaches to an existing subscription and does not create/delete one.
    """

    BASE = "https://api.kick.com/public/v1/"
    TYPE = "chat.message.sent"
    MAX_BYTES = 65536
    CLOSE_TIMEOUT_SECONDS = 2
    CALLBACK_PATH = "/integrations/kick/events"
    ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
    IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
    SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,24}\Z")
    HEADERS = ("kick-event-message-id", "kick-event-subscription-id", "kick-event-signature",
               "kick-event-message-timestamp", "kick-event-type", "kick-event-version")

    def __init__(self, audience_service, credentials_provider, registration=None, *, http_factory=None,
                 clock=time.time, transcript_sink=None):
        self._audience, self._credentials_provider, self._registration = audience_service, credentials_provider, registration
        self._transcript_sink = transcript_sink
        self._factory = http_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(5, connect=3), follow_redirects=False))
        self._clock, self._lock = clock, asyncio.Lock()
        self._http = self._key = None
        self._token = self._client_id = self._channel_id = self._slug = None
        self._expires = self._validated = self._key_at = self._last_received = 0.0
        self._last_attempt = float("-inf")
        self._ready = False
        self._reason = "dashboard_registration_approval_required"
        self._seen, self._rate = OrderedDict(), deque()
        self._received = self._rejected = 0
        self._cleanup_incomplete = False

    def cached_status(self):
        now = self._clock()
        ready = self._ready and now < self._expires and now - self._validated < 60
        connected = ready and self._last_received > 0 and now - self._last_received <= 120
        reason = "authorization_refresh_required" if self._ready and not ready else "waiting_for_verified_chat" if ready and not connected else self._reason
        return {"platform": "kick", "implemented": True, "state": "connected" if connected else "ready" if ready else "not_connected",
                "connected": connected, "authorized": ready,
                "verified": connected, "reason": reason,
                "events": ["first_chat", "featured_chat"], "available_events": ["first_chat", "featured_chat"] if ready else [],
                "viewer_join_supported": False, "received": self._received, "rejected": self._rejected,
                "cleanup_incomplete": self._cleanup_incomplete,
                "dashboard_registration_approved": bool(self._registration and self._registration.dashboard_approved),
                "subscription_management": "external_registration_required"}

    @classmethod
    def _callback(cls, value):
        if not isinstance(value, str) or len(value) > 512:
            raise KickAudienceError("approved_https_callback_required")
        parsed = urlsplit(value)
        try:
            host = parsed.hostname or ""
            if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.port not in (None, 443) or parsed.path != cls.CALLBACK_PATH
                    or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host)
                    or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test", ".home.arpa"))):
                raise ValueError()
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None or parsed.netloc != host:
                raise ValueError()
        except ValueError:
            raise KickAudienceError("approved_https_callback_required") from None
        return value

    def accepts_url(self, url):
        return bool(self._ready and self._registration and url == self._registration.url)

    @staticmethod
    def _id(value):
        if type(value) is not int or not 0 < value < 2**63:
            raise KickAudienceError("invalid_provider_identity")
        return str(value)

    async def _request(self, method, endpoint, **kwargs):
        async with self._http.stream(method, self.BASE + endpoint, **kwargs) as response:
            if response.status_code != 200:
                raise KickAudienceError("provider_authorization_rejected" if response.status_code in (401, 403) else "provider_unavailable")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > self.MAX_BYTES:
                    raise KickAudienceError("provider_response_too_large")
                raw.extend(chunk)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
            return payload["data"]
        except (ValueError, KeyError, TypeError):
            raise KickAudienceError("invalid_provider_payload") from None

    async def _validate(self):
        values = self._credentials_provider()
        if not isinstance(values, dict):
            raise KickAudienceError("host_credentials_required")
        token, client_id, slug = (values.get(k) for k in ("user_access_token", "client_id", "channel_slug"))
        if (not isinstance(token, str) or not 1 <= len(token) <= 4096 or any(c.isspace() for c in token)
                or not isinstance(client_id, str) or not self.IDENTIFIER.fullmatch(client_id)
                or not isinstance(slug, str) or not self.SLUG.fullmatch(slug)):
            raise KickAudienceError("host_credentials_required")
        headers = {"Authorization": "Bearer " + token}
        auth = await self._request("POST", "token/introspect", headers=headers)
        if (not isinstance(auth, dict) or auth.get("active") is not True or auth.get("token_type") != "user"
                or auth.get("client_id") != client_id or type(auth.get("exp")) not in (int, float)
                or not math.isfinite(auth["exp"]) or auth["exp"] <= self._clock() + 30 or not isinstance(auth.get("scope"), str)
                or not {"user:read", "channel:read", "events:subscribe"}.issubset(auth["scope"].split())):
            raise KickAudienceError("owned_channel_events_scope_required")
        users = await self._request("GET", "users", headers=headers)
        channels = await self._request("GET", "channels", headers=headers)
        if not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict) or not isinstance(channels, list):
            raise KickAudienceError("owned_channel_required")
        channel_id = self._id(users[0].get("user_id"))
        if not any(isinstance(channel, dict) and channel.get("slug") == slug
                   and type(channel.get("broadcaster_user_id")) is int and str(channel["broadcaster_user_id"]) == channel_id for channel in channels):
            raise KickAudienceError("owned_channel_required")
        if self._channel_id is not None and (channel_id, client_id, slug) != (self._channel_id, self._client_id, self._slug):
            raise KickAudienceError("host_identity_changed")
        subscriptions = await self._request("GET", "events/subscriptions", headers=headers)
        binding = self._registration
        if not isinstance(subscriptions, list) or not any(isinstance(sub, dict)
                and sub.get("id") == binding.subscription_id and sub.get("app_id") == binding.app_id
                and str(sub.get("broadcaster_user_id")) == channel_id and type(sub.get("broadcaster_user_id")) is int
                and sub.get("method") == "webhook" and sub.get("event") == self.TYPE
                and type(sub.get("version")) is int and sub["version"] == 1 for sub in subscriptions):
            raise KickAudienceError("owned_chat_subscription_required")
        self._token, self._client_id, self._channel_id, self._slug = token, client_id, channel_id, slug
        self._expires, self._validated = float(auth["exp"]), self._clock()

    async def _fetch_key(self):
        data = await self._request("GET", "public-key")
        try:
            pem = data.get("public_key") if isinstance(data, dict) else None
            if not isinstance(pem, str) or len(pem) > 8192:
                raise ValueError()
            key = serialization.load_pem_public_key(pem.encode("ascii"))
            if not isinstance(key, rsa.RSAPublicKey) or not 2048 <= key.key_size <= 8192:
                raise ValueError()
            self._key = key
            self._key_at = self._clock()
        except (ValueError, TypeError, UnicodeError):
            raise KickAudienceError("invalid_provider_public_key") from None

    async def connect(self):
        async with self._lock:
            if self.cached_status()["authorized"]:
                return self.cached_status()
            if self._clock() - self._last_attempt < 5:
                return {**self.cached_status(), "reason": "connection_retry_limited"}
            self._last_attempt = self._clock()
            try:
                registration = self._registration
                if not isinstance(registration, KickWebhookRegistration) or registration.dashboard_approved is not True:
                    raise KickAudienceError("dashboard_registration_approval_required")
                self._callback(registration.url)
                if not self.ULID.fullmatch(registration.subscription_id) or not self.ULID.fullmatch(registration.app_id):
                    raise KickAudienceError("approved_subscription_required")
                if self._http is None:
                    self._http = self._factory()
                    self._cleanup_incomplete = False
                await self._validate()
                await self._fetch_key()
                if not self._ready:
                    self._received = 0
                    self._last_received = 0
                self._ready, self._reason = True, "waiting_for_verified_chat"
            except asyncio.CancelledError:
                await self._disable("connection_cancelled")
                raise
            except Exception as exc:
                await self._disable(str(exc) if isinstance(exc, KickAudienceError) else "provider_unavailable")
            return self.cached_status()

    async def _disable(self, reason):
        self._ready, self._reason = False, reason
        self._token = self._client_id = self._channel_id = self._slug = self._key = None
        self._expires = self._validated = self._key_at = self._last_received = 0
        if self._http is not None:
            client, self._http = self._http, None
            try:
                await asyncio.wait_for(client.aclose(), self.CLOSE_TIMEOUT_SECONDS)
            except Exception:
                self._cleanup_incomplete = True

    async def disconnect(self):
        async with self._lock:
            await self._disable("disconnected_by_operator")
            return self.cached_status()

    close = disconnect

    def _timestamp(self, value):
        try:
            if not isinstance(value, str) or not 20 <= len(value) <= 40:
                raise ValueError()
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
            stamp = parsed.timestamp()
            if not self._clock() - 120 <= stamp <= self._clock() + 5:
                raise ValueError()
            return stamp
        except (ValueError, OverflowError):
            raise KickAudienceError("stale_provider_event") from None

    async def receive(self, headers, raw):
        async with self._lock:
            if not self._ready:
                return {"ok": False, "reason": "receiver_inactive"}, 503
            try:
                now = self._clock()
                while self._rate and now - self._rate[0] >= 60:
                    self._rate.popleft()
                if len(self._rate) >= 120:
                    return {"ok": False, "reason": "event_rate_limited"}, 429
                self._rate.append(now)
                if not isinstance(raw, bytes) or not 1 <= len(raw) <= self.MAX_BYTES:
                    raise KickAudienceError("invalid_event_body")
                if any(not isinstance(headers.get(key), str) for key in self.HEADERS):
                    raise KickAudienceError("invalid_event_headers")
                message_id, subscription_id = headers[self.HEADERS[0]], headers[self.HEADERS[1]]
                if not self.ULID.fullmatch(message_id) or subscription_id != self._registration.subscription_id or headers["kick-event-type"] != self.TYPE or headers["kick-event-version"] != "1":
                    raise KickAudienceError("unbound_event")
                timestamp = headers["kick-event-message-timestamp"]
                self._timestamp(timestamp)
                if len(headers["kick-event-signature"]) > 1400:
                    raise KickAudienceError("invalid_event_signature")
                try:
                    signature = base64.b64decode(headers["kick-event-signature"], validate=True)
                except ValueError:
                    raise KickAudienceError("invalid_event_signature") from None
                signed = message_id.encode("ascii") + b"." + timestamp.encode("ascii") + b"." + raw
                if now - self._key_at >= 300:
                    try:
                        await self._fetch_key()
                    except Exception:
                        await self._disable("provider_key_unavailable")
                        return {"ok": False, "reason": self._reason}, 503
                try:
                    self._key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
                except InvalidSignature:
                    if now - self._key_at < 30:
                        raise KickAudienceError("invalid_event_signature") from None
                    await self._fetch_key()
                    try:
                        self._key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
                    except InvalidSignature:
                        raise KickAudienceError("invalid_event_signature") from None
                if now >= self._expires or now - self._validated >= 60:
                    try:
                        await self._validate()
                    except Exception:
                        await self._disable("provider_authorization_expired")
                        return {"ok": False, "reason": self._reason}, 503
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get("broadcaster"), dict) or not isinstance(payload.get("sender"), dict):
                    raise KickAudienceError("invalid_chat_event")
                broadcaster, sender = payload["broadcaster"], payload["sender"]
                if self._id(broadcaster.get("user_id")) != self._channel_id or broadcaster.get("channel_slug") != self._slug or broadcaster.get("is_anonymous") is not False or sender.get("is_anonymous") is not False:
                    raise KickAudienceError("unbound_chat_event")
                chat_id, name = payload.get("message_id"), sender.get("username")
                if not isinstance(chat_id, str) or not self.IDENTIFIER.fullmatch(chat_id) or not isinstance(payload.get("content"), str) or len(payload["content"]) > 4096:
                    raise KickAudienceError("invalid_chat_event")
                event = TrustedAudienceEvent("kick", self._channel_id, chat_id, self._id(sender.get("user_id")), name, "chat", self._timestamp(payload.get("created_at")))
                receipt = hashlib.sha256(signed).digest()
                while self._seen and now - next(iter(self._seen.values()))[0] > 125:
                    self._seen.popitem(last=False)
                if message_id in self._seen:
                    if self._seen[message_id][1] != receipt:
                        raise KickAudienceError("event_id_conflict")
                    return {"ok": True, "duplicate": True}, 200
                if self._transcript_sink is not None:
                    deliver_viewer_chat(self._transcript_sink, "kick", event.channel_id,
                                       event.event_id, event.subject_id, event.display_name,
                                       payload["content"], event.occurred_at)
                accepted = self._audience.accept(event)
                if accepted.get("ok") is not True:
                    self._rejected += 1
                    reason = accepted.get("reason")
                    allowed = {"audience_event_outside_session", "audience_event_capacity", "audience_participant_capacity"}
                    return {"ok": False, "reason": reason if reason in allowed else "audience_intake_rejected", "queued": 0}, 409
                self._seen[message_id] = (now, receipt)
                if len(self._seen) > 1000:
                    self._seen.popitem(last=False)
                self._received += 1
                self._last_received = now
                self._reason = "observing_verified_chat"
                return {"ok": True, "duplicate": bool(accepted.get("duplicate")), "queued": int(accepted.get("queued", 0))}, 200
            except Exception as exc:
                self._rejected += 1
                reason = str(exc) if isinstance(exc, KickAudienceError) else "invalid_provider_event"
                return {"ok": False, "reason": reason}, 400
