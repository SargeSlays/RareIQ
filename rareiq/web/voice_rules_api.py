"""Local-operator custom voice settings. This never arms or executes commands."""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rareiq.web.remote_access import is_loopback_client


class VoiceRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=0)
    rules: list[dict] = Field(max_length=24)


def voice_rules_router(service) -> APIRouter:
    router = APIRouter(prefix="/api/production/voice/rules")

    def response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def denied(request):
        return not is_loopback_client(request.client.host if request.client else None)

    @router.get("")
    async def get_rules(request: Request):
        if denied(request):
            return response({"ok": False, "reason": "voice_requires_local_operator"}, 403)
        result = await asyncio.to_thread(service.rules_status)
        return response(result, 200 if result.get("ok") else 503)

    @router.put("")
    async def put_rules(request: Request):
        if denied(request):
            return response({"ok": False, "reason": "voice_requires_local_operator"}, 403)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return response({"ok": False, "reason": "voice_rules_require_json"}, 415)
        body = bytearray()
        async for chunk in request.stream():
            if len(chunk) > 65536 - len(body):
                return response({"ok": False, "reason": "voice_rules_too_large"}, 413)
            body.extend(chunk)
        try:
            config = VoiceRulesRequest.model_validate(json.loads(body))
        except (ValueError, TypeError, ValidationError):
            return response({"ok": False, "reason": "invalid_voice_rules"}, 400)
        result = await asyncio.to_thread(service.replace_rules, config.rules, config.expected_revision)
        status = 200 if result.get("ok") else 503 if result.get("reason") in {"voice_rules_unavailable", "voice_rules_storage_unavailable"} else 400 if result.get("reason") == "invalid_voice_rules" else 409
        return response(result, status)

    return router
