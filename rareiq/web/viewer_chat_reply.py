"""Explicit loopback operator replies; no public ingestion or automatic sending."""
import asyncio
from contextlib import nullcontext
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.web.remote_access import is_loopback_client


def create_viewer_chat_reply_router(service, authorize_operator, *, can_send=lambda: True, publication_guard=None):
    router = APIRouter()

    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    def authorized(request):
        return bool(request.client and is_loopback_client(request.client.host)
            and is_loopback_client(request.url.hostname) and authorize_operator(request))

    @router.get("/api/production/viewer-chat/reply-status")
    async def status(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        payload = service.status()
        try:
            allowed = can_send() is True
        except Exception:
            allowed = False
        if not allowed:
            for target in payload["targets"]:
                target.update(ready=False, reason="rehearsal_active")
        return response(payload)

    @router.post("/api/production/viewer-chat/reply")
    async def reply(request: Request):
        if not authorized(request):
            return response({"ok": False, "reason": "local_operator_required"}, 403)
        parsed = urlsplit(str(request.url))
        if (request.headers.get("origin") != parsed.scheme + "://" + parsed.netloc
                or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")
                or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
            return response({"ok": False, "reason": "same_origin_required"}, 403)

        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        async def body():
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > 2048:
                    raise ValueError()
                data.extend(chunk)
            return json.loads(data, object_pairs_hook=unique)

        try:
            value = await asyncio.wait_for(body(), 5)
            service.validate(value)
        except (ValueError, TypeError, TimeoutError, ClientDisconnect, UnicodeError):
            return response({"ok": False, "reason": "invalid_chat_reply"}, 400)
        try:
            with publication_guard() if publication_guard else nullcontext():
                if can_send() is not True:
                    return response({"ok": False, "reason": "rehearsal_active"}, 409)
                return response(await service.reply(value))
        except ValueError as exc:
            code = str(exc)
            known = {"chat_storage_unavailable", "chat_receipt_capacity", "chat_request_conflict", "invalid_chat_reply"}
            reason = code if code in known else "chat_reply_blocked"
            return response({"ok": False, "reason": reason}, 409 if reason == "chat_request_conflict" else 503)
        except Exception:
            return response({"ok": False, "reason": "chat_reply_blocked"}, 503)

    return router
