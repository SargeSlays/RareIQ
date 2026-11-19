"""Volatile, operator-opted-in viewer transcript; never an event or disk log."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import json
import math
import threading
import time
import uuid


PLATFORMS = ("twitch", "youtube", "kick")
MAX_CURSOR = 2**53 - 1


def _text(value, maximum, *, multiline=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any((ord(c) < 32 and (not multiline or c not in "\n\t"))
                   or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError("invalid_viewer_chat_text")
    return value


@dataclass(frozen=True, repr=False)
class TrustedViewerChatMessage:
    """Construct only after the adapter verifies the provider and channel binding."""

    platform: str
    channel_id: str
    message_id: str
    author_id: str
    display_name: str
    text: str
    occurred_at: float

    def __post_init__(self):
        if self.platform not in PLATFORMS:
            raise ValueError("unsupported_viewer_chat_platform")
        for value in (self.channel_id, self.message_id, self.author_id):
            _text(value, 160)
        _text(self.display_name, 80)
        _text(self.text, 4096, multiline=True)
        if (type(self.occurred_at) not in (int, float) or not math.isfinite(self.occurred_at)
                or not 0 < self.occurred_at < 1e12):
            raise ValueError("invalid_viewer_chat_timestamp")


def deliver_viewer_chat(sink, *args):
    """A transcript fault must never interrupt an otherwise valid observation."""
    if sink is None:
        return
    try:
        sink(TrustedViewerChatMessage(*args))
    except Exception:
        # Neither provider data nor exception text is logged or exposed.
        pass


class ViewerChatService:
    MAX_MESSAGES = 300
    RETENTION_SECONDS = 20 * 60
    MAX_DEDUP = 4096
    MAX_EVENT_AGE = 120

    def __init__(self, *, clock=time.time):
        self._clock, self._lock = clock, threading.RLock()
        self._active = False
        self._session_id = uuid.uuid4().hex
        self._started_at = clock()
        self._cursor = 0
        self._messages = deque()
        self._seen = OrderedDict()

    @property
    def active(self):
        with self._lock:
            return self._active

    def set_listening(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("invalid_viewer_chat_listening")
        with self._lock:
            if enabled != self._active:
                self._active = enabled
                self._session_id = uuid.uuid4().hex
                self._started_at = self._clock()
                self._messages.clear()
                self._seen.clear()
            return self.status()

    def _cleanup(self, now):
        cutoff = now - self.RETENTION_SECONDS
        while self._messages and self._messages[0]["received_at"] <= cutoff:
            self._messages.popleft()
        while self._seen and next(iter(self._seen.values())) <= cutoff:
            self._seen.popitem(last=False)

    def accept(self, message):
        if not isinstance(message, TrustedViewerChatMessage):
            raise ValueError("trusted_viewer_chat_message_required")
        with self._lock:
            now = self._clock()
            self._cleanup(now)
            if not self._active:
                return {"ok": False, "reason": "viewer_chat_listening_disabled"}
            if not max(self._started_at, now - self.MAX_EVENT_AGE) <= message.occurred_at <= now + 5:
                return {"ok": False, "reason": "viewer_chat_message_outside_session"}
            key = hashlib.sha256(json.dumps([message.platform, message.channel_id,
                                            message.message_id]).encode("utf-8")).digest()
            if key in self._seen:
                return {"ok": True, "duplicate": True}
            if self._cursor >= MAX_CURSOR:
                return {"ok": False, "reason": "viewer_chat_cursor_exhausted"}
            self._cursor += 1
            self._messages.append({"id": self._cursor, "platform": message.platform,
                                   "display_name": message.display_name, "text": message.text,
                                   "occurred_at": message.occurred_at, "received_at": now})
            while len(self._messages) > self.MAX_MESSAGES:
                self._messages.popleft()
            self._seen[key] = now
            while len(self._seen) > self.MAX_DEDUP:
                self._seen.popitem(last=False)
            return {"ok": True, "duplicate": False}

    def status(self, *, after=0, session_id=None):
        if type(after) is not int or not 0 <= after <= MAX_CURSOR:
            raise ValueError("invalid_viewer_chat_cursor")
        if session_id is not None and (not isinstance(session_id, str) or len(session_id) > 64):
            raise ValueError("invalid_viewer_chat_session")
        with self._lock:
            self._cleanup(self._clock())
            floor = self._messages[0]["id"] - 1 if self._messages else self._cursor
            reset = session_id != self._session_id or after > self._cursor or after < floor
            return {"active": self._active, "session_id": self._session_id,
                    "cursor": self._cursor, "reset": reset,
                    "messages": [dict(row) for row in self._messages if reset or row["id"] > after]}
