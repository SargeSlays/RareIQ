"""Read-only existing YouTube ingest resolution through an owned native pipe.

Successful stdout is private: never expose it over renderer IPC, HTTP or logs.
This helper cannot refresh credentials or mutate account/provider state.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from rareiq.core.platform_credentials import PlatformCredentialVault
from rareiq.services.youtube_destination_service import (
    HASH, YouTubeReader, account_ref, fail, identifier, safe_reason, validate_record,
)
from tools.desktop_twitch_account import credential_path


async def resolve_stream_key(request, *, vault=None, http_factory=None, clock=time.time):
    if (not isinstance(request, dict) or set(request) != {"accountRef", "broadcastId", "streamId", "settingsFingerprint"}
            or not isinstance(request["accountRef"], str) or not HASH.fullmatch(request["accountRef"])
            or not isinstance(request["settingsFingerprint"], str) or not HASH.fullmatch(request["settingsFingerprint"])):
        fail("invalid_account_request")
    identifier(request["broadcastId"])
    identifier(request["streamId"])
    try:
        vault = vault if vault is not None else PlatformCredentialVault(credential_path())
        record = deepcopy(vault.get("youtube"))
    except Exception:
        fail("account_storage_unavailable")
    def guard():
        try:
            current = vault.get("youtube")
        except Exception:
            fail("account_storage_unavailable")
        if current != record:
            fail("account_state_changed")
        validate_record(current, clock=clock, headroom=30)
        configured = os.environ.get("RAREIQ_YOUTUBE_CLIENT_ID", "").strip()
        if account_ref(current) != request["accountRef"] or configured and configured != current["client_id"]:
            fail("account_identity_mismatch")
    guard()
    factory = http_factory or (lambda: httpx.AsyncClient(
        timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))
    try:
        async with factory() as client:
            selection, server, key = await YouTubeReader(record, guard, client).inspect(request["broadcastId"], private=True)
        guard()
        if (selection["stream_id"] != request["streamId"]
                or selection["settings_fingerprint"] != request["settingsFingerprint"]):
            fail("broadcast_selection_changed")
        return {"ok": True, "platform": "youtube", "accountRef": request["accountRef"],
                "broadcastId": request["broadcastId"], "streamId": request["streamId"],
                "settingsFingerprint": request["settingsFingerprint"],
                "autoStart": selection["auto_start"], "autoStop": selection["auto_stop"],
                "privacyStatus": selection["privacy_status"],
                "serverUrl": server, "streamKey": key}
    except asyncio.CancelledError:
        raise
    except Exception as error:
        fail(safe_reason(error))


def main():
    try:
        if len(sys.argv) != 1:
            fail("invalid_account_request")
        raw = sys.stdin.buffer.read(1025)
        if len(raw) > 1024:
            fail("invalid_account_request")
        try:
            request = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            fail("invalid_account_request")
        result = asyncio.run(resolve_stream_key(request))
    except ValueError as error:
        result = {"ok": False, "reason": safe_reason(error)}
    except Exception:
        result = {"ok": False, "reason": "invalid_account_request"}
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
