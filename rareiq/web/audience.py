"""Operator-only audience configuration; never a public event/webhook receiver."""
from pathlib import Path
import json
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from rareiq.web.remote_access import is_loopback_client


def create_audience_router(service, static_dir: Path, *, sources_provider=None):
    """Mount inside the Studio's existing operator/remote-access boundary."""
    router = APIRouter()

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def unavailable():
        return response({"ok": False, "reason": "audience_storage_unavailable", "message": "Audience settings are unavailable. Keep your changes and retry."}, 503)

    async def body(request):
        if (request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                or request.headers.get("sec-fetch-site") == "cross-site"
                or (request.headers.get("origin") and request.headers["origin"] != str(request.base_url).rstrip("/"))):
            raise ValueError("invalid_audience_request_origin")
        data = bytearray()
        async for chunk in request.stream():
            if len(chunk) > 16384 - len(data):
                raise ValueError("audience_request_too_large")
            data.extend(chunk)
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("invalid_audience_request")
        return value

    @router.get("/api/production/audience")
    async def audience_status():
        try:
            status = service.status()
            if sources_provider:
                cached = {source["platform"]: source for source in sources_provider()}
                status["sources"] = [{**source, **cached.get(source["platform"], {})} for source in status["sources"]]
            return response(status)
        except (OSError, sqlite3.Error, ValueError):
            return unavailable()

    @router.post("/api/production/audience/configure")
    async def audience_configure(request: Request):
        try:
            payload = await body(request)
            if set(payload) != {"action", "data", "expected_revision", "request_id"}:
                raise ValueError("invalid_audience_request")
            actor_kind = "local_operator" if is_loopback_client(request.client.host if request.client else None) else "paired_lan_operator"
            result = service.configure(**payload, actor_kind=actor_kind)
            return response(result, result.get("status", 200))
        except (ValueError, TypeError, KeyError):
            return response({"ok": False, "reason": "invalid_audience_request", "message": "Check the audience settings and try again."}, 400)
        except (OSError, sqlite3.Error):
            return unavailable()

    @router.post("/api/production/audience/preview")
    async def audience_preview(request: Request):
        try:
            payload = await body(request)
            if set(payload) != {"rule", "display_name"}:
                raise ValueError("invalid_audience_preview")
            return response(service.preview(**payload))
        except (ValueError, TypeError, KeyError):
            return response({"ok": False, "reason": "invalid_audience_preview", "message": "Check the rule before previewing it."}, 400)

    @router.get("/api/production/audience/output")
    async def audience_output():
        try:
            return response(service.output())
        except (OSError, sqlite3.Error, ValueError):
            return unavailable()

    @router.get("/overlay/audience", include_in_schema=False)
    async def audience_overlay():
        return FileResponse(static_dir / "audience_overlay.html", headers={"Cache-Control": "no-store"})

    return router
