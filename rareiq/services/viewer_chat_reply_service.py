"""Explicit operator chat replies with durable, content-free send receipts.

Readiness never connects accounts. Pending writes are committed before contacting
a provider; a lost reply or backend restart is uncertain and is never resent.
"""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading

import httpx

from rareiq.core.platform_credentials import _owner_only
from rareiq.services.viewer_chat_service import PLATFORMS


_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_CHANNEL = re.compile(r"[A-Za-z0-9_-]{1,160}\Z")
_NUMBER = re.compile(r"[1-9][0-9]{0,23}\Z")
REASONS = frozenset({"ready", "chat_send_permission_required", "chat_not_connected",
    "chat_account_required", "chat_target_unavailable", "chat_target_changed",
    "chat_provider_rejected", "chat_provider_rate_limited", "chat_send_uncertain",
    "chat_sent", "chat_storage_unavailable", "chat_receipt_capacity",
    "chat_request_conflict", "chat_not_attempted", "chat_activity_unavailable"})


def _result(platform, state, reason, retryable=False):
    return dict(platform=platform, state=state, reason=reason, retryable=retryable)


class ChatReplyReceipts:
    """One backend owns this bounded ledger. SQLite serializes durable claims."""

    MAX_RECEIPTS = 5000

    def __init__(self, path):
        self.path, self._lock = Path(path), threading.RLock()
        if not self.path.is_absolute():
            raise ValueError("chat_storage_unavailable")
        source = Path(__file__).resolve().parents[2]
        if source == self.path.resolve() or source in self.path.resolve().parents:
            raise ValueError("chat_storage_unavailable")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not self.path.exists():
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
            self._regular()
            _owner_only(self.path)
            with closing(self._connection()) as db:
                db.execute("CREATE TABLE IF NOT EXISTS replies (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, results TEXT NOT NULL)")
        except Exception:
            raise ValueError("chat_storage_unavailable") from None

    def _regular(self):
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode) or self.path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_size > 8 * 1024 * 1024):
            raise ValueError("chat_storage_unavailable")

    def _connection(self):
        self._regular()
        db = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA max_page_count=2048")
        return db

    def reserve(self, request_id, fingerprint, rows):
        with self._lock:
            try:
                with closing(self._connection()) as db:
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute("SELECT fingerprint,results FROM replies WHERE request_id=?", (request_id,)).fetchone()
                    if prior:
                        db.rollback()
                        if prior[0] != fingerprint:
                            raise ValueError("chat_request_conflict")
                        return json.loads(prior[1]), False
                    if db.execute("SELECT count(*) FROM replies").fetchone()[0] >= self.MAX_RECEIPTS:
                        raise ValueError("chat_receipt_capacity")
                    db.execute("INSERT INTO replies VALUES (?,?,?)", (request_id, fingerprint, json.dumps(rows)))
                    db.commit()
                    return rows, True
            except ValueError:
                raise
            except Exception:
                raise ValueError("chat_storage_unavailable") from None

    def save(self, request_id, rows):
        with self._lock:
            try:
                with closing(self._connection()) as db:
                    db.execute("BEGIN IMMEDIATE")
                    changed = db.execute("UPDATE replies SET results=? WHERE request_id=?", (json.dumps(rows), request_id)).rowcount
                    if changed != 1:
                        raise ValueError()
                    db.commit()
            except Exception:
                raise ValueError("chat_storage_unavailable") from None

    def update_row(self, request_id, platform, change, *, from_state, binding=None):
        """Compare-and-set one target without clobbering another caller's receipt."""
        with self._lock:
            try:
                with closing(self._connection()) as db:
                    db.execute("BEGIN IMMEDIATE")
                    raw = db.execute("SELECT results FROM replies WHERE request_id=?", (request_id,)).fetchone()
                    rows = json.loads(raw[0])
                    row = next(item for item in rows if item["platform"] == platform)
                    if row["state"] != from_state or from_state == "failed" and row.get("retryable") is not True:
                        db.rollback()
                        return False
                    if binding is not None and row["binding"] is not None and row["binding"] != binding:
                        db.rollback()
                        return False
                    row.update(change)
                    if binding is not None:
                        row["binding"] = binding
                    db.execute("UPDATE replies SET results=? WHERE request_id=?", (json.dumps(rows), request_id))
                    db.commit()
                    return True
            except Exception:
                raise ValueError("chat_storage_unavailable") from None

    def load(self, request_id):
        with closing(self._connection()) as db:
            row = db.execute("SELECT results FROM replies WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                raise ValueError("chat_storage_unavailable")
            return json.loads(row[0])


class AccountChatReplyAdapter:
    SCOPES = {"twitch": "user:write:chat", "youtube": "https://www.googleapis.com/auth/youtube.force-ssl", "kick": "chat:write"}
    ENDPOINTS = {"twitch": "https://api.twitch.tv/helix/chat/messages",
                 "youtube": "https://www.googleapis.com/youtube/v3/liveChat/messages",
                 "kick": "https://api.kick.com/public/v1/chat"}

    def __init__(self, platform, account, connector, *, http_factory=None):
        self.platform, self.account, self.connector = platform, account, connector
        self.http_factory = http_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(8, connect=3), follow_redirects=False, trust_env=False))

    def context(self):
        try:
            account = self.account.cached_chat_reply_context()
            if account.get("authorized") is not True:
                return None, "chat_account_required"
            scopes = account.get("scopes")
            if not isinstance(scopes, (tuple, list)) or self.SCOPES[self.platform] not in scopes:
                return None, "chat_send_permission_required"
            target = self.connector.cached_chat_reply_target()
            if target is None:
                return None, "chat_not_connected"
            channel, account_ref = account.get("channel_id"), account.get("account_ref")
            if (not isinstance(channel, str) or not _CHANNEL.fullmatch(channel)
                    or channel != target.get("channel_id") or not isinstance(account_ref, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", account_ref)
                    or self.platform in {"twitch", "kick"} and not _NUMBER.fullmatch(channel)
                    or self.platform == "youtube" and (not isinstance(target.get("live_chat_id"), str)
                        or not _CHANNEL.fullmatch(target["live_chat_id"]))):
                return None, "chat_target_unavailable"
            value = {"channel_id": channel, "account_ref": account_ref, "live_chat_id": target.get("live_chat_id")}
            value["binding"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            return value, "ready"
        except Exception:
            return None, "chat_target_unavailable"

    def status(self):
        context, reason = self.context()
        return {"platform": self.platform, "ready": context is not None, "reason": reason}

    async def send(self, text, binding):
        attempted = False

        async def operation(record, guard):
            nonlocal attempted
            context, reason = self.context()
            if context is None:
                return _result(self.platform, "failed", reason, reason in {"chat_not_connected", "chat_target_unavailable"})
            if context["binding"] != binding or record.get("channel_id") != context["channel_id"]:
                return _result(self.platform, "failed", "chat_target_changed")
            guard()
            channel = context["channel_id"]
            headers = {"Authorization": "Bearer " + record["access_token"]}
            params = None
            if self.platform == "twitch":
                headers["Client-Id"] = record["client_id"]
                body = {"broadcaster_id": channel, "sender_id": channel, "message": text}
            elif self.platform == "kick":
                body = {"broadcaster_user_id": int(channel), "content": text, "type": "user"}
            else:
                params = {"part": "snippet"}
                body = {"snippet": {"liveChatId": context["live_chat_id"], "type": "textMessageEvent", "textMessageDetails": {"messageText": text}}}
            client = self.http_factory()
            try:
                guard()
                attempted = True
                async with client.stream("POST", self.ENDPOINTS[self.platform], headers=headers,
                                         params=params, json=body, follow_redirects=False) as response:
                    if response.status_code == 429:
                        return _result(self.platform, "failed", "chat_provider_rate_limited", True)
                    if response.status_code in {401, 403}:
                        return _result(self.platform, "failed", "chat_send_permission_required")
                    if 400 <= response.status_code < 500:
                        return _result(self.platform, "failed", "chat_provider_rejected")
                    if response.status_code not in {200, 201}:
                        return _result(self.platform, "uncertain", "chat_send_uncertain")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 65536:
                            return _result(self.platform, "uncertain", "chat_send_uncertain")
                        data.extend(chunk)
                    value = json.loads(data)
                if self.platform == "twitch":
                    items = value.get("data")
                    item = items[0] if isinstance(items, list) and len(items) == 1 else {}
                elif self.platform == "kick":
                    item = value.get("data", {})
                else:
                    item = value
                    if item.get("snippet", {}).get("liveChatId") != context["live_chat_id"]:
                        return _result(self.platform, "uncertain", "chat_send_uncertain")
                if self.platform in {"twitch", "kick"} and item.get("is_sent") is False:
                    return _result(self.platform, "failed", "chat_provider_rejected")
                identifier = item.get("id") if self.platform == "youtube" else item.get("message_id")
                if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 160
                        or self.platform in {"twitch", "kick"} and item.get("is_sent") is not True):
                    return _result(self.platform, "uncertain", "chat_send_uncertain")
                return _result(self.platform, "sent", "chat_sent")
            finally:
                await client.aclose()

        try:
            return await self.account.with_chat_reply_access(operation)
        except Exception as exc:
            if attempted:
                return _result(self.platform, "uncertain", "chat_send_uncertain")
            reason = "chat_send_permission_required" if str(exc) == "chat_send_permission_required" else "chat_account_required"
            return _result(self.platform, "failed", reason)


class ViewerChatReplyService:
    def __init__(self, accounts=None, connectors=None, *, receipt_path, http_factory=None, adapters=None, audit=None):
        self._adapters = dict(adapters) if adapters is not None else {
            platform: AccountChatReplyAdapter(platform, (accounts or {}).get(platform),
                (connectors or {}).get(platform), http_factory=http_factory) for platform in PLATFORMS}
        try:
            self._store = ChatReplyReceipts(receipt_path)
        except ValueError:
            self._store = None
        self._lock, self._audit = asyncio.Lock(), audit

    def status(self):
        targets = []
        for platform in PLATFORMS:
            adapter = self._adapters.get(platform)
            try:
                raw = adapter.status() if adapter else {}
            except Exception:
                raw = {}
            if self._store is None:
                raw = {"ready": False, "reason": "chat_storage_unavailable"}
            targets.append({"platform": platform, "ready": raw.get("ready") is True,
                            "reason": raw.get("reason") if raw.get("reason") in REASONS else "chat_target_unavailable"})
        return {"ok": True, "max_length": 200, "targets": targets}

    @staticmethod
    def validate(value):
        if (not isinstance(value, dict) or set(value) - {"request_id", "text", "targets", "retry_failed"}
                or not {"request_id", "text", "targets"}.issubset(value)
                or not isinstance(value["request_id"], str) or not _ID.fullmatch(value["request_id"])
                or not isinstance(value["text"], str) or not value["text"].strip() or len(value["text"]) > 200
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF for char in value["text"])
                or not isinstance(value["targets"], list) or not 1 <= len(value["targets"]) <= 3
                or any(not isinstance(item, str) or item not in PLATFORMS for item in value["targets"])
                or len(set(value["targets"])) != len(value["targets"])
                or type(value.get("retry_failed", False)) is not bool):
            raise ValueError("invalid_chat_reply")
        return {**value, "targets": [platform for platform in PLATFORMS if platform in value["targets"]]}

    async def reply(self, value):
        value = self.validate(value)
        if self._store is None:
            raise ValueError("chat_storage_unavailable")
        fingerprint = hashlib.sha256(json.dumps([value["text"], value["targets"]], ensure_ascii=True).encode()).hexdigest()
        async with self._lock:
            initial = []
            for platform in value["targets"]:
                adapter = self._adapters.get(platform)
                context, _reason = adapter.context() if adapter else (None, None)
                initial.append({**_result(platform, "failed", "chat_not_attempted", True), "binding": context["binding"] if context else None})
            rows, created = self._store.reserve(value["request_id"], fingerprint, initial)
            if created or value.get("retry_failed"):
                for row in rows:
                    if row["state"] != "failed" or row.get("retryable") is not True:
                        continue
                    adapter = self._adapters.get(row["platform"])
                    context, reason = adapter.context() if adapter else (None, "chat_target_unavailable")
                    if context is None:
                        row.update(_result(row["platform"], "failed", reason, reason in {"chat_not_connected", "chat_target_unavailable"}))
                        self._store.update_row(value["request_id"], row["platform"], row, from_state="failed")
                        continue
                    if row["binding"] is not None and row["binding"] != context["binding"]:
                        row.update(_result(row["platform"], "failed", "chat_target_changed"))
                        self._store.update_row(value["request_id"], row["platform"], row, from_state="failed")
                        continue
                    row["binding"] = context["binding"]
                    if self._audit:
                        try:
                            self._audit(platform=row["platform"], outcome="requested", request_id=value["request_id"])
                        except Exception:
                            row.update(_result(row["platform"], "failed", "chat_activity_unavailable", True))
                            self._store.update_row(value["request_id"], row["platform"], row, from_state="failed")
                            continue
                    row.update(_result(row["platform"], "pending", "chat_send_uncertain"))
                    if not self._store.update_row(value["request_id"], row["platform"], row,
                                                  from_state="failed", binding=row["binding"]):
                        continue
                    try:
                        sent = await adapter.send(value["text"], row["binding"])
                        if (sent.get("state") not in {"sent", "failed", "uncertain"}
                                or sent.get("reason") not in REASONS):
                            raise ValueError()
                    except Exception:
                        sent = _result(row["platform"], "uncertain", "chat_send_uncertain")
                    row.update(sent)
                    self._store.update_row(value["request_id"], row["platform"], row, from_state="pending", binding=row["binding"])
                    if self._audit:
                        try:
                            self._audit(platform=row["platform"], outcome=row["state"], request_id=value["request_id"])
                        except Exception:
                            pass
            rows = self._store.load(value["request_id"])
            public = [{key: row[key] for key in ("platform", "state", "reason", "retryable")} for row in rows]
            for row in public:
                if row["state"] == "pending":
                    row.update(state="uncertain", reason="chat_send_uncertain", retryable=False)
            return {"ok": True, "request_id": value["request_id"], "duplicate": not created, "results": public}
