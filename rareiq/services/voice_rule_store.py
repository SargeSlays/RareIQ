"""Bounded exact voice bindings, with atomic revision checks and local attribution."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

MAX_RULES = 24
ALLOWED_ACTIONS = frozenset({"program.take", "scene.take", "clip.save"})


def normalize_phrase(value: str) -> str:
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("invalid_voice_phrase")
    phrase = " ".join(value.lower().split())
    if not 3 <= len(phrase) <= 60 or re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+)*", phrase) is None:
        raise ValueError("invalid_voice_phrase")
    if phrase.startswith(("sarge ", "hey sarge ", "producer please ")) or phrase in {"sarge", "hey sarge", "producer please"}:
        raise ValueError("voice_phrase_includes_wake_words")
    if (re.fullmatch(r"(?:camera|cam) (?:one|two|three|four|[1-4])", phrase)
            or phrase == "clip that" or phrase.startswith("save the last ")):
        raise ValueError("voice_phrase_reserved")
    return phrase


class VoiceRuleStore:
    def __init__(self, path: Path, validate_action):
        self.path, self.validate_action = Path(path), validate_action

    def normalize(self, rules: list[dict]) -> list[dict]:
        if not isinstance(rules, list) or len(rules) > MAX_RULES:
            raise ValueError("too_many_voice_rules")
        normalized, phrases = [], set()
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {"phrase", "action_id", "params"}:
                raise ValueError("invalid_voice_rule")
            phrase = normalize_phrase(rule["phrase"])
            if phrase in phrases:
                raise ValueError("duplicate_voice_phrase")
            phrases.add(phrase)
            action = rule["action_id"]
            if not isinstance(action, str) or action not in ALLOWED_ACTIONS or not isinstance(rule["params"], dict):
                raise ValueError("voice_action_not_allowed")
            params = self.validate_action(action, deepcopy(rule["params"]))
            if len(json.dumps(params, allow_nan=False)) > 2048:
                raise ValueError("invalid_voice_rule")
            normalized.append({"phrase": phrase, "action_id": action, "params": params})
        return sorted(normalized, key=lambda item: item["phrase"])

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS voice_rules (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, rules TEXT NOT NULL);
                INSERT OR IGNORE INTO voice_rules VALUES (1,0,'[]');
                CREATE TABLE IF NOT EXISTS voice_rule_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    revision INTEGER NOT NULL, actor_kind TEXT NOT NULL, rule_count INTEGER NOT NULL);
                CREATE TRIGGER IF NOT EXISTS voice_rule_activity_no_update BEFORE UPDATE ON voice_rule_activity
                    BEGIN SELECT RAISE(ABORT, 'activity_is_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS voice_rule_activity_no_delete BEFORE DELETE ON voice_rule_activity
                    BEGIN SELECT RAISE(ABORT, 'activity_is_append_only'); END;
            """)
            return db
        except Exception:
            db.close()
            raise

    def snapshot(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT revision,rules FROM voice_rules WHERE id=1").fetchone()
        return {"ok": True, "revision": row["revision"], "rules": self.normalize(json.loads(row["rules"]))}

    def replace(self, rules, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid_voice_rules_revision")
        normalized = self.normalize(rules)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision,rules FROM voice_rules WHERE id=1").fetchone()
            revision = row["revision"]
            if json.loads(row["rules"]) == normalized:
                return {"ok": True, "revision": revision, "rules": normalized}
            if revision != expected_revision:
                return {"ok": False, "reason": "voice_rules_revision_conflict", "revision": revision}
            db.execute("UPDATE voice_rules SET revision=?,rules=? WHERE id=1", (revision + 1, json.dumps(normalized, allow_nan=False)))
            db.execute("INSERT INTO voice_rule_activity(timestamp,revision,actor_kind,rule_count) VALUES (?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), revision + 1, "local_operator", len(normalized)))
            return {"ok": True, "revision": revision + 1, "rules": normalized}

    def history(self):
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM voice_rule_activity ORDER BY id DESC LIMIT 50").fetchall()
        return {"ok": True, "events": [dict(row) | {"identity_verified": False} for row in rows]}
