"""Opt-in scene-only access boundary; no identity provider is enabled here."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Server-created identity returned by a trusted session verifier."""

    provider: str
    app_id: str
    subject: str = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.provider, self.app_id, self.subject):
            if (not isinstance(value, str) or not 1 <= len(value) <= 256
                    or value != value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError("invalid_verified_principal")


@dataclass(frozen=True)
class SharedScenePolicy:
    enabled: bool = False
    verifier: Callable[[str], Awaitable[VerifiedPrincipal | None]] | None = field(
        default=None, repr=False,
    )

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or (self.verifier is not None and not callable(self.verifier)):
            raise ValueError("invalid_shared_scene_policy")


def _allowed_route(scope: Scope) -> bool:
    method, path = scope.get("method"), scope.get("path", "")
    if method == "GET":
        return path in {"/api/production/scenes", "/api/production/scenes/activity"}
    if method == "POST":
        return path == "/api/production/scenes"
    if method == "DELETE" and path.startswith("/api/production/scenes/"):
        target = path.removeprefix("/api/production/scenes/")
        return (target not in {"", ".", "..", "activity"}
                and re.fullmatch(r"[^/\\\x00-\x20\x7f]+", target) is not None)
    return False


def _bearer_token(scope: Scope) -> str | None:
    headers = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
    if len(headers) != 1 or len(headers[0]) > 8192:
        return None
    match = re.fullmatch(rb"(?i:Bearer) ([A-Za-z0-9._~+/-]+=*)", headers[0])
    return match[1].decode("ascii") if match else None


class SharedSceneAccessMiddleware:
    def __init__(self, app: ASGIApp, policy: Callable[[], SharedScenePolicy]) -> None:
        self.app, self.policy = app, policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        try:
            policy = self.policy()
            if not isinstance(policy, SharedScenePolicy):
                raise ValueError("invalid_shared_scene_policy")
        except Exception:
            await self._deny(scope, receive, send, 503, "shared_scene_access_unavailable")
            return
        if not policy.enabled:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            original_send = send

            async def no_store_send(message):
                if message["type"] == "http.response.start":
                    headers = [(key, value) for key, value in message.get("headers", [])
                               if key.lower() != b"cache-control"]
                    message = {**message, "headers": headers + [(b"cache-control", b"no-store")]}
                await original_send(message)

            send = no_store_send
        scope.pop("studio_principal", None)
        if scope["type"] == "websocket" or not _allowed_route(scope):
            await self._deny(scope, receive, send, 403, "shared_scene_route_unavailable")
            return
        token = _bearer_token(scope)
        if token is None:
            await self._deny(scope, receive, send, 401, "studio_sign_in_required")
            return
        if policy.verifier is None:
            await self._deny(scope, receive, send, 503, "shared_scene_access_unavailable")
            return
        try:
            principal = await policy.verifier(token)
        except Exception:
            await self._deny(scope, receive, send, 503, "shared_scene_access_unavailable")
            return
        if not isinstance(principal, VerifiedPrincipal):
            await self._deny(scope, receive, send, 401, "studio_sign_in_required")
            return
        scope["studio_principal"] = principal
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send, status: int, reason: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"ok": False, "reason": reason}, status_code=status,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)
