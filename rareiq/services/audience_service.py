"""Audience rules and scheduled graphics. Real platform adapters are not connected.

Only trusted server adapters may construct TrustedAudienceEvent after validating the
provider, channel binding and transport signature/session. There is no HTTP ingest.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Callable
import uuid


PLATFORMS = ("twitch", "youtube", "kick")
EVENTS = ("first_chat", "featured_chat", "follow", "subscription")
ANIMATIONS = ("slide", "pop", "spotlight")


def _text(value, maximum, *, empty=False):
    if (not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip())
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("invalid_audience_text")
    return value.strip()


@dataclass(frozen=True)
class TrustedAudienceEvent:
    platform: str
    channel_id: str
    event_id: str
    subject_id: str
    display_name: str
    kind: str
    occurred_at: float

    def __post_init__(self):
        if self.platform not in PLATFORMS or self.kind not in {"chat", "follow", "subscription"}:
            raise ValueError("unsupported_audience_event")
        for field in (self.channel_id, self.event_id, self.subject_id):
            if field != _text(field, 160):
                raise ValueError("invalid_audience_identifier")
        if self.platform == "youtube" and self.kind == "follow":
            raise ValueError("unsupported_audience_event")
        _text(self.display_name, 80)
        if type(self.occurred_at) not in (int, float) or not 0 < self.occurred_at < 1e12:
            raise ValueError("invalid_audience_time")


class AudienceService:
    MAX_EVENT_AGE = 120
    MAX_QUEUE = 12
    MAX_QUEUE_WAIT = 30
    MAX_EVENTS = 10000
    RETENTION_SECONDS = 86400

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(path), clock
        self._runtime = uuid.uuid4().hex
        self._runtime_started = clock()
        self._initialized = False
        self._lock = threading.RLock()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with self._lock:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS audience_state(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,enabled INTEGER NOT NULL,run_id TEXT NOT NULL,started_at REAL NOT NULL,runtime TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_rules(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_featured(identity TEXT PRIMARY KEY,label TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_events(key TEXT PRIMARY KEY,received_at REAL NOT NULL,kind TEXT NOT NULL,outcome TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_participants(identity TEXT PRIMARY KEY,run_id TEXT NOT NULL,label TEXT NOT NULL,chats INTEGER NOT NULL,last_seen REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_cooldowns(identity TEXT PRIMARY KEY,last_at REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,payload TEXT NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL,created_at REAL NOT NULL);
                    CREATE TABLE IF NOT EXISTS audience_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp REAL NOT NULL,actor_kind TEXT NOT NULL,action TEXT NOT NULL,revision INTEGER NOT NULL);
                    CREATE TRIGGER IF NOT EXISTS audience_audit_no_update BEFORE UPDATE ON audience_audit BEGIN SELECT RAISE(ABORT,'audience_audit_append_only'); END;
                    CREATE TRIGGER IF NOT EXISTS audience_audit_no_delete BEFORE DELETE ON audience_audit BEGIN SELECT RAISE(ABORT,'audience_audit_append_only'); END;
                """)
                if not self._initialized:
                    with db:
                        db.execute("BEGIN IMMEDIATE")
                        row = db.execute("SELECT * FROM audience_state WHERE id=1").fetchone()
                        if row is None:
                            db.execute("INSERT INTO audience_state VALUES(1,0,0,?,?,?)", (uuid.uuid4().hex, self._runtime_started, self._runtime))
                        elif row["runtime"] != self._runtime:
                            # Never replay pending graphics or keep automation armed after restart.
                            db.execute("UPDATE audience_state SET revision=revision+1,enabled=0,run_id=?,started_at=?,runtime=? WHERE id=1", (uuid.uuid4().hex, self._runtime_started, self._runtime))
                            db.execute("DELETE FROM audience_queue")
                            db.execute("DELETE FROM audience_participants")
                            db.execute("DELETE FROM audience_cooldowns")
                    self._initialized = True
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def validate_rule(data):
        if not isinstance(data, dict) or set(data) != {"id", "name", "enabled", "platform", "event", "message", "animation", "duration_ms", "cooldown_seconds"}:
            raise ValueError("invalid_audience_rule")
        result = dict(data)
        if (not isinstance(result["id"], str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", result["id"]) is None
                or type(result["enabled"]) is not bool or result["platform"] not in (*PLATFORMS, "any")
                or result["event"] not in EVENTS or result["animation"] not in ANIMATIONS
                or type(result["duration_ms"]) is not int or not 1500 <= result["duration_ms"] <= 10000
                or type(result["cooldown_seconds"]) is not int or not 10 <= result["cooldown_seconds"] <= 3600):
            raise ValueError("invalid_audience_rule")
        result["name"] = _text(result["name"], 60)
        result["message"] = _text(result["message"], 120)
        if result["platform"] == "youtube" and result["event"] == "follow":
            raise ValueError("unsupported_audience_trigger")
        if re.search(r"[{}]", result["message"].replace("{name}", "")):
            raise ValueError("audience_template_only_supports_name")
        return result

    @staticmethod
    def _identity(platform, channel_id, subject_id):
        if platform not in PLATFORMS:
            raise ValueError("unsupported_audience_platform")
        return json.dumps([platform, _text(channel_id, 160), _text(subject_id, 160)], separators=(",", ":"))

    def _cleanup(self, db, now):
        db.execute("DELETE FROM audience_queue WHERE ends_at<=?", (now,))
        db.execute("DELETE FROM audience_events WHERE received_at<?", (now - self.RETENTION_SECONDS,))
        db.execute("DELETE FROM audience_requests WHERE created_at<?", (now - self.RETENTION_SECONDS,))
        db.execute("DELETE FROM audience_participants WHERE last_seen<?", (now - self.RETENTION_SECONDS,))
        db.execute("DELETE FROM audience_cooldowns WHERE last_at<?", (now - 3600,))

    def configure(self, *, action, data, expected_revision, request_id, actor_kind):
        if action not in {"settings", "session", "save_rule", "delete_rule", "feature", "unfeature"} or not isinstance(data, dict):
            raise ValueError("invalid_audience_action")
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(request_id, str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", request_id) is None:
            raise ValueError("invalid_audience_precondition")
        if actor_kind not in {"local_operator", "paired_lan_operator"}:
            raise ValueError("invalid_audience_actor")
        if action == "save_rule":
            data = self.validate_rule(data)
        elif action in {"feature", "unfeature"}:
            if set(data) != ({"platform", "channel_id", "subject_id", "label"} if action == "feature" else {"platform", "channel_id", "subject_id"}):
                raise ValueError("invalid_audience_participant")
            identity = self._identity(data["platform"], data["channel_id"], data["subject_id"])
            if action == "feature":
                label = _text(data["label"], 80)
        elif action == "settings" and (set(data) != {"enabled"} or type(data["enabled"]) is not bool):
            raise ValueError("invalid_audience_settings")
        elif action == "session" and data:
            raise ValueError("invalid_audience_session")
        elif action == "delete_rule" and (set(data) != {"id"} or not isinstance(data["id"], str)):
            raise ValueError("invalid_audience_rule")
        fingerprint = hashlib.sha256(json.dumps([action, data, expected_revision, actor_kind], sort_keys=True).encode()).hexdigest()
        now = self.clock()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db, now)
            prior = db.execute("SELECT * FROM audience_requests WHERE id=?", (request_id,)).fetchone()
            if prior:
                return json.loads(prior["result"]) if prior["fingerprint"] == fingerprint else {"ok": False, "reason": "audience_request_conflict", "status": 409}
            state = db.execute("SELECT * FROM audience_state WHERE id=1").fetchone()
            if state["revision"] != expected_revision:
                return {"ok": False, "reason": "audience_revision_conflict", "status": 409}
            if action == "settings":
                db.execute("UPDATE audience_state SET enabled=? WHERE id=1", (int(data["enabled"]),))
                if not data["enabled"]:
                    db.execute("DELETE FROM audience_queue")
            elif action == "session":
                db.execute("UPDATE audience_state SET run_id=?,started_at=?,enabled=0 WHERE id=1", (uuid.uuid4().hex, now))
                for table in ("audience_participants", "audience_cooldowns", "audience_queue"):
                    db.execute("DELETE FROM " + table)
            elif action == "save_rule":
                exists = db.execute("SELECT 1 FROM audience_rules WHERE id=?", (data["id"],)).fetchone()
                if not exists and db.execute("SELECT COUNT(*) FROM audience_rules").fetchone()[0] >= 20:
                    return {"ok": False, "reason": "audience_rule_limit", "status": 409}
                db.execute("INSERT INTO audience_rules VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (data["id"], json.dumps(data)))
                db.execute("DELETE FROM audience_queue WHERE json_extract(payload,'$.rule_id')=?", (data["id"],))
            elif action == "delete_rule":
                db.execute("DELETE FROM audience_rules WHERE id=?", (data["id"],))
                # Do not let a removed rule's scheduled graphics play later.
                db.execute("DELETE FROM audience_queue WHERE json_extract(payload,'$.rule_id')=?", (data["id"],))
            elif action == "feature":
                exists = db.execute("SELECT 1 FROM audience_featured WHERE identity=?", (identity,)).fetchone()
                if not exists and db.execute("SELECT COUNT(*) FROM audience_featured").fetchone()[0] >= 200:
                    return {"ok": False, "reason": "audience_featured_limit", "status": 409}
                db.execute("INSERT INTO audience_featured VALUES (?,?) ON CONFLICT(identity) DO UPDATE SET label=excluded.label", (identity, label))
            elif action == "unfeature":
                db.execute("DELETE FROM audience_featured WHERE identity=?", (identity,))
                participant_key = hashlib.sha256(identity.encode()).hexdigest()
                db.execute("DELETE FROM audience_queue WHERE json_extract(payload,'$._participant_key')=? AND json_extract(payload,'$.subtitle')='Featured participant'", (participant_key,))
            revision = state["revision"] + 1
            db.execute("UPDATE audience_state SET revision=? WHERE id=1", (revision,))
            db.execute("INSERT INTO audience_audit(timestamp,actor_kind,action,revision) VALUES(?,?,?,?)", (now, actor_kind, action, revision))
            result = {"ok": True, "revision": revision}
            db.execute("INSERT INTO audience_requests VALUES(?,?,?,?)", (request_id, fingerprint, json.dumps(result), now))
            return result

    @staticmethod
    def _graphic(rule, name, platform):
        return {"rule_id": rule["id"], "title": rule["message"].replace("{name}", name)[:240],
                "subtitle": {"first_chat": "First chat this session", "featured_chat": "Featured participant", "follow": "New follower", "subscription": "Subscription"}[rule["event"]],
                "platform": platform, "animation": rule["animation"], "duration_ms": rule["duration_ms"]}

    def preview(self, rule, display_name):
        return {"ok": True, "simulation": True, "graphic": self._graphic(self.validate_rule(rule), _text(display_name, 80), "preview")}

    def accept(self, event: TrustedAudienceEvent):
        if not isinstance(event, TrustedAudienceEvent):
            raise ValueError("trusted_server_event_required")
        now = self.clock()
        key = hashlib.sha256(json.dumps([event.platform, event.channel_id, event.event_id]).encode()).hexdigest()
        identity = self._identity(event.platform, event.channel_id, event.subject_id)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db, now)
            state = db.execute("SELECT * FROM audience_state WHERE id=1").fetchone()
            if db.execute("SELECT 1 FROM audience_events WHERE key=?", (key,)).fetchone():
                return {"ok": True, "duplicate": True, "queued": 0}
            if event.occurred_at < max(now - self.MAX_EVENT_AGE, state["started_at"]) or event.occurred_at > now + 5:
                return {"ok": False, "reason": "audience_event_outside_session", "queued": 0}
            if db.execute("SELECT COUNT(*) FROM audience_events").fetchone()[0] >= self.MAX_EVENTS:
                return {"ok": False, "reason": "audience_event_capacity", "queued": 0}
            seen = db.execute("SELECT * FROM audience_participants WHERE identity=?", (identity,)).fetchone()
            if seen is None and db.execute("SELECT COUNT(*) FROM audience_participants").fetchone()[0] >= 2000:
                return {"ok": False, "reason": "audience_participant_capacity", "queued": 0}
            chats = (seen["chats"] if seen else 0) + int(event.kind == "chat")
            db.execute("INSERT INTO audience_participants VALUES(?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET label=excluded.label,chats=excluded.chats,last_seen=excluded.last_seen", (identity, state["run_id"], event.display_name, chats, now))
            kinds = {event.kind}
            if event.kind == "chat" and chats == 1:
                kinds.add("first_chat")
            if event.kind == "chat" and db.execute("SELECT 1 FROM audience_featured WHERE identity=?", (identity,)).fetchone():
                kinds.add("featured_chat")
            queued = 0
            if state["enabled"]:
                for row in db.execute("SELECT payload FROM audience_rules ORDER BY id").fetchall():
                    rule = json.loads(row["payload"])
                    if not rule["enabled"] or rule["event"] not in kinds or rule["platform"] not in {"any", event.platform}:
                        continue
                    cooldown_key = json.dumps([state["run_id"], rule["id"], identity])
                    last = db.execute("SELECT last_at FROM audience_cooldowns WHERE identity=?", (cooldown_key,)).fetchone()
                    if last and now - last["last_at"] < rule["cooldown_seconds"]:
                        continue
                    if db.execute("SELECT COUNT(*) FROM audience_queue").fetchone()[0] >= self.MAX_QUEUE:
                        continue
                    end = db.execute("SELECT MAX(ends_at) FROM audience_queue").fetchone()[0]
                    start = max(now, end or now)
                    if start > now + self.MAX_QUEUE_WAIT:
                        continue
                    graphic = self._graphic(rule, event.display_name, event.platform)
                    graphic["_participant_key"] = hashlib.sha256(identity.encode()).hexdigest()
                    db.execute("INSERT INTO audience_queue(payload,starts_at,ends_at) VALUES(?,?,?)", (json.dumps(graphic), start, start + rule["duration_ms"] / 1000))
                    db.execute("INSERT INTO audience_cooldowns VALUES(?,?) ON CONFLICT(identity) DO UPDATE SET last_at=excluded.last_at", (cooldown_key, now))
                    queued += 1
            db.execute("INSERT INTO audience_events VALUES(?,?,?,?)", (key, now, event.kind, "queued" if queued else "observed"))
            return {"ok": True, "duplicate": False, "queued": queued}

    def output(self):
        now = self.clock()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db, now)
            enabled = bool(db.execute("SELECT enabled FROM audience_state WHERE id=1").fetchone()[0])
            row = db.execute("SELECT * FROM audience_queue WHERE starts_at<=? AND ends_at>? ORDER BY id LIMIT 1", (now, now)).fetchone() if enabled else None
            graphic = json.loads(row["payload"]) if row else None
            if graphic:
                graphic.pop("_participant_key", None)
                graphic.update(id=row["id"], starts_at=row["starts_at"], ends_at=row["ends_at"], remaining_ms=max(0, round((row["ends_at"] - now) * 1000)))
            return {"ok": True, "enabled": enabled, "graphic": graphic}

    def status(self):
        now = self.clock()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._cleanup(db, now)
            state = dict(db.execute("SELECT * FROM audience_state WHERE id=1").fetchone())
            return {"ok": True, "revision": state["revision"], "enabled": bool(state["enabled"]), "session_started_at": state["started_at"],
                    "rules": [json.loads(r["payload"]) for r in db.execute("SELECT payload FROM audience_rules ORDER BY id")],
                    "featured": [dict(zip(("platform", "channel_id", "subject_id"), json.loads(r["identity"])), label=r["label"]) for r in db.execute("SELECT * FROM audience_featured ORDER BY label")],
                    # Provider account references belong only to the operator status.
                    # Graphics and audit records never receive these IDs.
                    "participants": [dict(zip(("platform", "channel_id", "subject_id"), json.loads(r["identity"])),
                        label=r["label"], observed_chats=r["chats"], featured=bool(r["featured"]))
                        for r in db.execute("SELECT p.identity,p.label,p.chats,(f.identity IS NOT NULL) AS featured FROM audience_participants p LEFT JOIN audience_featured f ON f.identity=p.identity WHERE p.chats>0 ORDER BY p.chats DESC,p.last_seen DESC LIMIT 10")],
                    "queued": db.execute("SELECT COUNT(*) FROM audience_queue").fetchone()[0],
                    "history": [dict(r, identity_verified=False) for r in db.execute("SELECT timestamp,actor_kind,action,revision FROM audience_audit ORDER BY id DESC LIMIT 10")],
                    "sources": [{"platform": platform, "state": "not_connected", "implemented": False, "authorized": False, "verified": False,
                                 "events": ["first_chat", "featured_chat", "subscription"] + (["follow"] if platform != "youtube" else [])} for platform in PLATFORMS]}
