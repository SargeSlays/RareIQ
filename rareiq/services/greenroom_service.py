"""One private guest room: invitation/session capabilities and atomic decisions.

Producer methods are trusted host adapters, not public authorization checks. The web
boundary must authorize the producer and derive guest IDs from authenticate(), never
from a guest-supplied participant ID. Media flags are declarations, not frame evidence.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Callable
import uuid

from rareiq.web.shared_scene_access import VerifiedPrincipal


MEDIA_KEYS = ("camera", "microphone", "screen", "screen_audio")
EMPTY_MEDIA = dict.fromkeys(MEDIA_KEYS, False)


class GreenroomError(ValueError):
    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason, self.status = reason, status


class GreenroomService:
    def __init__(self, path: Path, *, max_guests: int = 6, max_invites: int = 16,
                 clock: Callable[[], float] = time.time, reset_runtime: bool = True) -> None:
        if type(max_guests) is not int or not 1 <= max_guests <= 12 or type(max_invites) is not int or not 1 <= max_invites <= 64:
            raise ValueError("invalid_greenroom_capacity")
        if type(reset_runtime) is not bool:
            raise ValueError("invalid_runtime_reset")
        self.path, self.max_guests, self.max_invites, self.clock = Path(path), max_guests, max_invites, clock
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS greenroom_room (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), id TEXT NOT NULL,
                    revision INTEGER NOT NULL, active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS greenroom_invites (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0, participant_id TEXT);
                CREATE TABLE IF NOT EXISTS greenroom_participants (
                    id TEXT PRIMARY KEY, room_id TEXT NOT NULL, invite_id TEXT NOT NULL UNIQUE,
                    session_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('waiting','admitted','removed')),
                    connected INTEGER NOT NULL, media TEXT NOT NULL,
                    joined_at REAL NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS greenroom_requests (
                    room_id TEXT NOT NULL, actor_key TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY(room_id,actor_key,request_id));
                CREATE TABLE IF NOT EXISTS greenroom_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL,
                    timestamp REAL NOT NULL, actor_kind TEXT NOT NULL, actor_id TEXT,
                    identity_verified INTEGER NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
                    outcome TEXT NOT NULL, before_revision INTEGER NOT NULL,
                    after_revision INTEGER NOT NULL, details TEXT NOT NULL, request_id TEXT);
                CREATE TRIGGER IF NOT EXISTS greenroom_activity_no_update
                    BEFORE UPDATE ON greenroom_activity BEGIN SELECT RAISE(ABORT,'activity_is_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS greenroom_activity_no_delete
                    BEFORE DELETE ON greenroom_activity BEGIN SELECT RAISE(ABORT,'activity_is_append_only'); END;
            """)
            db.execute("BEGIN IMMEDIATE")
            if "request_id" not in {row["name"] for row in db.execute("PRAGMA table_info(greenroom_activity)")}:
                db.execute("ALTER TABLE greenroom_activity ADD COLUMN request_id TEXT")
            db.execute("INSERT OR IGNORE INTO greenroom_room VALUES (1,?,0,1)", (uuid.uuid4().hex,))
        if reset_runtime:
            self.reset_runtime()

    def reset_runtime(self) -> None:
        """Explicit process startup only; importing the app must not disconnect guests."""
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM greenroom_participants WHERE connected=1 OR media!=?", (self._json(EMPTY_MEDIA),)).fetchall()
            if rows:
                db.execute("UPDATE greenroom_participants SET connected=0,media=?", (self._json(EMPTY_MEDIA),))
                self._event(db, "server", None, False, "room.restarted", self._room(db)["id"], {"cleared_connections": len(rows)})

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _room(db):
        return db.execute("SELECT * FROM greenroom_room WHERE singleton=1").fetchone()

    @staticmethod
    def _token_hash(token: str, reason: str) -> str:
        if not isinstance(token, str) or re.fullmatch(r"[a-f0-9]{64}", token) is None:
            raise GreenroomError(reason, 401)
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @staticmethod
    def _text(value: str, maximum: int, *, empty: bool = False) -> str:
        if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise GreenroomError("invalid_guest_text")
        value = value.strip()
        if not value and not empty:
            raise GreenroomError("guest_name_required")
        return value

    @staticmethod
    def _actor(actor_kind, principal):
        if principal is not None:
            if not isinstance(principal, VerifiedPrincipal):
                raise GreenroomError("invalid_producer_identity", 403)
            identity = json.dumps([principal.provider, principal.app_id, principal.subject], separators=(",", ":"))
            return "verified_account", identity, True
        if actor_kind not in {"local_operator", "paired_lan_operator"}:
            raise GreenroomError("invalid_producer_identity", 403)
        return actor_kind, None, False

    def _event(self, db, actor_kind, actor_id, verified, action, target, details,
               *, outcome="succeeded", changed=True, request_id=None):
        room = self._room(db)
        revision = room["revision"] + int(changed)
        db.execute("UPDATE greenroom_room SET revision=? WHERE singleton=1", (revision,))
        db.execute("INSERT INTO greenroom_activity(room_id,timestamp,actor_kind,actor_id,identity_verified,action,target,outcome,before_revision,after_revision,details,request_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (room["id"], self.clock(), actor_kind, actor_id, int(verified), action, target, outcome,
                    room["revision"], revision, self._json(details), request_id))
        return revision

    def _participant(self, row, *, room_active=True):
        expired = row["expires_at"] <= self.clock()
        available = room_active and not expired and row["state"] != "removed"
        media = json.loads(row["media"]) if available else dict(EMPTY_MEDIA)
        connected = bool(row["connected"]) and available
        return {"id": row["id"], "name": row["name"],
                "state": row["state"] if available else "removed", "expired": expired,
                "connected": connected, "media": media, "joined_at": row["joined_at"],
                "expires_at": row["expires_at"], "identity_verified": False,
                "sources": {kind: f"guest:{row['id']}:{kind}" for kind in ("camera", "screen", "audio")}}

    def _participant_row(self, db, participant_id):
        room = self._room(db)
        row = db.execute("SELECT * FROM greenroom_participants WHERE id=? AND room_id=?", (participant_id, room["id"])).fetchone()
        if not room["active"] or not row or row["state"] == "removed" or row["expires_at"] <= self.clock():
            raise GreenroomError("guest_unavailable", 404)
        return row

    def snapshot(self):
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN")
            room, now = self._room(db), self.clock()
            participants = [self._participant(row, room_active=bool(room["active"])) for row in db.execute(
                "SELECT * FROM greenroom_participants WHERE room_id=? ORDER BY CASE WHEN state='removed' OR expires_at<=? THEN 1 ELSE 0 END,joined_at DESC,id LIMIT ?", (room["id"], now, self.max_guests + 24))]
            invites = []
            for row in db.execute("SELECT * FROM greenroom_invites WHERE room_id=? ORDER BY CASE WHEN revoked=0 AND participant_id IS NULL AND expires_at>? THEN 0 ELSE 1 END,created_at DESC,id LIMIT ?", (room["id"], now, self.max_invites + 16)):
                status = "revoked" if row["revoked"] or not room["active"] else "used" if row["participant_id"] else "expired" if row["expires_at"] <= now else "ready"
                invites.append({"id": row["id"], "label": row["label"], "expires_at": row["expires_at"],
                                "status": status, "participant_id": row["participant_id"]})
            return {"ok": True, "room_id": room["id"], "active": bool(room["active"]),
                    "revision": room["revision"], "max_guests": self.max_guests,
                    "participants": participants, "invites": invites}

    def _producer(self, action, target, payload, mutate, actor_kind, principal, expected_revision, request_id):
        actor = self._actor(actor_kind, principal)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise GreenroomError("invalid_room_revision")
        if request_id is not None and (not isinstance(request_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id) is None):
            raise GreenroomError("invalid_room_request_id")
        fingerprint = hashlib.sha256(self._json([action, target, payload, expected_revision]).encode()).hexdigest()
        actor_key = self._json(actor[:2])
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            room = self._room(db)
            prior = db.execute("SELECT fingerprint,result FROM greenroom_requests WHERE room_id=? AND actor_key=? AND request_id=?",
                               (room["id"], actor_key, request_id)).fetchone() if request_id else None
            if prior and prior["fingerprint"] == fingerprint:
                return json.loads(prior["result"])
            reason = "room_request_conflict" if prior else "room_revision_conflict" if expected_revision is not None and room["revision"] != expected_revision else None
            if reason:
                self._event(db, *actor, action, target, {}, outcome=reason, changed=False, request_id=request_id)
                db.commit()  # Preserve rejected producer intent; no state mutation has run.
                raise GreenroomError(reason, 409)
            result, details, changed, actual_target = mutate(db, room)
            revision = self._event(db, *actor, action, actual_target, details, request_id=request_id) if changed else room["revision"]
            if "participant" in result:
                # Receipts identify the decision; read snapshot() for current names/media.
                result["participant"] = {key: result["participant"][key] for key in ("id", "state")}
            response = {"ok": True, "revision": revision, "room_id": self._room(db)["id"], **result}
            if request_id:
                receipt = dict(response)
                if "token" in receipt:
                    receipt.update(token=None, token_available=False)
                db.execute("INSERT INTO greenroom_requests VALUES (?,?,?,?,?)",
                           (self._room(db)["id"], actor_key, request_id, fingerprint, self._json(receipt)))
            return response

    def create_invite(self, label="", ttl_minutes=60, actor_kind="local_operator", *,
                      principal=None, expected_revision=None, request_id=None):
        label = self._text(label, 80, empty=True)
        if type(ttl_minutes) is not int or not 1 <= ttl_minutes <= 1440:
            raise GreenroomError("invalid_invitation_expiry")

        def mutate(db, room):
            if not room["active"]:
                raise GreenroomError("room_closed", 409)
            now = self.clock()
            count = db.execute("SELECT COUNT(*) FROM greenroom_invites WHERE room_id=? AND revoked=0 AND participant_id IS NULL AND expires_at>?", (room["id"], now)).fetchone()[0]
            if count >= self.max_invites:
                raise GreenroomError("invitation_capacity_reached", 409)
            token, invite_id, expires = secrets.token_hex(32), uuid.uuid4().hex, now + ttl_minutes * 60
            db.execute("INSERT INTO greenroom_invites(id,room_id,token_hash,label,created_at,expires_at) VALUES (?,?,?,?,?,?)",
                       (invite_id, room["id"], self._token_hash(token, "invalid_invitation"), label, now, expires))
            return {"invite_id": invite_id, "token": token, "token_available": True, "expires_at": expires}, {"ttl_minutes": ttl_minutes}, True, invite_id

        return self._producer("invite.created", "", {"label": label, "ttl_minutes": ttl_minutes}, mutate,
                              actor_kind, principal, expected_revision, request_id)

    def join(self, invite_token, name, session_token):
        invite_hash = self._token_hash(invite_token, "invalid_invitation")
        session_hash = self._token_hash(session_token, "invalid_guest_session")
        name = self._text(name, 60)
        if session_hash == invite_hash:
            raise GreenroomError("separate_guest_session_required")
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            room, now = self._room(db), self.clock()
            invite = db.execute("SELECT * FROM greenroom_invites WHERE token_hash=? AND room_id=?", (invite_hash, room["id"])).fetchone()
            if not room["active"] or not invite or invite["revoked"]:
                raise GreenroomError("invalid_invitation", 401)
            if invite["participant_id"]:
                row = db.execute("SELECT * FROM greenroom_participants WHERE id=?", (invite["participant_id"],)).fetchone()
                if row and row["session_hash"] == session_hash and row["name"] == name and row["state"] != "removed" and row["expires_at"] > now:
                    return self._participant(row)
                raise GreenroomError("invitation_already_used", 409)
            if invite["expires_at"] <= now:
                raise GreenroomError("invitation_expired", 410)
            if db.execute("SELECT 1 FROM greenroom_participants WHERE session_hash=?", (session_hash,)).fetchone():
                raise GreenroomError("guest_session_conflict", 409)
            count = db.execute("SELECT COUNT(*) FROM greenroom_participants WHERE room_id=? AND state!='removed' AND expires_at>?", (room["id"], now)).fetchone()[0]
            if count >= self.max_guests:
                raise GreenroomError("guest_capacity_reached", 409)
            participant_id = uuid.uuid4().hex
            db.execute("INSERT INTO greenroom_participants VALUES (?,?,?,?,?,'waiting',0,?,?,?)",
                       (participant_id, room["id"], invite["id"], session_hash, name, self._json(EMPTY_MEDIA), now, now + 12 * 3600))
            db.execute("UPDATE greenroom_invites SET participant_id=? WHERE id=?", (participant_id, invite["id"]))
            self._event(db, "guest_session", participant_id, False, "guest.joined", participant_id, {"state": "waiting"})
            return self._participant(db.execute("SELECT * FROM greenroom_participants WHERE id=?", (participant_id,)).fetchone())

    def authenticate(self, session_token):
        digest = self._token_hash(session_token, "invalid_guest_session")
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN")
            room = self._room(db)
            row = db.execute("SELECT p.* FROM greenroom_participants p JOIN greenroom_invites i ON i.id=p.invite_id WHERE p.session_hash=? AND p.room_id=? AND i.revoked=0", (digest, room["id"])).fetchone()
            if not room["active"] or not row or row["state"] == "removed" or row["expires_at"] <= self.clock():
                raise GreenroomError("invalid_guest_session", 401)
            return self._participant(row)

    def _guest_state(self, participant_id, *, connected=None, media=None):
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = self._participant_row(db, participant_id)
            old_media = json.loads(row["media"])
            next_connected = bool(row["connected"]) if connected is None else connected
            next_media = old_media if media is None else media
            if not next_connected:
                next_media = dict(EMPTY_MEDIA)
            if next_connected != bool(row["connected"]) or next_media != old_media:
                db.execute("UPDATE greenroom_participants SET connected=?,media=? WHERE id=?", (int(next_connected), self._json(next_media), participant_id))
                self._event(db, "server" if connected is not None else "guest_session", participant_id, False,
                            "guest.connection" if connected is not None else "guest.media", participant_id,
                            {"connected": next_connected} if connected is not None else {"media": next_media})
            return self._participant(db.execute("SELECT * FROM greenroom_participants WHERE id=?", (participant_id,)).fetchone())

    def set_connected(self, participant_id, connected):
        if type(connected) is not bool:
            raise GreenroomError("invalid_guest_connection")
        return self._guest_state(participant_id, connected=connected)

    def update_media(self, participant_id, media):
        if not isinstance(media, dict) or set(media) != set(MEDIA_KEYS) or any(type(v) is not bool for v in media.values()) or (media["screen_audio"] and not media["screen"]):
            raise GreenroomError("invalid_guest_media")
        return self._guest_state(participant_id, media=dict(media))

    def leave(self, participant_id):
        """Called only for the participant derived from an authenticated guest session."""
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            room = self._room(db)
            row = db.execute("SELECT * FROM greenroom_participants WHERE id=? AND room_id=?", (participant_id, room["id"])).fetchone()
            if not row:
                raise GreenroomError("guest_unavailable", 404)
            if row["state"] != "removed":
                db.execute("UPDATE greenroom_participants SET state='removed',connected=0,media=? WHERE id=?", (self._json(EMPTY_MEDIA), participant_id))
                db.execute("UPDATE greenroom_invites SET revoked=1 WHERE id=?", (row["invite_id"],))
                self._event(db, "guest_session", participant_id, False, "guest.left", participant_id, {"state": "removed"})
            return {"ok": True, "participant_id": participant_id, "revision": self._room(db)["revision"]}

    def moderate(self, participant_id, action, actor_kind="local_operator", *, principal=None, expected_revision=None, request_id=None):
        if action not in {"admit", "remove"}:
            raise GreenroomError("invalid_guest_action")

        def mutate(db, room):
            row = self._participant_row(db, participant_id)
            state = "admitted" if action == "admit" else "removed"
            if state == row["state"]:
                return {"participant": self._participant(row)}, {}, False, participant_id
            db.execute("UPDATE greenroom_participants SET state=? WHERE id=?", (state, participant_id))
            if action == "remove":
                db.execute("UPDATE greenroom_participants SET connected=0,media=? WHERE id=?", (self._json(EMPTY_MEDIA), participant_id))
                db.execute("UPDATE greenroom_invites SET revoked=1 WHERE id=?", (row["invite_id"],))
            updated = db.execute("SELECT * FROM greenroom_participants WHERE id=?", (participant_id,)).fetchone()
            return {"participant": self._participant(updated)}, {"before": row["state"], "after": state}, True, participant_id

        return self._producer("guest." + action, participant_id, {}, mutate, actor_kind, principal, expected_revision, request_id)

    def revoke_invite(self, invite_id, actor_kind="local_operator", *, principal=None, expected_revision=None, request_id=None):
        def mutate(db, room):
            row = db.execute("SELECT * FROM greenroom_invites WHERE id=? AND room_id=?", (invite_id, room["id"])).fetchone()
            if not row:
                raise GreenroomError("invitation_not_found", 404)
            if not row["revoked"]:
                db.execute("UPDATE greenroom_invites SET revoked=1 WHERE id=?", (invite_id,))
                if row["participant_id"]:
                    db.execute("UPDATE greenroom_participants SET state='removed',connected=0,media=? WHERE id=?", (self._json(EMPTY_MEDIA), row["participant_id"]))
            return {"invite_id": invite_id, "removed_participant_id": row["participant_id"]}, {}, not bool(row["revoked"]), invite_id

        return self._producer("invite.revoked", invite_id, {}, mutate, actor_kind, principal, expected_revision, request_id)

    def close_room(self, actor_kind="local_operator", *, principal=None, expected_revision=None, request_id=None):
        def mutate(db, room):
            db.execute("UPDATE greenroom_room SET active=0 WHERE singleton=1")
            db.execute("UPDATE greenroom_invites SET revoked=1 WHERE room_id=?", (room["id"],))
            db.execute("UPDATE greenroom_participants SET state='removed',connected=0,media=? WHERE room_id=?", (self._json(EMPTY_MEDIA), room["id"]))
            return {"active": False}, {}, bool(room["active"]), room["id"]

        return self._producer("room.closed", "", {}, mutate, actor_kind, principal, expected_revision, request_id)

    def open_room(self, actor_kind="local_operator", *, principal=None, expected_revision=None, request_id=None):
        def mutate(db, room):
            room_id = room["id"] if room["active"] else uuid.uuid4().hex
            db.execute("UPDATE greenroom_room SET active=1,id=? WHERE singleton=1", (room_id,))
            return {"active": True}, {}, not bool(room["active"]), room_id

        return self._producer("room.opened", "", {}, mutate, actor_kind, principal, expected_revision, request_id)

    def source_available(self, source_id):
        if not isinstance(source_id, str):
            return False
        match = re.fullmatch(r"guest:([a-f0-9]{32}):(camera|screen|audio)", source_id)
        if not match:
            return False
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN")
            try:
                row = self._participant_row(db, match[1])
            except GreenroomError:
                return False
            media_kind = "microphone" if match[2] == "audio" else match[2]
            return row["state"] == "admitted" and bool(row["connected"]) and json.loads(row["media"])[media_kind] is True

    def record_production_event(self, action, target, outcome, actor_kind="local_operator", *,
                                principal=None, request_id=None, details=None):
        if action not in {"program.preview", "program.take", "program.rendered", "host.microphone"}:
            raise GreenroomError("invalid_production_event")
        if outcome not in {"requested", "succeeded", "failed", "rejected", "confirmed"}:
            raise GreenroomError("invalid_production_outcome")
        if not isinstance(target, str) or re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", target) is None:
            raise GreenroomError("invalid_production_target")
        if details is None:
            details = {}
        allowed_ids = {"source_id", "previous_source_id", "participant_id", "renderer_id"}
        allowed_numbers = {"generation", "duration_ms"}
        allowed_bools = {"muted", "connected"}
        if not isinstance(details, dict) or not set(details) <= allowed_ids | allowed_numbers | allowed_bools | {"source_ids"}:
            raise GreenroomError("invalid_production_details")
        for key, value in details.items():
            valid = (key == "source_ids" and isinstance(value, list) and len(value) <= 6 and all(isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", s) for s in value)
                     or key in allowed_ids and isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", value) is not None
                     or key in allowed_numbers and type(value) is int and 0 <= value <= 2**53 - 1
                     or key in allowed_bools and type(value) is bool)
            if not valid:
                raise GreenroomError("invalid_production_details")
        if request_id is not None and (not isinstance(request_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id) is None):
            raise GreenroomError("invalid_room_request_id")
        origin_kinds = {"producer_control", "host_voice", "host_gesture"}
        if actor_kind == "program_renderer" and action == "program.rendered" and principal is None:
            actor = ("program_renderer", None, False)
        elif actor_kind in origin_kinds:
            validated = self._actor("local_operator", principal)
            actor = (actor_kind, validated[1], validated[2])
        else:
            actor = self._actor(actor_kind, principal)
        fingerprint = hashlib.sha256(self._json([action, target, outcome, details]).encode()).hexdigest()
        actor_key = "production:" + self._json(actor[:2])
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            room = self._room(db)
            previous = db.execute("SELECT fingerprint,result FROM greenroom_requests WHERE room_id=? AND actor_key=? AND request_id=?", (room["id"], actor_key, request_id)).fetchone() if request_id else None
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise GreenroomError("room_request_conflict", 409)
                return json.loads(previous["result"])
            self._event(db, *actor, action, target, details, outcome=outcome, changed=False, request_id=request_id)
            result = {"ok": True, "revision": room["revision"], "outcome": outcome}
            if request_id:
                db.execute("INSERT INTO greenroom_requests VALUES (?,?,?,?,?)", (room["id"], actor_key, request_id, fingerprint, self._json(result)))
            return result

    def history(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise GreenroomError("invalid_history_page")
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM greenroom_activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return {"ok": True, "events": [dict(row) | {"identity_verified": bool(row["identity_verified"]),
                    "details": json.loads(row["details"])} for row in rows]}
