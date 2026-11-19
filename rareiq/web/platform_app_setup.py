"""Producer-only local app-credential ingress; never return supplied fields."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.services.platform_app_setup import AppSetupError
from rareiq.web.remote_access import is_loopback_client

MAX_BYTES = 16384
SAFE_REASONS = {"invalid_app_provider", "invalid_app_configuration", "app_setup_unavailable",
                "external_app_configuration_active", "disconnect_before_app_setup", "account_storage_unavailable"}


async def _result(value):
    return await value if inspect.isawaitable(value) else value


def create_platform_app_setup_router(service, authorize_operator, *, audit=None):
    router = APIRouter()
    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    @router.post("/api/production/accounts/{platform}/configure-app")
    async def configure(platform: str, request: Request):
        try:
            parsed = urlsplit(str(request.url))
            expected = parsed.scheme + "://" + parsed.netloc
            if (not request.client or not is_loopback_client(request.client.host)
                    or not is_loopback_client(parsed.hostname) or parsed.username or parsed.password
                    or len(request.headers.getlist("host")) != 1
                    or await _result(authorize_operator(request)) is not True):
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            if (request.headers.getlist("origin") != [expected]
                    or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")):
                return response({"ok": False, "reason": "same_origin_required"}, 403)
            if platform not in {"youtube", "kick"}:
                return response({"ok": False, "reason": "invalid_app_provider"}, 404)
            types = request.headers.getlist("content-type")
            lengths = request.headers.getlist("content-length")
            if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"
                    or lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0])
                                    or int(lengths[0]) > MAX_BYTES)):
                return response({"ok": False, "reason": "invalid_app_configuration"}, 400)
            async def read():
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise ValueError()
                    data.extend(chunk)
                return json.loads(bytes(data).decode("utf-8"))
            try:
                value = await asyncio.wait_for(read(), 5)
            except (ValueError, TypeError, TimeoutError, ClientDisconnect):
                return response({"ok": False, "reason": "invalid_app_configuration"}, 400)
            if audit is not None:
                try:
                    await _result(audit(action=platform + ".configure_app", outcome="requested"))
                except Exception:
                    return response({"ok": False, "reason": "activity_history_unavailable"}, 503)
            try:
                saved = await service.configure(platform, value)
            except AppSetupError as error:
                return response({"ok": False, "reason": str(error) if str(error) in SAFE_REASONS else "app_setup_unavailable"}, 409)
            warning = False
            if audit is not None:
                try:
                    await _result(audit(action=platform + ".configure_app", outcome="configured"))
                except Exception:
                    warning = True
            return response({"ok": True, "platform": platform, "configured": saved["configured"],
                             "replayed": saved["replayed"], **({"activity_history_warning": True} if warning else {})})
        except Exception:
            return response({"ok": False, "reason": "app_setup_unavailable"}, 503)
    return router
