"""Explicit personal-app Kick OAuth; credentials stay with the encrypted vault.

Kick currently requires an owner's private app secret even with PKCE. Never ship
a shared developer secret in a desktop package. Listener parsing, state binding,
bounded callback receipts and cleanup reuse the audited installed-app transport.
No construction/status call opens a listener or contacts Kick.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
import secrets
import uuid
from urllib.parse import urlencode

import httpx

from rareiq.services.youtube_account_service import YouTubeAccountService, _AccountError


class KickAccountService(YouTubeAccountService):
    AUTHORIZE_URL = "https://id.kick.com/oauth/authorize"
    TOKEN_URL = "https://id.kick.com/oauth/token"
    INTROSPECT_URL = "https://id.kick.com/oauth/token/introspect"
    USERS_URL = "https://api.kick.com/public/v1/users"
    CHANNELS_URL = "https://api.kick.com/public/v1/channels"
    SCOPE = "user:read channel:read streamkey:read"
    SCOPES = frozenset(SCOPE.split())
    METADATA_SCOPE = "channel:write"
    CHAT_REPLY_SCOPE = "chat:write"
    REDIRECT_URI = "http://localhost:8770/callback"
    _CLIENT = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
    _CHANNEL = re.compile(r"[0-9]{1,24}\Z")
    _SLUG = re.compile(r"[a-z0-9][a-z0-9_-]{0,24}\Z")
    _SAFE_REASONS = YouTubeAccountService._SAFE_REASONS | {"streaming_scope_required", "kick_channel_required"}

    def __init__(self, *args, callback_port=8770, **kwargs):
        super().__init__(*args, **kwargs)
        # Port zero is a dependency-injection option for isolated listener tests.
        if type(callback_port) is not int or callback_port != 0 and not 1024 <= callback_port <= 65535:
            raise ValueError("invalid_callback_port")
        self._callback_port = callback_port
        self._validated_access = self._rejected_access = None
        self._validated_until = 0

    def _stored(self):
        try:
            value = self._vault.get("kick")
            return dict(value) if isinstance(value, dict) else None
        except Exception:
            raise _AccountError("account_storage_unavailable") from None

    @staticmethod
    def _mismatch(config, stored):
        return config is not None and isinstance(stored, dict) and any(
            stored.get(key) != config[key] for key in ("client_id", "client_secret"))

    @staticmethod
    def _access_ref(record):
        return hashlib.sha256(record["access_token"].encode("ascii")).hexdigest()

    @staticmethod
    def account_ref(record):
        return hashlib.sha256(("kick:" + record["client_id"] + ":" + record["channel_id"]).encode("ascii")).hexdigest()

    def _valid_record(self, value, *, headroom=0, allow_expired=False):
        try:
            if (not isinstance(value, dict) or self._configuration_record(value) is None
                    or not isinstance(value.get("channel_id"), str) or not self._CHANNEL.fullmatch(value["channel_id"])
                    or not isinstance(value.get("channel_slug"), str) or not self._SLUG.fullmatch(value["channel_slug"])
                    or not self._title(value.get("public_label")) or value.get("token_type") != "bearer"
                    or not isinstance(value.get("scopes"), list) or len(value["scopes"]) > 32
                    or not all(isinstance(scope, str) for scope in value["scopes"])
                    or not self.SCOPES.issubset(value["scopes"])):
                return False
            self._secret(value.get("access_token"))
            self._secret(value.get("refresh_token"))
            expires = value.get("expires_at")
            return (type(expires) in (int, float) and math.isfinite(expires)
                    and (allow_expired or expires > self._clock() + headroom))
        except _AccountError:
            return False

    def status(self):
        result = super().status()
        result["platform"] = "kick"
        result["streaming_authorized"] = False
        if result["authorized"]:
            try:
                stored = self._stored()
                config = self._configuration(stored)
                if (self._closed or config is None or self._mismatch(config, stored)
                        or not self._valid_record(stored) or self._access_ref(stored) == self._rejected_access):
                    result.update(authorized=False, metadata_authorized=False, chat_reply_authorized=False,
                                  state="unavailable" if self._closed else "pending" if self._pending else "not_authorized")
                    result.pop("public_label", None)
                else:
                    result.update(streaming_authorized=True, account_ref=self.account_ref(stored))
            except Exception:
                result.update(authorized=False, metadata_authorized=False, chat_reply_authorized=False, state="unavailable", reason="account_storage_unavailable")
        return result

    async def _request(self, method, url, **kwargs):
        client = None
        try:
            if url not in {self.TOKEN_URL, self.INTROSPECT_URL, self.USERS_URL, self.CHANNELS_URL}:
                raise _AccountError("provider_unavailable")
            client = self._http_factory()
            async with client.stream(method, url, follow_redirects=False,
                                     timeout=httpx.Timeout(8, connect=3), **kwargs) as response:
                if response.status_code not in {200, 400, 401, 403}:
                    raise _AccountError("provider_unavailable")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > self.MAX_BYTES:
                        raise _AccountError("provider_response_too_large")
                    raw.extend(chunk)
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise _AccountError("invalid_provider_response")
                return response.status_code, value
        except asyncio.CancelledError:
            raise
        except _AccountError:
            raise
        except Exception:
            raise _AccountError("provider_unavailable") from None
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.aclose(), self.CLOSE_TIMEOUT_SECONDS)
                except Exception:
                    pass

    async def _verified_record(self, config, token, *, prior=None, required_scopes=None):
        access = self._secret(token.get("access_token"))
        refresh = self._secret(token.get("refresh_token", prior.get("refresh_token") if prior else None))
        expires = token.get("expires_in")
        if (type(expires) is not int or not 60 <= expires <= 31536000
                or not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer"):
            raise _AccountError("invalid_provider_response")
        headers = {"Authorization": "Bearer " + access}
        code, payload = await self._request("POST", self.INTROSPECT_URL, headers=headers)
        auth = payload.get("data")
        if (code != 200 or not isinstance(auth, dict) or auth.get("active") is not True
                or auth.get("token_type") != "user" or auth.get("client_id") != config["client_id"]):
            raise _AccountError("authorization_rejected")
        scopes = auth.get("scope")
        if not isinstance(scopes, str) or len(scopes) > 4096 or not self.SCOPES.issubset(scopes.split()):
            raise _AccountError("streaming_scope_required")
        scopes = scopes.split()
        if len(scopes) > 32 or any(len(s) > 128 or any(not 33 <= ord(c) <= 126 for c in s) for s in scopes):
            raise _AccountError("invalid_provider_response")
        if required_scopes and not set(required_scopes).issubset(scopes):
            if self.CHAT_REPLY_SCOPE in required_scopes and self.CHAT_REPLY_SCOPE not in scopes:
                raise _AccountError("chat_send_permission_required")
            raise _AccountError("metadata_scope_required")
        deadline = auth.get("exp")
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= self._clock() + 30:
            raise _AccountError("authorization_rejected")
        code, users = await self._request("GET", self.USERS_URL, headers=headers)
        users = users.get("data")
        if code != 200 or not isinstance(users, list) or len(users) != 1 or not isinstance(users[0], dict):
            raise _AccountError("authorization_rejected")
        user_id = users[0].get("user_id")
        if type(user_id) is not int or user_id <= 0 or len(str(user_id)) > 24:
            raise _AccountError("invalid_provider_response")
        code, channels = await self._request("GET", self.CHANNELS_URL, headers=headers)
        channels = channels.get("data")
        if code != 200 or not isinstance(channels, list) or len(channels) != 1 or not isinstance(channels[0], dict):
            raise _AccountError("kick_channel_required")
        channel = channels[0]
        slug = channel.get("slug")
        if (type(channel.get("broadcaster_user_id")) is not int or channel["broadcaster_user_id"] != user_id
                or not isinstance(slug, str) or not self._SLUG.fullmatch(slug)):
            raise _AccountError("account_identity_mismatch")
        bound = prior or (self._pending.get("stored_before") if self._pending else None)
        if self._valid_record(bound, allow_expired=True) and bound["channel_id"] != str(user_id):
            raise _AccountError("account_identity_mismatch")
        return {**config, "access_token": access, "refresh_token": refresh, "token_type": "bearer",
                "scopes": list(dict.fromkeys(scopes)), "expires_at": min(self._clock() + expires, deadline),
                "channel_id": str(user_id), "channel_slug": slug, "public_label": slug}

    def _save(self, record, *, previous=None):
        try:
            self._vault.set("kick", record)
        except Exception:
            raise _AccountError("account_storage_unavailable") from None
        self._rejected_access = None
        self._validated_access = self._access_ref(record)
        self._validated_until = min(self._clock() + 3600, record["expires_at"] - 30)
        pending = self._pending
        if (previous is not None and pending is not None and self._current(pending)
                and pending["stored_before"] == previous
                and previous.get("client_id") == record["client_id"]
                and previous.get("channel_id") == record["channel_id"]):
            pending["stored_before"] = dict(record)

    async def begin(self):
        return await self._begin(metadata=False)

    async def _begin(self, *, metadata, replies=False):
        if self._closed:
            return self.status()
        generation, previous = self._invalidate(None)
        await self._dispose(previous)
        if self._closed or generation != self._generation:
            return self.status()
        pending = None
        try:
            stored = self._stored()
            config = self._configuration(stored)
            if config is None:
                raise _AccountError("app_setup_required")
            scopes = self.SCOPE.split()
            if metadata or (self._valid_record(stored, allow_expired=True)
                            and self.METADATA_SCOPE in stored["scopes"]):
                scopes.append(self.METADATA_SCOPE)
            if replies or (self._valid_record(stored, allow_expired=True)
                           and self.CHAT_REPLY_SCOPE in stored["scopes"]):
                scopes.append(self.CHAT_REPLY_SCOPE)
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            pending = {"generation": generation, "flow_id": uuid.uuid4().hex, "config": config,
                       "stored_before": stored, "state": secrets.token_urlsafe(32), "verifier": verifier,
                       "scopes": scopes, "authorization_kind": "replies" if replies else "metadata" if metadata else "chat",
                       "expires_at": self._clock() + self.FLOW_LIFETIME_SECONDS, "claimed": False,
                       "server": None, "writers": {}, "tasks": set(), "expiry_task": None}
            try:
                server = await asyncio.start_server(lambda reader, writer: self._handle_callback(reader, writer, pending),
                    host="127.0.0.1", port=self._callback_port, limit=self.MAX_CALLBACK_HEADERS)
            except OSError:
                raise _AccountError("callback_listener_unavailable") from None
            pending["server"] = server
            if self._closed or generation != self._generation:
                await self._dispose(pending)
                return self.status()
            port = server.sockets[0].getsockname()[1]
            pending["host"] = "localhost:" + str(port)
            pending["redirect_uri"] = "http://" + pending["host"] + "/callback"
            pending["authorization_url"] = self.AUTHORIZE_URL + "?" + urlencode({
                "response_type": "code", "client_id": config["client_id"], "redirect_uri": pending["redirect_uri"],
                "scope": " ".join(scopes), "state": pending["state"], "code_challenge": challenge, "code_challenge_method": "S256"})
            self._pending = pending
            pending["expiry_task"] = asyncio.create_task(self._expire(pending), name="kick-account-expiry")
        except asyncio.CancelledError:
            if generation == self._generation:
                self._invalidate("authorization_cancelled")
            await self._dispose(pending)
            raise
        except Exception as exc:
            if generation == self._generation:
                self._reason = self._safe_reason(exc)
            await self._dispose(pending)
        return self.status()

    def _callback_query(self, raw, pending):
        query = super()._callback_query(raw, pending)
        if set(query) - {"state", "code", "error", "error_description"}:
            raise ValueError()
        return query

    async def ensure_authorization(self, *, force_validate=False):
        if self._closed:
            return None
        generation = self._generation
        async with self._credential_lock:
            try:
                stored = self._stored()
                config = self._configuration(stored)
                if config is None:
                    raise _AccountError("app_setup_required")
                if self._mismatch(config, stored):
                    raise _AccountError("account_identity_mismatch")
                if not self._valid_record(stored, allow_expired=True):
                    raise _AccountError("authorization_required")
                if self._valid_record(stored, headroom=self.REFRESH_HEADROOM_SECONDS):
                    record = stored
                    if force_validate or self._validated_access != self._access_ref(stored) or self._clock() >= self._validated_until:
                        record = await self._verified_record(config, {"access_token": stored["access_token"],
                            "refresh_token": stored["refresh_token"], "token_type": "bearer",
                            "expires_in": max(60, int(stored["expires_at"] - self._clock()))}, prior=stored)
                else:
                    code, token = await self._request("POST", self.TOKEN_URL, data={
                        **config, "refresh_token": stored["refresh_token"], "grant_type": "refresh_token"})
                    if code != 200:
                        raise _AccountError("authorization_refresh_required")
                    record = await self._verified_record(config, token, prior=stored)
                if self._closed or generation != self._generation:
                    return None
                if self._stored() != stored or self._configuration() != config:
                    raise _AccountError("account_state_changed")
                if record != stored:
                    self._save(record, previous=stored)
                self._validated_access = self._access_ref(record)
                self._validated_until = min(self._clock() + 3600, record["expires_at"] - 30)
                self._rejected_access = None
                self._reason = "account_authorized"
                return {"access_token": record["access_token"], "channel_id": record["channel_id"],
                        "channel_slug": record["channel_slug"], "scopes": list(record["scopes"]), "expires_at": record["expires_at"]}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._closed and generation == self._generation:
                    self._reason = self._safe_reason(exc)
                    if self._reason in {"authorization_rejected", "authorization_refresh_required", "streaming_scope_required", "account_identity_mismatch"} and isinstance(locals().get("stored"), dict) and stored.get("access_token"):
                        self._rejected_access = self._access_ref(stored)
                return None

    async def ensure_credentials(self):
        return await self.ensure_authorization()

    async def check(self):
        await self.ensure_authorization(force_validate=True)
        return self.status()

    async def disconnect(self):
        generation, pending = self._invalidate("account_disconnected")
        await self._dispose(pending)
        async with self._credential_lock:
            if self._closed or generation != self._generation:
                return self.status()
            try:
                if self._stored():
                    self._vault.set("kick", {"access_token": "", "refresh_token": "", "token_type": "",
                        "scopes": [], "expires_at": 0, "channel_id": "", "channel_slug": "", "public_label": ""})
            except Exception:
                self._reason = "account_storage_unavailable"
        return self.status()
