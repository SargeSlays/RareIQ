"""Immutable local production definitions with atomic retry receipts and audit."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid


class ProductionSourceError(ValueError):
    def __init__(self, reason, status=400):
        self.reason, self.status = reason, status
        super().__init__(reason)


class ProductionSourceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS production_sources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, definition TEXT NOT NULL, created_at REAL NOT NULL, actor_kind TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(actor_kind,request_id))")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _public(row, *, definition=False):
        result = {"id": row["kind"] + ":" + row["id"], "kind": row["kind"], "name": row["name"],
                  "url": "/api/production/sources/" + row["kind"] + "/" + row["id"]}
        if definition:
            result.update(json.loads(row["definition"]))
            result["source_id"] = result["id"]
        return result

    def create_text(self, *, name, text, position, request_id, actor_kind):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ProductionSourceError("invalid_source_name")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000 or len(text) > 1000 or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ProductionSourceError("invalid_source_text")
        if len(re.split(r"[\n\x85\u2028\u2029]", text)) > 8:
            raise ProductionSourceError("invalid_source_text_lines")
        if position not in {"lower-third", "center", "top"}:
            raise ProductionSourceError("invalid_source_position")
        return self._create("text", name.strip(), {"text": text, "position": position}, request_id, actor_kind)

    def _create(self, kind, name, definition, request_id, actor_kind):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request_id):
            raise ProductionSourceError("invalid_source_request_id")
        if actor_kind not in {"local_operator", "paired_lan_operator"}:
            raise ProductionSourceError("source_actor_required", 403)
        encoded = json.dumps(definition, sort_keys=True)
        fingerprint = hashlib.sha256(json.dumps([kind, name, encoded]).encode()).hexdigest()
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM production_sources WHERE actor_kind=? AND request_id=?", (actor_kind, request_id)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ProductionSourceError("source_request_conflict", 409)
                return {"ok": True, "created": True, "replayed": True, "source": self._public(previous, definition=True)}
            if db.execute("SELECT COUNT(*) FROM production_sources").fetchone()[0] >= 500:
                raise ProductionSourceError("source_library_full", 409)
            source_id = str(uuid.uuid4())
            db.execute("INSERT INTO production_sources VALUES (?,?,?,?,?,?,?,?)", (source_id, kind, name, encoded, time.time(), actor_kind, request_id, fingerprint))
            row = db.execute("SELECT * FROM production_sources WHERE id=?", (source_id,)).fetchone()
            return {"ok": True, "created": True, "replayed": False, "source": self._public(row, definition=True)}

    def get(self, kind, source_id):
        with self._lock, closing(self._connect()) as db:
            row = db.execute("SELECT * FROM production_sources WHERE kind=? AND id=?", (kind, source_id)).fetchone()
            return self._public(row, definition=True) if row else None

    def catalog(self, kind=None):
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM production_sources ORDER BY created_at DESC").fetchall()
            return [self._public(row) for row in rows if kind is None or row["kind"] == kind]
