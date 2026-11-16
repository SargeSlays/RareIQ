"""Atomic scenes, membership and history for one production instance."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from rareiq.web.shared_scene_access import VerifiedPrincipal


class ProductionSceneStore:
    SAFE_VALUES = frozenset({"program_slot", "preview_slot", "transition", "duration_ms",
                            "spotify_action", "soundboard_action", "screen_action",
                            "screen_mode", "screen_countdown_seconds", "screen_accent"})

    def __init__(self, path: Path, legacy_path: Path, defaults: list[dict]) -> None:
        self.path, self.legacy_path, self.defaults = Path(path), Path(legacy_path), defaults

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scene_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, scenes TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scene_requests (
                    request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS studio_members (
                    identity TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')));
                CREATE TABLE IF NOT EXISTS studio_membership_state (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO studio_membership_state VALUES (1,0);
                CREATE TABLE IF NOT EXISTS scene_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    actor_kind TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
                    before_revision INTEGER NOT NULL, after_revision INTEGER NOT NULL,
                    outcome TEXT NOT NULL, changes TEXT NOT NULL, request_id TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS scene_activity_no_update BEFORE UPDATE ON scene_activity
                    BEGIN SELECT RAISE(ABORT, 'activity_is_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS scene_activity_no_delete BEFORE DELETE ON scene_activity
                    BEGIN SELECT RAISE(ABORT, 'activity_is_append_only'); END;
            """)
            with db:
                db.execute("BEGIN IMMEDIATE")
                if "actor_identity" not in {row["name"] for row in db.execute("PRAGMA table_info(scene_activity)")}:
                    db.execute("ALTER TABLE scene_activity ADD COLUMN actor_identity TEXT")
                if not db.execute("SELECT 1 FROM scene_state WHERE id=1").fetchone():
                    scenes = json.loads(self.legacy_path.read_text(encoding="utf-8")) if self.legacy_path.exists() else self.defaults
                    if not isinstance(scenes, list) or len(scenes) > 20 or any(not isinstance(s, dict) or not s.get("id") for s in scenes):
                        raise ValueError("invalid_legacy_scenes")
                    if len({s["id"] for s in scenes}) != len(scenes):
                        raise ValueError("duplicate_legacy_scene_ids")
                    db.execute("INSERT INTO scene_state VALUES (1,0,?)", (json.dumps(scenes, allow_nan=False),))
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def _snapshot(db: sqlite3.Connection) -> dict[str, Any]:
        row = db.execute("SELECT revision,scenes FROM scene_state WHERE id=1").fetchone()
        return {"ok": True, "revision": row["revision"], "scenes": json.loads(row["scenes"])}

    @staticmethod
    def _identity(principal: VerifiedPrincipal) -> str:
        if not isinstance(principal, VerifiedPrincipal):
            raise PermissionError("verified_identity_required")
        return json.dumps([principal.provider, principal.app_id, principal.subject], separators=(",", ":"))

    def _require_member(self, db, principal, roles=("owner", "editor", "viewer")) -> str:
        identity = self._identity(principal)
        row = db.execute("SELECT role FROM studio_members WHERE identity=?", (identity,)).fetchone()
        if row is None or row["role"] not in roles:
            raise PermissionError("studio_permission_denied")
        return row["role"]

    def bootstrap_owner(self, principal: VerifiedPrincipal) -> None:
        """Trusted host setup only; never invoked by an HTTP request or first visitor."""
        identity = self._identity(principal)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT revision FROM studio_membership_state WHERE id=1").fetchone()
            if state["revision"] != 0:
                raise ValueError("studio_owner_already_initialized")
            db.execute("INSERT INTO studio_members VALUES (?, 'owner')", (identity,))
            self._membership_event(db, identity, identity, None, "owner", 0, "host_bootstrap")

    def membership(self, principal: VerifiedPrincipal) -> dict:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            self._require_member(db, principal, ("owner",))
            revision = db.execute("SELECT revision FROM studio_membership_state WHERE id=1").fetchone()["revision"]
            return {"revision": revision, "members": [dict(identity=json.loads(r["identity"]), role=r["role"])
                    for r in db.execute("SELECT identity,role FROM studio_members ORDER BY identity")]}

    def set_member(self, actor: VerifiedPrincipal, member: VerifiedPrincipal,
                   role: str | None, expected_revision: int) -> dict:
        """Host-side administration; account-mode HTTP deliberately exposes no grants."""
        if role not in {None, "owner", "editor", "viewer"} or type(expected_revision) is not int:
            raise ValueError("invalid_membership_change")
        identity, target = self._identity(actor), self._identity(member)
        if (actor.provider, actor.app_id) != (member.provider, member.app_id):
            raise ValueError("membership_app_mismatch")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            self._require_member(db, actor, ("owner",))
            revision = db.execute("SELECT revision FROM studio_membership_state WHERE id=1").fetchone()["revision"]
            if revision != expected_revision:
                raise ValueError("membership_revision_conflict")
            row = db.execute("SELECT role FROM studio_members WHERE identity=?", (target,)).fetchone()
            before = row["role"] if row else None
            if before == role:
                return {"ok": True, "revision": revision}
            if before == "owner" and role != "owner" and db.execute("SELECT COUNT(*) FROM studio_members WHERE role='owner'").fetchone()[0] == 1:
                raise ValueError("last_studio_owner")
            if role is None:
                db.execute("DELETE FROM studio_members WHERE identity=?", (target,))
            else:
                db.execute("INSERT INTO studio_members VALUES (?,?) ON CONFLICT(identity) DO UPDATE SET role=excluded.role", (target, role))
            self._membership_event(db, identity, target, before, role, revision, "verified_account")
            return {"ok": True, "revision": revision + 1}

    @staticmethod
    def _membership_event(db, identity, target, before, after, revision, actor_kind):
        db.execute("UPDATE studio_membership_state SET revision=? WHERE id=1", (revision + 1,))
        db.execute("INSERT INTO scene_activity(timestamp,actor_kind,action,target,before_revision,after_revision,outcome,changes,request_id,actor_identity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), actor_kind, "member.role", target, revision,
                    revision + 1, "succeeded", json.dumps({"role": {"before": before, "after": after}}), uuid.uuid4().hex, identity))

    def snapshot(self, principal: VerifiedPrincipal | None = None) -> dict[str, Any]:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            if principal is not None:
                self._require_member(db, principal)
            return self._snapshot(db)

    def edit(self, *, action: str, target: str | None, scene: dict | None,
             expected_revision: int, request_id: str, actor_kind: str,
             principal: VerifiedPrincipal | None = None) -> dict[str, Any]:
        identity = self._identity(principal) if principal is not None else None
        if identity:
            actor_kind = "verified_account"
        if action not in {"save", "delete"} or (actor_kind not in {"local_operator", "paired_lan_operator"} and not identity):
            raise ValueError("invalid_scene_operation")
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(request_id, str) or not 1 <= len(request_id) <= 80 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in request_id):
            raise ValueError("invalid_scene_precondition")
        fingerprint_parts = [action, target, scene, expected_revision, actor_kind]
        if identity:
            fingerprint_parts.append(identity)
        fingerprint = hashlib.sha256(json.dumps(fingerprint_parts, sort_keys=True, allow_nan=False).encode()).hexdigest()
        receipt_key = "verified:" + hashlib.sha256(json.dumps([identity, request_id]).encode()).hexdigest() if identity else request_id
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if principal is not None:
                # Authorization and receipt replay share the mutation transaction.
                self._require_member(db, principal, ("owner", "editor"))
            prior = db.execute("SELECT fingerprint,result FROM scene_requests WHERE request_id=?", (receipt_key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    return {"ok": False, "reason": "scene_request_conflict", "status": 409}
                return json.loads(prior["result"])
            state = self._snapshot(db)
            revision, scenes = state["revision"], state["scenes"]
            target = target or f"scene-{uuid.uuid4().hex[:10]}"
            before = next((item for item in scenes if item.get("id") == target), None)
            reason = None
            if expected_revision != revision:
                reason = "scene_revision_conflict"
            elif action == "delete" and before is None:
                reason = "scene_not_found"
            elif action == "save" and before is None and len(scenes) >= 20:
                reason = "scene_limit_reached"
            changes = {}
            if reason:
                result = {"ok": False, "reason": reason, "revision": revision, "status": 404 if reason == "scene_not_found" else 409}
            else:
                after = dict(scene, id=target) if action == "save" else None
                for key in sorted(set(before or {}) | set(after or {})):
                    old, new = (before or {}).get(key), (after or {}).get(key)
                    if old != new and key != "id":
                        changes[key] = {"before": old, "after": new} if key in self.SAFE_VALUES else {"changed": True}
                scenes = [after if item.get("id") == target else item for item in scenes] if before and after else [item for item in scenes if item.get("id") != target]
                if after and before is None:
                    scenes.append(after)
                db.execute("UPDATE scene_state SET revision=?,scenes=? WHERE id=1", (revision + 1, json.dumps(scenes, allow_nan=False)))
                # Retain an operation receipt, not an archive of every scene's free text.
                result = {"ok": True, "revision": revision + 1, "scene_id": target}
            db.execute("INSERT INTO scene_activity(timestamp,actor_kind,action,target,before_revision,after_revision,outcome,changes,request_id,actor_identity) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), actor_kind, f"scene.{action}", target, revision,
                        result["revision"], reason or "succeeded", json.dumps(changes, allow_nan=False), request_id, identity))
            db.execute("INSERT INTO scene_requests VALUES (?,?,?)", (receipt_key, fingerprint, json.dumps(result, allow_nan=False)))
            return result

    def history(self, *, before_id: int | None = None, limit: int = 50,
                principal: VerifiedPrincipal | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 100 or (before_id is not None and before_id < 1):
            raise ValueError("invalid_history_page")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            if principal is not None:
                self._require_member(db, principal)
            rows = db.execute("SELECT * FROM scene_activity WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                              (before_id, before_id, limit + 1)).fetchall()
        events = [dict(row) | {"changes": json.loads(row["changes"]),
                  "actor_identity": json.loads(row["actor_identity"]) if row["actor_identity"] else None,
                  "identity_verified": row["actor_kind"] == "verified_account"} for row in rows[:limit]]
        return {"ok": True, "events": events, "next_before_id": events[-1]["id"] if len(rows) > limit else None,
                "coverage": "scene_save_delete_and_membership" if principal else "scene_save_delete",
                "individual_identity_available": principal is not None}
