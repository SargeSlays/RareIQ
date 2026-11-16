"""Local operator opt-in controls; no tokens or public event ingestion over HTTP."""
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from rareiq.web.remote_access import is_loopback_client


def create_twitch_audience_router(connector, authorize_operator):
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

    async def command(request, action):
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
        return response(await action())

    @router.post("/api/production/audience/twitch/connect")
    async def connect(request: Request):
        return await command(request, connector.connect)

    @router.post("/api/production/audience/twitch/disconnect")
    async def disconnect(request: Request):
        return await command(request, connector.disconnect)

    return router
