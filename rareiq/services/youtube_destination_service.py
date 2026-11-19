"""Read-only selection of an existing owned, bound YouTube broadcast.

Account owners retain refresh authority. This module never creates, binds,
transitions or updates a broadcast, and public selections contain no ingest data.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from urllib.parse import urlsplit

import httpx

from rareiq.services.youtube_account_service import YouTubeAccountService

CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
STREAMS_URL = "https://www.googleapis.com/youtube/v3/liveStreams"
MAX_BYTES = 262144
MAX_PAGES = 2
MAX_BROADCASTS = 100
ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
LIVE_STATES = frozenset({"created", "ready", "testing", "testStarting", "live", "liveStarting"})
STREAM_STATES = frozenset({"ready", "active", "inactive"})
PRIVACY_STATES = frozenset({"public", "unlisted", "private"})
SAFE_REASONS = frozenset({
    "authorization_required", "authorization_rejected", "authorization_refresh_required",
    "app_setup_required", "account_authorization_required", "account_identity_mismatch",
    "account_storage_unavailable", "account_state_changed", "streaming_scope_required",
    "provider_unavailable", "provider_rate_limited", "provider_response_too_large",
    "invalid_provider_response", "invalid_account_request", "invalid_broadcast_id",
    "youtube_broadcast_unavailable", "youtube_broadcast_not_owned", "youtube_stream_unavailable",
    "youtube_stream_not_owned", "youtube_stream_shared", "broadcast_selection_changed",
    "broadcast_selection_limit", "secure_ingest_unavailable", "streaming_not_available",
})


def fail(reason):
    raise ValueError(reason)


def safe_reason(error):
    reason = str(error)
    return reason if reason in SAFE_REASONS else "provider_unavailable"


def account_ref(record):
    return YouTubeAccountService.account_ref(record)


def validate_record(record, *, clock=time.time, headroom=0):
    if (not isinstance(record, dict) or not isinstance(record.get("client_id"), str)
            or not YouTubeAccountService._CLIENT.fullmatch(record["client_id"])
            or not isinstance(record.get("channel_id"), str)
            or not YouTubeAccountService._CHANNEL.fullmatch(record["channel_id"])
            or record.get("token_type") != "bearer"):
        fail("account_authorization_required")
    scopes = record.get("scopes")
    if (not isinstance(scopes, list) or len(scopes) > 32
            or any(not isinstance(scope, str) or not 1 <= len(scope) <= 128 for scope in scopes)
            or YouTubeAccountService.SCOPE not in scopes):
        fail("streaming_scope_required")
    expires = record.get("expires_at")
    if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= clock() + headroom:
        fail("authorization_refresh_required")
    secret(record.get("access_token"))
    return record


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(not 33 <= ord(c) <= 126 for c in value):
        fail("invalid_provider_response")
    return value


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail("invalid_broadcast_id")
    return value


def _text(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 100 or not value.strip()
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        fail("invalid_provider_response")
    return value


def settings_fingerprint(ref, broadcast_id, stream_id, auto_start, auto_stop, privacy_status):
    fixed = ["youtube-bound-broadcast-v2", ref, broadcast_id, stream_id, auto_start, auto_stop, privacy_status]
    return hashlib.sha256(json.dumps(fixed, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def _selection(record, item):
    snippet, status, details = item.get("snippet"), item.get("status"), item.get("contentDetails")
    if not isinstance(snippet, dict) or not isinstance(status, dict) or not isinstance(details, dict):
        fail("invalid_provider_response")
    if snippet.get("channelId") != record["channel_id"]:
        fail("youtube_broadcast_not_owned")
    if status.get("lifeCycleStatus") not in LIVE_STATES:
        fail("youtube_broadcast_unavailable")
    if status.get("privacyStatus") not in PRIVACY_STATES:
        fail("invalid_provider_response")
    broadcast_id, stream_id = identifier(item.get("id")), details.get("boundStreamId")
    if not isinstance(stream_id, str) or not ID.fullmatch(stream_id):
        fail("youtube_stream_unavailable")
    if type(details.get("enableAutoStart")) is not bool or type(details.get("enableAutoStop")) is not bool:
        fail("invalid_provider_response")
    ref = account_ref(record)
    return {"platform": "youtube", "account_ref": ref, "broadcast_id": broadcast_id,
            "stream_id": stream_id, "title": _text(snippet.get("title")),
            "auto_start": details["enableAutoStart"], "auto_stop": details["enableAutoStop"],
            "lifecycle": status["lifeCycleStatus"], "privacy_status": status["privacyStatus"],
            "settings_fingerprint": settings_fingerprint(ref, broadcast_id, stream_id,
                details["enableAutoStart"], details["enableAutoStop"], status["privacyStatus"])}


def secure_ingest(value):
    if not isinstance(value, str) or not value.startswith("rtmps://") or len(value) > 2048:
        fail("secure_ingest_unavailable")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != "rtmps" or not host or parsed.username is not None or parsed.password is not None
                or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value or "?" in value or "#" in value
                or parsed.port not in (None, 443) or not re.fullmatch(r"[A-Za-z0-9.-]+", host)
                or not any(host.lower() == domain or host.lower().endswith("." + domain) for domain in ("rtmp.youtube.com", "rtmps.youtube.com"))
                or parsed.path.rstrip("/") != "/live2"):
            fail("secure_ingest_unavailable")
    except ValueError:
        fail("secure_ingest_unavailable")
    return value


class YouTubeReader:
    """One bounded transport; its only permitted provider method is GET."""
    def __init__(self, record, guard, client):
        self.record, self.guard, self.client = record, guard, client

    async def request(self, endpoint, params):
        if endpoint not in {CHANNELS_URL, BROADCASTS_URL, STREAMS_URL}:
            fail("invalid_provider_response")
        self.guard()
        try:
            async with self.client.stream("GET", endpoint, params=params,
                    headers={"Authorization": "Bearer " + self.record["access_token"]},
                    follow_redirects=False, timeout=httpx.Timeout(8, connect=3)) as response:
                self.guard()
                if response.status_code != 200:
                    fail({401: "authorization_rejected", 403: "streaming_not_available", 429: "provider_rate_limited"}.get(response.status_code, "provider_unavailable"))
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    fail("invalid_provider_response")
                data = bytearray()
                async for block in response.aiter_bytes():
                    self.guard()
                    if len(data) + len(block) > MAX_BYTES:
                        fail("provider_response_too_large")
                    data.extend(block)
                value = json.loads(bytes(data).decode("utf-8"))
                if not isinstance(value, dict):
                    fail("invalid_provider_response")
                self.guard()
                return value
        except asyncio.CancelledError:
            raise
        except Exception as error:
            fail(safe_reason(error))

    @staticmethod
    def items(value, limit=50):
        rows = value.get("items")
        if not isinstance(rows, list) or len(rows) > limit or any(not isinstance(row, dict) for row in rows):
            fail("invalid_provider_response")
        return rows

    async def broadcasts(self):
        channels = await self.request(CHANNELS_URL, {"part": "id", "mine": "true", "maxResults": 2})
        rows = self.items(channels, 2)
        if len(rows) != 1 or rows[0].get("id") != self.record["channel_id"] or channels.get("nextPageToken"):
            fail("account_identity_mismatch")
        # The API defaults broadcastType to event; persistent broadcasts must
        # also participate in dedicated-stream checks. mine is the sole filter.
        params = {"part": "id,snippet,status,contentDetails", "mine": "true", "broadcastType": "all", "maxResults": 50,
                  "fields": "items(id,snippet(channelId,title),status(lifeCycleStatus,privacyStatus),contentDetails(boundStreamId,enableAutoStart,enableAutoStop)),nextPageToken"}
        items, seen, tokens = [], set(), set()
        for _ in range(MAX_PAGES):
            value = await self.request(BROADCASTS_URL, params)
            for item in self.items(value):
                broadcast_id = identifier(item.get("id"))
                if broadcast_id in seen:
                    fail("invalid_provider_response")
                seen.add(broadcast_id)
                snippet, state = item.get("snippet"), item.get("status")
                if not isinstance(snippet, dict) or not isinstance(state, dict):
                    fail("invalid_provider_response")
                if snippet.get("channelId") != self.record["channel_id"]:
                    fail("youtube_broadcast_not_owned")
                if state.get("lifeCycleStatus") in LIVE_STATES:
                    if not isinstance(item.get("contentDetails"), dict):
                        fail("invalid_provider_response")
                    items.append(item)
            token = value.get("nextPageToken")
            if not token:
                return items
            if not isinstance(token, str) or not 1 <= len(token) <= 256 or token in tokens or any(ord(c) < 33 or ord(c) > 126 for c in token):
                fail("invalid_provider_response")
            tokens.add(token)
            params["pageToken"] = token
        fail("broadcast_selection_limit")

    async def inspect(self, broadcast_id, *, private=False):
        identifier(broadcast_id)
        rows = await self.broadcasts()
        matches = [row for row in rows if row.get("id") == broadcast_id]
        if len(matches) != 1:
            fail("youtube_broadcast_unavailable")
        selection = _selection(self.record, matches[0])
        for row in rows:
            if row.get("id") != broadcast_id and (row.get("contentDetails") or {}).get("boundStreamId") == selection["stream_id"]:
                fail("youtube_stream_shared")
        value = await self.request(STREAMS_URL, {"part": "id,snippet,status,cdn", "id": selection["stream_id"], "maxResults": 1})
        streams = self.items(value, 1)
        if len(streams) != 1 or streams[0].get("id") != selection["stream_id"] or value.get("nextPageToken"):
            fail("youtube_stream_unavailable")
        stream = streams[0]
        if not isinstance(stream.get("snippet"), dict) or stream["snippet"].get("channelId") != self.record["channel_id"]:
            fail("youtube_stream_not_owned")
        state = stream.get("status")
        if not isinstance(state, dict) or state.get("streamStatus") not in STREAM_STATES:
            fail("youtube_stream_unavailable")
        selection["stream_status"] = state["streamStatus"]
        cdn = stream.get("cdn")
        ingestion = cdn.get("ingestionInfo") if isinstance(cdn, dict) else None
        if not isinstance(ingestion, dict) or cdn.get("ingestionType") != "rtmp":
            fail("streaming_not_available")
        server, key = secure_ingest(ingestion.get("rtmpsIngestionAddress")), secret(ingestion.get("streamName"))
        return (selection, server, key) if private else selection


class YouTubeDestinationService:
    def __init__(self, owner, *, http_factory=None, clock=time.time):
        self.owner, self.clock = owner, clock
        self.http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))

    async def _access(self, operation):
        if not callable(getattr(self.owner, "with_stream_info_access", None)):
            fail("account_authorization_required")
        async def use(record, guard):
            validate_record(record, clock=self.clock)
            async with self.http_factory() as client:
                result = await operation(YouTubeReader(record, guard, client))
            guard()
            return result
        try:
            return await self.owner.with_stream_info_access(use, require_edit=False)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            fail(safe_reason(error))

    async def list_broadcasts(self):
        async def operation(reader):
            rows = await reader.broadcasts()
            selections = []
            for row in rows:
                try:
                    selection = _selection(reader.record, row)
                except ValueError as error:
                    if str(error) == "youtube_stream_unavailable":
                        continue  # Unbound broadcasts are deliberately outside this slice.
                    raise
                shared = any(other["id"] != row["id"] and (other.get("contentDetails") or {}).get("boundStreamId") == selection["stream_id"] for other in rows)
                if not shared:
                    selections.append(selection)
            streams = {}
            ids = sorted({item["stream_id"] for item in selections})
            for offset in range(0, len(ids), 50):
                batch = ids[offset:offset + 50]
                value = await reader.request(STREAMS_URL, {"part": "id,snippet,status", "id": ",".join(batch), "maxResults": 50,
                    "fields": "items(id,snippet(channelId),status(streamStatus))"})
                if value.get("nextPageToken"):
                    fail("invalid_provider_response")
                for stream in reader.items(value):
                    stream_id = identifier(stream.get("id"))
                    if stream_id not in batch or stream_id in streams:
                        fail("invalid_provider_response")
                    if not isinstance(stream.get("snippet"), dict) or stream["snippet"].get("channelId") != reader.record["channel_id"]:
                        fail("youtube_stream_not_owned")
                    state = stream.get("status")
                    if not isinstance(state, dict) or state.get("streamStatus") not in STREAM_STATES:
                        continue
                    streams[stream_id] = state["streamStatus"]
            selections = [{**item, "stream_status": streams[item["stream_id"]]} for item in selections if item["stream_id"] in streams]
            return {"platform": "youtube", "account_ref": account_ref(reader.record), "broadcasts": selections}
        return await self._access(operation)

    async def inspect_broadcast(self, broadcast_id):
        identifier(broadcast_id)
        return await self._access(lambda reader: reader.inspect(broadcast_id))
