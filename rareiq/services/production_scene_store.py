"""Atomic scene edits and device-attributed history; not individual authentication."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid


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

    def snapshot(self) -> dict[str, Any]:
        with closing(self._connect()) as db:
            return self._snapshot(db)

    def edit(self, *, action: str, target: str | None, scene: dict | None,
             expected_revision: int, request_id: str, actor_kind: str) -> dict[str, Any]:
        if action not in {"save", "delete"} or actor_kind not in {"local_operator", "paired_lan_operator"}:
            raise ValueError("invalid_scene_operation")
        if type(expected_revision) is not int or expected_revision < 0 or not isinstance(request_id, str) or not 1 <= len(request_id) <= 80 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in request_id):
            raise ValueError("invalid_scene_precondition")
        fingerprint = hashlib.sha256(json.dumps([action, target, scene, expected_revision, actor_kind], sort_keys=True, allow_nan=False).encode()).hexdigest()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT fingerprint,result FROM scene_requests WHERE request_id=?", (request_id,)).fetchone()
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
            db.execute("INSERT INTO scene_activity(timestamp,actor_kind,action,target,before_revision,after_revision,outcome,changes,request_id) VALUES (?,?,?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), actor_kind, f"scene.{action}", target, revision,
                        result["revision"], reason or "succeeded", json.dumps(changes, allow_nan=False), request_id))
            db.execute("INSERT INTO scene_requests VALUES (?,?,?)", (request_id, fingerprint, json.dumps(result, allow_nan=False)))
            return result

    def history(self, *, before_id: int | None = None, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 100 or (before_id is not None and before_id < 1):
            raise ValueError("invalid_history_page")
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM scene_activity WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                              (before_id, before_id, limit + 1)).fetchall()
        events = [dict(row) | {"changes": json.loads(row["changes"]), "identity_verified": False} for row in rows[:limit]]
        return {"ok": True, "events": events, "next_before_id": events[-1]["id"] if len(rows) > limit else None,
                "coverage": "scene_save_delete", "individual_identity_available": False}
