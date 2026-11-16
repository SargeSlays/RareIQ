"""Unused server-only verifier for StackThis's deployed app-session contract.

This does not register Producer, Please or enable shared account access.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re

import httpx

from rareiq.web.shared_scene_access import VerifiedPrincipal


STACKTHIS_ORIGIN = "https://stackthis.binary6labs.com"
STACKTHIS_APP_ID = "producer-please"
MAX_RESPONSE_BYTES = 16 * 1024
TIMEOUT_SECONDS = 5.0
MAX_CHECK_AGE_SECONDS = 60
MAX_FUTURE_SKEW_SECONDS = 5


class StackThisIdentityUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("stackthis_identity_unavailable")


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_identity_response")
        result[key] = value
    return result


def _principal(body: bytes) -> VerifiedPrincipal:
    payload = json.loads(body.decode("utf-8"), object_pairs_hook=_strict_object)
    if (not isinstance(payload, dict)
            or set(payload) != {"allowed", "appId", "subject", "source", "checkedAt"}
            or payload["allowed"] is not True or payload["appId"] != STACKTHIS_APP_ID):
        raise ValueError("invalid_identity_response")
    source, checked_at = payload["source"], payload["checkedAt"]
    if (not isinstance(source, str) or not 1 <= len(source) <= 256
            or source != source.strip() or any(ord(char) < 32 or ord(char) == 127 for char in source)
            or not isinstance(checked_at, str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", checked_at) is None):
        raise ValueError("invalid_identity_response")
    checked = datetime.fromisoformat(checked_at)
    age = (datetime.now(timezone.utc) - checked).total_seconds()
    if not -MAX_FUTURE_SKEW_SECONDS <= age <= MAX_CHECK_AGE_SECONDS:
        raise ValueError("invalid_identity_response")
    # Access source is provider metadata, never a studio role or entitlement.
    return VerifiedPrincipal("stackthis", STACKTHIS_APP_ID, payload["subject"])


class StackThisSessionVerifier:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Transport injection is reserved for isolated offline tests."""
        self._transport = transport

    async def __call__(self, token: str) -> VerifiedPrincipal | None:
        if not isinstance(token, str) or re.fullmatch(r"[a-f0-9]{64}", token) is None:
            return None
        try:
            # A fresh client prevents cookie/session reuse; the total deadline also
            # bounds slow streamed responses beyond httpx's per-operation timeout.
            async with asyncio.timeout(TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(TIMEOUT_SECONDS), follow_redirects=False,
                    trust_env=False, transport=self._transport,
                ) as client:
                    async with client.stream(
                        "GET", STACKTHIS_ORIGIN + "/api/apps/session/check",
                        params={"appId": STACKTHIS_APP_ID},
                        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                                 "Accept-Encoding": "identity", "Cache-Control": "no-store",
                                 "Pragma": "no-cache"},
                    ) as response:
                        if response.status_code in {401, 403}:
                            return None
                        if response.status_code != 200:
                            raise ValueError("identity_verification_unavailable")
                        if (response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"
                                or response.headers.get("content-encoding", "identity").strip().lower() != "identity"):
                            raise ValueError("invalid_identity_response")
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isascii() or not length.isdecimal()
                                                   or len(length) > 6 or int(length) > MAX_RESPONSE_BYTES):
                            raise ValueError("invalid_identity_response")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(chunk) > MAX_RESPONSE_BYTES - len(body):
                                raise ValueError("invalid_identity_response")
                            body.extend(chunk)
                        return _principal(bytes(body))
        except Exception:
            # Never attach provider errors, request objects, credentials or bodies.
            pass
        raise StackThisIdentityUnavailable()
