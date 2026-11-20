"""Explicit public-client Twitch device authorization and encrypted-vault ownership.

No constructor/status operation contacts Twitch. Device codes remain in memory;
only a token verified against Twitch's fixed validation endpoint enters the vault.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
import uuid

import httpx


class _AccountError(Exception):
    """Constant, non-sensitive reason codes only."""


class TwitchAccountService:
    DEVICE_URL = "https://id.twitch.tv/oauth2/device"
    TOKEN_URL = "https://id.twitch.tv/oauth2/token"
    VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
    VERIFICATION_URL = "https://www.twitch.tv/activate"
    SCOPE = "user:read:chat"
    STREAM_SCOPE = "channel:read:stream_key"
    METADATA_SCOPE = "channel:manage:broadcast"
    CHAT_REPLY_SCOPE = "user:write:chat"
    DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
    MAX_BYTES = 16384
    CLOSE_TIMEOUT_SECONDS = 2
    MAX_POLLS = 360
    REFRESH_HEADROOM_SECONDS = 120
    _ID = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
    _LOGIN = re.compile(r"[a-z0-9_]{1,25}\Z")
    _USER = re.compile(r"[0-9]{1,24}\Z")
    _CODE = re.compile(r"[A-Za-z0-9-]{4,32}\Z")
    _SAFE_REASONS = frozenset({
        "app_setup_required", "invalid_provider_response", "invalid_provider_endpoint",
        "provider_unavailable", "provider_response_too_large", "provider_rate_limited",
        "authorization_rejected", "account_identity_mismatch", "chat_scope_required",
        "account_storage_unavailable", "authorization_required", "authorization_expired",
        "authorization_denied", "authorization_refresh_required", "account_state_changed",
        "streaming_scope_required", "metadata_scope_required", "account_disconnected", "chat_send_permission_required",
    })
    _STREAM_INFO_FAILURES = frozenset({
        "app_setup_required", "provider_unavailable", "invalid_provider_response",
        "provider_rate_limited", "account_storage_unavailable", "authorization_refresh_required",
        "authorization_rejected", "account_identity_mismatch",
    })

    def __init__(self, vault, *, client_id_provider=None, http_factory=None,
                 clock=time.time, sleep=asyncio.sleep):
        self._vault = vault
        self._client_id_provider = client_id_provider or (lambda: None)
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))
        self._clock, self._sleep = clock, sleep
        self._credential_lock = asyncio.Lock()
        self._generation = 0
        self._pending = self._task = None
        self._reason = None
        self._closed = False
        self._validated_access = self._rejected_access = None
        self._validated_until = 0

    @staticmethod
    def account_ref(record):
        return hashlib.sha256((record["client_id"] + ":" + record["channel_id"]).encode("ascii")).hexdigest()

    @staticmethod
    def _access_ref(record):
        return hashlib.sha256(record["access_token"].encode("ascii")).hexdigest()

    @staticmethod
    def _secret(value):
        if (not isinstance(value, str) or not 1 <= len(value) <= 4096
                or any(not 33 <= ord(c) <= 126 for c in value)):
            raise _AccountError("invalid_provider_response")
        return value

    @staticmethod
    def _number(value, minimum, maximum):
        if type(value) is not int or not minimum <= value <= maximum:
            raise _AccountError("invalid_provider_response")
        return value

    def _stored(self):
        try:
            value = self._vault.get("twitch")
        except Exception:
            raise _AccountError("account_storage_unavailable") from None
        return dict(value) if isinstance(value, dict) else None

    def _configured_client_id(self):
        try:
            value = self._client_id_provider()
        except Exception:
            raise _AccountError("app_setup_required") from None
        if value is None or value == "":
            return None
        if not isinstance(value, str) or not self._ID.fullmatch(value):
            raise _AccountError("app_setup_required")
        return value

    @staticmethod
    def _app_mismatch(configured_id, stored):
        return (configured_id is not None and isinstance(stored, dict)
                and stored.get("client_id") != configured_id)

    def _valid_record(self, value, *, headroom=0, allow_expired=False):
        if not isinstance(value, dict):
            return False
        try:
            if (not isinstance(value.get("client_id"), str) or not self._ID.fullmatch(value["client_id"])
                    or not isinstance(value.get("channel_login"), str) or not self._LOGIN.fullmatch(value["channel_login"])
                    or not isinstance(value.get("channel_id"), str) or not self._USER.fullmatch(value["channel_id"])
                    or not isinstance(value.get("scopes"), list) or self.SCOPE not in value["scopes"]
                    or value.get("token_type") != "bearer"):
                return False
            self._secret(value.get("access_token"))
            expires = value.get("expires_at")
            return (type(expires) in (int, float) and math.isfinite(expires)
                    and (allow_expired or expires > self._clock() + headroom))
        except _AccountError:
            return False

    def status(self):
        """Read cached/vault metadata only; never include tokens, IDs or device codes."""
        try:
            configured_id = self._configured_client_id()
            configuration_reason = None
        except _AccountError:
            configured_id, configuration_reason = None, "app_setup_required"
        try:
            stored = self._stored()
            mismatch = self._app_mismatch(configured_id, stored)
            authorized = self._valid_record(stored) and not mismatch and not configuration_reason
            if authorized and self._access_ref(stored) == self._rejected_access:
                authorized = False
            storage_reason = None
        except _AccountError:
            stored, authorized, storage_reason = None, False, "account_storage_unavailable"
            mismatch = False
        reason = self._reason
        if reason == "app_setup_required" and configured_id is not None:
            reason = "account_authorized" if authorized else "authorization_required"
        if reason == "account_authorized" and not authorized:
            reason = "authorization_refresh_required"
        result = {"platform": "twitch", "state": "authorized" if authorized else "not_authorized",
                  "reason": storage_reason or configuration_reason or ("account_identity_mismatch" if mismatch else None)
                            or reason or ("account_authorized" if authorized else "authorization_required"),
                  "authorized": authorized, "streaming_authorized": bool(authorized and self.STREAM_SCOPE in stored["scopes"]),
                  "metadata_authorized": bool(authorized and self.METADATA_SCOPE in stored["scopes"]),
                  "chat_reply_authorized": bool(authorized and self.CHAT_REPLY_SCOPE in stored["scopes"]),
                  "app_configured": configured_id is not None}
        if authorized:
            # Public account metadata describes stored authorization, not a live chat socket.
            result.update(public_label=stored["channel_login"], expires_at=stored["expires_at"],
                          account_ref=self.account_ref(stored))
        pending = self._pending
        if pending is not None and pending["generation"] == self._generation:
            if self._clock() >= pending["expires_at"]:
                result["reason"] = "authorization_expired"
            else:
                result.update(state="pending", reason="authorization_pending", flow_id=pending["flow_id"],
                              user_code=pending["user_code"], verification_url=self.VERIFICATION_URL,
                              expires_at=pending["expires_at"], poll_after=pending["interval"])
                result["authorization_kind"] = pending["authorization_kind"]
        elif self._closed:
            result.update(state="unavailable", reason="account_service_closed")
        elif storage_reason:
            result["state"] = "unavailable"
        return result

    async def _request(self, method, url, **kwargs):
        if url not in (self.DEVICE_URL, self.TOKEN_URL, self.VALIDATE_URL):
            raise _AccountError("invalid_provider_endpoint")
        client = None
        try:
            client = self._http_factory()
            async with client.stream(method, url, follow_redirects=False,
                                     timeout=httpx.Timeout(8, connect=3), **kwargs) as response:
                if response.status_code not in (200, 400, 401, 403):
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

    @staticmethod
    def _provider_error(value):
        # Twitch error messages can contain provider text. Only exact protocol
        # error values are interpreted; never display the raw response.
        error = value.get("error", value.get("message"))
        return error if error in ("authorization_pending", "slow_down", "access_denied",
                                 "authorization_declined", "expired_token", "invalid_grant") else None

    async def _verified_record(self, client_id, token, *, expected_channel=None, required_scopes=None):
        access = self._secret(token.get("access_token"))
        refresh = self._secret(token.get("refresh_token"))
        expires = self._number(token.get("expires_in"), 60, 31536000)
        if not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer":
            raise _AccountError("invalid_provider_response")
        code, value = await self._request("GET", self.VALIDATE_URL,
                                          headers={"Authorization": "OAuth " + access})
        if code != 200:
            raise _AccountError("authorization_rejected")
        scopes = value.get("scopes")
        if (value.get("client_id") != client_id or not isinstance(value.get("login"), str)
                or not self._LOGIN.fullmatch(value["login"]) or not isinstance(value.get("user_id"), str)
                or not self._USER.fullmatch(value["user_id"])
                or (expected_channel is not None and value["user_id"] != expected_channel)):
            raise _AccountError("account_identity_mismatch")
        if (not isinstance(scopes, list) or len(scopes) > 200 or self.SCOPE not in scopes
                or any(not isinstance(scope, str) or len(scope) > 160 for scope in scopes)):
            raise _AccountError("chat_scope_required")
        if required_scopes and not set(required_scopes).issubset(scopes):
            if self.CHAT_REPLY_SCOPE in required_scopes and self.CHAT_REPLY_SCOPE not in scopes:
                raise _AccountError("chat_send_permission_required")
            raise _AccountError("metadata_scope_required" if self.METADATA_SCOPE in required_scopes
                                and self.METADATA_SCOPE not in scopes else "streaming_scope_required")
        valid_expires = self._number(value.get("expires_in"), 60, 31536000)
        return {"client_id": client_id, "access_token": access, "refresh_token": refresh,
                "token_type": "bearer", "expires_at": self._clock() + min(expires, valid_expires),
                "scopes": list(scopes), "channel_login": value["login"],
                "channel_id": value["user_id"], "public_label": value["login"]}

    def _save(self, value, *, previous=None):
        try:
            self._vault.set("twitch", value)
        except Exception:
            raise _AccountError("account_storage_unavailable") from None
        # An owned validation/refresh is allowed to rotate the same saved login
        # while its permission upgrade waits for consent. Advance only that
        # exact pending snapshot; unrelated writers retain the stale-state guard.
        pending = self._pending
        if (isinstance(previous, dict) and pending is not None
                and self._current(pending["generation"])
                and pending["stored_before"] == previous
                and value.get("client_id") == previous.get("client_id") == pending["client_id"]
                and value.get("channel_id") == previous.get("channel_id")
                and (pending["expected_channel"] is None or value.get("channel_id") == pending["expected_channel"])):
            updated = {**previous, **value}
            if self._stored() == updated:
                pending["stored_before"] = updated

    def _current(self, generation):
        return not self._closed and generation == self._generation

    @classmethod
    def _safe_reason(cls, exc):
        value = str(exc) if isinstance(exc, _AccountError) else None
        return value if value in cls._SAFE_REASONS else "provider_unavailable"

    def _invalidate(self, reason):
        self._generation += 1
        self._pending = None
        self._reason = reason
        task, self._task = self._task, None
        return self._generation, task

    async def _stop_task(self, task):
        if task is not None and not task.done():
            task.cancel()
            done, _ = await asyncio.wait((task,), timeout=self.CLOSE_TIMEOUT_SECONDS)
            if done and not task.cancelled():
                task.exception()

    async def begin(self):
        return await self._begin(streaming=False)

    async def begin_streaming(self):
        return await self._begin(streaming=True)

    async def begin_metadata(self):
        return await self._begin(streaming=False, metadata=True)

    async def begin_replies(self):
        return await self._begin(streaming=False, replies=True)

    async def _begin(self, *, streaming, metadata=False, replies=False):
        if self._closed:
            return self.status()
        # Reserve this invocation's generation before waiting for old cleanup;
        # a newer Begin/Cancel must win even while that cleanup is stalled.
        generation, old_task = self._invalidate(None)
        await self._stop_task(old_task)
        if not self._current(generation):
            return self.status()
        try:
            client_id = self._client_id_provider()
            if not isinstance(client_id, str) or not self._ID.fullmatch(client_id):
                raise _AccountError("app_setup_required")
            stored_before = self._stored()
            scopes = [self.SCOPE]
            if streaming or (self._valid_record(stored_before, allow_expired=True)
                             and self.STREAM_SCOPE in stored_before["scopes"]):
                scopes.append(self.STREAM_SCOPE)
            if metadata or (self._valid_record(stored_before, allow_expired=True)
                            and self.METADATA_SCOPE in stored_before["scopes"]):
                scopes.append(self.METADATA_SCOPE)
            if replies or (self._valid_record(stored_before, allow_expired=True)
                           and self.CHAT_REPLY_SCOPE in stored_before["scopes"]):
                scopes.append(self.CHAT_REPLY_SCOPE)
            code, value = await self._request("POST", self.DEVICE_URL,
                                              data={"client_id": client_id, "scopes": " ".join(scopes)})
            if not self._current(generation):
                return self.status()
            if code != 200:
                raise _AccountError("app_setup_required")
            device_code = self._secret(value.get("device_code"))
            user_code = value.get("user_code")
            if not isinstance(user_code, str) or not self._CODE.fullmatch(user_code):
                raise _AccountError("invalid_provider_response")
            expires = self._number(value.get("expires_in"), 1, 1800)
            interval = max(5, self._number(value.get("interval", 5), 1, 60))
            self._pending = {"generation": generation, "flow_id": uuid.uuid4().hex,
                             "device_code": device_code, "client_id": client_id,
                             "user_code": user_code.upper(), "expires_at": self._clock() + expires,
                             "interval": interval, "stored_before": stored_before, "scopes": scopes,
                             "authorization_kind": "replies" if replies else "metadata" if metadata else "streaming" if streaming else "chat",
                             "expected_channel": stored_before["channel_id"] if (streaming or metadata or replies)
                                 and self._valid_record(stored_before, allow_expired=True) else None}
            self._task = asyncio.create_task(self._poll(generation), name="twitch-account-authorization")
        except asyncio.CancelledError:
            if self._current(generation):
                self._generation += 1
                self._pending = None
                self._reason = "authorization_cancelled"
            raise
        except Exception as exc:
            if self._current(generation):
                self._reason = self._safe_reason(exc)
        return self.status()

    async def _poll(self, generation):
        pending = self._pending
        try:
            for _ in range(self.MAX_POLLS):
                if not self._current(generation) or pending is not self._pending:
                    return
                remaining = pending["expires_at"] - self._clock()
                if remaining <= 0:
                    raise _AccountError("authorization_expired")
                await self._sleep(min(pending["interval"], remaining))
                if not self._current(generation) or pending is not self._pending:
                    return
                if self._clock() >= pending["expires_at"]:
                    raise _AccountError("authorization_expired")
                code, value = await self._request("POST", self.TOKEN_URL, data={
                    "client_id": pending["client_id"], "device_code": pending["device_code"],
                    "grant_type": self.DEVICE_GRANT, "scopes": " ".join(pending["scopes"])})
                if not self._current(generation):
                    return
                if self._clock() >= pending["expires_at"]:
                    raise _AccountError("authorization_expired")
                if code != 200:
                    error = self._provider_error(value)
                    if error == "authorization_pending":
                        continue
                    if error == "slow_down":
                        if pending["interval"] >= 60:
                            raise _AccountError("provider_rate_limited")
                        pending["interval"] = min(60, pending["interval"] + 5)
                        continue
                    if error in ("access_denied", "authorization_declined"):
                        raise _AccountError("authorization_denied")
                    if error in ("expired_token", "invalid_grant"):
                        raise _AccountError("authorization_expired")
                    raise _AccountError("authorization_rejected")
                record = await self._verified_record(pending["client_id"], value,
                    expected_channel=pending["expected_channel"], required_scopes=pending["scopes"])
                async with self._credential_lock:
                    if not self._current(generation) or pending is not self._pending:
                        return
                    if self._clock() >= pending["expires_at"]:
                        raise _AccountError("authorization_expired")
                    if self._configured_client_id() != pending["client_id"]:
                        raise _AccountError("account_identity_mismatch")
                    if self._stored() != pending["stored_before"]:
                        raise _AccountError("account_state_changed")
                    self._save(record)
                    self._mark_validated(record)
                    self._pending = None
                    self._reason = "account_authorized"
                return
            raise _AccountError("authorization_expired")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._current(generation):
                self._reason = self._safe_reason(exc)
                self._pending = None
        finally:
            if self._task is asyncio.current_task():
                self._task = None

    @staticmethod
    def _connector_credentials(record):
        return {"client_id": record["client_id"], "channel_login": record["channel_login"],
                "user_access_token": record["access_token"]}

    def _mark_validated(self, record):
        self._validated_access = self._access_ref(record)
        self._validated_until = min(self._clock() + 3600, record["expires_at"] - self.REFRESH_HEADROOM_SECONDS)
        self._rejected_access = None

    async def check(self):
        await self.ensure_credentials(force_validate=True)
        return self.status()

    async def ensure_credentials(self, *, force_validate=False):
        """Internal only: explicitly load/refresh credentials for a chat connection."""
        if self._closed:
            return None
        async with self._credential_lock:
            if self._closed:
                return None
            try:
                generation = self._generation
                configured_id = self._configured_client_id()
                stored = self._stored()
                if self._app_mismatch(configured_id, stored):
                    raise _AccountError("account_identity_mismatch")
                if self._valid_record(stored, headroom=self.REFRESH_HEADROOM_SECONDS):
                    if (not force_validate and self._validated_access == self._access_ref(stored)
                            and self._clock() < self._validated_until):
                        return self._connector_credentials(stored)
                    remaining = max(60, int(stored["expires_at"] - self._clock()))
                    record = await self._verified_record(stored["client_id"], {
                        "access_token": stored["access_token"], "refresh_token": stored.get("refresh_token"),
                        "token_type": "bearer", "expires_in": remaining}, expected_channel=stored["channel_id"])
                    if not self._current(generation) or self._stored() != stored:
                        return None
                    if self._app_mismatch(self._configured_client_id(), record):
                        raise _AccountError("account_identity_mismatch")
                    self._save(record, previous=stored)
                    self._mark_validated(record)
                    self._reason = "account_authorized"
                    return self._connector_credentials(record)
                if not self._valid_record(stored, allow_expired=True):
                    raise _AccountError("authorization_required")
                client_id = stored.get("client_id")
                if not isinstance(client_id, str) or not self._ID.fullmatch(client_id):
                    raise _AccountError("authorization_required")
                refresh = self._secret(stored.get("refresh_token"))
                code, value = await self._request("POST", self.TOKEN_URL, data={
                    "client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh})
                if code != 200:
                    raise _AccountError("authorization_refresh_required")
                record = await self._verified_record(client_id, value, expected_channel=stored.get("channel_id"))
                if not self._current(generation):
                    return None
                configured_id = self._configured_client_id()
                if self._app_mismatch(configured_id, record):
                    raise _AccountError("account_identity_mismatch")
                # A separate credential owner must not have changed the record
                # during a network wait. Never overwrite a newer account/token.
                current = self._stored()
                if current != stored:
                    if self._app_mismatch(configured_id, current):
                        raise _AccountError("account_identity_mismatch")
                    return self._connector_credentials(current) if self._valid_record(current) else None
                self._save(record, previous=stored)
                self._mark_validated(record)
                self._reason = "account_authorized"
                return self._connector_credentials(record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._current(generation):
                    return None
                self._reason = self._safe_reason(exc)
                if self._reason in {"authorization_rejected", "authorization_refresh_required",
                                    "chat_scope_required", "account_identity_mismatch"} and isinstance(locals().get("stored"), dict):
                    try:
                        self._rejected_access = self._access_ref(stored)
                    except (KeyError, TypeError, ValueError):
                        pass
                return None

    async def with_stream_info_access(self, operation, *, require_edit=False):
        """Run an internal operation with the current owned account; never publish credentials."""
        generation = self._generation
        try:
            configured = self._configured_client_id()
            original = self._stored()
            identity = (original.get("client_id"), original.get("channel_id")) if original else None
        except _AccountError as exc:
            reason = str(exc)
            raise _AccountError(reason if reason in self._STREAM_INFO_FAILURES else "authorization_required") from None
        credentials = await self.ensure_credentials()
        if credentials is None and self._current(generation):
            raise _AccountError(self._reason if self._reason in self._STREAM_INFO_FAILURES
                                else "authorization_required")
        try:
            changed = not self._current(generation) or self._configured_client_id() != configured
        except _AccountError:
            changed = True
        if changed:
            raise _AccountError("account_state_changed")
        async with self._credential_lock:
            try:
                record = self._stored()
            except _AccountError as exc:
                reason = str(exc)
                raise _AccountError(reason if reason in self._STREAM_INFO_FAILURES else "authorization_required") from None
            active = True
            def guard():
                try:
                    changed = (not active or not self._credential_lock.locked()
                               or not self._current(generation) or self._configured_client_id() != configured
                               or self._stored() != record)
                except _AccountError:
                    changed = True
                if changed:
                    raise _AccountError("account_state_changed")
                if (not self._valid_record(record) or self._app_mismatch(configured, record)
                        or (record["client_id"], record["channel_id"]) != identity
                        or record["access_token"] != credentials["user_access_token"]
                        or record["client_id"] != credentials["client_id"]
                        or record["channel_login"] != credentials["channel_login"]
                        or self._access_ref(record) == self._rejected_access):
                    raise _AccountError("authorization_required")
                if require_edit and self.METADATA_SCOPE not in record["scopes"]:
                    raise _AccountError("metadata_scope_required")
            guard()
            private = {**record, "scopes": list(record["scopes"])}
            try:
                return await operation(private, guard)
            finally:
                active = False

    def cached_chat_reply_context(self):
        """Internal, token-free capability projection; never refresh or request consent."""
        try:
            status = self.status()
            if status.get("authorized") is not True:
                return {"authorized": False}
            record = self._stored()
            return {"authorized": True, "channel_id": record["channel_id"],
                    "account_ref": status.get("account_ref"), "scopes": tuple(record["scopes"])}
        except Exception:
            return {"authorized": False}

    async def with_chat_reply_access(self, operation):
        async def owned(record, guard):
            guard()
            if self.CHAT_REPLY_SCOPE not in record["scopes"]:
                raise _AccountError("chat_send_permission_required")
            return await operation(record, guard)
        return await self.with_stream_info_access(owned, require_edit=False)

    async def disconnect(self):
        generation, task = self._invalidate("account_disconnected")
        await self._stop_task(task)
        async with self._credential_lock:
            if not self._current(generation):
                return self.status()
            try:
                stored = self._stored()
                if stored:
                    if self._valid_record(stored, allow_expired=True):
                        self._rejected_access = self._access_ref(stored)
                    # One atomic merge clears authorization while retaining public app setup.
                    self._save({"access_token": "", "refresh_token": "", "client_secret": "", "channel_id": "",
                        "channel_login": "", "public_label": "", "token_type": "", "scopes": [],
                        "expires_at": 0, "client_id": stored.get("client_id", "")})
                self._validated_access = self._rejected_access = None
                self._validated_until = 0
            except Exception as exc:
                self._reason = self._safe_reason(exc)
        return self.status()

    async def cancel(self):
        _, task = self._invalidate("authorization_cancelled")
        await self._stop_task(task)
        return self.status()

    async def close(self):
        self._closed = True
        return await self.cancel()
