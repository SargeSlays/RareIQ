"""Local operator opt-in controls; no tokens or public event ingestion over HTTP."""
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rareiq.web.remote_access import is_loopback_client


def create_twitch_audience_router(connector, authorize_operator, *, prepare_connect=None, audit=None):
    router = APIRouter()

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def authorized(request):
        # A matching Origin alone doesn't prevent DNS rebinding to a loopback service.
        return bool(request.client and is_loopback_client(request.client.host)
                    and is_loopback_client(request.url.hostname) and authorize_operator(request))

    @router.get("/api/production/audience/twitch")
    async def status(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        return response(connector.cached_status())

    async def command(request, action, operation):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        parsed = urlsplit(str(request.url))
        origin = parsed.scheme + "://" + parsed.netloc
        if (request.headers.get("origin") != origin
                or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")
                or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
            return response({"ok": False, "reason": "same_origin_required"}, 403)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 128:
                return response({"ok": False, "reason": "empty_command_required"}, 400)
            data.extend(chunk)
        try:
            if json.loads(data) != {}:
                raise ValueError()
        except (ValueError, TypeError):
            return response({"ok": False, "reason": "empty_command_required"}, 400)
        history_warning = False
        try:
            if audit is not None:
                audit(action="twitch." + operation, outcome="requested")
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
                audit(action="twitch." + operation, outcome=outcome)
            except Exception:
                if operation != "disconnect":
                    return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
                history_warning = True
        if history_warning:
            result = {**result, "activity_history_warning": True}
        return response(result)

    @router.post("/api/production/audience/twitch/connect")
    async def connect(request: Request):
        async def prepared():
            if prepare_connect is not None:
                try:
                    await prepare_connect()
                except Exception:
                    return {**connector.cached_status(), "connected": False,
                            "authorized": False, "reason": "authorization_refresh_required"}
            return await connector.connect()
        return await command(request, prepared, "connect")

    @router.post("/api/production/audience/twitch/disconnect")
    async def disconnect(request: Request):
        return await command(request, connector.disconnect, "disconnect")

    return router
