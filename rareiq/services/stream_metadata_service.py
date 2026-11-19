"""Guarded metadata-only adapters. Never create, start, or transition broadcasts.

Account owners retain credential ownership for the entire operation. Provider
responses are bounded and projected onto public fields; errors are constant codes.
Optional durable fingerprints preserve uncertainty across backend restarts.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import re

import httpx

from rareiq.core.stream_metadata_receipts import StreamMetadataReceiptStore


class StreamMetadataService:
    TWITCH_CHANNELS = "https://api.twitch.tv/helix/channels"
    TWITCH_SEARCH = "https://api.twitch.tv/helix/search/categories"
    TWITCH_GAMES = "https://api.twitch.tv/helix/games"
    KICK_CHANNELS = "https://api.kick.com/public/v1/channels"
    KICK_CATEGORIES = "https://api.kick.com/public/v2/categories"
    YOUTUBE_BROADCASTS = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
    YOUTUBE_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
    YOUTUBE_CATEGORIES = "https://www.googleapis.com/youtube/v3/videoCategories"
    EDIT_SCOPES = {"twitch": "channel:manage:broadcast", "kick": "channel:write",
                   "youtube": "https://www.googleapis.com/auth/youtube.force-ssl"}
    MAX_BYTES = 262144
    MAX_RECEIPTS = 128
    MAX_BROADCASTS = 100
    _ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
    _NUMBER = re.compile(r"[1-9][0-9]{0,18}\Z")
    _CHANNEL = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
    _LIVE_STATES = frozenset({"created", "ready", "testing", "testStarting", "live", "liveStarting"})
    _SAFE_ERRORS = frozenset({
        "authorization_required", "authorization_rejected", "authorization_refresh_required",
        "authorization_expired", "account_disconnected", "account_state_changed",
        "account_identity_mismatch", "account_storage_unavailable", "app_setup_required",
        "stream_info_scope_required", "metadata_scope_required", "provider_unavailable",
        "provider_rate_limited", "provider_rejected", "provider_response_too_large",
        "invalid_provider_response", "broadcast_selection_required", "broadcast_not_owned",
        "broadcast_unavailable", "category_not_found", "invalid_category_id",
        "request_id_conflict", "receipt_capacity_reached", "invalid_provider_endpoint",
        "metadata_precondition_required",
        "metadata_recovery_storage_invalid", "metadata_recovery_storage_unavailable",
    })

    def __init__(self, accounts, *, http_factory=None, receipt_path=None):
        self._accounts = dict(accounts)
        self._http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))
        self._locks = {platform: asyncio.Lock() for platform in self.EDIT_SCOPES}
        self._receipts = OrderedDict()
        self._receipt_store, self._receipt_error = None, None
        if receipt_path is not None:
            try:
                self._receipt_store = StreamMetadataReceiptStore(receipt_path)
            except ValueError as exc:
                self._receipt_error = str(exc)

    @classmethod
    def _platform(cls, platform):
        if not isinstance(platform, str) or platform not in cls.EDIT_SCOPES:
            raise ValueError("unsupported_platform")
        return platform

    @staticmethod
    def _text(value, limit, *, empty=True, multiline=False, code="invalid_provider_response"):
        if (not isinstance(value, str) or len(value) > limit or (not empty and not value.strip())
                or any((ord(c) < 32 and not (multiline and c in "\n\r\t"))
                       or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
            raise ValueError(code)
        return value

    @classmethod
    def _numeric_id(cls, value, *, empty=False, code="invalid_provider_response"):
        if type(value) is int:
            value = str(value)
        if empty and value == "":
            return value
        if not isinstance(value, str) or not cls._NUMBER.fullmatch(value):
            raise ValueError(code)
        return value

    @classmethod
    def _broadcast_id(cls, value):
        if value is not None and (not isinstance(value, str) or not cls._ID.fullmatch(value)):
            raise ValueError("invalid_broadcast_id")
        return value

    @classmethod
    def _values(cls, platform, values):
        supported = {"title", "category_id", "tags"} | ({"description"} if platform == "youtube" else set())
        if not isinstance(values, dict) or not values or len(values) > 4:
            raise ValueError("invalid_metadata")
        if set(values) - supported:
            raise ValueError("unsupported_metadata_field")
        result = {}
        for key, value in values.items():
            if key == "title":
                result[key] = cls._text(value, 100, empty=False, code="invalid_title")
                if platform == "youtube" and any(c in value for c in "<>"):
                    raise ValueError("invalid_title")
            elif key == "description":
                result[key] = cls._text(value, 5000, multiline=True, code="invalid_description")
                if len(value.encode("utf-8")) > 5000 or any(c in value for c in "<>"):
                    raise ValueError("invalid_description")
            elif key == "category_id":
                if value == "":  # An empty category input means preserve the provider value.
                    continue
                result[key] = cls._numeric_id(value, code="invalid_category_id")
            elif key == "tags":
                max_count = 100 if platform == "youtube" else 10
                max_length = 25 if platform == "twitch" else 100
                if not isinstance(value, list) or len(value) > max_count:
                    raise ValueError("invalid_tags")
                tags = [cls._text(tag, max_length, empty=False, code="invalid_tags") for tag in value]
                if (len({tag.casefold() for tag in tags}) != len(tags)
                        or platform == "twitch" and any(not tag.isalnum() for tag in tags)):
                    raise ValueError("invalid_tags")
                if platform == "youtube" and sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + max(0, len(tags) - 1) > 500:
                    raise ValueError("invalid_tags")
                result[key] = tags
        if not result:
            raise ValueError("no_metadata_changes")
        return result

    @classmethod
    def _capabilities(cls, platform):
        return {"title": True, "description": platform == "youtube", "category_id": True,
                "tags": True, "requires_broadcast_selection": platform == "youtube"}

    async def _access(self, platform, operation, *, edit=False):
        owner = self._accounts.get(platform)
        if owner is None or not callable(getattr(owner, "with_stream_info_access", None)):
            raise ValueError("authorization_required")
        try:
            return await owner.with_stream_info_access(operation, require_edit=edit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = str(exc)
            raise ValueError(reason if reason in self._SAFE_ERRORS else "provider_unavailable") from None

    @staticmethod
    def _headers(platform, record):
        headers = {"Authorization": "Bearer " + record["access_token"]}
        if platform == "twitch":
            headers["Client-Id"] = record["client_id"]
        return headers

    async def _request(self, platform, record, guard, method, endpoint, **kwargs):
        allowed = {self.TWITCH_CHANNELS, self.TWITCH_SEARCH, self.TWITCH_GAMES,
                   self.KICK_CHANNELS, self.KICK_CATEGORIES, self.YOUTUBE_BROADCASTS,
                   self.YOUTUBE_VIDEOS, self.YOUTUBE_CATEGORIES}
        if endpoint not in allowed or method not in {"GET", "PATCH", "PUT"}:
            raise ValueError("invalid_provider_endpoint")
        guard()
        client = None
        try:
            client = self._http_factory()
            headers = self._headers(platform, record) | kwargs.pop("headers", {})
            async with client.stream(method, endpoint, headers=headers,
                                     timeout=httpx.Timeout(8, connect=3), follow_redirects=False, **kwargs) as response:
                guard()
                status = response.status_code
                if status not in (200, 204):
                    reason = {400: "provider_rejected", 401: "authorization_rejected",
                              403: "authorization_rejected", 404: "provider_rejected",
                              409: "provider_rejected", 412: "provider_rejected", 422: "provider_rejected",
                              429: "provider_rate_limited"}.get(status, "provider_unavailable")
                    raise ValueError(reason)
                if status == 204:
                    return {}
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    guard()
                    if len(raw) + len(chunk) > self.MAX_BYTES:
                        raise ValueError("provider_response_too_large")
                    raw.extend(chunk)
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("invalid_provider_response")
                return value
        except asyncio.CancelledError:
            raise
        except ValueError as exc:
            reason = str(exc)
            raise ValueError(reason if reason in self._SAFE_ERRORS else "invalid_provider_response") from None
        except Exception as exc:
            reason = str(exc)
            raise ValueError(reason if reason in self._SAFE_ERRORS else "provider_unavailable") from None
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.aclose(), 2)
                except Exception:
                    pass

    @staticmethod
    def _items(value, key, limit=100):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > limit or any(not isinstance(item, dict) for item in items):
            raise ValueError("invalid_provider_response")
        return items

    @classmethod
    def _channel_id(cls, record):
        value = record.get("channel_id")
        if not isinstance(value, str) or not cls._CHANNEL.fullmatch(value):
            raise ValueError("account_identity_mismatch")
        return value

    async def _broadcasts(self, record, guard, broadcast_id=None):
        channel_id = self._channel_id(record)
        params = {"part": "snippet,status", "broadcastType": "all", "maxResults": 50,
                  "fields": "items(id,snippet(channelId,title),status(lifeCycleStatus)),nextPageToken"}
        params["id" if broadcast_id else "mine"] = broadcast_id or "true"
        results, seen = [], set()
        # Bound provider pagination. Do not silently choose a truncated first event.
        for _ in range(3):
            value = await self._request("youtube", record, guard, "GET", self.YOUTUBE_BROADCASTS, params=params)
            for item in self._items(value, "items", 50):
                snippet, status = item.get("snippet"), item.get("status")
                if not isinstance(snippet, dict) or not isinstance(status, dict):
                    raise ValueError("invalid_provider_response")
                if snippet.get("channelId") != channel_id:
                    if broadcast_id:
                        raise ValueError("broadcast_not_owned")
                    continue
                item_id = self._broadcast_id(item.get("id"))
                if not item_id or (broadcast_id and item_id != broadcast_id):
                    raise ValueError("invalid_provider_response")
                state = status.get("lifeCycleStatus")
                if state not in self._LIVE_STATES:
                    continue
                title = self._text(snippet.get("title"), 100)
                if item_id not in seen:
                    results.append({"id": item_id, "title": title, "state": state})
                    seen.add(item_id)
            token = value.get("nextPageToken")
            if not token or broadcast_id or len(results) >= self.MAX_BROADCASTS:
                break
            params["pageToken"] = self._text(token, 256, empty=False)
        if broadcast_id and not results:
            raise ValueError("broadcast_unavailable")
        return results[:self.MAX_BROADCASTS]

    async def _read(self, platform, record, guard, broadcast_id=None):
        channel = self._channel_id(record)
        if platform == "youtube":
            if not broadcast_id:
                raise ValueError("broadcast_selection_required")
            await self._broadcasts(record, guard, broadcast_id)
            value = await self._request(platform, record, guard, "GET", self.YOUTUBE_VIDEOS,
                                        params={"part": "snippet", "id": broadcast_id})
            items = self._items(value, "items", 1)
            if len(items) != 1 or items[0].get("id") != broadcast_id:
                raise ValueError("broadcast_unavailable")
            snippet = items[0].get("snippet")
            if not isinstance(snippet, dict) or snippet.get("channelId") != channel:
                raise ValueError("broadcast_not_owned")
            fields = {"title": self._text(snippet.get("title"), 100),
                      "description": self._text(snippet.get("description", ""), 5000, multiline=True),
                      "category_id": self._numeric_id(snippet.get("categoryId")),
                      "tags": self._read_tags(snippet.get("tags", []), 100, 100)}
            preserved = {key: deepcopy(snippet[key]) for key in
                         ("title", "description", "categoryId", "tags", "defaultLanguage", "defaultAudioLanguage")
                         if key in snippet}
            for key in ("defaultLanguage", "defaultAudioLanguage"):
                if key in preserved:
                    self._text(preserved[key], 80, empty=False)
            etag = items[0].get("etag")
            if etag is not None:
                self._text(etag, 256, empty=False)
            return fields, {"snippet": preserved, "etag": etag}
        endpoint = self.TWITCH_CHANNELS if platform == "twitch" else self.KICK_CHANNELS
        # Kick omits query parameters to prove the token's actual owner.
        params = {"broadcaster_id": channel} if platform == "twitch" else {}
        value = await self._request(platform, record, guard, "GET", endpoint, params=params)
        items = self._items(value, "data", 1)
        if len(items) != 1:
            raise ValueError("account_identity_mismatch")
        item = items[0]
        identity = item.get("broadcaster_id") if platform == "twitch" else item.get("broadcaster_user_id")
        if str(identity) != channel:
            raise ValueError("account_identity_mismatch")
        if platform == "twitch":
            fields = {"title": self._text(item.get("title"), 140),
                      "category_id": self._numeric_id(item.get("game_id", ""), empty=True),
                      "category_name": self._text(item.get("game_name", ""), 200),
                      "tags": self._read_tags(item.get("tags", []), 10, 25)}
        else:
            category, stream = item.get("category", {}), item.get("stream", {})
            if not isinstance(category, dict) or not isinstance(stream, dict):
                raise ValueError("invalid_provider_response")
            category_id = category.get("id", "")
            category_name = self._text(category.get("name", ""), 200)
            # An owned channel that has never assigned a category can return
            # this exact empty sentinel. Never interpret a named zero ID as one.
            if type(category_id) is int and category_id == 0 and category_name == "":
                category_id = ""
            tags = stream.get("custom_tags", [])
            if tags is None:
                tags = []
            fields = {"title": self._text(item.get("stream_title"), 200),
                      "category_id": self._numeric_id(category_id, empty=True),
                      "category_name": category_name,
                      "tags": self._read_tags(tags, 10, 100)}
        return fields, None

    @classmethod
    def _read_tags(cls, tags, count, length):
        if not isinstance(tags, list) or len(tags) > count:
            raise ValueError("invalid_provider_response")
        return [cls._text(tag, length, empty=False) for tag in tags]

    async def inspect(self, platform, broadcast_id=None):
        platform, broadcast_id = self._platform(platform), self._broadcast_id(broadcast_id)
        if platform != "youtube" and broadcast_id is not None:
            raise ValueError("unsupported_broadcast_selection")
        async def operation(record, guard):
            guard()
            editable = self.EDIT_SCOPES[platform] in record.get("scopes", [])
            result = {"platform": platform, "authorized": True, "editable": editable,
                      "channel_id": self._channel_id(record), "fields": {},
                      "capabilities": self._capabilities(platform)}
            label = record.get("public_label", record.get("channel_login", ""))
            result["public_label"] = self._text(label, 120)
            if platform == "youtube" and broadcast_id is None:
                result["broadcasts"] = await self._broadcasts(record, guard)
                result["reason"] = "broadcast_selection_required"
            else:
                result["fields"], _ = await self._read(platform, record, guard, broadcast_id)
                if broadcast_id:
                    result["broadcast_id"] = broadcast_id
            if not editable:
                result["reason"] = "stream_info_scope_required"
            guard()
            return result
        try:
            return await self._access(platform, operation)
        except ValueError as exc:
            return {"platform": platform, "authorized": False, "editable": False, "fields": {},
                    "capabilities": self._capabilities(platform), "reason": str(exc)}

    async def _category_list(self, platform, record, guard, query=None, category_id=None):
        if platform == "twitch":
            endpoint = self.TWITCH_GAMES if category_id else self.TWITCH_SEARCH
            params = {"id": category_id} if category_id else {"query": query, "first": 30}
        elif platform == "kick":
            endpoint = self.KICK_CATEGORIES
            params = {"id": category_id, "limit": 30} if category_id else {"name": query, "limit": 30}
        else:
            endpoint = self.YOUTUBE_CATEGORIES
            params = {"part": "snippet", "id": category_id} if category_id else {"part": "snippet", "regionCode": "US"}
        value = await self._request(platform, record, guard, "GET", endpoint, params=params)
        items = self._items(value, "items" if platform == "youtube" else "data", 100)
        results = []
        for item in items:
            snippet = item.get("snippet") if platform == "youtube" else item
            if not isinstance(snippet, dict):
                raise ValueError("invalid_provider_response")
            if platform == "youtube" and snippet.get("assignable") is not True:
                continue
            item_id = self._numeric_id(item.get("id"))
            name = self._text(snippet.get("title" if platform == "youtube" else "name"), 200, empty=False)
            if (category_id and item_id != category_id) or (platform == "youtube" and query and query.casefold() not in name.casefold()):
                continue
            results.append({"id": item_id, "name": name})
        return results[:30]

    async def categories(self, platform, query):
        platform = self._platform(platform)
        query = self._text(query, 100, empty=platform == "youtube", code="invalid_category_query").strip()
        if platform == "kick" and len(query) < 3:
            raise ValueError("category_query_too_short")
        async def operation(record, guard):
            results = await self._category_list(platform, record, guard, query=query)
            guard()
            return {"platform": platform, "categories": results}
        return await self._access(platform, operation)

    def _load_receipts(self):
        if self._receipt_error:
            raise ValueError(self._receipt_error)
        if self._receipt_store is None:
            return
        records = self._receipt_store.load()
        for key, receipt in records.items():
            previous = self._receipts.get(key)
            if previous and previous["fingerprint"] == receipt["fingerprint"]:
                if "result" in previous:
                    receipt["result"] = previous["result"]
                # A failed completion write must not make a local uncertainty
                # evictable merely because the older disk state was applied.
                if previous.get("state") == "reserved":
                    receipt["state"] = "reserved"
        self._receipts = records

    def _reserve(self, key, fingerprint):
        if self._receipt_store is not None:
            protected = {old_key for old_key, value in self._receipts.items() if value.get("state") == "reserved"}
            receipt, created = self._receipt_store.reserve(key, fingerprint, maximum=self.MAX_RECEIPTS, protected=protected)
            self._receipts[key] = receipt
            # Merge reservations from other platforms without losing their
            # in-memory safe results; all store mutations are synchronous.
            self._load_receipts()
            return self._receipts[key], created
        if len(self._receipts) >= self.MAX_RECEIPTS:
            for old_key, receipt in list(self._receipts.items()):
                if receipt.get("state") == "applied":
                    del self._receipts[old_key]
                    break
            else:
                raise ValueError("receipt_capacity_reached")
        receipt = {"fingerprint": fingerprint, "state": "reserved"}
        self._receipts[key] = receipt
        return receipt, True

    def _finish(self, key, receipt, result):
        state = "applied" if result["state"] == "applied" else "reserved"
        if self._receipt_store is not None:
            try:
                self._receipt_store.finish(key, receipt["fingerprint"], state)
            except ValueError:
                result["recovery_storage_warning"] = True
                receipt["state"] = "reserved"
            else:
                receipt["state"] = state
        else:
            receipt["state"] = state
        receipt["result"] = deepcopy(result)
        self._receipts[key] = receipt
        return result

    def _forget(self, key):
        if self._receipt_store is not None:
            try:
                self._receipt_store.remove(key)
            except ValueError:
                return  # The durable reservation conservatively prevents a retry.
        self._receipts.pop(key, None)

    @staticmethod
    def _matches(fields, values):
        return all((set(fields.get(key, [])) == set(value) if key == "tags" else fields.get(key) == value)
                   for key, value in values.items())

    async def apply(self, platform, values, request_id, expected_channel_id, broadcast_id=None):
        platform, broadcast_id = self._platform(platform), self._broadcast_id(broadcast_id)
        values = self._values(platform, values)
        if not isinstance(request_id, str) or not self._ID.fullmatch(request_id):
            raise ValueError("invalid_request_id")
        if not isinstance(expected_channel_id, str) or not self._CHANNEL.fullmatch(expected_channel_id):
            raise ValueError("invalid_channel_id")
        if platform == "youtube" and not broadcast_id:
            raise ValueError("broadcast_selection_required")
        if platform != "youtube" and broadcast_id:
            raise ValueError("unsupported_broadcast_selection")
        fingerprint = hashlib.sha256(json.dumps([values, expected_channel_id, broadcast_id],
                                                sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        key = (platform, request_id)
        async with self._locks[platform]:
            # Corrupt/unreadable recovery state blocks Apply before credential
            # access; inspection and category lookup never touch this store.
            self._load_receipts()
            async def operation(record, guard):
                guard()
                if self._channel_id(record) != expected_channel_id:
                    raise ValueError("account_identity_mismatch")
                if self.EDIT_SCOPES[platform] not in record.get("scopes", []):
                    raise ValueError("stream_info_scope_required")
                receipt = self._receipts.get(key)
                if receipt is not None and receipt["fingerprint"] != fingerprint:
                    raise ValueError("request_id_conflict")
                # Always prove selection ownership even when returning an existing receipt.
                if receipt and receipt.get("result", {}).get("state") == "applied":
                    if platform == "youtube":
                        await self._broadcasts(record, guard, broadcast_id)
                    guard()
                    result = deepcopy(receipt["result"])
                    result.pop("recovery_storage_warning", None)
                    return self._finish(key, receipt, result)
                result = {"platform": platform, "request_id": request_id, "channel_id": expected_channel_id,
                          "state": "unconfirmed"}
                if broadcast_id:
                    result["broadcast_id"] = broadcast_id
                try:
                    fields, preserved = await self._read(platform, record, guard, broadcast_id)
                except ValueError as exc:
                    if receipt is None:
                        raise
                    if str(exc) in {"account_state_changed", "account_identity_mismatch", "broadcast_not_owned"}:
                        raise
                    result["reason"] = "readback_unavailable"
                    guard()
                    return self._finish(key, receipt, result)
                if self._matches(fields, values):
                    if receipt is None:
                        receipt, _ = self._reserve(key, fingerprint)
                    result.update(state="applied", fields=fields)
                    guard()
                    return self._finish(key, receipt, result)
                if receipt is not None:
                    # A previous attempt may still settle later. A new ID is an explicit new update.
                    result.update(reason="readback_mismatch", fields=fields)
                    guard()
                    return self._finish(key, receipt, result)
                if "category_id" in values:
                    categories = await self._category_list(platform, record, guard, category_id=values["category_id"])
                    if not any(category["id"] == values["category_id"] for category in categories):
                        raise ValueError("category_not_found")
                if platform == "youtube":
                    etag = preserved["etag"]
                    if (not etag or etag == "*" or "," in etag
                            or any(not 33 <= ord(char) <= 126 for char in etag)):
                        raise ValueError("metadata_precondition_required")
                    snippet = preserved["snippet"]
                    for field, provider_field in (("title", "title"), ("description", "description"),
                                                  ("tags", "tags"), ("category_id", "categoryId")):
                        if field in values:
                            snippet[provider_field] = values[field]
                    method, endpoint = "PUT", self.YOUTUBE_VIDEOS
                    kwargs = {"params": {"part": "snippet"}, "json": {"id": broadcast_id, "snippet": snippet}}
                    kwargs["headers"] = {"If-Match": etag}
                elif platform == "twitch":
                    body = {("game_id" if field == "category_id" else field): value for field, value in values.items()}
                    method, endpoint = "PATCH", self.TWITCH_CHANNELS
                    kwargs = {"params": {"broadcaster_id": expected_channel_id}, "json": body}
                else:
                    names = {"title": "stream_title", "category_id": "category_id", "tags": "custom_tags"}
                    body = {names[field]: int(value) if field == "category_id" else value for field, value in values.items()}
                    method, endpoint, kwargs = "PATCH", self.KICK_CHANNELS, {"json": body}
                guard()
                receipt, created = self._reserve(key, fingerprint)
                if not created:
                    # Another cooperating service reserved this ID during our
                    # preflight. Never issue a second provider mutation.
                    result.update(reason="readback_mismatch", fields=fields)
                    return self._finish(key, receipt, result)
                try:
                    await self._request(platform, record, guard, method, endpoint, **kwargs)
                except ValueError as exc:
                    if str(exc) in {"provider_rejected", "authorization_rejected", "provider_rate_limited"}:
                        self._forget(key)
                        raise
                    if str(exc) == "account_state_changed":
                        raise
                try:
                    fields, _ = await self._read(platform, record, guard, broadcast_id)
                    result.update(fields=fields)
                    if self._matches(fields, values):
                        result["state"] = "applied"
                    else:
                        result["reason"] = "readback_mismatch"
                except ValueError as exc:
                    if str(exc) in {"account_state_changed", "account_identity_mismatch", "broadcast_not_owned"}:
                        raise
                    result["reason"] = "readback_unavailable"
                guard()
                return self._finish(key, receipt, result)
            return await self._access(platform, operation, edit=True)
