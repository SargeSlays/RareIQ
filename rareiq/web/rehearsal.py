"""Private operator rehearsal commands and a metadata-only public badge."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.services.rehearsal_service import RehearsalError
from rareiq.web.remote_access import is_loopback_client


BODY_LIMIT = 1024
BODY_TIMEOUT_SECONDS = 5


def create_rehearsal_router(service, authorize_operator):
    router = APIRouter()

    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    def unavailable():
        return response({"ok": False, "reason": "rehearsal_unavailable"}, 503)

    async def guard(request, *, command=False):
        try:
            parsed = urlsplit(str(request.url))
            if (not request.client or not is_loopback_client(request.client.host)
                    or not is_loopback_client(parsed.hostname) or parsed.username or parsed.password
                    or len(request.headers.getlist("host")) != 1):
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            allowed = authorize_operator(request)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if allowed is not True:
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            origins = request.headers.getlist("origin")
            expected = parsed.scheme + "://" + parsed.netloc
            if ((origins and origins != [expected]) or command and origins != [expected]
                    or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")):
                return response({"ok": False, "reason": "same_origin_required"}, 403)
        except Exception:
            return unavailable()
        return None

    async def body(request, fields):
        types = request.headers.getlist("content-type")
        lengths = request.headers.getlist("content-length")
        if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"
                or lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]) or int(lengths[0]) > BODY_LIMIT)):
            raise RehearsalError("invalid_rehearsal_command", 400)
        async def read():
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > BODY_LIMIT:
                    raise ValueError()
                raw.extend(chunk)
            return bytes(raw)
        def unique(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError()
                value[key] = item
            return value
        try:
            raw = await asyncio.wait_for(read(), BODY_TIMEOUT_SECONDS)
            value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(value, dict) or set(value) != fields:
                raise ValueError()
            return value
        except (ValueError, TypeError, TimeoutError, ClientDisconnect, RecursionError):
            raise RehearsalError("invalid_rehearsal_command", 400) from None

    @router.get("/api/production/rehearsal")
    async def status(request: Request):
        denied = await guard(request)
        if denied is not None:
            return denied
        try:
            return response({"ok": True, "room": service.snapshot()})
        except Exception:
            return unavailable()

    @router.get("/api/guest/rehearsal")
    async def guest_status():
        try:
            room = service.snapshot()
            return response({"active": room["active"], "label": "Rehearsal" if room["active"] else "Production",
                             "mode": room["mode"], "generation": room["generation"]})
        except Exception:
            return response({"active": True, "label": "Rehearsal", "mode": "recovery_required", "generation": None}, 503)

    async def command(request, action):
        denied = await guard(request, command=True)
        if denied is not None:
            return denied
        fields = {"request_id", "expected_revision"}
        if action != "enter":
            fields.add("generation")
        if action == "mark":
            fields.update({"check_id", "status"})
        if action == "recover":
            fields.add("confirm_recovery")
        try:
            values = await body(request, fields)
            if action == "recover" and values.pop("confirm_recovery") is not True:
                raise RehearsalError("rehearsal_recovery_confirmation_required", 400)
            room = await getattr(service, action)(**values)
            return response({"ok": True, "room": room})
        except RehearsalError as exc:
            return response({"ok": False, "reason": exc.reason}, exc.status)
        except Exception:
            return unavailable()

    @router.post("/api/production/rehearsal/enter")
    async def enter(request: Request):
        return await command(request, "enter")

    @router.post("/api/production/rehearsal/exit")
    async def exit(request: Request):
        return await command(request, "exit")

    @router.post("/api/production/rehearsal/mark")
    async def mark(request: Request):
        return await command(request, "mark")

    @router.post("/api/production/rehearsal/recover")
    async def recover(request: Request):
        return await command(request, "recover")

    return router
