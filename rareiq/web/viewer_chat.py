"""Local operator viewer-chat controls; no public ingestion or automatic connect."""
import asyncio
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rareiq.services.viewer_chat_service import MAX_CURSOR, PLATFORMS
from rareiq.web.remote_access import is_loopback_client


_STATES = {"not_connected", "connecting", "connected", "reconnecting", "ready", "unavailable"}
_REASONS = frozenset("""
explicit_connection_required validating_authorization observing_chat disconnected_by_operator
credentials_required connection_retry_limited connection_cancelled authorization_rejected
token_channel_or_client_mismatch chat_scope_required token_expiring provider_unavailable
provider_rate_limited provider_request_failed provider_payload_too_large invalid_provider_payload
invalid_subscription_response invalid_provider_welcome invalid_reconnect_destination
unexpected_subscription_event unexpected_provider_event subscription_revoked
provider_event_rate_exceeded channel_identity_mismatch invalid_access_token
chat_ended chat_disabled chat_unavailable no_active_chat multiple_active_chats
broadcast_selection_limit invalid_provider_pagination invalid_provider_poll_interval
invalid_provider_timestamp unexpected_chat_author unexpected_chat_event provider_quota_exhausted
dashboard_registration_approval_required authorization_refresh_required waiting_for_verified_chat
observing_verified_chat approved_https_callback_required approved_subscription_required
provider_authorization_rejected owned_channel_events_scope_required owned_channel_required
invalid_provider_identity invalid_provider_public_key provider_key_unavailable
provider_authorization_expired source_status_unavailable
""".split())


def create_viewer_chat_router(service, authorize_operator, *, sources_provider=None, audit=None):
    router = APIRouter()

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def authorized(request):
        return bool(request.client and is_loopback_client(request.client.host)
                    and is_loopback_client(request.url.hostname) and authorize_operator(request))

    def snapshot(**query):
        payload = service.status(**query)
        # Only known state/reason codes and booleans cross this boundary, never
        # account IDs, arbitrary errors, credentials or provider history.
        sources = {}
        try:
            for raw in sources_provider() if sources_provider else ():
                if not isinstance(raw, dict) or raw.get("platform") not in PLATFORMS:
                    continue
                state, reason = raw.get("state"), raw.get("reason")
                sources[raw["platform"]] = {
                    "platform": raw["platform"], "state": state if state in _STATES else "unavailable",
                    "reason": reason if reason in _REASONS else "source_status_unavailable",
                    **{key: raw.get(key) is True for key in ("implemented", "connected", "authorized", "verified")}}
                if raw["platform"] == "kick":
                    sources[raw["platform"]]["dashboard_registration_approved"] = raw.get("dashboard_registration_approved") is True
                for key in ("poll_interval_seconds", "retry_after_seconds"):
                    value = raw.get(key)
                    if type(value) in (int, float) and 0 <= value <= 86400:
                        sources[raw["platform"]][key] = value
        except Exception:
            sources = {}
        payload["sources"] = [sources.get(platform, {"platform": platform, "state": "unavailable",
                                "reason": "source_status_unavailable", "implemented": False,
                                "connected": False, "authorized": False, "verified": False})
                              for platform in PLATFORMS]
        return payload

    @router.get("/api/production/viewer-chat")
    async def status(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        query = request.query_params
        if (set(query) - {"after", "session_id"}
                or any(len(query.getlist(key)) != 1 for key in query)):
            return response({"ok": False, "reason": "invalid_viewer_chat_query"}, 400)
        after, session_id = query.get("after", "0"), query.get("session_id")
        if (not re.fullmatch(r"[0-9]{1,16}", after) or int(after) > MAX_CURSOR
                or (session_id is not None and not re.fullmatch(r"[a-f0-9]{32}", session_id))):
            return response({"ok": False, "reason": "invalid_viewer_chat_query"}, 400)
        return response(snapshot(after=int(after), session_id=session_id))

    @router.post("/api/production/viewer-chat/listening")
    async def listening(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        parsed = urlsplit(str(request.url))
        if (request.headers.get("origin") != parsed.scheme + "://" + parsed.netloc
                or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")
                or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
            return response({"ok": False, "reason": "same_origin_required"}, 403)

        async def body():
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > 128:
                    raise ValueError()
                data.extend(chunk)
            return json.loads(data)

        try:
            value = await asyncio.wait_for(body(), 5)
            if not isinstance(value, dict) or set(value) != {"enabled"} or type(value["enabled"]) is not bool:
                raise ValueError()
        except (ValueError, TypeError, TimeoutError):
            return response({"ok": False, "reason": "invalid_viewer_chat_listening"}, 400)
        history_warning = False
        try:
            if audit is not None:
                audit(enabled=value["enabled"])
        except Exception:
            if value["enabled"]:
                return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
            history_warning = True
        try:
            service.set_listening(value["enabled"])
        except (ValueError, TypeError, TimeoutError):
            return response({"ok": False, "reason": "invalid_viewer_chat_listening"}, 400)
        payload = snapshot()
        if history_warning:
            payload["activity_history_warning"] = True
        return response(payload)

    return router
