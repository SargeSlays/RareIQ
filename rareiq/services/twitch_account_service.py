"""Explicit public-client Twitch device authorization and encrypted-vault ownership.

No constructor/status operation contacts Twitch. Device codes remain in memory;
only a token verified against Twitch's fixed validation endpoint enters the vault.
"""
from __future__ import annotations

import asyncio
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
                  "authorized": authorized, "app_configured": configured_id is not None}
        if authorized:
            # Public account metadata describes stored authorization, not a live chat socket.
            result.update(public_label=stored["channel_login"], expires_at=stored["expires_at"])
        pending = self._pending
        if pending is not None and pending["generation"] == self._generation:
            if self._clock() >= pending["expires_at"]:
                result["reason"] = "authorization_expired"
            else:
                result.update(state="pending", reason="authorization_pending", flow_id=pending["flow_id"],
                              user_code=pending["user_code"], verification_url=self.VERIFICATION_URL,
                              expires_at=pending["expires_at"], poll_after=pending["interval"])
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

    async def _verified_record(self, client_id, token, *, expected_channel=None):
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
        valid_expires = self._number(value.get("expires_in"), 60, 31536000)
        return {"client_id": client_id, "access_token": access, "refresh_token": refresh,
                "token_type": "bearer", "expires_at": self._clock() + min(expires, valid_expires),
                "scopes": list(scopes), "channel_login": value["login"],
                "channel_id": value["user_id"], "public_label": value["login"]}

    def _save(self, value):
        try:
            self._vault.set("twitch", value)
        except Exception:
            raise _AccountError("account_storage_unavailable") from None

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
            code, value = await self._request("POST", self.DEVICE_URL,
                                              data={"client_id": client_id, "scopes": self.SCOPE})
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
                             "interval": interval, "stored_before": stored_before}
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
                    "grant_type": self.DEVICE_GRANT, "scopes": self.SCOPE})
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
                record = await self._verified_record(pending["client_id"], value)
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

    async def ensure_credentials(self):
        """Internal only: explicitly load/refresh credentials for a chat connection."""
        if self._closed:
            return None
        async with self._credential_lock:
            if self._closed:
                return None
            try:
                configured_id = self._configured_client_id()
                stored = self._stored()
                if self._app_mismatch(configured_id, stored):
                    raise _AccountError("account_identity_mismatch")
                if self._valid_record(stored, headroom=self.REFRESH_HEADROOM_SECONDS):
                    return self._connector_credentials(stored)
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
                if self._closed:
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
                self._save(record)
                self._reason = "account_authorized"
                return self._connector_credentials(record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._reason = self._safe_reason(exc)
                return None

    async def cancel(self):
        _, task = self._invalidate("authorization_cancelled")
        await self._stop_task(task)
        return self.status()

    async def close(self):
        self._closed = True
        return await self.cancel()
