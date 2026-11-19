"""Loopback operator account setup. No configuration, credentials or auto-connect API."""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from urllib.parse import parse_qsl, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.web.remote_access import is_loopback_client


BODY_LIMIT = 128
BODY_TIMEOUT_SECONDS = 5
VERIFICATION_URL = "https://www.twitch.tv/activate"
_STATES = {"authorized", "not_authorized", "pending", "unavailable"}
_REASONS = frozenset("""
app_setup_required invalid_provider_response invalid_provider_endpoint provider_unavailable
provider_response_too_large provider_rate_limited authorization_rejected account_identity_mismatch
chat_scope_required account_storage_unavailable authorization_required authorization_expired
authorization_denied authorization_refresh_required account_authorized authorization_pending
account_service_closed authorization_cancelled account_unavailable account_state_changed
streaming_scope_required account_disconnected
""".split())
_STORAGE = {"empty", "stored", "locked", "unavailable"}
_FLAGS = ("stored", "has_client_id", "has_client_secret", "has_access_token", "has_refresh_token", "has_channel")
_YOUTUBE_REASONS = _REASONS | {"account_state_changed", "account_disconnected", "offline_access_required", "youtube_channel_required",
    "channel_selection_required", "callback_listener_unavailable", "validating_authorization"}


async def _result(value):
    return await value if inspect.isawaitable(value) else value


def _public_label(value):
    return value if (isinstance(value, str) and 0 < len(value) <= 80
                     and not any(ord(char) < 32 or ord(char) == 127 for char in value)) else None


def _number(value, maximum=1e12):
    return type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value)


def _twitch_status(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_account_status")
    state, reason = raw.get("state"), raw.get("reason")
    if state not in _STATES or reason not in _REASONS:
        state, reason = "unavailable", "account_unavailable"
    result = {"platform": "twitch", "state": state, "reason": reason,
              "authorized": raw.get("authorized") is True if state != "unavailable" else False,
              "app_configured": raw.get("app_configured") is True}
    result["streaming_authorized"] = result["authorized"] and raw.get("streaming_authorized") is True
    account_ref = raw.get("account_ref")
    if result["authorized"] and isinstance(account_ref, str) and re.fullmatch(r"[a-f0-9]{64}", account_ref):
        result["account_ref"] = account_ref
    label = _public_label(raw.get("public_label"))
    if label and result["authorized"]:
        result["public_label"] = label
    if _number(raw.get("expires_at")):
        result["expires_at"] = raw["expires_at"]
    if state == "pending":
        code, flow = raw.get("user_code"), raw.get("flow_id")
        if (not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9-]{4,32}", code)
                or not isinstance(flow, str) or not re.fullmatch(r"[a-f0-9]{32}", flow)
                or not _number(raw.get("expires_at"))):
            return {"platform": "twitch", "state": "unavailable", "reason": "account_unavailable",
                    "authorized": False, "app_configured": result["app_configured"]}
        result.update(user_code=code, flow_id=flow, verification_url=VERIFICATION_URL)
        result["authorization_kind"] = "streaming" if raw.get("authorization_kind") == "streaming" else "chat"
        if _number(raw.get("poll_after"), 60) and raw["poll_after"] >= 1:
            result["poll_after"] = raw["poll_after"]
    return result


def _youtube_status(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_account_status")
    state, reason = raw.get("state"), raw.get("reason")
    if state not in _STATES or reason not in _YOUTUBE_REASONS:
        state, reason = "unavailable", "account_unavailable"
    result = {"platform": "youtube", "state": state, "reason": reason,
              "authorized": state != "unavailable" and raw.get("authorized") is True,
              "app_configured": raw.get("app_configured") is True}
    label = _public_label(raw.get("public_label"))
    if label and result["authorized"]:
        result["public_label"] = label
    if _number(raw.get("expires_at")):
        result["expires_at"] = raw["expires_at"]
    if state == "pending":
        flow = raw.get("flow_id")
        if not isinstance(flow, str) or not re.fullmatch(r"[a-f0-9]{32}", flow) or not _number(raw.get("expires_at")):
            raise ValueError("invalid_account_flow")
        result["flow_id"] = flow
    return result


def _google_authorization_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid_authorization_url")
    url = urlsplit(value)
    if url.scheme != "https" or url.netloc != "accounts.google.com" or url.path != "/o/oauth2/v2/auth" or url.fragment:
        raise ValueError("invalid_authorization_url")
    pairs = parse_qsl(url.query, strict_parsing=True, max_num_fields=12)
    query = dict(pairs)
    allowed = {"client_id", "redirect_uri", "response_type", "scope", "access_type", "prompt", "state", "code_challenge", "code_challenge_method"}
    if len(query) != len(pairs) or set(query) != allowed or query["response_type"] != "code" or query["code_challenge_method"] != "S256":
        raise ValueError("invalid_authorization_url")
    redirect = urlsplit(query["redirect_uri"])
    if (redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "::1"}
            or redirect.username or redirect.password or not redirect.port or not 1024 <= redirect.port <= 65535
            or redirect.path != "/callback" or redirect.query or redirect.fragment):
        raise ValueError("invalid_authorization_url")
    return value


def _kick_status(raw):
    if not isinstance(raw, dict):
        raise ValueError("invalid_account_status")
    safe = _YOUTUBE_REASONS | {"account_scope_required", "kick_user_required", "kick_channel_required", "streaming_scope_required"}
    value = dict(raw)
    if value.get("reason") not in safe:
        value.update(state="unavailable", reason="account_unavailable", authorized=False)
    reason = value.get("reason")
    if reason not in _YOUTUBE_REASONS:
        value["reason"] = "authorization_required"
    result = _youtube_status(value)
    result.update(platform="kick", reason=reason)
    return result


def _kick_authorization_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("invalid_authorization_url")
    url = urlsplit(value)
    pairs = parse_qsl(url.query, strict_parsing=True, max_num_fields=8)
    query = dict(pairs)
    fields = {"client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method"}
    if (url.scheme != "https" or url.netloc != "id.kick.com" or url.path != "/oauth/authorize" or url.fragment
            or len(pairs) != len(query) or set(query) != fields or query["response_type"] != "code"
            or query["redirect_uri"] != "http://localhost:8770/callback" or query["code_challenge_method"] != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,220}", query["client_id"])
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", query["state"])
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", query["code_challenge"])
            or len(query["scope"].split(" ")) != 3
            or set(query["scope"].split(" ")) != {"user:read", "channel:read", "streamkey:read"}):
        raise ValueError("invalid_authorization_url")
    return value


def create_platform_accounts_router(twitch_service, authorize_operator, *, vault=None, audit=None,
                                   youtube_service=None, twitch_disconnect=None, kick_service=None,
                                   youtube_disconnect=None, kick_disconnect=None):
    router = APIRouter()

    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    def unavailable():
        return response({"ok": False, "reason": "account_unavailable"}, 503)

    async def guard(request, *, command=False):
        try:
            parsed = urlsplit(str(request.url))
            if (not request.client or not is_loopback_client(request.client.host)
                    or not is_loopback_client(parsed.hostname) or parsed.username or parsed.password
                    or len(request.headers.getlist("host")) != 1):
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            if await _result(authorize_operator(request)) is not True:
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            origins = request.headers.getlist("origin")
            expected = parsed.scheme + "://" + parsed.netloc
            if ((origins and origins != [expected]) or (command and origins != [expected])
                    or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")):
                return response({"ok": False, "reason": "same_origin_required"}, 403)
        except Exception:
            return unavailable()
        return None

    def other_status(provider):
        raw = vault.status(provider) if vault is not None else {}
        if not isinstance(raw, dict):
            raise ValueError("invalid_account_storage_status")
        storage = raw.get("state") if raw.get("state") in _STORAGE else "unavailable"
        stored = storage == "stored" and raw.get("stored") is True
        result = {"platform": provider, "state": "setup_required", "authorized": False,
                  "reason": "youtube_sign_in_setup_required" if provider == "youtube" else "kick_public_callback_required",
                  "storage_state": storage,
                  **{flag: stored and raw.get(flag) is True for flag in _FLAGS}}
        label = _public_label(raw.get("public_label"))
        if stored and label:
            result["public_label"] = label
        return result

    @router.get("/api/production/accounts")
    async def status(request: Request):
        denied = await guard(request)
        if denied is not None:
            return denied
        try:
            account = _twitch_status(await _result(twitch_service.status()))
            youtube = _youtube_status(await _result(youtube_service.status())) if youtube_service is not None else other_status("youtube")
            kick = _kick_status(await _result(kick_service.status())) if kick_service is not None else other_status("kick")
            return response({"accounts": [account, youtube, kick]})
        except Exception:
            return unavailable()

    async def empty_command(request):
        types = request.headers.getlist("content-type")
        if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
            return False
        lengths = request.headers.getlist("content-length")
        if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]) or int(lengths[0]) > BODY_LIMIT):
            return False
        async def read():
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > BODY_LIMIT:
                    raise ValueError("command_too_large")
                data.extend(chunk)
            return bytes(data)
        try:
            value = await asyncio.wait_for(read(), BODY_TIMEOUT_SECONDS)
            return json.loads(value.decode("utf-8")) == {}
        except (ValueError, TypeError, TimeoutError, ClientDisconnect):
            return False

    async def command(request, action, platform="twitch"):
        denied = await guard(request, command=True)
        if denied is not None:
            return denied
        try:
            if not await empty_command(request):
                return response({"ok": False, "reason": "empty_command_required"}, 400)
        except Exception:
            return unavailable()
        history_warning = False
        connection_stop_warning = False
        if audit is not None:
            try:
                await _result(audit(action=platform + "." + action, outcome="requested"))
            except Exception:
                if action not in {"cancel", "disconnect"}:
                    return unavailable()
                history_warning = True
        outcome = "failed"
        payload = None
        try:
            service = {"twitch": twitch_service, "youtube": youtube_service, "kick": kick_service}[platform]
            sanitize = {"twitch": _twitch_status, "youtube": _youtube_status, "kick": _kick_status}[platform]
            stop = {"twitch": twitch_disconnect, "youtube": youtube_disconnect, "kick": kick_disconnect}[platform]
            if action == "disconnect" and stop is not None:
                try:
                    await _result(stop())
                except Exception:
                    # Still forget local credentials; a failed stop must not suppress it.
                    connection_stop_warning = True
            await _result(getattr(service, action)())
            account = sanitize(await _result(service.status()))
            # A cached login can remain stored through a provider outage. That
            # must not become evidence that an explicit verification succeeded.
            outcome = "failed" if action == "check" and account["state"] != "pending" and account["reason"] != "account_authorized" else account["state"]
            payload = {"account": account}
        except Exception:
            pass
        if audit is not None:
            try:
                await _result(audit(action=platform + "." + action, outcome=outcome))
            except Exception:
                if action not in {"cancel", "disconnect"} or payload is None:
                    return unavailable()
                history_warning = True
        if payload is None:
            return unavailable()
        if history_warning:
            payload["activity_history_warning"] = True
        if connection_stop_warning:
            payload["connection_stop_warning"] = True
        return response(payload)

    @router.post("/api/production/accounts/twitch/begin")
    async def begin(request: Request):
        return await command(request, "begin")

    @router.post("/api/production/accounts/twitch/cancel")
    async def cancel(request: Request):
        return await command(request, "cancel")

    @router.post("/api/production/accounts/twitch/begin-streaming")
    async def begin_streaming(request: Request):
        return await command(request, "begin_streaming")

    @router.post("/api/production/accounts/twitch/check")
    async def check(request: Request):
        return await command(request, "check")

    @router.post("/api/production/accounts/twitch/disconnect")
    async def disconnect(request: Request):
        return await command(request, "disconnect")

    @router.post("/api/production/accounts/youtube/begin")
    async def youtube_begin(request: Request):
        return await command(request, "begin", "youtube")

    @router.post("/api/production/accounts/youtube/cancel")
    async def youtube_cancel(request: Request):
        return await command(request, "cancel", "youtube")

    @router.post("/api/production/accounts/youtube/check")
    async def youtube_check(request: Request):
        return await command(request, "check", "youtube")

    @router.post("/api/production/accounts/youtube/disconnect")
    async def youtube_disconnect_account(request: Request):
        return await command(request, "disconnect", "youtube")

    @router.post("/api/production/accounts/kick/{action}")
    async def kick_command(action: str, request: Request):
        if action not in {"begin", "cancel", "check", "disconnect"}:
            return response({"ok": False, "reason": "invalid_account_action"}, 404)
        return await command(request, action, "kick")

    @router.get("/api/production/accounts/kick/authorization")
    async def kick_authorization(request: Request):
        denied = await guard(request)
        if denied is not None:
            return denied
        flows = request.query_params.getlist("flow_id")
        if set(request.query_params) != {"flow_id"} or len(flows) != 1 or not re.fullmatch(r"[a-f0-9]{32}", flows[0]):
            return response({"ok": False, "reason": "invalid_authorization_flow"}, 400)
        try:
            value = await _result(kick_service.authorization_url(flows[0]))
            if value is None:
                return response({"ok": False, "reason": "authorization_flow_unavailable"}, 409)
            return response({"authorization_url": _kick_authorization_url(value)})
        except Exception:
            return unavailable()

    @router.get("/api/production/accounts/youtube/authorization")
    async def youtube_authorization(request: Request):
        denied = await guard(request)
        if denied is not None:
            return denied
        flows = request.query_params.getlist("flow_id")
        if set(request.query_params) != {"flow_id"} or len(flows) != 1 or not re.fullmatch(r"[a-f0-9]{32}", flows[0]):
            return response({"ok": False, "reason": "invalid_authorization_flow"}, 400)
        try:
            value = await _result(youtube_service.authorization_url(flows[0]))
            if value is None:
                return response({"ok": False, "reason": "authorization_flow_unavailable"}, 409)
            return response({"authorization_url": _google_authorization_url(value)})
        except Exception:
            return unavailable()

    return router
