from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable


class CatalogService:
    API_BASE = "https://api.tcgdex.net/v2"
    LANGUAGE_MAP = {
        "English": ["en"],
        "Japanese": ["ja"],
        "Chinese": ["zh-tw", "zh-cn", "en"],
        "Simplified Chinese": ["zh-cn", "en"],
        "Traditional Chinese": ["zh-tw", "en"],
        "Korean": ["ko", "en"],
        "Unknown": ["en"],
    }

    def __init__(self, emit: Callable[[dict[str, Any]], None], cache_dir: Path) -> None:
        self.emit = emit
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._manual_price_path = self.cache_dir / "manual_prices.json"
        self._price_resolution_audit_path = self.cache_dir / "price_resolution_audit.json"
        self._price_history_path = self.cache_dir / "price_history.json"
        self._price_alert_path = self.cache_dir / "price_alerts.json"
        self._history_lock = threading.Lock()
        self._watch_lock = threading.Lock()
        self._watch_busy = False
        self._watch_stop = threading.Event()
        self._watch_interval_seconds = 6 * 60 * 60
        self._watch_status: dict[str, Any] = {"busy": False, "last_run_at": None, "next_run_at": time.time() + 60, "checked": 0, "updated": 0, "errors": []}
        self._lock = threading.Lock()
        self._busy = False
        self._last_key: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._status: dict[str, Any] = {
            "busy": False,
            "source": None,
            "query": None,
            "match": None,
            "candidates": [],
            "latency_ms": None,
            "error": None,
            "note": None,
            "prediction_prefetch": {"queued": 0, "warmed": 0, "errors": 0, "active": 0},
        }
        self._prefetch_lock = threading.Lock()
        self._prefetch_active: set[str] = set()
        self._prefetched_lookup_ms: dict[str, float] = {}
        self._prefetch_context = threading.local()
        threading.Thread(target=self._watch_scheduler, daemon=True, name="rareiq-price-watch").start()

    def shutdown(self) -> None:
        self._watch_stop.set()

    def watch_status(self) -> dict[str, Any]:
        with self._watch_lock:
            return dict(self._watch_status)

    def _watch_scheduler(self) -> None:
        # Give startup/catalog recovery priority before the first automatic run.
        if self._watch_stop.wait(60):
            return
        while not self._watch_stop.is_set():
            self.refresh_watched_prices()
            self._watch_stop.wait(self._watch_interval_seconds)

    def refresh_watched_prices(self) -> dict[str, Any]:
        with self._watch_lock:
            if self._watch_busy:
                return {"ok": False, "error": "Watchlist refresh already running.", "scheduler": dict(self._watch_status)}
            self._watch_busy = True
            self._watch_status.update({"busy": True, "errors": []})
        threading.Thread(target=self._watch_refresh_worker, daemon=True, name="rareiq-price-refresh").start()
        return {"ok": True, "scheduler": self.watch_status()}

    def _watch_refresh_worker(self) -> None:
        checked = updated = 0
        errors: list[str] = []
        for identity, alert in self._read_price_alerts().items():
            if self._watch_stop.is_set():
                break
            try:
                set_id, number, identity_language, _variant = self._price_identity_parts(identity)
                language = str(alert.get("language") or identity_language or "English")
                code = self.LANGUAGE_MAP.get(language, ["en"])[0]
                self._cache_path(code, number).unlink(missing_ok=True)
                result = self._lookup_language(code, number)
                candidates = result.get("candidates") or []
                match = next((card for card in candidates if str(card.get("set_id") or "").casefold() == set_id), None)
                checked += 1
                if match and match.get("pricing"):
                    self._record_price(match)
                    updated += 1
            except Exception as exc:
                errors.append(f"{identity}: {exc}")
        now = time.time()
        with self._watch_lock:
            self._watch_busy = False
            self._watch_status.update({"busy": False, "last_run_at": now, "next_run_at": now + self._watch_interval_seconds, "checked": checked, "updated": updated, "errors": errors[-10:]})
        self.emit({"type": "price_watch_update", "payload": self.price_alert_dashboard()})

    @staticmethod
    def _legacy_price_identity(card: dict[str, Any]) -> str:
        return "|".join((
            str(card.get("set_id") or card.get("set_code") or "").strip().casefold(),
            str(card.get("collector_number") or card.get("card_number") or "").strip().casefold(),
        ))

    @classmethod
    def _price_identity(cls, card: dict[str, Any]) -> str:
        set_id = str(card.get("set_id") or card.get("set_code") or "").strip().casefold()
        raw_number = str(card.get("collector_number") or card.get("card_number") or "").strip().casefold()
        numerator, denominator = cls._split_number(raw_number)
        number = f"{numerator}/{denominator}" if denominator else numerator
        raw_language = str(card.get("language_code") or card.get("language") or "unknown").strip().casefold()
        language_aliases = {
            "english": "en", "japanese": "ja", "simplified chinese": "zh-cn",
            "traditional chinese": "zh-tw", "chinese": "zh", "korean": "ko",
        }
        language = language_aliases.get(raw_language, raw_language or "unknown")
        pricing = card.get("pricing") if isinstance(card.get("pricing"), dict) else {}
        variant = str(
            card.get("price_variant") or card.get("variant") or card.get("finish")
            or pricing.get("variant") or "standard"
        ).strip().casefold().replace("_", "-")
        return "|".join((set_id, number, language, variant or "standard"))

    @staticmethod
    def _price_identity_parts(identity: str) -> tuple[str, str, str, str]:
        parts = str(identity or "").split("|")
        parts += [""] * (4 - len(parts))
        return parts[0], parts[1], parts[2], parts[3]

    @classmethod
    def _valid_price_identity(cls, identity: str) -> bool:
        set_id, number, _language, _variant = cls._price_identity_parts(identity)
        return bool(set_id and number)

    @classmethod
    def _stored_price_value(cls, saved: dict[str, Any], card: dict[str, Any], default: Any = None) -> Any:
        identity = cls._price_identity(card)
        if identity in saved:
            return saved[identity]
        return saved.get(cls._legacy_price_identity(card), default)

    def _read_manual_prices(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._manual_price_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _read_price_resolution_audit(self) -> dict[str, list[dict[str, Any]]]:
        try:
            payload = json.loads(self._price_resolution_audit_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write_price_resolution_audit(self, audit: dict[str, list[dict[str, Any]]]) -> None:
        self._price_resolution_audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _apply_manual_price(self, card: dict[str, Any]) -> dict[str, Any]:
        override = self._stored_price_value(self._read_manual_prices(), card)
        if not isinstance(override, dict):
            return card
        enriched = dict(card)
        enriched["pricing"] = self._decorate_price(
            override, confidence=str(override.get("confidence") or "verified")
        )
        return self._attach_price_history(enriched)

    def _read_price_history(self) -> dict[str, list[dict[str, Any]]]:
        try:
            payload = json.loads(self._price_history_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _read_price_alerts(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self._price_alert_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def set_price_alert(self, recognition: dict[str, Any], alert: dict[str, Any]) -> dict[str, Any]:
        identity = self._price_identity(recognition)
        if not self._valid_price_identity(identity):
            return {"ok": False, "error": "An exact set and collector number are required."}
        enabled = bool(alert.get("enabled", True))
        entry = {
            "direction": "below" if str(alert.get("direction")) == "below" else "above",
            "target": float(alert["target"]),
            "currency": str(alert.get("currency") or "USD").upper(),
            "enabled": enabled,
            "created_at": time.time(),
            "card_name": str(recognition.get("english_name") or recognition.get("name") or recognition.get("card_name") or "").strip(),
            "set_name": str(recognition.get("set_name") or recognition.get("set_id") or recognition.get("set_code") or "").strip(),
            "collector_number": str(recognition.get("collector_number") or recognition.get("card_number") or "").strip(),
            "identity": identity,
            "language": str(recognition.get("language") or "English"),
        }
        saved = self._read_price_alerts()
        inventory_targets = (saved.get(identity) or {}).get("inventory_targets")
        if isinstance(inventory_targets, dict) and inventory_targets:
            entry["inventory_targets"] = inventory_targets
        if enabled:
            saved[identity] = entry
        elif isinstance(inventory_targets, dict) and inventory_targets:
            saved[identity] = {key: value for key, value in entry.items() if key not in {"direction", "target", "currency", "enabled", "created_at"}}
        else:
            saved.pop(identity, None)
        self._price_alert_path.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ok": True, "alert": entry if enabled else None}

    def set_inventory_price_alert(self, item: dict[str, Any], alert: dict[str, Any]) -> dict[str, Any]:
        identity = self._price_identity(item)
        item_id = str(item.get("item_id") or "").upper()
        if not self._valid_price_identity(identity) or not item_id:
            return {"ok": False, "error": "An exact inventory item is required."}
        saved = self._read_price_alerts()
        entry = dict(saved.get(identity) or {})
        targets = dict(entry.get("inventory_targets") or {})
        if bool(alert.get("enabled", True)):
            targets[item_id] = {"item_id": item_id, "direction": "below" if str(alert.get("direction")) == "below" else "above", "target": float(alert["target"]), "currency": str(alert.get("currency") or item.get("currency") or "USD").upper(), "created_at": time.time()}
        else:
            targets.pop(item_id, None)
        if targets:
            entry.update({"inventory_targets": targets, "card_name": str(item.get("english_name") or item.get("card_name") or ""), "set_name": str(item.get("set_name") or item.get("set_code") or ""), "collector_number": str(item.get("collector_number") or ""), "identity": identity, "language": str(item.get("language") or "English")})
            saved[identity] = entry
        elif not entry.get("enabled"):
            saved.pop(identity, None)
        else:
            entry.pop("inventory_targets", None); saved[identity] = entry
        self._price_alert_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "alert": targets.get(item_id), "removed": item_id not in targets}

    def remove_price_alert(self, identity: str) -> dict[str, Any]:
        saved = self._read_price_alerts()
        key = str(identity); existing = saved.get(key)
        removed = existing is not None
        if isinstance(existing, dict) and existing.get("inventory_targets"):
            kept = {key_name: value for key_name, value in existing.items() if key_name not in {"direction", "target", "currency", "enabled", "created_at"}}
            saved[key] = kept
        else:
            saved.pop(key, None)
        self._price_alert_path.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"ok": True, "removed": removed is not None}

    def price_alert_dashboard(self) -> dict[str, Any]:
        alerts, history = self._read_price_alerts(), self._read_price_history()
        rows: list[dict[str, Any]] = []
        for identity, alert in alerts.items():
            snapshots = history.get(identity) or []
            latest = snapshots[-1] if snapshots else {}
            current = latest.get("market")
            def append_alert(target_alert: dict[str, Any], item_id: str | None = None) -> None:
                target = target_alert.get("target")
                triggered = isinstance(current, (int, float)) and isinstance(target, (int, float)) and (current >= target if target_alert.get("direction") == "above" else current <= target)
                rows.append({**alert, **target_alert, "inventory_item_id": item_id, "identity": identity, "current": current, "current_currency": latest.get("currency"), "price_source": latest.get("source"), "price_updated_at": latest.get("captured_at"), "triggered": triggered})
            if alert.get("enabled") and isinstance(alert.get("target"), (int, float)):
                append_alert(alert)
            for item_id, target_alert in (alert.get("inventory_targets") or {}).items():
                if isinstance(target_alert, dict): append_alert(target_alert, str(item_id))
        rows.sort(key=lambda row: (not row["triggered"], str(row.get("card_name") or row["identity"])))
        return {"alerts": rows, "total": len(rows), "triggered": sum(1 for row in rows if row["triggered"]), "scheduler": self.watch_status()}

    def inventory_valuation(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        history, alerts = self._read_price_history(), self._read_price_alerts()
        rows: list[dict[str, Any]] = []
        for item in items:
            if item.get("status") != "in_stock":
                continue
            identity = self._price_identity(item)
            snapshots = self._stored_price_value(history, item, []) or []
            latest = snapshots[-1] if snapshots else None
            currency = str((latest or {}).get("currency") or item.get("currency") or "USD")
            market = (latest or {}).get("market")
            cost = float(item.get("cost_basis") or 0)
            try:
                quote_age = max(0, time.time() - float((latest or {}).get("quote_updated_at") or (latest or {}).get("captured_at") or 0))
            except (TypeError, ValueError):
                quote_age = None
            stale_now = quote_age is not None and quote_age > 604800
            valuation_eligible = (latest or {}).get("valuation_eligible") is not False and not stale_now
            currency_compatible = currency == str(item.get("currency") or "USD")
            comparable = isinstance(market, (int, float)) and currency_compatible and valuation_eligible
            unrealized = round(float(market) - cost, 2) if comparable else None
            movement = None
            if comparable and len(snapshots) >= 2 and isinstance(snapshots[-2].get("market"), (int, float)):
                movement = round(float(market) - float(snapshots[-2]["market"]), 2)
            alert = self._stored_price_value(alerts, item, {}) or {}
            target = alert.get("target") if alert.get("currency") == currency else None
            upside = round(float(target) - float(market), 2) if comparable and isinstance(target, (int, float)) else None
            exclusion_reason = None if comparable else (
                "Quote is older than 7 days" if stale_now else
                (latest or {}).get("verification_reason") if not valuation_eligible else
                "Currency does not match inventory basis" if isinstance(market, (int, float)) and not currency_compatible else
                "No verified market quote"
            )
            rows.append({"item_id": item.get("item_id"), "card_name": item.get("english_name") or item.get("card_name"), "set_name": item.get("set_name") or item.get("set_code"), "collector_number": item.get("collector_number"), "identity": identity, "cost_basis": cost, "market": market, "currency": currency, "unrealized_profit": unrealized, "movement": movement, "target": target, "target_upside": upside, "priced": comparable, "valuation_eligible": valuation_eligible, "pricing_status": "stale" if stale_now else (latest or {}).get("verification_state") or ("verified" if comparable else "unpriced"), "price_age_seconds": round(quote_age, 1) if quote_age is not None else None, "price_exclusion_reason": exclusion_reason, "allocation_group": item.get("allocation_group") or "", "allocation_weight": float(item.get("allocation_weight") or 1), "reference_image_url": item.get("reference_image_url"), "profile_url": item.get("profile_url")})
        priced = [row for row in rows if row["priced"]]
        # Portfolio headline is currency-safe: only USD-compatible rows contribute.
        usd = [row for row in priced if row["currency"] == "USD"]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["allocation_group"]:
                grouped.setdefault(row["allocation_group"], []).append(row)
        allocation_groups = []
        for group, group_rows in grouped.items():
            group_priced = [row for row in group_rows if row["priced"] and row["currency"] == "USD"]
            cost = round(sum(float(row["cost_basis"]) for row in group_rows), 2)
            market_value = round(sum(float(row["market"]) for row in group_priced), 2)
            priced_cost = sum(float(row["cost_basis"]) for row in group_priced)
            strongest = max(group_priced, key=lambda row: float(row.get("market") or 0), default=None)
            allocation_groups.append({"group": group, "cards": len(group_rows), "priced": len(group_priced), "cost_basis": cost, "verified_value": market_value, "unrealized_profit": round(market_value - priced_cost, 2), "roi_percent": round((market_value - priced_cost) / priced_cost * 100, 1) if priced_cost else None, "coverage_percent": round(len(group_priced) / len(group_rows) * 100, 1), "complete": len(group_priced) == len(group_rows), "strongest_pull": strongest, "items": group_rows})
        allocation_groups.sort(key=lambda group: group["group"], reverse=True)
        excluded = [row for row in rows if not row["priced"] and isinstance(row.get("market"), (int, float))]
        return {"items": rows, "allocation_groups": allocation_groups, "in_stock": len(rows), "priced": len(priced), "unpriced": len(rows) - len(priced), "excluded_quotes": len(excluded), "stale_excluded": sum(1 for row in excluded if row.get("pricing_status") == "stale"), "unverified_excluded": sum(1 for row in excluded if row.get("pricing_status") == "unverified"), "coverage_percent": round(len(priced) / len(rows) * 100, 1) if rows else 0.0, "currency": "USD", "verified_value": round(sum(float(row["market"]) for row in usd), 2), "cost_basis": round(sum(float(row["cost_basis"]) for row in usd), 2), "unrealized_profit": round(sum(float(row["unrealized_profit"]) for row in usd), 2), "movement": round(sum(float(row["movement"] or 0) for row in usd), 2), "target_upside": round(sum(max(0.0, float(row["target_upside"] or 0)) for row in usd), 2), "excluded_non_usd": len(priced) - len(usd)}

    def inventory_item_timeline(self, item: dict[str, Any]) -> dict[str, Any]:
        """Build a currency-safe, item-level valuation and realized-return record."""
        snapshots = self._stored_price_value(self._read_price_history(), item, []) or []
        acquisition = item.get("acquisition_valuation") if isinstance(item.get("acquisition_valuation"), dict) else {}
        sale = item.get("sale") if isinstance(item.get("sale"), dict) else {}
        currency = str(item.get("currency") or acquisition.get("currency") or "USD")
        events: list[dict[str, Any]] = []
        if acquisition:
            events.append({"kind": "acquisition", "timestamp": acquisition.get("captured_at") or item.get("created_at"), "market": acquisition.get("market"), "currency": acquisition.get("currency") or currency, "provider": acquisition.get("provider"), "resolution_id": acquisition.get("resolution_id") or item.get("pricing_resolution_id"), "reason": acquisition.get("resolution_reason"), "note": acquisition.get("resolution_note")})
        # Price history already suppresses unchanged same-day quotes. Preserve a bounded
        # series here so a sleeve profile remains useful without growing indefinitely.
        verified_snapshots = [snapshot for snapshot in snapshots if snapshot.get("valuation_eligible") is not False and snapshot.get("verification_state") != "unverified" and isinstance(snapshot.get("market"), (int, float))]
        retained_snapshots = verified_snapshots[-90:]
        latest = snapshots[-1] if snapshots else None
        current_market = (latest or {}).get("market")
        current_currency = str((latest or {}).get("currency") or currency)
        current_verified = bool(latest and latest.get("valuation_eligible") is not False and latest.get("verification_state") != "unverified")
        for snapshot in retained_snapshots:
            events.append({"kind": "market", "timestamp": snapshot.get("captured_at") or snapshot.get("quote_updated_at"), "market": snapshot.get("market"), "currency": snapshot.get("currency") or currency, "provider": snapshot.get("source") or snapshot.get("provider"), "verified": True})
        for listing in item.get("listings") or []:
            if not isinstance(listing, dict): continue
            events.append({"kind": "listing", "timestamp": listing.get("listed_at"), "market": listing.get("asking_price"), "currency": currency, "provider": listing.get("channel"), "listing_id": listing.get("listing_id"), "status": listing.get("status")})
            if listing.get("ended_at"):
                events.append({"kind": "listing ended", "timestamp": listing.get("ended_at"), "currency": currency, "provider": listing.get("channel"), "listing_id": listing.get("listing_id"), "status": listing.get("status")})
        if sale:
            events.append({"kind": "sale", "timestamp": sale.get("sold_at"), "gross": sale.get("gross"), "net_proceeds": sale.get("net_proceeds"), "profit": sale.get("profit"), "currency": currency, "channel": sale.get("channel"), "order_reference": sale.get("order_reference")})
        acquisition_market = acquisition.get("market")
        comparable = isinstance(acquisition_market, (int, float)) and isinstance(current_market, (int, float)) and str(acquisition.get("currency") or currency) == current_currency
        change = round(float(current_market) - float(acquisition_market), 2) if comparable else None
        change_percent = round(change / float(acquisition_market) * 100, 1) if comparable and acquisition_market else None
        realized_profit = sale.get("profit") if isinstance(sale.get("profit"), (int, float)) else None
        cost = float(item.get("cost_basis") or 0)
        realized_roi = round(float(realized_profit) / cost * 100, 1) if realized_profit is not None and cost else None
        compatible_values = [float(snapshot["market"]) for snapshot in retained_snapshots if str(snapshot.get("currency") or currency) == currency]
        return {"item_id": item.get("item_id"), "status": item.get("status"), "currency": currency, "acquisition_market": acquisition_market, "current_market": current_market if current_verified else None, "market_change": change if current_verified else None, "market_change_percent": change_percent if current_verified else None, "market_low": min(compatible_values) if compatible_values else None, "market_high": max(compatible_values) if compatible_values else None, "checkpoint_count": len(retained_snapshots), "realized_profit": realized_profit, "realized_roi_percent": realized_roi, "events": sorted(events, key=lambda event: float(event.get("timestamp") or 0))}

    def inventory_break_performance(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        valuation = self.inventory_valuation(items)
        valued = {row["item_id"]: row for row in valuation["items"]}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            group = str(item.get("allocation_group") or "")
            if group:
                grouped.setdefault(group, []).append(item)
        packs = []
        for group, group_items in grouped.items():
            stock_rows = [valued[item["item_id"]] for item in group_items if item.get("item_id") in valued]
            sold = [item for item in group_items if item.get("status") == "sold" and isinstance(item.get("sale"), dict)]
            cost = round(sum(float(item.get("cost_basis") or 0) for item in group_items), 2)
            verified_value = round(sum(float(row.get("market") or 0) for row in stock_rows if row.get("priced") and row.get("currency") == "USD"), 2)
            realized_sales = round(sum(float((item.get("sale") or {}).get("net_proceeds") or 0) for item in sold), 2)
            total_return = round(verified_value + realized_sales, 2)
            profit = round(total_return - cost, 2)
            hits = sum(1 for item in group_items if float(item.get("allocation_weight") or 1) > 1)
            candidates = [({"card_name": row["card_name"], "value": float(row["market"]), "source": "market"}) for row in stock_rows if row.get("priced")]
            candidates += [({"card_name": item.get("english_name") or item.get("card_name"), "value": float((item.get("sale") or {}).get("gross") or 0), "source": "sale"}) for item in sold]
            packs.append({"group": group, "box": group.rsplit(":pack-", 1)[0], "pack_number": group.rsplit("pack-", 1)[-1], "cards": len(group_items), "hits": hits, "hit_rate": round(hits / len(group_items) * 100, 1) if group_items else 0, "cost": cost, "verified_value": verified_value, "realized_sales": realized_sales, "total_return": total_return, "profit": profit, "roi_percent": round(profit / cost * 100, 1) if cost else None, "priced": sum(1 for row in stock_rows if row.get("priced")) + len(sold), "coverage_percent": round((sum(1 for row in stock_rows if row.get("priced")) + len(sold)) / len(group_items) * 100, 1) if group_items else 0, "strongest_pull": max(candidates, key=lambda row: row["value"], default=None)})
        packs.sort(key=lambda row: float(row["roi_percent"]) if row.get("roi_percent") is not None else -1000000, reverse=True)
        box_groups: dict[str, list[dict[str, Any]]] = {}
        for pack in packs:
            box_groups.setdefault(pack["box"], []).append(pack)
        boxes = []
        for box, box_packs in box_groups.items():
            cost = round(sum(pack["cost"] for pack in box_packs), 2); total_return = round(sum(pack["total_return"] for pack in box_packs), 2); profit = round(total_return - cost, 2)
            boxes.append({"box": box, "packs": len(box_packs), "cards": sum(pack["cards"] for pack in box_packs), "cost": cost, "total_return": total_return, "profit": profit, "roi_percent": round(profit / cost * 100, 1) if cost else None, "realized_sales": round(sum(pack["realized_sales"] for pack in box_packs), 2), "strongest_pull": max((pack["strongest_pull"] for pack in box_packs if pack["strongest_pull"]), key=lambda row: row["value"], default=None)})
        boxes.sort(key=lambda row: float(row["roi_percent"]) if row.get("roi_percent") is not None else -1000000, reverse=True)
        return {"currency": "USD", "packs": packs, "boxes": boxes, "pack_count": len(packs), "box_count": len(boxes), "best_pack": packs[0] if packs else None, "best_box": boxes[0] if boxes else None}

    def _attach_price_history(self, card: dict[str, Any]) -> dict[str, Any]:
        pricing = card.get("pricing")
        if not isinstance(pricing, dict):
            return card
        history = self._stored_price_value(self._read_price_history(), card, []) or []
        enriched = dict(card)
        decorated = self._decorate_price(
            pricing, confidence=str(pricing.get("confidence") or "unknown")
        )
        decorated["history_count"] = len(history)
        decorated["history"] = history[-12:]
        alert = self._stored_price_value(self._read_price_alerts(), card)
        if isinstance(alert, dict):
            current, target = decorated.get("market"), alert.get("target")
            triggered = isinstance(current, (int, float)) and isinstance(target, (int, float)) and (
                current >= target if alert.get("direction") == "above" else current <= target
            )
            decorated["alert"] = {**alert, "triggered": triggered, "current": current}
        if len(history) >= 2:
            previous, latest = history[-2], history[-1]
            old, new = previous.get("market"), latest.get("market")
            if isinstance(old, (int, float)) and old > 0 and isinstance(new, (int, float)):
                change = round(((new - old) / old) * 100, 2)
                decorated["change_percent"] = change
                decorated["trend"] = "rising" if change > 0.25 else "falling" if change < -0.25 else "stable"
        enriched["pricing"] = decorated
        return enriched

    def _record_price(self, card: dict[str, Any]) -> dict[str, Any]:
        pricing = card.get("pricing")
        identity = self._price_identity(card)
        market = pricing.get("market") if isinstance(pricing, dict) else None
        if not self._valid_price_identity(identity) or not isinstance(market, (int, float)):
            return self._attach_price_history(card)
        snapshot = {
            "market": float(market),
            "low": pricing.get("low"),
            "high": pricing.get("high"),
            "currency": pricing.get("currency") or pricing.get("unit") or "USD",
            "source": pricing.get("source"),
            "verified": pricing.get("verified", True),
            "valuation_eligible": pricing.get("valuation_eligible", pricing.get("verified", True)),
            "verification_state": pricing.get("verification_state") or "verified",
            "verification_reason": pricing.get("verification_reason"),
            "freshness_status": pricing.get("freshness_status") or "legacy",
            "quote_updated_at": pricing.get("updated_at"),
            "captured_at": time.time(),
        }
        with self._history_lock:
            saved = self._read_price_history()
            entries = saved.setdefault(identity, [])
            last = entries[-1] if entries else None
            # One unchanged snapshot per day is enough for useful movement data.
            unchanged = last and all(last.get(key) == snapshot.get(key) for key in ("market", "currency", "source", "valuation_eligible", "verification_state"))
            recent = last and snapshot["captured_at"] - float(last.get("captured_at") or 0) < 86400
            if not (unchanged and recent):
                entries.append(snapshot)
                saved[identity] = entries[-180:]
                self._price_history_path.write_text(
                    json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        return self._attach_price_history(card)

    @staticmethod
    def _quote_consensus(quotes: list[dict[str, Any]], selected_currency: str) -> dict[str, Any]:
        comparable = [
            quote for quote in quotes
            if str(quote.get("unit") or quote.get("currency") or "").upper() == str(selected_currency or "").upper()
            and isinstance(quote.get("market"), (int, float))
        ]
        values = [float(quote["market"]) for quote in comparable]
        if len(values) < 2:
            return {"status": "single-source", "comparable_providers": len(values), "spread_percent": None, "minimum": min(values) if values else None, "maximum": max(values) if values else None}
        minimum, maximum = min(values), max(values)
        midpoint = (minimum + maximum) / 2
        spread = round((maximum - minimum) / midpoint * 100, 2) if midpoint else 0.0
        status = "aligned" if spread <= 10 else "mixed" if spread <= 25 else "divergent"
        return {"status": status, "comparable_providers": len(values), "spread_percent": spread, "minimum": minimum, "maximum": maximum}

    @staticmethod
    def _decorate_price(price: dict[str, Any], *, confidence: str) -> dict[str, Any]:
        decorated = dict(price)
        decorated.setdefault("updated_at", time.time())
        try:
            updated_at = float(decorated.get("updated_at") or 0)
        except (TypeError, ValueError):
            updated_at = 0.0
        age_seconds = max(0, int(time.time() - updated_at)) if updated_at else None
        freshness_status = (
            "unknown" if age_seconds is None else
            "fresh" if age_seconds <= 86400 else
            "aging" if age_seconds <= 604800 else "stale"
        )
        normalized_confidence = str(confidence or "unknown").strip().casefold()
        strong = normalized_confidence in {"high", "verified"}
        has_market = isinstance(decorated.get("market"), (int, float))
        consensus = decorated.get("quote_consensus") if isinstance(decorated.get("quote_consensus"), dict) else {}
        provider_conflict = consensus.get("status") == "divergent"
        verified = bool(strong and has_market and freshness_status in {"fresh", "aging"} and not provider_conflict)
        decorated["confidence"] = normalized_confidence
        decorated["age_seconds"] = age_seconds
        decorated["freshness_status"] = freshness_status
        decorated["freshness"] = {
            "fresh": "Updated within 24 hours",
            "aging": "Updated within 7 days",
            "stale": "Older than 7 days",
            "unknown": "Update time unavailable",
        }[freshness_status]
        decorated["stale"] = freshness_status == "stale"
        decorated["verified"] = verified
        decorated["valuation_eligible"] = verified
        decorated["verification_state"] = "verified" if verified else "stale" if decorated["stale"] else "unverified"
        decorated["verification_reason"] = (
            "Strong current quote" if verified else
            "Comparable providers materially disagree" if provider_conflict else
            "Quote is older than 7 days" if decorated["stale"] else
            "Quote confidence is not strong enough" if not strong else
            "Market value is unavailable"
        )
        decorated["provenance"] = {
            "source": decorated.get("source"),
            "provider_count": int(decorated.get("provider_count") or len(decorated.get("quotes") or [])),
            "selection_reason": decorated.get("selection_reason"),
            "variant": decorated.get("variant") or "standard",
            "currency": decorated.get("currency") or decorated.get("unit") or "USD",
            "consensus": consensus or None,
        }
        return decorated

    def set_manual_price(
        self, recognition: dict[str, Any], pricing: dict[str, Any]
    ) -> dict[str, Any]:
        identity = self._price_identity(recognition)
        if not self._valid_price_identity(identity):
            return {"ok": False, "error": "An exact set and collector number are required."}
        entry = {
            "source": "Manual verified",
            "market": float(pricing["market"]),
            "low": float(pricing["low"]) if pricing.get("low") is not None else None,
            "high": float(pricing["high"]) if pricing.get("high") is not None else None,
            "unit": str(pricing.get("currency") or "USD").upper(),
            "currency": str(pricing.get("currency") or "USD").upper(),
            "note": str(pricing.get("note") or "").strip() or None,
            "updated_at": time.time(),
            "manual": True,
            "confidence": "verified",
            "freshness": "just updated",
            "verified": True,
            "quotes": [],
        }
        saved = self._read_manual_prices()
        saved[identity] = entry
        self._manual_price_path.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        match = dict(recognition)
        match.setdefault("name", recognition.get("card_name") or recognition.get("english_name"))
        match["pricing"] = entry
        match = self._record_price(match)
        payload = {
            "busy": False,
            "source": "manual_verified",
            "query": {"identity": identity},
            "match": match,
            "candidates": [match],
            "latency_ms": 0.0,
            "error": None,
            "note": entry.get("note"),
        }
        with self._lock:
            self._status.update(payload)
            self._last_result = payload
        self.emit({"type": "catalog_update", "payload": payload})
        return {"ok": True, "pricing": match["pricing"], "match": match}

    def undo_price_quote_selection(self, recognition: dict[str, Any]) -> dict[str, Any]:
        identity = self._price_identity(recognition)
        audit = self._read_price_resolution_audit()
        history = audit.get(identity) if isinstance(audit.get(identity), list) else []
        resolution = next((item for item in reversed(history)
            if item.get("action") == "select-provider-quote" and not item.get("undone_at")), None)
        if resolution is None:
            return {"ok": False, "error": "No provider quote selection is available to undo."}
        saved = self._read_manual_prices()
        previous_override = resolution.get("previous_override")
        if isinstance(previous_override, dict):
            saved[identity] = previous_override
        else:
            saved.pop(identity, None)
        self._manual_price_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        resolution["undone_at"] = time.time()
        self._write_price_resolution_audit(audit)
        match = dict(recognition)
        before = resolution.get("before") if isinstance(resolution.get("before"), dict) else {}
        match["pricing"] = self._decorate_price(before, confidence=str(before.get("confidence") or "high")) if before else {}
        payload = {"busy": False, "source": "operator_quote_undo", "query": {"identity": identity},
            "match": match, "candidates": [match], "latency_ms": 0.0, "error": None}
        with self._lock:
            self._status.update(payload)
            self._last_result = payload
        self.emit({"type": "catalog_update", "payload": payload})
        return {"ok": True, "pricing": match["pricing"], "match": match, "resolution": resolution}

    def price_resolution_history(self, recognition: dict[str, Any]) -> list[dict[str, Any]]:
        history = self._read_price_resolution_audit().get(self._price_identity(recognition), [])
        return list(reversed(history[-20:])) if isinstance(history, list) else []

    def price_resolution_report(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for identity, history in self._read_price_resolution_audit().items():
            set_code, collector_number, language, card_variant = self._price_identity_parts(identity)
            if not isinstance(history, list):
                continue
            for item in history:
                rows.append({
                    "resolution_id": item.get("id"), "set_code": set_code,
                    "collector_number": collector_number, "language": language,
                    "card_variant": card_variant, "provider": item.get("source"),
                    "quote_variant": item.get("variant"), "currency": item.get("currency"),
                    "market": item.get("market"), "reason": item.get("reason"),
                    "note": item.get("note"), "selected_at": item.get("created_at"),
                    "undone_at": item.get("undone_at"),
                    "status": "reverted" if item.get("undone_at") else "active",
                })
        rows.sort(key=lambda item: float(item.get("selected_at") or 0), reverse=True)
        return {"schema": "rareiq-price-resolution-v1", "exported_at": time.time(),
                "decision_count": len(rows), "decisions": rows}

    def select_price_quote(self, recognition: dict[str, Any], choice: dict[str, Any]) -> dict[str, Any]:
        identity = self._price_identity(recognition)
        if not self._valid_price_identity(identity):
            return {"ok": False, "error": "An exact set and collector number are required."}
        current = recognition.get("pricing") if isinstance(recognition.get("pricing"), dict) else {}
        quotes = current.get("quotes") if isinstance(current.get("quotes"), list) else []
        wanted_source = str(choice.get("source") or "").strip().casefold()
        wanted_variant = str(choice.get("variant") or "standard").strip().casefold()
        wanted_currency = str(choice.get("currency") or "").strip().upper()
        resolution_reason = str(choice.get("reason") or "trusted-provider").strip().casefold()
        resolution_note = str(choice.get("note") or "").strip()[:300] or None
        selected = next((quote for quote in quotes if
            str(quote.get("source") or "").strip().casefold() == wanted_source and
            str(quote.get("variant") or "standard").strip().casefold() == wanted_variant and
            str(quote.get("unit") or quote.get("currency") or "").strip().upper() == wanted_currency and
            isinstance(quote.get("market"), (int, float))), None)
        if selected is None:
            return {"ok": False, "error": "That exact provider quote is no longer available. Refresh market data and try again."}
        now = time.time()
        entry = self._decorate_price({**selected,
            "currency": wanted_currency, "unit": wanted_currency,
            "updated_at": selected.get("updated_at") or now, "quotes": quotes,
            "provider_count": len(quotes), "selection_reason": "Operator selected provider quote",
            "quote_consensus": {"status": "operator-resolved", "original": current.get("quote_consensus"),
                "selected_source": selected.get("source"), "selected_variant": selected.get("variant") or "standard",
                "selected_at": now},
            "operator_selected": True, "operator_selected_at": now,
            "resolution_reason": resolution_reason, "resolution_note": resolution_note, "manual": False,
        }, confidence="verified")
        saved = self._read_manual_prices()
        previous_override = saved.get(identity)
        audit = self._read_price_resolution_audit()
        resolution_id = f"price-resolution-{int(now * 1000)}"
        audit.setdefault(identity, []).append({
            "id": resolution_id, "action": "select-provider-quote", "created_at": now,
            "source": selected.get("source"), "variant": selected.get("variant") or "standard",
            "currency": wanted_currency, "market": selected.get("market"),
            "reason": resolution_reason, "note": resolution_note,
            "before": current, "previous_override": previous_override, "undone_at": None,
        })
        audit[identity] = audit[identity][-20:]
        self._write_price_resolution_audit(audit)
        entry["resolution_id"] = resolution_id
        saved[identity] = entry
        self._manual_price_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        match = dict(recognition)
        match.setdefault("name", recognition.get("card_name") or recognition.get("english_name"))
        match["pricing"] = entry
        match = self._record_price(match)
        payload = {"busy": False, "source": "operator_selected_quote", "query": {"identity": identity},
            "match": match, "candidates": [match], "latency_ms": 0.0, "error": None}
        with self._lock:
            self._status.update(payload)
            self._last_result = payload
        self.emit({"type": "catalog_update", "payload": payload})
        return {"ok": True, "pricing": match["pricing"], "match": match}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def submit(self, recognition: dict[str, Any], *, force: bool = False) -> None:
        number = (
            recognition.get("collector_number")
            or recognition.get("ocr_collector_number")
        )
        name = (
            recognition.get("name_candidate")
            or recognition.get("printed_name")
            or recognition.get("name")
        )

        number_text = str(number or "").strip()
        name_text = str(name or "").strip()

        has_number = bool(number_text and "/" in number_text)
        has_name = bool(name_text)

        if not has_number and not has_name:
            return

        language = str(
            recognition.get("language") or "Unknown"
        )

        key = f"{language}|{number_text}|{name_text}"

        with self._lock:
            if self._busy or (key == self._last_key and not force):
                return

            self._busy = True
            self._last_key = key
            self._status.update({
                "busy": True,
                "query": {
                    "language": language,
                    "number": number_text or None,
                    "name": name_text or None,
                },
                "error": None,
            })

        threading.Thread(
            target=self._lookup_worker,
            args=(
                language,
                number_text,
                name_text or None,
            ),
            daemon=True,
        ).start()

    def prefetch_predictions(self, records: list[dict[str, Any]]) -> int:
        """Warm metadata/price responses for likely next cards off the scan thread."""
        queued: list[tuple[str, str, str]] = []
        for row in records[:3]:
            number = str(row.get("printed_code") or row.get("collector_number") or "").strip()
            language = str(row.get("language") or "English")
            if "/" not in number:
                continue
            for code in self.LANGUAGE_MAP.get(language, ["en"]):
                key = f"{code}|{number}"
                with self._prefetch_lock:
                    if key in self._prefetch_active:
                        continue
                    self._prefetch_active.add(key)
                queued.append((key, code, number))
        if not queued:
            return 0
        with self._lock:
            stats = dict(self._status.get("prediction_prefetch") or {})
            stats["queued"] = int(stats.get("queued") or 0) + len(queued)
            stats["active"] = len(self._prefetch_active)
            self._status["prediction_prefetch"] = stats
        threading.Thread(target=self._prediction_prefetch_worker, args=(queued,),
                         daemon=True, name="rareiq-price-prefetch").start()
        return len(queued)

    def _prediction_prefetch_worker(self, queued: list[tuple[str, str, str]]) -> None:
        warmed = errors = 0
        self._prefetch_context.active = True
        try:
            for key, code, number in queued:
                try:
                    started = time.perf_counter()
                    self._lookup_language(code, number)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    with self._prefetch_lock:
                        self._prefetched_lookup_ms[key] = elapsed_ms
                    warmed += 1
                except Exception:
                    errors += 1
                finally:
                    with self._prefetch_lock:
                        self._prefetch_active.discard(key)
        finally:
            self._prefetch_context.active = False
        with self._lock:
            stats = dict(self._status.get("prediction_prefetch") or {})
            stats["warmed"] = int(stats.get("warmed") or 0) + warmed
            stats["errors"] = int(stats.get("errors") or 0) + errors
            stats["active"] = len(self._prefetch_active)
            stats["ready"] = len(self._prefetched_lookup_ms)
            self._status["prediction_prefetch"] = stats

    def refresh(self, recognition: dict[str, Any]) -> dict[str, Any]:
        """Force a fresh provider lookup for the current exact card."""
        number = str(
            recognition.get("collector_number")
            or recognition.get("ocr_collector_number")
            or ""
        ).strip()
        language = str(recognition.get("language") or "Unknown")
        if not number and not (
            recognition.get("name_candidate")
            or recognition.get("printed_name")
            or recognition.get("name")
        ):
            return {"ok": False, "error": "No recognized card is available."}
        if number and "/" in number:
            for language_code in self.LANGUAGE_MAP.get(language, ["en"]):
                try:
                    self._cache_path(language_code, number).unlink(missing_ok=True)
                except OSError:
                    pass
        with self._lock:
            self._last_key = None
        self.submit(recognition, force=True)
        return {"ok": True, "status": self.status()}

    @staticmethod
    def _http_json(url: str, timeout: float = 6.0) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RareIQ/0.8",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _split_number(number: str) -> tuple[str, str]:
        left, right = number.split("/", 1)
        return left.lstrip("0") or "0", right.lstrip("0") or "0"

    def _cache_path(self, language_code: str, number: str) -> Path:
        safe = number.replace("/", "-")
        return self.cache_dir / f"{language_code}_{safe}.json"

    def _read_cache(self, language_code: str, number: str) -> dict[str, Any] | None:
        path = self._cache_path(language_code, number)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(payload.get("cached_at", 0)) < 86400:
                return payload
        except Exception:
            return None
        return None

    def _write_cache(self, language_code: str, number: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(language_code, number)
        payload = dict(payload)
        payload["cached_at"] = time.time()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _extract_price(card: dict[str, Any]) -> dict[str, Any] | None:
        pricing = card.get("pricing") or {}
        quotes: list[dict[str, Any]] = []
        tcgplayer = pricing.get("tcgplayer") or {}
        for variant_name in ("normal", "holofoil", "reverse-holofoil"):
            variant = tcgplayer.get(variant_name)
            if isinstance(variant, dict):
                market = variant.get("marketPrice")
                low = variant.get("lowPrice")
                high = variant.get("highPrice")
                if any(value is not None for value in (market, low, high)):
                    quotes.append({
                        "source": "TCGPlayer",
                        "variant": variant_name,
                        "market": market,
                        "low": low,
                        "high": high,
                        "unit": tcgplayer.get("unit", "USD"),
                        "updated_at": time.time(),
                    })
                    break

        cardmarket = pricing.get("cardmarket") or {}
        if cardmarket:
            quotes.append({
                "source": "Cardmarket",
                "variant": "standard",
                "market": cardmarket.get("trend") or cardmarket.get("avg"),
                "low": cardmarket.get("low"),
                "high": None,
                "unit": cardmarket.get("unit", "EUR"),
                "updated_at": time.time(),
            })
        if not quotes:
            return None
        selected = next((quote for quote in quotes if quote.get("unit") == "USD"), quotes[0])
        selection_reason = (
            "Preferred USD market quote" if selected.get("unit") == "USD"
            else "Best available public market quote"
        )
        selected_payload = {
            **selected,
            "quotes": quotes,
            "provider_count": len(quotes),
            "selection_reason": selection_reason,
            "quote_consensus": CatalogService._quote_consensus(quotes, str(selected.get("unit") or "USD")),
        }
        result = CatalogService._decorate_price(
            selected_payload,
            confidence="high" if selected.get("market") is not None else "medium",
        )
        return result

    @classmethod
    def _normalize_card(cls, card: dict[str, Any], language_code: str) -> dict[str, Any]:
        set_info = card.get("set") or {}
        counts = set_info.get("cardCount") or {}
        total = counts.get("total")
        official = counts.get("official")
        denominator = total or official
        local_id = str(card.get("localId") or "")
        number = f"{local_id}/{denominator}" if denominator else local_id

        raw_image = card.get("image")
        image_url = None
        if raw_image:
            raw_image = str(raw_image).rstrip("/")
            image_url = (
                raw_image
                if raw_image.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                else f"{raw_image}/high.webp"
            )

        return {
            "id": card.get("id"),
            "name": card.get("name"),
            "english_name": card.get("name") if language_code == "en" else None,
            "language_code": language_code,
            "collector_number": number,
            "local_id": local_id,
            "set_id": set_info.get("id"),
            "set_name": set_info.get("name"),
            "set_total": total,
            "set_official": official,
            "rarity": card.get("rarity"),
            "category": card.get("category"),
            "hp": card.get("hp"),
            "image": raw_image,
            "image_url": image_url,
            "reference_image_url": image_url,
            "pricing": cls._extract_price(card),
        }

    def _lookup_language(self, language_code: str, number: str) -> dict[str, Any]:
        cached = self._read_cache(language_code, number)
        if cached is not None:
            cached["source"] = "cache"
            if not getattr(self._prefetch_context, "active", False):
                key = f"{language_code}|{number}"
                with self._prefetch_lock:
                    saved_ms = self._prefetched_lookup_ms.pop(key, None)
                if saved_ms is not None:
                    with self._lock:
                        stats = dict(self._status.get("prediction_prefetch") or {})
                        stats["consumed"] = int(stats.get("consumed") or 0) + 1
                        stats["estimated_saved_ms"] = round(float(stats.get("estimated_saved_ms") or 0) + saved_ms, 1)
                        stats["last_saved_ms"] = round(saved_ms, 1)
                        stats["ready"] = len(self._prefetched_lookup_ms)
                        self._status["prediction_prefetch"] = stats
            return cached

        numerator, denominator = self._split_number(number)
        query = urllib.parse.urlencode({"localId": f"eq:{numerator}"})
        cards_url = f"{self.API_BASE}/{language_code}/cards?{query}"
        briefs = self._http_json(cards_url)

        if not isinstance(briefs, list):
            briefs = []

        details: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    self._http_json,
                    f"{self.API_BASE}/{language_code}/cards/{brief.get('id')}",
                ): brief
                for brief in briefs[:40]
                if brief.get("id")
            }
            for future in as_completed(futures):
                try:
                    card = future.result()
                except Exception:
                    continue
                if not isinstance(card, dict):
                    continue
                set_info = card.get("set") or {}
                counts = set_info.get("cardCount") or {}
                values = {str(counts.get("total")), str(counts.get("official"))}
                if denominator in values:
                    details.append(self._normalize_card(card, language_code))

        payload = {
            "source": "tcgdex",
            "language_code": language_code,
            "number": number,
            "candidates": details,
        }
        self._write_cache(language_code, number, payload)
        return payload

    def _lookup_name(
        self,
        language_code: str,
        name: str,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode({
            "name": f"eq:{name}",
        })

        cards_url = (
            f"{self.API_BASE}/{language_code}/cards?{query}"
        )

        briefs = self._http_json(cards_url)

        if not isinstance(briefs, list):
            briefs = []

        details: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    self._http_json,
                    (
                        f"{self.API_BASE}/{language_code}/cards/"
                        f"{brief.get('id')}"
                    ),
                ): brief
                for brief in briefs[:30]
                if brief.get("id")
            }

            for future in as_completed(futures):
                try:
                    card = future.result()
                except Exception:
                    continue

                if not isinstance(card, dict):
                    continue

                details.append(
                    self._normalize_card(
                        card,
                        language_code,
                    )
                )

        return {
            "source": "tcgdex",
            "language_code": language_code,
            "name": name,
            "candidates": details,
        }

    def _lookup_worker(self, language: str, number: str, name: str | None) -> None:
        started = time.perf_counter()
        try:
            language_codes = self.LANGUAGE_MAP.get(language, ["en"])
            all_candidates: list[dict[str, Any]] = []
            source = "tcgdex"
            notes: list[str] = []

            for code in language_codes:
                try:
                    if number and "/" in number:
                        result = self._lookup_language(
                            code,
                            number,
                        )
                    elif name:
                        result = self._lookup_name(
                            code,
                            name,
                        )
                    else:
                        continue

                    source = result.get("source") or source
                    all_candidates.extend(
                        result.get("candidates") or []
                    )
                except Exception as exc:
                    notes.append(f"{code}: {exc}")

            if language == "Chinese":
                notes.append(
                    "TCGdex currently lists Traditional Chinese, not Simplified Chinese; English fallback candidates may appear."
                )

            # Deduplicate by card id while preserving order.
            deduped: list[dict[str, Any]] = []
            seen: set[str] = set()
            for card in all_candidates:
                key = str(card.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                priced = self._apply_manual_price(card)
                deduped.append(self._record_price(priced))

            english_candidates = [
                card for card in deduped if card.get("language_code") == "en"
            ]
            local_candidates = [
                card for card in deduped if card.get("language_code") != "en"
            ]

            for card in local_candidates:
                partner = next(
                    (
                        english
                        for english in english_candidates
                        if english.get("collector_number") == card.get("collector_number")
                    ),
                    None,
                )
                if partner:
                    card["english_name"] = partner.get("name")
                    card["english_image_url"] = partner.get("image_url")
                    if not card.get("reference_image_url"):
                        card["reference_image_url"] = partner.get("image_url")

            ordered = local_candidates + english_candidates if local_candidates else english_candidates
            match = ordered[0] if len(ordered) == 1 else None
            payload = {
                "busy": False,
                "source": source,
                "query": {"language": language, "number": number, "name": name},
                "match": match,
                "candidates": ordered[:8],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": None,
                "note": " | ".join(notes) if notes else None,
            }

        except Exception as exc:
            payload = {
                "busy": False,
                "source": None,
                "query": {"language": language, "number": number, "name": name},
                "match": None,
                "candidates": [],
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": str(exc),
                "note": None,
            }

        with self._lock:
            self._busy = False
            self._status.update(payload)
            self._last_result = payload

        self.emit({"type": "catalog_update", "payload": payload})
