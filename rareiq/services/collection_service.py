from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class CollectionService:
    """Durable, exact-version inventory built from verified session pulls."""

    SCHEMA_VERSION = 5
    MAX_ACTIVITY = 10000
    MAX_CORRECTIONS = 5000
    MAX_ARCHIVED_GOALS = 1000

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path
        self._lock = threading.RLock()
        self._cards: dict[str, dict[str, Any]] = {}
        self._events: dict[str, str] = {}
        self._corrections: list[dict[str, Any]] = []
        self._activity: list[dict[str, Any]] = []
        self._goals: list[dict[str, Any]] = []
        self._load()

    @staticmethod
    def _text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def version_key(cls, card: dict[str, Any]) -> str:
        set_identity = cls._text(
            card.get("set_code") or card.get("set_id") or card.get("set_name")
        ).casefold()
        number = cls._text(
            card.get("collector_number") or card.get("printed_code")
        ).casefold()
        language = cls._text(card.get("language") or "unknown").casefold()
        name = cls._text(
            card.get("english_name") or card.get("card_name") or card.get("printed_name")
        ).casefold()
        return "|".join((set_identity, number, language, name))

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            cards = payload.get("cards") or {}
            events = payload.get("events") or {}
            corrections = payload.get("corrections") or []
            activity = payload.get("activity") or []
            goals = payload.get("goals") or []
            schema_version = int(payload.get("schema_version") or 1)
            if isinstance(cards, dict) and isinstance(events, dict):
                self._cards = cards
                self._events = events
                self._corrections = corrections if isinstance(corrections, list) else []
                self._activity = activity if isinstance(activity, list) else []
                self._goals = goals if isinstance(goals, list) else []
                self._migrate_loaded_state(schema_version)
                if not self._activity and self._cards:
                    quantity = sum(int(card.get("quantity") or 0) for card in self._cards.values())
                    self._activity.append({
                        "id": "legacy-baseline",
                        "type": "baseline",
                        "quantity_delta": quantity,
                        "value_delta": None,
                        "created_at": min(float(card.get("first_seen_at") or time.time()) for card in self._cards.values()),
                        "label": "Existing collection baseline",
                    })
        except (OSError, ValueError, TypeError):
            self._cards = {}
            self._events = {}
            self._corrections = []
            self._activity = []
            self._goals = []

    def _migrate_loaded_state(self, schema_version: int) -> None:
        """Normalize every supported legacy schema without inventing inventory."""
        for key, card in self._cards.items():
            card.setdefault("version_key", key)
            card["quantity"] = max(0, int(card.get("quantity") or 0))
            card.setdefault("event_ids", [])
            card.setdefault("currency", "USD")
            card.setdefault("disposition", {"trade": 0, "sell": 0})
            self._clamp_disposition(card)
        if schema_version < 3 and not self._activity and self._cards:
            quantity = sum(int(card.get("quantity") or 0) for card in self._cards.values())
            self._activity.append({
                "id": "legacy-baseline", "type": "baseline",
                "quantity_delta": quantity, "value_delta": None,
                "created_at": min(float(card.get("first_seen_at") or time.time()) for card in self._cards.values()),
                "label": "Existing collection baseline",
            })

    def _bound_history(self) -> None:
        self._activity = self._activity[-self.MAX_ACTIVITY:]
        self._corrections = self._corrections[-self.MAX_CORRECTIONS:]
        active_goals = [item for item in self._goals if not item.get("archived_at")]
        archived_goals = [item for item in self._goals if item.get("archived_at")]
        self._goals = active_goals + archived_goals[-self.MAX_ARCHIVED_GOALS:]

    def _persist(self) -> None:
        if not self.state_path:
            return
        self._bound_history()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(
            json.dumps(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "cards": self._cards,
                    "events": self._events,
                    "corrections": self._corrections,
                    "activity": self._activity,
                    "goals": self._goals,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temp.replace(self.state_path)

    def backup(self) -> dict[str, Any]:
        with self._lock:
            return {
                "format": "rareiq_collection_backup",
                "schema_version": self.SCHEMA_VERSION,
                "exported_at": time.time(),
                "cards": {key: dict(value) for key, value in self._cards.items()},
                "events": dict(self._events),
                "corrections": [dict(item) for item in self._corrections],
                "activity": [dict(item) for item in self._activity],
                "goals": [dict(item) for item in self._goals],
            }

    @staticmethod
    def _validate_backup(payload: dict[str, Any]) -> str | None:
        if not isinstance(payload, dict) or payload.get("format") != "rareiq_collection_backup":
            return "unsupported_backup_format"
        if not isinstance(payload.get("cards"), dict) or not isinstance(payload.get("events"), dict):
            return "invalid_backup_structure"
        for field in ("corrections", "activity", "goals"):
            if not isinstance(payload.get(field, []), list):
                return "invalid_backup_structure"
        return None

    def preview_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_backup(payload)
        if error:
            return {"valid": False, "reason": error}
        incoming = payload["cards"]
        with self._lock:
            local_keys = set(self._cards)
            incoming_keys = set(incoming)
            conflicts = []
            unchanged = 0
            for key in sorted(local_keys & incoming_keys):
                local_quantity = int(self._cards[key].get("quantity") or 0)
                incoming_quantity = int(incoming[key].get("quantity") or 0)
                if local_quantity != incoming_quantity:
                    conflicts.append({
                        "version_key": key,
                        "card_name": incoming[key].get("english_name") or incoming[key].get("card_name"),
                        "local_quantity": local_quantity,
                        "incoming_quantity": incoming_quantity,
                        "resolved_quantity": max(local_quantity, incoming_quantity),
                        "strategy": "keep_higher_quantity",
                    })
                else:
                    unchanged += 1
            return {
                "valid": True,
                "new_versions": len(incoming_keys - local_keys),
                "conflicts": conflicts,
                "conflict_count": len(conflicts),
                "unchanged_versions": unchanged,
                "incoming_events": len(payload["events"]),
                "new_events": len(set(payload["events"]) - set(self._events)),
                "strategy": "merge_by_stable_id_keep_higher_quantity",
            }

    def merge_backup(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.preview_import(payload)
        if not preview.get("valid"):
            return {"merged": False, **preview}
        with self._lock:
            for key, incoming in payload["cards"].items():
                incoming = dict(incoming)
                local = self._cards.get(key)
                if local is None:
                    self._cards[key] = incoming
                else:
                    local_quantity = int(local.get("quantity") or 0)
                    incoming_quantity = int(incoming.get("quantity") or 0)
                    if incoming_quantity > local_quantity:
                        preserved = dict(local)
                        preserved.update(incoming)
                        self._cards[key] = preserved
                    local_disposition = (self._cards[key].get("disposition") or {})
                    incoming_disposition = incoming.get("disposition") or {}
                    self._cards[key]["disposition"] = {
                        "trade": max(int(local_disposition.get("trade") or 0), int(incoming_disposition.get("trade") or 0)),
                        "sell": max(int(local_disposition.get("sell") or 0), int(incoming_disposition.get("sell") or 0)),
                    }
                    self._clamp_disposition(self._cards[key])
            self._events.update({str(key): str(value) for key, value in payload["events"].items() if key not in self._events})
            for field, target in (("corrections", self._corrections), ("activity", self._activity), ("goals", self._goals)):
                known = {str(item.get("id")) for item in target if item.get("id")}
                target.extend(dict(item) for item in payload.get(field, []) if item.get("id") and str(item["id"]) not in known)
            self._persist()
        return {"merged": True, **preview, "collection": self.snapshot()}

    def record(self, card: dict[str, Any], event_id: str) -> dict[str, Any]:
        event_id = self._text(event_id)
        if not event_id:
            raise ValueError("A collection event ID is required.")
        if card.get("provisional") or card.get("unverified_test_add"):
            return {"recorded": False, "reason": "verified_card_required"}

        key = self.version_key(card)
        now = time.time()
        with self._lock:
            if event_id in self._events:
                return {
                    "recorded": False,
                    "reason": "duplicate_event",
                    "card": dict(self._cards.get(self._events[event_id]) or {}),
                }
            entry = self._cards.get(key)
            if entry is None:
                entry = {
                    "version_key": key,
                    "card_name": card.get("card_name"),
                    "printed_name": card.get("printed_name"),
                    "english_name": card.get("english_name"),
                    "set_name": card.get("set_name"),
                    "set_code": card.get("set_code") or card.get("set_id"),
                    "collector_number": card.get("collector_number"),
                    "language": card.get("language"),
                    "rarity": card.get("rarity"),
                    "reference_image_url": card.get("reference_image_url"),
                    "market_price": card.get("market_price") or card.get("raw_market") or card.get("raw_value"),
                    "currency": card.get("currency") or "USD",
                    "pricing_source": card.get("pricing_source") or card.get("price_source"),
                    "price_updated_at": card.get("price_updated_at"),
                    "quantity": 0,
                    "disposition": {"trade": 0, "sell": 0},
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "event_ids": [],
                }
                self._cards[key] = entry
            entry["quantity"] = int(entry.get("quantity") or 0) + 1
            entry.setdefault("disposition", {"trade": 0, "sell": 0})
            entry["last_seen_at"] = now
            entry.setdefault("event_ids", []).append(event_id)
            self._events[event_id] = key
            unit_price = self._verified_unit_price(entry)
            self._activity.append({
                "id": event_id,
                "type": "acquired",
                "version_key": key,
                "card_name": entry.get("english_name") or entry.get("card_name"),
                "set_name": entry.get("set_name") or entry.get("set_code"),
                "collector_number": entry.get("collector_number"),
                "quantity_delta": 1,
                "value_delta": unit_price,
                "created_at": now,
                "label": "Verified card added",
            })
            self._persist()
            return {"recorded": True, "card": dict(entry)}

    def remove_event(self, event_id: str) -> dict[str, Any]:
        with self._lock:
            key = self._events.pop(self._text(event_id), None)
            if key is None:
                return {"removed": False, "reason": "event_not_found"}
            entry = self._cards.get(key)
            if entry is not None:
                unit_price = self._verified_unit_price(entry)
                entry["event_ids"] = [
                    item for item in entry.get("event_ids", []) if item != event_id
                ]
                entry["quantity"] = max(0, int(entry.get("quantity") or 0) - 1)
                self._clamp_disposition(entry)
                if entry["quantity"] == 0:
                    self._cards.pop(key, None)
                self._activity.append({
                    "id": str(uuid.uuid4()), "type": "scan_undo", "version_key": key,
                    "card_name": entry.get("english_name") or entry.get("card_name"),
                    "set_name": entry.get("set_name") or entry.get("set_code"),
                    "collector_number": entry.get("collector_number"), "quantity_delta": -1,
                    "value_delta": -unit_price if unit_price is not None else None,
                    "created_at": time.time(), "label": "Session scan undone",
                })
            self._persist()
            return {"removed": True, "version_key": key}

    def adjust_quantity(
        self,
        version_key: str,
        delta: int,
        reason: str = "operator_correction",
    ) -> dict[str, Any]:
        delta = int(delta)
        reason = self._text(reason) or "operator_correction"
        if delta == 0:
            return {"adjusted": False, "reason": "zero_delta"}
        with self._lock:
            entry = self._cards.get(self._text(version_key))
            if entry is None:
                return {"adjusted": False, "reason": "card_not_found"}
            before = int(entry.get("quantity") or 0)
            after = before + delta
            if after < 0:
                return {"adjusted": False, "reason": "quantity_below_zero"}
            correction = {
                "id": str(uuid.uuid4()),
                "version_key": version_key,
                "delta": delta,
                "before": before,
                "after": after,
                "reason": reason,
                "created_at": time.time(),
                "undone_at": None,
            }
            entry["quantity"] = after
            self._clamp_disposition(entry)
            entry["last_corrected_at"] = correction["created_at"]
            self._corrections.append(correction)
            unit_price = self._verified_unit_price(entry)
            self._activity.append({
                "id": correction["id"], "type": "correction", "version_key": version_key,
                "card_name": entry.get("english_name") or entry.get("card_name"),
                "set_name": entry.get("set_name") or entry.get("set_code"),
                "collector_number": entry.get("collector_number"), "quantity_delta": delta,
                "value_delta": round(unit_price * delta, 2) if unit_price is not None else None,
                "created_at": correction["created_at"], "label": reason,
            })
            self._persist()
            return {"adjusted": True, "correction": dict(correction), "card": dict(entry)}

    def undo_correction(self, correction_id: str) -> dict[str, Any]:
        with self._lock:
            correction = next(
                (item for item in self._corrections if item.get("id") == correction_id),
                None,
            )
            if correction is None:
                return {"undone": False, "reason": "correction_not_found"}
            if correction.get("undone_at"):
                return {"undone": False, "reason": "already_undone"}
            entry = self._cards.get(str(correction.get("version_key") or ""))
            if entry is None:
                return {"undone": False, "reason": "card_not_found"}
            inverse = -int(correction.get("delta") or 0)
            quantity = int(entry.get("quantity") or 0) + inverse
            if quantity < 0:
                return {"undone": False, "reason": "quantity_below_zero"}
            correction["undone_at"] = time.time()
            entry["quantity"] = quantity
            self._clamp_disposition(entry)
            entry["last_corrected_at"] = correction["undone_at"]
            unit_price = self._verified_unit_price(entry)
            self._activity.append({
                "id": str(uuid.uuid4()), "type": "correction_undo", "version_key": correction.get("version_key"),
                "card_name": entry.get("english_name") or entry.get("card_name"),
                "set_name": entry.get("set_name") or entry.get("set_code"),
                "collector_number": entry.get("collector_number"), "quantity_delta": inverse,
                "value_delta": round(unit_price * inverse, 2) if unit_price is not None else None,
                "created_at": correction["undone_at"], "label": "Correction undone",
            })
            self._persist()
            return {"undone": True, "correction": dict(correction), "card": dict(entry)}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cards = sorted(
                (dict(card) for card in self._cards.values() if int(card.get("quantity") or 0) > 0),
                key=lambda card: (
                    -float(card.get("last_seen_at") or 0),
                    str(card.get("card_name") or ""),
                ),
            )
            return {
                "schema_version": self.SCHEMA_VERSION,
                "unique_cards": len(cards),
                "total_cards": sum(int(card.get("quantity") or 0) for card in cards),
                "duplicate_copies": sum(
                    max(0, int(card.get("quantity") or 0) - 1) for card in cards
                ),
                "cards": cards,
                "corrections": [dict(item) for item in reversed(self._corrections[-50:])],
            }

    @classmethod
    def _set_key(cls, card: dict[str, Any]) -> str:
        return cls._text(card.get("set_code") or card.get("set_id") or card.get("set_name")).casefold()

    @classmethod
    def _checklist_key(cls, card: dict[str, Any]) -> str:
        return "|".join((
            cls._text(card.get("collector_number")).casefold(),
            cls._text(card.get("language") or "unknown").casefold(),
        ))

    def set_progress(self, reference_cards: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            owned = [
                dict(card) for card in self._cards.values()
                if int(card.get("quantity") or 0) > 0
            ]
        references_by_set: dict[str, dict[str, dict[str, Any]]] = {}
        for card in reference_cards:
            set_key = self._set_key(card)
            checklist_key = self._checklist_key(card)
            if set_key and checklist_key.split("|", 1)[0]:
                references_by_set.setdefault(set_key, {})[checklist_key] = dict(card)

        owned_by_set: dict[str, list[dict[str, Any]]] = {}
        for card in owned:
            owned_by_set.setdefault(self._set_key(card), []).append(card)

        summaries: list[dict[str, Any]] = []
        for set_key in sorted(set(owned_by_set) | set(references_by_set)):
            owned_cards = owned_by_set.get(set_key, [])
            reference_map = references_by_set.get(set_key, {})
            owned_keys = {self._checklist_key(card) for card in owned_cards}
            missing = [
                card for key, card in reference_map.items() if key not in owned_keys
            ]
            label_source = (owned_cards or list(reference_map.values()) or [{}])[0]
            catalog_total = len(reference_map)
            owned_catalog = len(owned_keys & set(reference_map))
            summaries.append({
                "set_key": set_key,
                "set_name": label_source.get("set_name") or label_source.get("set_code") or "Unknown set",
                "set_code": label_source.get("set_code") or label_source.get("set_id"),
                "owned_versions": len(owned_cards),
                "total_copies": sum(int(card.get("quantity") or 0) for card in owned_cards),
                "duplicate_copies": sum(max(0, int(card.get("quantity") or 0) - 1) for card in owned_cards),
                "catalog_total": catalog_total or None,
                "catalog_owned": owned_catalog if catalog_total else None,
                "completion_percent": round(owned_catalog / catalog_total * 100, 1) if catalog_total else None,
                "checklist_status": "available" if catalog_total else "unavailable",
                "missing_cards": sorted(missing, key=lambda card: str(card.get("collector_number") or "")),
            })
        summaries.sort(key=lambda item: (-int(item["total_copies"]), str(item["set_name"])))
        return {"sets": summaries, "set_count": len(summaries)}

    @staticmethod
    def _verified_unit_price(card: dict[str, Any]) -> float | None:
        source = str(card.get("pricing_source") or "").strip()
        if not source or source.casefold() in {"demo", "test", "test_auto_add"}:
            return None
        try:
            value = float(card.get("market_price") or 0)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def valuation(self) -> dict[str, Any]:
        cards = self.snapshot()["cards"]
        priced: list[dict[str, Any]] = []
        unpriced_copies = 0
        by_set: dict[str, dict[str, Any]] = {}
        by_rarity: dict[str, dict[str, Any]] = {}
        for card in cards:
            quantity = int(card.get("quantity") or 0)
            unit_price = self._verified_unit_price(card)
            if unit_price is None:
                unpriced_copies += quantity
                continue
            total_value = round(unit_price * quantity, 2)
            valued = {
                **card,
                "unit_price": unit_price,
                "total_value": total_value,
            }
            priced.append(valued)
            set_key = self._set_key(card)
            set_bucket = by_set.setdefault(set_key, {
                "set_name": card.get("set_name") or card.get("set_code") or "Unknown set",
                "value": 0.0,
                "priced_copies": 0,
            })
            set_bucket["value"] = round(float(set_bucket["value"]) + total_value, 2)
            set_bucket["priced_copies"] += quantity
            rarity = self._text(card.get("rarity") or "Unknown")
            rarity_bucket = by_rarity.setdefault(rarity, {"rarity": rarity, "value": 0.0, "copies": 0})
            rarity_bucket["value"] = round(float(rarity_bucket["value"]) + total_value, 2)
            rarity_bucket["copies"] += quantity

        priced_copies = sum(int(card.get("quantity") or 0) for card in priced)
        total_copies = priced_copies + unpriced_copies
        portfolio_value = round(sum(float(card["total_value"]) for card in priced), 2)
        return {
            "currency": "USD",
            "portfolio_value": portfolio_value,
            "priced_copies": priced_copies,
            "unpriced_copies": unpriced_copies,
            "pricing_coverage_percent": round(priced_copies / total_copies * 100, 1) if total_copies else 0.0,
            "biggest_hits": sorted(priced, key=lambda card: -float(card["unit_price"]))[:10],
            "set_values": sorted(by_set.values(), key=lambda item: -float(item["value"])),
            "rarity_values": sorted(by_rarity.values(), key=lambda item: -float(item["value"])),
        }

    def trends(self, days: int = 30) -> dict[str, Any]:
        cutoff = time.time() - max(1, int(days)) * 86400
        with self._lock:
            activity = [dict(item) for item in self._activity]
        buckets: dict[str, dict[str, Any]] = {}
        for item in activity:
            timestamp = float(item.get("created_at") or 0)
            if timestamp < cutoff and item.get("type") != "baseline":
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(timestamp))
            bucket = buckets.setdefault(day, {"date": day, "cards_delta": 0, "verified_value_delta": 0.0, "priced_events": 0})
            bucket["cards_delta"] += int(item.get("quantity_delta") or 0)
            if item.get("value_delta") is not None:
                bucket["verified_value_delta"] = round(float(bucket["verified_value_delta"]) + float(item["value_delta"]), 2)
                bucket["priced_events"] += 1
        set_growth: dict[str, int] = {}
        for item in activity:
            if float(item.get("created_at") or 0) >= cutoff and item.get("set_name"):
                set_growth[str(item["set_name"])] = set_growth.get(str(item["set_name"]), 0) + int(item.get("quantity_delta") or 0)
        return {
            "window_days": max(1, int(days)),
            "daily": [buckets[key] for key in sorted(buckets)],
            "recent_activity": sorted(activity, key=lambda item: -float(item.get("created_at") or 0))[:20],
            "set_growth": [{"set_name": key, "cards_delta": value} for key, value in sorted(set_growth.items(), key=lambda item: -item[1])],
            "has_legacy_baseline": any(item.get("type") == "baseline" for item in activity),
        }

    def add_goal(
        self,
        *,
        target_type: str,
        set_name: str,
        collector_number: str | None = None,
        language: str | None = None,
        card_name: str | None = None,
        target_quantity: int = 1,
        priority: str = "medium",
        notes: str = "",
    ) -> dict[str, Any]:
        target_type = self._text(target_type).casefold()
        if target_type not in {"card", "set"}:
            return {"created": False, "reason": "invalid_target_type"}
        if not self._text(set_name):
            return {"created": False, "reason": "set_required"}
        if target_type == "card" and not self._text(collector_number):
            return {"created": False, "reason": "collector_number_required"}
        goal = {
            "id": str(uuid.uuid4()), "target_type": target_type,
            "set_name": self._text(set_name), "collector_number": self._text(collector_number) or None,
            "language": self._text(language) or None, "card_name": self._text(card_name) or None,
            "target_quantity": max(1, int(target_quantity)),
            "priority": self._text(priority).casefold() if self._text(priority).casefold() in {"low", "medium", "high"} else "medium",
            "notes": self._text(notes), "created_at": time.time(), "archived_at": None,
        }
        with self._lock:
            self._goals.append(goal)
            self._persist()
        return {"created": True, "goal": dict(goal)}

    def archive_goal(self, goal_id: str) -> dict[str, Any]:
        with self._lock:
            goal = next((item for item in self._goals if item.get("id") == goal_id), None)
            if goal is None:
                return {"archived": False, "reason": "goal_not_found"}
            if goal.get("archived_at"):
                return {"archived": False, "reason": "already_archived"}
            goal["archived_at"] = time.time()
            self._persist()
            return {"archived": True, "goal": dict(goal)}

    def goals(self, reference_cards: list[dict[str, Any]]) -> dict[str, Any]:
        cards = self.snapshot()["cards"]
        active = [dict(goal) for goal in self._goals if not goal.get("archived_at")]
        for goal in active:
            set_name = self._text(goal.get("set_name")).casefold()
            matching_owned = [card for card in cards if set_name in {
                self._text(card.get("set_name")).casefold(), self._text(card.get("set_code")).casefold()
            }]
            matching_refs = [card for card in reference_cards if set_name in {
                self._text(card.get("set_name")).casefold(), self._text(card.get("set_code") or card.get("set_id")).casefold()
            }]
            if goal["target_type"] == "card":
                number = self._text(goal.get("collector_number")).casefold()
                language = self._text(goal.get("language")).casefold()
                owned = [card for card in matching_owned if self._text(card.get("collector_number")).casefold() == number and (not language or self._text(card.get("language")).casefold() == language)]
                current = sum(int(card.get("quantity") or 0) for card in owned)
                reference = next((card for card in matching_refs if self._text(card.get("collector_number")).casefold() == number), None)
                goal["resolved_name"] = (reference or {}).get("card_name") or goal.get("card_name")
                goal["identity_status"] = "catalog_resolved" if reference else "manual_target"
            else:
                current = len(matching_owned)
                goal["identity_status"] = "catalog_resolved" if matching_refs else "manual_target"
            target = int(goal.get("target_quantity") or 1)
            goal["current_quantity"] = current
            goal["progress_percent"] = round(min(1, current / target) * 100, 1)
            goal["complete"] = current >= target
        active.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item["priority"], 1), item["complete"], item["created_at"]))
        return {"goals": active, "active_goals": len(active), "completed_goals": sum(1 for item in active if item["complete"])}

    @staticmethod
    def _clamp_disposition(entry: dict[str, Any]) -> None:
        quantity = max(0, int(entry.get("quantity") or 0))
        disposition = entry.setdefault("disposition", {"trade": 0, "sell": 0})
        trade = min(quantity, max(0, int(disposition.get("trade") or 0)))
        sell = min(quantity - trade, max(0, int(disposition.get("sell") or 0)))
        entry["disposition"] = {"trade": trade, "sell": sell}

    def set_disposition(
        self,
        version_key: str,
        *,
        trade: int,
        sell: int,
    ) -> dict[str, Any]:
        trade, sell = int(trade), int(sell)
        if trade < 0 or sell < 0:
            return {"updated": False, "reason": "negative_allocation"}
        with self._lock:
            entry = self._cards.get(self._text(version_key))
            if entry is None:
                return {"updated": False, "reason": "card_not_found"}
            quantity = int(entry.get("quantity") or 0)
            if trade + sell > quantity:
                return {"updated": False, "reason": "allocation_exceeds_quantity"}
            entry["disposition"] = {"trade": trade, "sell": sell}
            entry["disposition_updated_at"] = time.time()
            self._persist()
            return {"updated": True, "card": dict(entry)}

    def disposition_queue(self) -> dict[str, Any]:
        cards = self.snapshot()["cards"]
        rows: list[dict[str, Any]] = []
        for card in cards:
            disposition = card.get("disposition") or {}
            trade = max(0, int(disposition.get("trade") or 0))
            sell = max(0, int(disposition.get("sell") or 0))
            quantity = int(card.get("quantity") or 0)
            keep = max(0, quantity - trade - sell)
            if trade or sell:
                rows.append({**card, "keep_quantity": keep, "trade_quantity": trade, "sell_quantity": sell})
        return {
            "disposition_cards": rows,
            "trade_copies": sum(item["trade_quantity"] for item in rows),
            "sell_copies": sum(item["sell_quantity"] for item in rows),
        }

    def dashboard(self, reference_cards: list[dict[str, Any]]) -> dict[str, Any]:
        """Build one internally consistent read model under the service lock."""
        with self._lock:
            collection = self.snapshot()
            progress = self.set_progress(reference_cards)
            valuation = self.valuation()
            trends = self.trends()
            goals = self.goals(reference_cards)
            disposition = self.disposition_queue()
            return {
                **collection, **progress, "valuation": valuation,
                "trends": trends, **goals, **disposition,
            }
