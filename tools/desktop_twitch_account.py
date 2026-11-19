"""Private native pipe only: read an owned Twitch key without HTTP exposure or writes.

Input is one bounded JSON accountRef on stdin. Stdout belongs exclusively to the
trusted desktop process and can contain the stream key; never forward or log it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from rareiq.core.platform_credentials import PlatformCredentialVault
from rareiq.core.storage import StorageManager

VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
KEY_URL = "https://api.twitch.tv/helix/streams/key"
SCOPES = {"user:read:chat", "channel:read:stream_key"}
MAX_BYTES = 16384


class AccountError(ValueError):
    pass


def _fail(reason):
    raise AccountError(reason)


def credential_path(project_root=None):
    """Resolve existing storage configuration exactly as the backend, without initializing it."""
    manager = StorageManager(project_root=project_root)
    try:
        with manager.config_file.open("rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            _fail("account_storage_unavailable")
        config = json.loads(raw)
        value = config.get("config_path") if isinstance(config, dict) else None
        if not isinstance(value, str) or not value or len(value) > 32768:
            _fail("account_storage_unavailable")
        expanded = Path(os.path.expandvars(os.path.expanduser(value)))
        root = expanded if expanded.is_absolute() else manager.config_file.parent / expanded
        return root.resolve() / "platform_accounts.enc.json"
    except AccountError:
        raise
    except Exception:
        _fail("account_storage_unavailable")


def _secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(not 33 <= ord(c) <= 126 for c in value):
        _fail("invalid_provider_response")
    return value


def _record(value, account_ref, clock):
    if not isinstance(value, dict):
        _fail("authorization_required")
    if (not isinstance(value.get("client_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value["client_id"])
            or not isinstance(value.get("channel_id"), str) or not re.fullmatch(r"[0-9]{1,24}", value["channel_id"])
            or not isinstance(value.get("channel_login"), str) or not re.fullmatch(r"[a-z0-9_]{1,25}", value["channel_login"])
            or value.get("token_type") != "bearer"):
        _fail("authorization_required")
    expected = hashlib.sha256((value["client_id"] + ":" + value["channel_id"]).encode("ascii")).hexdigest()
    configured = os.environ.get("RAREIQ_TWITCH_CLIENT_ID", "").strip()
    if expected != account_ref or (configured and configured != value["client_id"]):
        _fail("account_identity_mismatch")
    scopes = value.get("scopes")
    if not isinstance(scopes, list) or not all(isinstance(v, str) for v in scopes) or not SCOPES.issubset(scopes):
        _fail("streaming_scope_required")
    expires = value.get("expires_at")
    if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= clock() + 30:
        _fail("authorization_refresh_required")
    _secret(value.get("access_token"))
    return value


async def resolve_stream_key(account_ref, *, vault=None, http_factory=None, clock=time.time):
    if not isinstance(account_ref, str) or not re.fullmatch(r"[a-f0-9]{64}", account_ref):
        _fail("invalid_account_request")
    try:
        vault = vault or PlatformCredentialVault(credential_path())
        record = _record(vault.get("twitch"), account_ref, clock)
    except AccountError:
        raise
    except Exception:
        _fail("account_storage_unavailable")
    factory = http_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3),
                                                       follow_redirects=False, trust_env=False))
    try:
        async with factory() as client:
            async def request(url, *, headers, params=None):
                if url not in {VALIDATE_URL, KEY_URL}:
                    _fail("invalid_provider_endpoint")
                async with client.stream("GET", url, headers=headers, params=params, follow_redirects=False,
                                         timeout=httpx.Timeout(8, connect=3)) as response:
                    if response.status_code == 403 and url == KEY_URL:
                        _fail("streaming_not_available")
                    if response.status_code in {401, 403}:
                        _fail("authorization_rejected")
                    if response.status_code != 200:
                        _fail("provider_unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > MAX_BYTES:
                            _fail("provider_response_too_large")
                        raw.extend(chunk)
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        _fail("invalid_provider_response")
                    return result

            validation = await request(VALIDATE_URL, headers={"Authorization": "OAuth " + record["access_token"]})
            if (validation.get("client_id") != record["client_id"] or validation.get("user_id") != record["channel_id"]
                    or not isinstance(validation.get("login"), str)
                    or not re.fullmatch(r"[a-z0-9_]{1,25}", validation["login"])):
                _fail("account_identity_mismatch")
            scopes = validation.get("scopes")
            if not isinstance(scopes, list) or not all(isinstance(v, str) for v in scopes) or not SCOPES.issubset(scopes):
                _fail("streaming_scope_required")
            if type(validation.get("expires_in")) is not int or validation["expires_in"] <= 30:
                _fail("authorization_refresh_required")
            value = await request(KEY_URL, headers={"Authorization": "Bearer " + record["access_token"],
                "Client-Id": record["client_id"]}, params={"broadcaster_id": record["channel_id"]})
            data = value.get("data")
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                _fail("invalid_provider_response")
            key = _secret(data[0].get("stream_key"))
            if vault.get("twitch") != record:
                _fail("account_state_changed")
            return {"ok": True, "streamKey": key, "accountRef": account_ref, "publicLabel": validation["login"]}
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
