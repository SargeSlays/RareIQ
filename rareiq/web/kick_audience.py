"""Unmounted Kick receiver factory. Public ingress requires separate deployment approval.

Do not add this endpoint to the guest gateway. Host controls remain loopback-only;
the exact approved HTTPS event URL is the only intended external receiver surface.
"""
import asyncio
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rareiq.web.remote_access import is_loopback_client


def create_kick_audience_router(connector, authorize_operator, *, include_receiver=False, audit=None):
    router = APIRouter()

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def local_operator(request):
        return bool(request.client and is_loopback_client(request.client.host)
                    and is_loopback_client(request.url.hostname) and authorize_operator(request))

    async def body(request, maximum):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > maximum:
                raise ValueError()
            data.extend(chunk)
        return bytes(data)

    @router.get("/api/production/audience/kick")
    async def status(request: Request):
        if not local_operator(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        return response(connector.cached_status())

    async def command(request, action, operation):
        if not local_operator(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        parsed = urlsplit(str(request.url))
        if (request.headers.get("origin") != parsed.scheme + "://" + parsed.netloc
                or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")
                or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"):
            return response({"ok": False, "reason": "same_origin_required"}, 403)
        try:
            if json.loads(await asyncio.wait_for(body(request, 128), 5)) != {}:
                raise ValueError()
        except (ValueError, TypeError, TimeoutError):
            return response({"ok": False, "reason": "empty_command_required"}, 400)
        history_warning = False
        try:
            if audit is not None:
                audit(action="kick." + operation, outcome="requested")
        except Exception:
            if operation != "disconnect":
                return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
            history_warning = True
        try:
            result = await action()
        except Exception:
            return response({"ok": False, "reason": "provider_unavailable"}, 503)
        if audit is not None:
            outcome = ("succeeded" if result.get("connected") is True or operation == "disconnect"
                       and result.get("state") == "not_connected" else "requested"
                       if result.get("state") in {"connecting", "reconnecting", "ready"} else "failed")
            try:
                audit(action="kick." + operation, outcome=outcome)
            except Exception:
                if operation != "disconnect":
                    return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
                history_warning = True
        if history_warning:
            result = {**result, "activity_history_warning": True}
        return response(result)

    @router.post("/api/production/audience/kick/connect")
    async def connect(request: Request):
        return await command(request, connector.connect, "connect")

    @router.post("/api/production/audience/kick/disconnect")
    async def disconnect(request: Request):
        return await command(request, connector.disconnect, "disconnect")

    async def event(request: Request):
        if not connector.accepts_url(str(request.url)):
            return response({"ok": False, "reason": "receiver_inactive_or_unbound"}, 503)
        if (request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                or request.headers.get("content-encoding", "identity").lower() != "identity"
                or any(len(request.headers.getlist(key)) != 1 for key in connector.HEADERS)):
            return response({"ok": False, "reason": "invalid_event_headers"}, 400)
        try:
            raw = await asyncio.wait_for(body(request, connector.MAX_BYTES), 5)
        except (ValueError, TimeoutError):
            return response({"ok": False, "reason": "invalid_event_body"}, 413)
        payload, code = await connector.receive(dict(request.headers), raw)
        return response(payload, code)

    if include_receiver:
        router.add_api_route(connector.CALLBACK_PATH, event, methods=["POST"])
    return router
