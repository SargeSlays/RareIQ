"""Loopback-only public metadata for explicit existing YouTube destinations."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from rareiq.services.youtube_destination_service import HASH, LIVE_STATES, PRIVACY_STATES, STREAM_STATES, _text, identifier, safe_reason, settings_fingerprint
from rareiq.web.remote_access import is_loopback_client

MAX_BYTES = 1024


async def _result(value):
    return await value if inspect.isawaitable(value) else value


def _selection(value):
    if (not isinstance(value, dict) or value.get("platform") != "youtube"
            or any(not isinstance(value.get(key), str) or not HASH.fullmatch(value[key]) for key in ("account_ref", "settings_fingerprint"))
            or type(value.get("auto_start")) is not bool or type(value.get("auto_stop")) is not bool
            or value.get("privacy_status") not in PRIVACY_STATES
            or value.get("lifecycle") not in LIVE_STATES or value.get("stream_status") not in STREAM_STATES):
        raise ValueError("invalid_provider_response")
    result = {"platform": "youtube", "account_ref": value["account_ref"],
            "broadcast_id": identifier(value.get("broadcast_id")), "stream_id": identifier(value.get("stream_id")),
            "settings_fingerprint": value["settings_fingerprint"], "title": _text(value.get("title")),
            "auto_start": value["auto_start"], "auto_stop": value["auto_stop"],
            "lifecycle": value["lifecycle"], "stream_status": value["stream_status"], "privacy_status": value["privacy_status"]}
    if result["settings_fingerprint"] != settings_fingerprint(result["account_ref"], result["broadcast_id"], result["stream_id"], result["auto_start"], result["auto_stop"], result["privacy_status"]):
        raise ValueError("invalid_provider_response")
    return result


def create_youtube_destination_router(service, authorize_operator):
    router = APIRouter()
    def response(value, status=200):
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    async def command(request, action):
        try:
            parsed = urlsplit(str(request.url))
            expected = parsed.scheme + "://" + parsed.netloc
            if (not request.client or not is_loopback_client(request.client.host)
                    or not is_loopback_client(parsed.hostname) or parsed.username or parsed.password
                    or len(request.headers.getlist("host")) != 1 or await _result(authorize_operator(request)) is not True):
                return response({"ok": False, "reason": "local_operator_required"}, 403)
            if (request.headers.getlist("origin") != [expected]
                    or request.headers.get("sec-fetch-site") not in (None, "same-origin", "none")):
                return response({"ok": False, "reason": "same_origin_required"}, 403)
            types, lengths = request.headers.getlist("content-type"), request.headers.getlist("content-length")
            if (len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json"
                    or lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]) or int(lengths[0]) > MAX_BYTES)):
                return response({"ok": False, "reason": "invalid_account_request"}, 400)
            async def read():
                data = bytearray()
                async for block in request.stream():
                    if len(data) + len(block) > MAX_BYTES:
                        raise ValueError()
                    data.extend(block)
                return json.loads(bytes(data).decode("utf-8"))
            try:
                payload = await asyncio.wait_for(read(), 5)
                if not isinstance(payload, dict) or set(payload) != (set() if action == "list" else {"broadcast_id"}):
                    raise ValueError()
                if action == "inspect":
                    identifier(payload["broadcast_id"])
            except (ValueError, TypeError, TimeoutError, ClientDisconnect):
                return response({"ok": False, "reason": "invalid_account_request"}, 400)
            if action == "list":
                value = await asyncio.wait_for(service.list_broadcasts(), 60)
                rows = value.get("broadcasts") if isinstance(value, dict) else None
                if (not isinstance(rows, list) or len(rows) > 100 or value.get("platform") != "youtube"
                        or not isinstance(value.get("account_ref"), str) or not HASH.fullmatch(value["account_ref"])):
                    raise ValueError("invalid_provider_response")
                selections = [_selection(item) for item in rows]
                if any(item["account_ref"] != value["account_ref"] for item in selections):
                    raise ValueError("invalid_provider_response")
                return response({"ok": True, "platform": "youtube", "account_ref": value["account_ref"], "broadcasts": selections})
            selection = _selection(await asyncio.wait_for(service.inspect_broadcast(payload["broadcast_id"]), 60))
            return response({"ok": True, "selection": selection})
        except Exception as error:
            return response({"ok": False, "reason": safe_reason(error)}, 409)

    @router.post("/api/production/accounts/youtube/broadcasts")
    async def broadcasts(request: Request):
        return await command(request, "list")

    @router.post("/api/production/accounts/youtube/inspect-broadcast")
    async def inspect_broadcast(request: Request):
        return await command(request, "inspect")

    return router
