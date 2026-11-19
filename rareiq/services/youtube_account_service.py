"""Explicit installed-app Google OAuth with a private, temporary loopback callback.

Only begin() opens a listener. Google requests happen after its state/PKCE-bound
callback or an explicit ensure_credentials(); no token or callback code is logged.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx


class _AccountError(Exception):
    """Known, non-sensitive reason codes only."""


class YouTubeAccountService:
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
    SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
    FLOW_LIFETIME_SECONDS = 600
    MAX_BYTES = 16384
    MAX_CALLBACK_HEADERS = 8192
    CALLBACK_TIMEOUT_SECONDS = 5
    CLOSE_TIMEOUT_SECONDS = 2
    REFRESH_HEADROOM_SECONDS = 120
    _CLIENT = re.compile(r"[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com\Z")
    _CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{20,30}\Z")
    _HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
    _SAFE_REASONS = frozenset({
        "app_setup_required", "account_storage_unavailable", "provider_unavailable",
        "provider_response_too_large", "invalid_provider_response", "authorization_rejected",
        "authorization_required", "authorization_refresh_required", "authorization_expired",
        "authorization_denied", "account_identity_mismatch", "account_state_changed",
        "chat_scope_required", "offline_access_required", "youtube_channel_required",
        "channel_selection_required", "callback_listener_unavailable",
    })

    def __init__(self, vault, *, app_config_provider=None, http_factory=None,
                 clock=time.time, sleep=asyncio.sleep):
        self._vault, self._app_config_provider = vault, app_config_provider
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))
        self._clock, self._sleep = clock, sleep
        self._credential_lock = asyncio.Lock()
        self._generation = 0
        self._pending = None
        self._reason = None
        self._closed = False

    @staticmethod
    def _secret(value, limit=4096):
        if (not isinstance(value, str) or not 1 <= len(value) <= limit
                or any(not 33 <= ord(c) <= 126 for c in value)):
            raise _AccountError("invalid_provider_response")
        return value

    @staticmethod
    def _title(value):
        return (isinstance(value, str) and 1 <= len(value) <= 120 and bool(value.strip())
                and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value))

    @classmethod
    def _safe_reason(cls, exc):
        reason = str(exc) if isinstance(exc, _AccountError) else None
        return reason if reason in cls._SAFE_REASONS else "provider_unavailable"

    def _stored(self):
        try:
            value = self._vault.get("youtube")
        except Exception:
            raise _AccountError("account_storage_unavailable") from None
        return dict(value) if isinstance(value, dict) else None

    def _configuration(self, stored=None):
        try:
            raw = self._app_config_provider() if self._app_config_provider else (
                stored if stored is not None else self._stored())
            if (not isinstance(raw, dict) or not isinstance(raw.get("client_id"), str)
                    or not self._CLIENT.fullmatch(raw["client_id"])):
                return None
            secret = self._secret(raw.get("client_secret"))
            return {"client_id": raw["client_id"], "client_secret": secret}
        except Exception:
            raise _AccountError("app_setup_required") from None

    @staticmethod
    def _mismatch(config, stored):
        return (config is not None and isinstance(stored, dict)
                and stored.get("client_id") != config["client_id"])

    def _valid_record(self, value, *, headroom=0, allow_expired=False):
        try:
            if (not isinstance(value, dict) or self._configuration_record(value) is None
                    or not isinstance(value.get("channel_id"), str) or not self._CHANNEL.fullmatch(value["channel_id"])
                    or not self._title(value.get("public_label")) or value.get("token_type") != "bearer"
                    or not isinstance(value.get("scopes"), list) or len(value["scopes"]) > 32
                    or self.SCOPE not in value["scopes"]):
                return False
            self._secret(value.get("access_token"))
            self._secret(value.get("refresh_token"))
            expires = value.get("expires_at")
            return (type(expires) in (int, float) and math.isfinite(expires)
                    and (allow_expired or expires > self._clock() + headroom))
        except _AccountError:
            return False

    def _configuration_record(self, value):
        if (not isinstance(value.get("client_id"), str) or not self._CLIENT.fullmatch(value["client_id"])):
            return None
        self._secret(value.get("client_secret"))
        return True

    def _current(self, pending):
        return (not self._closed and self._pending is pending
                and pending["generation"] == self._generation)

    def authorization_url(self, flow_id):
        pending = self._pending
        if (pending is None or not self._current(pending) or pending["claimed"]
                or not isinstance(flow_id, str) or flow_id != pending["flow_id"]
                or self._clock() >= pending["expires_at"]):
            return None
        return pending["authorization_url"]

    def status(self):
        """Read local metadata only. Stored authorization is separate from live chat."""
        stored, config, reason = None, None, self._reason
        try:
            stored = self._stored()
            config = self._configuration(stored)
            mismatch = self._mismatch(config, stored)
            authorized = config is not None and not mismatch and self._valid_record(stored)
            if mismatch:
                reason = "account_identity_mismatch"
            elif reason == "app_setup_required" and config is not None:
                reason = "account_authorized" if authorized else "authorization_required"
            elif reason == "account_authorized" and not authorized:
                reason = "authorization_refresh_required"
        except _AccountError as exc:
            authorized, reason = False, self._safe_reason(exc)
        result = {"platform": "youtube", "state": "authorized" if authorized else "not_authorized",
                  "reason": reason or ("account_authorized" if authorized else "authorization_required"),
                  "authorized": authorized, "app_configured": config is not None}
        if authorized:
            result.update(public_label=stored["public_label"], expires_at=stored["expires_at"])
        pending = self._pending
        if pending is not None and self._current(pending):
            if self._clock() >= pending["expires_at"]:
                result["reason"] = "authorization_expired"
            else:
                result.update(state="pending", reason="validating_authorization" if pending["claimed"] else "authorization_pending",
                              flow_id=pending["flow_id"], expires_at=pending["expires_at"])
                if not pending["claimed"]:
                    result["authorization_url"] = pending["authorization_url"]
        if self._closed:
            result.update(state="unavailable", reason="account_service_closed")
        return result

    async def _request(self, method, url, **kwargs):
        client = None
        try:
            if url not in (self.TOKEN_URL, self.CHANNELS_URL):
                raise _AccountError("provider_unavailable")
            client = self._http_factory()
            async with client.stream(method, url, follow_redirects=False,
                                     timeout=httpx.Timeout(8, connect=3), **kwargs) as response:
                if response.status_code not in (200, 400, 401, 403):
                    raise _AccountError("provider_unavailable")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > self.MAX_BYTES:
                        raise _AccountError("provider_response_too_large")
                    data.extend(chunk)
                value = json.loads(data)
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

    async def _verified_record(self, config, token, *, prior=None):
        access = self._secret(token.get("access_token"))
        refresh = token.get("refresh_token", prior.get("refresh_token") if prior else None)
        if not refresh:
            raise _AccountError("offline_access_required")
        refresh = self._secret(refresh)
        expires = token.get("expires_in")
        if (type(expires) is not int or not 60 < expires <= 86400
                or not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer"):
            raise _AccountError("invalid_provider_response")
        raw_scope = token.get("scope")
        if raw_scope is None and prior is not None:
            scopes = prior["scopes"]
        elif isinstance(raw_scope, str) and len(raw_scope) <= 8192:
            scopes = raw_scope.split()
        else:
            raise _AccountError("chat_scope_required")
        if (len(scopes) > 32 or self.SCOPE not in scopes
                or any(not isinstance(scope, str) or len(scope) > 128
                       or any(not 33 <= ord(c) <= 126 for c in scope) for scope in scopes)):
            raise _AccountError("chat_scope_required")
        code, channels = await self._request("GET", self.CHANNELS_URL,
            headers={"Authorization": "Bearer " + access}, params={
                "part": "id,snippet", "mine": "true", "maxResults": 50,
                "fields": "items(id,snippet(title)),nextPageToken"})
        if code != 200:
            raise _AccountError("authorization_rejected")
        items = channels.get("items")
        if not isinstance(items, list) or len(items) > 50 or not all(isinstance(item, dict) for item in items):
            raise _AccountError("invalid_provider_response")
        if len(items) > 1 or channels.get("nextPageToken"):
            raise _AccountError("channel_selection_required")
        if not items:
            raise _AccountError("youtube_channel_required")
        channel = items[0]
        title = channel.get("snippet", {}).get("title") if isinstance(channel.get("snippet"), dict) else None
        if (not isinstance(channel.get("id"), str) or not self._CHANNEL.fullmatch(channel["id"])
                or not self._title(title)):
            raise _AccountError("invalid_provider_response")
        if prior is not None and channel["id"] != prior["channel_id"]:
            raise _AccountError("account_identity_mismatch")
        return {**config, "access_token": access, "refresh_token": refresh, "token_type": "bearer",
                "expires_at": self._clock() + expires, "scopes": list(scopes),
                "channel_id": channel["id"], "public_label": title[:80]}

    def _save(self, record):
        try:
            self._vault.set("youtube", record)
        except Exception:
            raise _AccountError("account_storage_unavailable") from None

    async def _dispose(self, pending):
        if pending is None:
            return
        server = pending.get("server")
        if server is not None:
            server.close()
        current = asyncio.current_task()
        tasks = {task for task in pending["tasks"] if task is not current and not task.done()}
        expiry = pending.get("expiry_task")
        if expiry is not None and expiry is not current and not expiry.done():
            tasks.add(expiry)
        for task in tasks:
            task.cancel()
        for writer in tuple(pending["writers"]):
            if pending["writers"].get(writer) is not current:
                writer.close()
        if tasks:
            await asyncio.wait(tasks, timeout=self.CLOSE_TIMEOUT_SECONDS)
        # Python 3.13 waits for client transports too. The active callback
        # must send its receipt and close its writer before this can complete.
        if server is not None and current not in pending["tasks"]:
            try:
                await asyncio.wait_for(server.wait_closed(), self.CLOSE_TIMEOUT_SECONDS)
            except Exception:
                pass

    def _invalidate(self, reason):
        self._generation += 1
        pending, self._pending = self._pending, None
        self._reason = reason
        return self._generation, pending

    async def begin(self):
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
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            pending = {"generation": generation, "flow_id": uuid.uuid4().hex,
                       "config": config, "stored_before": stored, "state": secrets.token_urlsafe(32),
                       "verifier": verifier, "expires_at": self._clock() + self.FLOW_LIFETIME_SECONDS,
                       "claimed": False, "server": None, "writers": {}, "tasks": set(), "expiry_task": None}
            try:
                server = await asyncio.start_server(lambda reader, writer: self._handle_callback(reader, writer, pending),
                    host="127.0.0.1", port=0, limit=self.MAX_CALLBACK_HEADERS)
            except OSError:
                raise _AccountError("callback_listener_unavailable") from None
            pending["server"] = server
            if self._closed or generation != self._generation:
                await self._dispose(pending)
                return self.status()
            port = server.sockets[0].getsockname()[1]
            pending["host"] = "127.0.0.1:" + str(port)
            pending["redirect_uri"] = "http://" + pending["host"] + "/callback"
            pending["authorization_url"] = self.AUTHORIZE_URL + "?" + urlencode({
                "client_id": config["client_id"], "redirect_uri": pending["redirect_uri"],
                "response_type": "code", "scope": self.SCOPE, "access_type": "offline", "prompt": "consent",
                "state": pending["state"], "code_challenge": challenge, "code_challenge_method": "S256"})
            self._pending = pending
            pending["expiry_task"] = asyncio.create_task(self._expire(pending), name="youtube-account-expiry")
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

    async def _finish(self, pending, reason):
        if self._current(pending):
            self._pending = None
            self._reason = reason
        await self._dispose(pending)

    async def _expire(self, pending):
        try:
            while self._current(pending):
                remaining = pending["expires_at"] - self._clock()
                if remaining <= 0:
                    await self._finish(pending, "authorization_expired")
                    return
                await self._sleep(remaining)
        except asyncio.CancelledError:
            pass

    def _callback_query(self, raw, pending):
        if len(raw) > self.MAX_CALLBACK_HEADERS:
            raise ValueError()
        lines = raw.decode("ascii").split("\r\n")
        method, target, version = lines[0].split(" ")
        if method != "GET" or version != "HTTP/1.1":
            raise ValueError()
        headers = {}
        for line in lines[1:]:
            if not line:
                continue
            name, separator, value = line.partition(":")
            if (not separator or not self._HEADER.fullmatch(name)
                    or any(ord(char) < 32 or ord(char) > 126 for char in value)):
                raise ValueError()
            headers.setdefault(name.lower(), []).append(value.strip())
        if (headers.get("host") != [pending["host"]] or "transfer-encoding" in headers
                or headers.get("content-length", ["0"]) != ["0"]):
            raise ValueError()
        if len(target) > 6144 or re.search(r"%(?![0-9A-Fa-f]{2})", target):
            raise ValueError()
        parsed = urlsplit(target)
        if (not target.startswith("/callback?") or parsed.scheme or parsed.netloc
                or parsed.path != "/callback" or parsed.fragment):
            raise ValueError()
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8,
                         encoding="utf-8", errors="strict")
        if (set(query) - {"state", "code", "error", "error_description", "scope", "authuser", "prompt"}
                or any(len(values) != 1 for values in query.values())
                or any(len(value[0]) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value[0]) for value in query.values())):
            raise ValueError()
        state = query.get("state", [""])[0]
        if not state or not hmac.compare_digest(state, pending["state"]):
            raise ValueError()
        if ("code" in query) == ("error" in query):
            raise ValueError()
        if "code" in query:
            try:
                self._secret(query["code"][0], 2048)
            except _AccountError:
                raise ValueError() from None
        elif not re.fullmatch(r"[a-z_]{1,80}", query["error"][0]):
            raise ValueError()
        return query

    async def _respond(self, writer, accepted):
        nonce = secrets.token_urlsafe(18)
        message = "Sign-in complete. Return to Producer, Please." if accepted else "Sign-in was not completed. Return to Producer, Please."
        body = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Producer, Please sign-in</title>"
                + '<script nonce="' + nonce + '">history.replaceState(null,"","/callback");</script><p>'
                + message + "</p></html>").encode("utf-8")
        headers = ("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\n"
                   "Referrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\n"
                   "Content-Security-Policy: default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
                   "form-action 'none'; script-src 'nonce-" + nonce + "'\r\nConnection: close\r\nContent-Length: "
                   + str(len(body)) + "\r\n\r\n").encode("ascii")
        writer.write(headers + body)
        await asyncio.wait_for(writer.drain(), self.CALLBACK_TIMEOUT_SECONDS)

    async def _handle_callback(self, reader, writer, pending):
        task = asyncio.current_task()
        pending["tasks"].add(task)
        pending["writers"][writer] = task
        accepted = False
        try:
            peer = writer.get_extra_info("peername")
            if len(pending["tasks"]) > 16 or not peer or peer[0] != "127.0.0.1":
                return
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), self.CALLBACK_TIMEOUT_SECONDS)
            query = self._callback_query(raw, pending)
            if not self._current(pending) or pending["claimed"]:
                raise ValueError()
            if self._clock() >= pending["expires_at"]:
                await self._finish(pending, "authorization_expired")
                return
            pending["claimed"] = True
            pending["server"].close()  # A valid state/code or denial consumes this listener once.
            if "error" in query:
                await self._finish(pending, "authorization_denied")
            else:
                code, value = await self._request("POST", self.TOKEN_URL, data={
                    **pending["config"], "code": query["code"][0], "grant_type": "authorization_code",
                    "redirect_uri": pending["redirect_uri"], "code_verifier": pending["verifier"]})
                if not self._current(pending):
                    return
                if self._clock() >= pending["expires_at"]:
                    raise _AccountError("authorization_expired")
                if code != 200:
                    raise _AccountError("authorization_rejected")
                record = await self._verified_record(pending["config"], value)
                async with self._credential_lock:
                    if not self._current(pending):
                        return
                    if self._clock() >= pending["expires_at"]:
                        raise _AccountError("authorization_expired")
                    config = self._configuration()
                    if config is None or self._mismatch(config, record):
                        raise _AccountError("account_identity_mismatch")
                    if self._stored() != pending["stored_before"]:
                        raise _AccountError("account_state_changed")
                    self._save(record)
                    accepted = True
                await self._finish(pending, "account_authorized")
        except asyncio.CancelledError:
            raise
        except _AccountError as exc:
            await self._finish(pending, self._safe_reason(exc))
        except (ValueError, UnicodeError, asyncio.LimitOverrunError, asyncio.IncompleteReadError, TimeoutError):
            pass  # Malformed/wrong-state requests never consume or expose a valid flow.
        except Exception:
            if pending["claimed"]:
                await self._finish(pending, "provider_unavailable")
        finally:
            try:
                await self._respond(writer, accepted)
            except (Exception, asyncio.CancelledError):
                pass
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), self.CLOSE_TIMEOUT_SECONDS)
            except (Exception, asyncio.CancelledError):
                pass
            pending["writers"].pop(writer, None)
            pending["tasks"].discard(task)

    @staticmethod
    def _connector_credentials(record, config):
        return {**config, "refresh_token": record["refresh_token"], "channel_id": record["channel_id"]}

    async def ensure_credentials(self):
        """Internal only: explicitly obtain/refresh the current owned channel credentials."""
        return await self._ensure_credentials()

    async def ensure_authorization(self):
        """Internal access token for the observer; this service owns any rotation."""
        return await self._ensure_credentials(authorization=True)

    async def _ensure_credentials(self, *, authorization=False):
        def output(record, config):
            if authorization:
                return {"access_token": record["access_token"], "channel_id": record["channel_id"],
                        "expires_at": record["expires_at"], "scopes": list(record["scopes"])}
            return self._connector_credentials(record, config)

        generation = self._generation
        if self._closed:
            return None
        async with self._credential_lock:
            try:
                if self._closed or generation != self._generation:
                    return None
                stored = self._stored()
                config = self._configuration(stored)
                if config is None:
                    raise _AccountError("app_setup_required")
                if self._mismatch(config, stored):
                    raise _AccountError("account_identity_mismatch")
                if self._valid_record(stored, headroom=self.REFRESH_HEADROOM_SECONDS):
                    return output(stored, config)
                if not self._valid_record(stored, allow_expired=True):
                    raise _AccountError("authorization_required")
                code, value = await self._request("POST", self.TOKEN_URL, data={
                    **config, "refresh_token": stored["refresh_token"], "grant_type": "refresh_token"})
                if code != 200:
                    raise _AccountError("authorization_refresh_required")
                record = await self._verified_record(config, value, prior=stored)
                if self._closed or generation != self._generation:
                    return None
                current, current_config = self._stored(), self._configuration()
                if current_config is None or self._mismatch(current_config, record):
                    raise _AccountError("account_identity_mismatch")
                if current != stored:
                    if self._mismatch(current_config, current):
                        raise _AccountError("account_identity_mismatch")
                    return output(current, current_config) if self._valid_record(current) else None
                self._save(record)
                self._reason = "account_authorized"
                return output(record, current_config)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._reason = self._safe_reason(exc)
                return None

    async def cancel(self):
        _, pending = self._invalidate("authorization_cancelled")
        await self._dispose(pending)
        return self.status()

    async def close(self):
        self._closed = True
        return await self.cancel()
