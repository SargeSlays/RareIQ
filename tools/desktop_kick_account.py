"""Read-only Kick ingest resolution over a private native child-process pipe.

Stdin contains only accountRef. Successful stdout is secret: Main must consume
it privately and must never forward it over renderer IPC, HTTP, logs or reports.
The backend remains the sole credential-refresh writer.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from rareiq.core.platform_credentials import PlatformCredentialVault
from tools.desktop_twitch_account import AccountError, credential_path

INTROSPECT_URL = "https://id.kick.com/oauth/token/introspect"
CHANNELS_URL = "https://api.kick.com/public/v1/channels"
SCOPES = frozenset({"user:read", "channel:read", "streamkey:read"})
MAX_BYTES = 16384


def _fail(reason):
    raise AccountError(reason)


def _secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(not 33 <= ord(c) <= 126 for c in value):
        _fail("invalid_provider_response")
    return value


def _scopes(value, *, serialized=False):
    if serialized:
        if not isinstance(value, str) or len(value) > 4096:
            _fail("streaming_scope_required")
        value = value.split()
    if (not isinstance(value, list) or len(value) > 32
            or any(not isinstance(scope, str) or not 1 <= len(scope) <= 128
                   or any(not 33 <= ord(c) <= 126 for c in scope) for scope in value)):
        _fail("streaming_scope_required")
    if not SCOPES.issubset(value):
        _fail("streaming_scope_required")


def _record(value, account_ref, clock):
    if not isinstance(value, dict):
        _fail("authorization_required")
    if (not isinstance(value.get("client_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value["client_id"])
            or not isinstance(value.get("channel_id"), str) or not re.fullmatch(r"[0-9]{1,24}", value["channel_id"])
            or not isinstance(value.get("channel_slug"), str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,24}", value["channel_slug"])
            or value.get("token_type") != "bearer"):
        _fail("authorization_required")
    expected = hashlib.sha256(("kick:" + value["client_id"] + ":" + value["channel_id"]).encode("ascii")).hexdigest()
    configured = os.environ.get("RAREIQ_KICK_CLIENT_ID", "").strip()
    if account_ref != expected or configured and configured != value["client_id"]:
        _fail("account_identity_mismatch")
    _scopes(value.get("scopes"))
    expires = value.get("expires_at")
    if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= clock() + 30:
        _fail("authorization_refresh_required")
    _secret(value.get("access_token"))
    return value


def _server_url(value):
    if value is None or value == "":
        _fail("streaming_not_available")
    if not isinstance(value, str) or len(value) > 2048 or any(not 33 <= ord(c) <= 126 for c in value):
        _fail("invalid_provider_response")
    if not value.startswith("rtmps://"):
        _fail("secure_ingest_unavailable")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "rtmps" or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or "?" in value or "#" in value or "\\" in value or parsed.query or parsed.fragment
                or parsed.netloc.endswith(":")
                or parsed.port is not None and not 1 <= parsed.port <= 65535):
            _fail("invalid_provider_response")
        host = parsed.hostname
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if (len(labels) < 2 or len(host) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)
                    or labels[-1].lower() in {"localhost", "local", "internal", "invalid", "test", "example"}
                    or re.fullmatch(r"[0-9.]+", host)):
                _fail("secure_ingest_unavailable")
        else:
            if not address.is_global:
                _fail("secure_ingest_unavailable")
        # Kick may return an origin-only RTMPS URL. The separate key owns any
        # application path; never invent or rewrite one here.
        if parsed.path and not parsed.path.startswith("/"):
            _fail("invalid_provider_response")
    except AccountError:
        raise
    except (ValueError, UnicodeError):
        _fail("invalid_provider_response")
    return value


async def resolve_stream_key(account_ref, *, vault=None, http_factory=None, clock=time.time):
    if not isinstance(account_ref, str) or not re.fullmatch(r"[a-f0-9]{64}", account_ref):
        _fail("invalid_account_request")
    try:
        vault = vault if vault is not None else PlatformCredentialVault(credential_path())
        record = _record(vault.get("kick"), account_ref, clock)
    except AccountError:
        raise
    except Exception:
        _fail("account_storage_unavailable")
    factory = http_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3),
                                                       follow_redirects=False, trust_env=False))
    try:
        async with factory() as client:
            async def request(method, url):
                if (method, url) not in {("POST", INTROSPECT_URL), ("GET", CHANNELS_URL)}:
                    _fail("invalid_provider_endpoint")
                async with client.stream(method, url, headers={"Authorization": "Bearer " + record["access_token"]},
                        follow_redirects=False, timeout=httpx.Timeout(8, connect=3)) as response:
                    if response.status_code == 403 and url == CHANNELS_URL:
                        _fail("streaming_not_available")
                    if response.status_code in {401, 403}:
                        _fail("authorization_rejected")
                    if response.status_code != 200:
                        _fail("provider_unavailable")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        _fail("invalid_provider_response")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_BYTES:
                            _fail("provider_response_too_large")
                        raw.extend(chunk)
                    try:
                        value = json.loads(raw)
                    except (ValueError, UnicodeError):
                        _fail("invalid_provider_response")
                    if not isinstance(value, dict):
                        _fail("invalid_provider_response")
                    return value

            introspection = await request("POST", INTROSPECT_URL)
            auth = introspection.get("data")
            if (not isinstance(auth, dict) or auth.get("active") is not True
                    or auth.get("token_type") != "user" or auth.get("client_id") != record["client_id"]):
                _fail("authorization_rejected")
            _scopes(auth.get("scope"), serialized=True)
            deadline = auth.get("exp")
            if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= clock() + 30:
                _fail("authorization_refresh_required")
            channels = (await request("GET", CHANNELS_URL)).get("data")
            if not isinstance(channels, list) or len(channels) != 1 or not isinstance(channels[0], dict):
                _fail("kick_channel_required")
            channel = channels[0]
            identifier, slug = channel.get("broadcaster_user_id"), channel.get("slug")
            if (type(identifier) is not int or identifier <= 0 or str(identifier) != record["channel_id"]
                    or not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,24}", slug)):
                _fail("account_identity_mismatch")
            stream = channel.get("stream")
            if not isinstance(stream, dict) or not stream.get("key"):
                _fail("streaming_not_available")
            server_url, key = _server_url(stream.get("url")), _secret(stream["key"])
            try:
                current = vault.get("kick")
            except Exception:
                _fail("account_storage_unavailable")
            if current != record:
                _fail("account_state_changed")
            # Validate again after both network waits; authorization may have expired.
            _record(current, account_ref, clock)
            if deadline <= clock() + 30:
                _fail("authorization_refresh_required")
            return {"ok": True, "platform": "kick", "accountRef": account_ref,
                    "serverUrl": server_url, "streamKey": key}
    except AccountError:
        raise
    except Exception:
        _fail("provider_unavailable")


def main():
    try:
        if len(sys.argv) != 1:
            _fail("invalid_account_request")
        raw = sys.stdin.buffer.read(513)
        value = json.loads(raw)
        if len(raw) > 512 or not isinstance(value, dict) or set(value) != {"accountRef"}:
            _fail("invalid_account_request")
        result = asyncio.run(resolve_stream_key(value["accountRef"]))
    except AccountError as exc:
        result = {"ok": False, "reason": str(exc)}
    except Exception:
        result = {"ok": False, "reason": "invalid_account_request"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
