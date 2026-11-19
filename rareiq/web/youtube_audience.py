"""Local explicit YouTube observation controls; no credentials or event ingestion."""
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rareiq.web.remote_access import is_loopback_client


def create_youtube_audience_router(connector, authorize_operator, *, audit=None):
    router = APIRouter()

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def authorized(request):
        return bool(request.client and is_loopback_client(request.client.host)
                    and is_loopback_client(request.url.hostname) and authorize_operator(request))

    @router.get("/api/production/audience/youtube")
    async def status(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        return response(connector.cached_status())

    async def command(request, action, operation):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        parsed = urlsplit(str(request.url))
        if (request.headers.get("origin") != parsed.scheme + "://" + parsed.netloc
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
                audit(action="youtube." + operation, outcome="requested")
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
                audit(action="youtube." + operation, outcome=outcome)
            except Exception:
                if operation != "disconnect":
                    return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
                history_warning = True
        if history_warning:
            result = {**result, "activity_history_warning": True}
        return response(result)

    @router.post("/api/production/audience/youtube/connect")
    async def connect(request: Request):
        return await command(request, connector.connect, "connect")

    @router.post("/api/production/audience/youtube/disconnect")
    async def disconnect(request: Request):
        return await command(request, connector.disconnect, "disconnect")

    return router
