from __future__ import annotations

import io
import base64
import binascii
import json
import re
import threading
import time
import uuid
import calendar
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


MAX_RECEIPT_BYTES = 5 * 1024 * 1024
MAX_RECEIPT_BASE64_CHARS = ((MAX_RECEIPT_BYTES + 2) // 3) * 4
MAX_RECEIPT_DATA_URL_CHARS = MAX_RECEIPT_BASE64_CHARS + 128
RECEIPT_TYPES = {
    "application/pdf": (".pdf", b"%PDF-"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
}


class InventoryService:
    """Copy-level stock ledger with immutable sleeve IDs and auditable sales."""

    SCHEMA_VERSION = 8
    TAX_CATEGORIES = {"fees": "Commissions and fees", "shipping": "Shipping and postage", "supplies": "Office expense and supplies", "packs": "Cost of goods sold", "boxes": "Cost of goods sold", "other": "Other business expense"}

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}
        self._locked_allocations: dict[str, float] = {}
        self._expenses: dict[str, dict[str, Any]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._marketplace_sync_queue: list[dict[str, Any]] = []
        self._business_profile: dict[str, Any] = {"company_name": "RareIQ Business", "currency": "USD", "fiscal_year_start": 1, "reporting_basis": "cash"}
        self._period_closes: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            items = payload.get("items")
            if isinstance(items, dict):
                self._items = items
            locked = payload.get("locked_allocations")
            if isinstance(locked, dict):
                self._locked_allocations = {str(key): float(value) for key, value in locked.items()}
            expenses = payload.get("expenses")
            if isinstance(expenses, dict):
                self._expenses = expenses
            audit = payload.get("audit_log")
            if isinstance(audit, list): self._audit_log = audit[-5000:]
            sync_queue = payload.get("marketplace_sync_queue")
            if isinstance(sync_queue, list): self._marketplace_sync_queue = sync_queue[-5000:]
            profile = payload.get("business_profile")
            if isinstance(profile, dict): self._business_profile.update(profile)
            closes = payload.get("period_closes")
            if isinstance(closes, dict): self._period_closes = closes
        except (OSError, ValueError, TypeError):
            return

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_path.is_file():
            backup_dir = self.state_path.parent / "backups"; backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"inventory-{time.strftime('%Y-%m-%d')}.json"
            if not backup.exists(): shutil.copy2(self.state_path, backup)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps({"schema_version": self.SCHEMA_VERSION, "items": self._items, "locked_allocations": self._locked_allocations, "expenses": self._expenses, "audit_log": self._audit_log, "marketplace_sync_queue": self._marketplace_sync_queue, "business_profile": self._business_profile, "period_closes": self._period_closes}, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.state_path)

    def _audit(self, action: str, entity_type: str, entity_id: str, detail: dict[str, Any] | None = None) -> None:
        self._audit_log.append({"audit_id": f"AUD-{uuid.uuid4().hex[:12].upper()}", "timestamp": time.time(), "action": action, "entity_type": entity_type, "entity_id": entity_id, "detail": detail or {}})
        self._audit_log = self._audit_log[-5000:]

    def audit_log(self, limit: int = 200) -> dict[str, Any]:
        with self._lock: rows = [dict(row) for row in self._audit_log[-max(1, min(1000, int(limit))):]]
        return {"entries": list(reversed(rows)), "total": len(self._audit_log)}

    def _queue_marketplace_sync(self, item_id: str, channel: str, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time(); job = {"job_id": f"SYNC-{uuid.uuid4().hex[:12].upper()}", "created_at": now, "updated_at": now, "item_id": str(item_id or "").upper(), "channel": str(channel or "other")[:40], "operation": str(operation or "update")[:40], "payload": dict(payload or {}), "status": "pending_approval", "attempts": 0, "last_error": None, "simulated": True}
        self._marketplace_sync_queue.append(job); self._marketplace_sync_queue = self._marketplace_sync_queue[-5000:]
        return job

    def marketplace_sync_queue(self, limit: int = 200) -> dict[str, Any]:
        with self._lock: jobs = [dict(job) for job in reversed(self._marketplace_sync_queue[-max(1, min(1000, int(limit or 200))):])]
        counts = {state: sum(1 for job in jobs if job.get("status") == state) for state in ("pending_approval", "ready", "succeeded", "failed")}
        connectors = [{"channel": channel, "mode": "safe_simulation", "connected": False, "ready": True, "external_writes": False} for channel in ("ebay", "tcgplayer", "shopify", "whatnot", "other")]
        return {"jobs": jobs, "counts": counts, "connectors": connectors, "external_writes_enabled": False}

    def update_marketplace_sync_job(self, job_id: str, action: str, *, simulated_outcome: str = "success") -> dict[str, Any]:
        key = str(job_id or ""); now = time.time()
        with self._lock:
            job = next((row for row in self._marketplace_sync_queue if row.get("job_id") == key), None)
            if not job: return {"updated": False, "reason": "sync_job_not_found"}
            command = str(action or "")
            if command == "approve":
                if job.get("status") != "pending_approval": return {"updated": False, "reason": "job_not_pending_approval", "job": dict(job)}
                job.update({"status": "ready", "approved_at": now, "updated_at": now})
            elif command == "retry":
                if job.get("status") != "failed": return {"updated": False, "reason": "job_not_failed", "job": dict(job)}
                job.update({"status": "ready", "last_error": None, "updated_at": now})
            elif command == "simulate":
                if job.get("status") != "ready": return {"updated": False, "reason": "job_not_ready", "job": dict(job)}
                attempts = int(job.get("attempts") or 0) + 1
                if simulated_outcome == "failure": job.update({"status": "failed", "attempts": attempts, "last_error": "simulated_connector_failure", "updated_at": now})
                else: job.update({"status": "succeeded", "attempts": attempts, "completed_at": now, "last_error": None, "updated_at": now})
            else: return {"updated": False, "reason": "unsupported_action"}
            self._audit("inventory.marketplace_sync_updated", "marketplace_sync", key, {"action": command, "status": job.get("status"), "simulated": True}); self._persist()
            return {"updated": True, "job": dict(job)}

    def business_profile(self) -> dict[str, Any]:
        with self._lock: return dict(self._business_profile)

    def update_business_profile(self, **changes: Any) -> dict[str, Any]:
        allowed = {"company_name", "currency", "fiscal_year_start", "reporting_basis"}
        with self._lock:
            before = dict(self._business_profile)
            for key, value in changes.items():
                if key not in allowed or value is None: continue
                if key == "fiscal_year_start": value = max(1, min(12, int(value)))
                elif key == "currency": value = str(value or "USD").upper()[:8]
                elif key == "reporting_basis": value = value if value in {"cash", "accrual"} else "cash"
                else: value = str(value or "")[:120]
                self._business_profile[key] = value
            self._audit("business_profile.updated", "business_profile", "primary", {"before": before, "after": dict(self._business_profile)})
            self._persist(); return {"updated": True, "profile": dict(self._business_profile)}

    def backup_status(self) -> dict[str, Any]:
        backup_dir = self.state_path.parent / "backups"; backups = sorted(backup_dir.glob("inventory-*.json"), reverse=True) if backup_dir.is_dir() else []
        return {"automatic": True, "frequency": "daily_before_first_change", "count": len(backups), "latest": str(backups[0]) if backups else None}

    @staticmethod
    def _period_key(timestamp: float) -> str:
        return time.strftime("%Y-%m", time.localtime(timestamp))

    def period_closes(self) -> dict[str, Any]:
        with self._lock: rows = [dict(row) for row in self._period_closes.values()]
        return {"periods": sorted(rows, key=lambda row: row["period"], reverse=True)}

    def profit_and_loss(self, year: int, month: int) -> dict[str, Any]:
        selected_year=max(2000,min(2100,int(year))); selected_month=max(1,min(12,int(month)))
        summary=self.tax_summary(selected_year); row=dict(summary["months"][selected_month-1])
        row["gross_profit"]=round(row["revenue"]-row["card_cost"],2)
        row["selling_expenses"]=round(row["fees"]+row["shipping"],2)
        period=f"{selected_year:04d}-{selected_month:02d}"
        with self._lock: closed=dict(self._period_closes.get(period) or {})
        return {"period":period,"currency":summary["currency"],"company_name":self.business_profile()["company_name"],"closed":bool(closed),"close":closed or None,"statement":row}

    def close_period(self, year: int, month: int) -> dict[str, Any]:
        report=self.profit_and_loss(year,month); period=report["period"]
        current=time.strftime("%Y-%m")
        if period>=current: return {"closed":False,"reason":"period_not_finished"}
        with self._lock:
            if period in self._period_closes: return {"closed":False,"reason":"period_already_closed","period_close":dict(self._period_closes[period])}
            record={"period":period,"closed_at":time.time(),"statement":dict(report["statement"]),"currency":report["currency"]}
            self._period_closes[period]=record; self._audit("accounting.period_closed","accounting_period",period,{"net_income":report["statement"]["net_income"]}); self._persist()
            return {"closed":True,"period_close":dict(record)}

    def _is_period_closed(self, timestamp: float) -> bool:
        return self._period_key(timestamp) in self._period_closes

    @staticmethod
    def _money(value: Any, minimum: float = 0.0) -> float:
        return round(max(minimum, float(value or 0)), 2)

    @staticmethod
    def _item_id() -> str:
        return f"RIQ-{uuid.uuid4().hex[:12].upper()}"

    @staticmethod
    def _valuation_snapshot(card: dict[str, Any], captured_at: float) -> dict[str, Any] | None:
        pricing = card.get("pricing") if isinstance(card.get("pricing"), dict) else {}
        market = pricing.get("market", card.get("market_price"))
        resolution_id = pricing.get("resolution_id") or card.get("pricing_resolution_id")
        if market is None and not resolution_id:
            return None
        try:
            market_value = round(float(market), 2) if market is not None else None
        except (TypeError, ValueError):
            market_value = None
        return {"captured_at": captured_at, "resolution_id": resolution_id, "market": market_value,
            "currency": str(pricing.get("currency") or pricing.get("unit") or card.get("currency") or "USD")[:8],
            "provider": pricing.get("source") or pricing.get("provider") or card.get("pricing_source"),
            "quote_variant": pricing.get("variant") or card.get("variant") or "standard",
            "resolution_reason": pricing.get("resolution_reason"), "resolution_note": pricing.get("resolution_note"),
            "quote_updated_at": pricing.get("updated_at"),
            "verified": bool(pricing.get("verified", card.get("price_verified", False))),
            "valuation_eligible": bool(pricing.get("valuation_eligible", pricing.get("verified", False)))}

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["qr_value"] = item["item_id"]
        result["qr_url"] = f"/api/inventory/items/{item['item_id']}/qr.png"
        result["label_url"] = f"/api/inventory/items/{item['item_id']}/label.png"
        result["profile_url"] = f"/inventory/item/{item['item_id']}"
        result["active_listing"] = next((dict(listing) for listing in reversed(item.get("listings") or []) if listing.get("status") == "active"), None)
        return result

    def create(self, card: dict[str, Any], *, cost_basis: Any = 0, asking_price: Any = None, condition: str = "raw", location: str = "", notes: str = "", allocation_group: str = "", allocation_weight: Any = 1.0) -> dict[str, Any]:
        result = self.create_many(card, quantity=1, cost_basis=cost_basis, asking_price=asking_price, condition=condition, location=location, notes=notes, allocation_group=allocation_group, allocation_weight=allocation_weight)
        if not result.get("created"):
            return {"created": False, "reason": result.get("reason")}
        return {"created": True, "item": result["items"][0]}

    def create_many(self, card: dict[str, Any], *, quantity: int = 1, cost_basis: Any = 0, asking_price: Any = None, condition: str = "raw", location: str = "", notes: str = "", allocation_group: str = "", allocation_weight: Any = 1.0) -> dict[str, Any]:
        if not isinstance(card, dict) or not (card.get("english_name") or card.get("card_name")):
            return {"created": False, "reason": "card_identity_required"}
        try:
            count = int(quantity)
        except (TypeError, ValueError):
            return {"created": False, "reason": "invalid_quantity"}
        if count < 1 or count > 100:
            return {"created": False, "reason": "invalid_quantity"}
        now = time.time()
        valuation_snapshot = self._valuation_snapshot(card, now)
        batch_id = f"BATCH-{uuid.uuid4().hex[:10].upper()}"
        items = []
        with self._lock:
            group_key = str(allocation_group or "")[:120]
            if group_key and group_key in self._locked_allocations:
                return {"created": False, "reason": "allocation_group_locked"}
            for copy_number in range(1, count + 1):
                item_id = self._item_id()
                while item_id in self._items:
                    item_id = self._item_id()
                item = {
                    "item_id": item_id, "status": "in_stock", "created_at": now, "updated_at": now,
                    "batch_id": batch_id, "batch_copy_number": copy_number, "batch_quantity": count,
                    "version_key": card.get("version_key"), "card_name": card.get("card_name"),
                    "english_name": card.get("english_name") or card.get("card_name"), "printed_name": card.get("printed_name"),
                    "set_name": card.get("set_name"), "set_code": card.get("set_code") or card.get("set_id"),
                    "collector_number": card.get("collector_number"), "language": card.get("language"),
                    "rarity": card.get("rarity"), "reference_image_url": card.get("reference_image_url"),
                    "condition": str(condition or "raw")[:40], "location": str(location or "")[:100], "notes": str(notes or "")[:500],
                    "cost_basis": self._money(cost_basis), "asking_price": None if asking_price in (None, "") else self._money(asking_price),
                    "allocation_group": str(allocation_group or "")[:120], "allocation_weight": max(0.1, float(allocation_weight or 1.0)),
                    "currency": str(card.get("currency") or (valuation_snapshot or {}).get("currency") or "USD")[:8],
                    "pricing_resolution_id": (valuation_snapshot or {}).get("resolution_id"),
                    "acquisition_valuation": dict(valuation_snapshot) if valuation_snapshot else None, "listings": [], "sale": None,
                }
                self._items[item_id] = item
                items.append(item)
            self._audit("inventory.created", "inventory_batch", batch_id, {"quantity": count, "allocation_group": group_key})
            self._persist()
        return {"created": True, "batch_id": batch_id, "quantity": count, "items": [self._public(item) for item in items]}

    def rebalance_allocation(self, group: str, total_cost: Any, currency: str = "USD") -> dict[str, Any]:
        key = str(group or "")[:120]
        if not key:
            return {"rebalanced": False, "reason": "allocation_group_required"}
        with self._lock:
            if key in self._locked_allocations:
                return {"rebalanced": False, "reason": "allocation_group_locked", "locked_at": self._locked_allocations[key]}
            items = [item for item in self._items.values() if item.get("status") == "in_stock" and item.get("allocation_group") == key]
            if not items:
                return {"rebalanced": False, "reason": "allocation_group_not_found"}
            weights = [max(0.1, float(item.get("allocation_weight") or 1.0)) for item in items]
            total_weight, total = sum(weights), self._money(total_cost)
            allocated = 0.0
            for index, (item, weight) in enumerate(zip(items, weights)):
                share = round(total - allocated, 2) if index == len(items) - 1 else round(total * weight / total_weight, 2)
                allocated += share
                item["cost_basis"] = share; item["currency"] = str(currency or "USD")[:8]; item["updated_at"] = time.time()
            self._audit("allocation.rebalanced", "allocation_group", key, {"total_cost": total, "items": len(items), "currency": str(currency or "USD")[:8]})
            self._persist()
            return {"rebalanced": True, "group": key, "total_cost": total, "total_weight": total_weight, "items": [self._public(item) for item in items]}

    def lock_allocation(self, group: str) -> dict[str, Any]:
        key = str(group or "")[:120]
        if not key:
            return {"locked": False, "reason": "allocation_group_required"}
        with self._lock:
            items = [item for item in self._items.values() if item.get("allocation_group") == key]
            if not items:
                return {"locked": False, "reason": "allocation_group_not_found"}
            locked_at = self._locked_allocations.setdefault(key, time.time())
            self._audit("allocation.locked", "allocation_group", key, {"items": len(items), "locked_at": locked_at})
            self._persist()
            return {"locked": True, "group": key, "locked_at": locked_at, "items": [self._public(item) for item in items]}

    def allocation_snapshot(self, group: str) -> dict[str, Any]:
        key = str(group or "")[:120]
        with self._lock:
            items = [self._public(item) for item in self._items.values() if item.get("allocation_group") == key]
            return {"found": bool(items), "group": key, "locked": key in self._locked_allocations, "locked_at": self._locked_allocations.get(key), "items": items}

    def _expense_public(self, expense: dict[str, Any]) -> dict[str, Any]:
        result = dict(expense)
        result["receipt_url"] = (
            f"/api/inventory/expenses/{expense['expense_id']}/receipt"
            if self._safe_receipt_path(expense.get("receipt_file"))
            else None
        )
        return result

    def add_expense(self, category: str, amount: Any, currency: str = "USD", note: str = "", incurred_at: Any = None, recurrence: str = "none", receipt_name: str = "", receipt_data_url: str = "") -> dict[str, Any]:
        value = self._money(amount)
        if value <= 0:
            return {"created": False, "reason": "expense_amount_required"}
        now = time.time(); timestamp = float(incurred_at or now)
        if self._is_period_closed(timestamp): return {"created": False, "reason": "accounting_period_closed"}
        expense_id = f"EXP-{uuid.uuid4().hex[:12].upper()}"
        recurring = recurrence if recurrence in {"none", "weekly", "monthly", "annual"} else "none"
        category_key = str(category or "other")[:40]
        expense = {"expense_id": expense_id, "category": category_key, "tax_category": self.TAX_CATEGORIES.get(category_key, self.TAX_CATEGORIES["other"]), "amount": value, "currency": str(currency or "USD")[:8], "note": str(note or "")[:300], "incurred_at": timestamp, "created_at": now, "recurrence": recurring, "receipt_name": str(receipt_name or "")[:180], "receipt_file": None}
        if receipt_data_url:
            if "," not in receipt_data_url:
                return {"created": False, "reason": "receipt_invalid"}
            header, encoded = receipt_data_url.split(",", 1)
            media_type = header[5:].split(";", 1)[0].strip().lower() if header.lower().startswith("data:") else ""
            receipt_type = RECEIPT_TYPES.get(media_type)
            if not receipt_type or not header.lower().endswith(";base64"):
                return {"created": False, "reason": "receipt_unsupported_media_type"}
            if len(encoded) > MAX_RECEIPT_BASE64_CHARS:
                return {"created": False, "reason": "receipt_too_large", "max_bytes": MAX_RECEIPT_BYTES}
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                return {"created": False, "reason": "receipt_invalid"}
            if len(raw) > MAX_RECEIPT_BYTES:
                return {"created": False, "reason": "receipt_too_large", "max_bytes": MAX_RECEIPT_BYTES}
            extension, signature = receipt_type
            if not raw.startswith(signature):
                return {"created": False, "reason": "receipt_signature_mismatch"}
            receipt_dir = self.state_path.parent / "expense_receipts"; receipt_dir.mkdir(parents=True, exist_ok=True)
            receipt_file = f"{expense_id}{extension}"; (receipt_dir / receipt_file).write_bytes(raw); expense["receipt_file"] = receipt_file
        with self._lock:
            self._expenses[expense_id] = expense
            self._audit("expense.created", "expense", expense_id, {"category": category_key, "amount": value, "recurrence": recurring}); self._persist()
        return {"created": True, "expense": self._expense_public(expense)}

    def remove_expense(self, expense_id: str) -> dict[str, Any]:
        key = str(expense_id or "").upper()
        with self._lock:
            expense = self._expenses.pop(key, None)
            if not expense:
                return {"removed": False, "reason": "expense_not_found"}
            if self._is_period_closed(float(expense.get("incurred_at") or 0)):
                self._expenses[key]=expense; return {"removed":False,"reason":"accounting_period_closed"}
            receipt = expense.get("receipt_file")
            if receipt:
                try:
                    path = self._safe_receipt_path(receipt)
                    if path is not None:
                        path.unlink()
                except OSError: pass
            self._audit("expense.removed", "expense", key, {"category": expense.get("category"), "amount": expense.get("amount")}); self._persist(); return {"removed": True, "expense": self._expense_public(expense)}

    def update_expense(self, expense_id: str, **changes: Any) -> dict[str, Any]:
        key = str(expense_id or "").upper()
        with self._lock:
            expense = self._expenses.get(key)
            if not expense: return {"updated": False, "reason": "expense_not_found"}
            if self._is_period_closed(float(expense.get("incurred_at") or 0)): return {"updated":False,"reason":"accounting_period_closed"}
            if changes.get("amount") is not None:
                amount = self._money(changes["amount"])
                if amount <= 0: return {"updated": False, "reason": "expense_amount_required"}
                expense["amount"] = amount
            if changes.get("category") is not None:
                category = str(changes["category"] or "other")[:40]; expense["category"] = category; expense["tax_category"] = self.TAX_CATEGORIES.get(category, self.TAX_CATEGORIES["other"])
            if changes.get("note") is not None: expense["note"] = str(changes["note"] or "")[:300]
            if changes.get("recurrence") is not None and changes["recurrence"] in {"none", "weekly", "monthly", "annual"}: expense["recurrence"] = changes["recurrence"]
            if changes.get("incurred_at") is not None: expense["incurred_at"] = float(changes["incurred_at"])
            self._audit("expense.updated", "expense", key, {"changes": {key: value for key, value in changes.items() if value is not None}}); self._persist(); return {"updated": True, "expense": self._expense_public(expense)}

    def expense_receipt(self, expense_id: str) -> Path | None:
        with self._lock:
            expense = self._expenses.get(str(expense_id or "").upper()); receipt = (expense or {}).get("receipt_file")
        return self._safe_receipt_path(receipt)

    def _safe_receipt_path(self, receipt: Any) -> Path | None:
        name = str(receipt or "")
        if not name or Path(name).name != name:
            return None
        try:
            root = (self.state_path.parent / "expense_receipts").resolve()
            path = (root / name).resolve()
        except OSError:
            return None
        if path.parent != root or path.suffix.lower() not in {".jpg", ".png", ".pdf"}:
            return None
        return path if path.is_file() else None

    @staticmethod
    def _expense_occurrences(expense: dict[str, Any], start: float, end: float) -> list[float]:
        initial = float(expense.get("incurred_at") or 0); recurrence = expense.get("recurrence") or "none"
        if recurrence == "none":
            return [initial] if start <= initial <= end else []
        anchor = datetime.fromtimestamp(initial); current = anchor
        def advance(value: datetime) -> datetime:
            if recurrence == "weekly": return value + timedelta(days=7)
            if recurrence == "annual":
                day = min(anchor.day, calendar.monthrange(value.year + 1, anchor.month)[1]); return value.replace(year=value.year + 1, month=anchor.month, day=day)
            month_index = value.year * 12 + value.month; year, month_zero = divmod(month_index, 12); month = month_zero + 1
            day = min(anchor.day, calendar.monthrange(year, month)[1]); return value.replace(year=year, month=month, day=day)
        while current.timestamp() < start: current = advance(current)
        result = []
        while current.timestamp() <= end: result.append(current.timestamp()); current = advance(current)
        return result

    def business_trends(self, days: int = 30) -> dict[str, Any]:
        window = max(1, min(3650, int(days))); today = time.time(); start = today - window * 86400
        with self._lock:
            items = [dict(item) for item in self._items.values()]
            expenses = [dict(item) for item in self._expenses.values()]
        buckets: dict[str, dict[str, Any]] = {}
        def bucket(timestamp: float) -> dict[str, Any]:
            key = time.strftime("%Y-%m-%d", time.localtime(timestamp))
            return buckets.setdefault(key, {"date": key, "revenue": 0.0, "card_profit": 0.0, "expenses": 0.0, "operating_net": 0.0})
        for item in items:
            sale = item.get("sale") or {}; sold_at = float(sale.get("sold_at") or 0)
            if sold_at >= start:
                row = bucket(sold_at); row["revenue"] += float(sale.get("gross") or 0); row["card_profit"] += float(sale.get("profit") or 0)
        for expense in expenses:
            if str(expense.get("currency") or "USD") == "USD":
                for incurred in self._expense_occurrences(expense, start, today): bucket(incurred)["expenses"] += float(expense.get("amount") or 0)
        rows = []
        for row in sorted(buckets.values(), key=lambda value: value["date"]):
            row = {key: round(value, 2) if isinstance(value, float) else value for key, value in row.items()}; row["operating_net"] = round(row["card_profit"] - row["expenses"], 2); rows.append(row)
        relevant_expenses = [self._expense_public(item) for item in expenses if self._expense_occurrences(item, start, today)]
        totals = {"revenue": round(sum(row["revenue"] for row in rows), 2), "card_profit": round(sum(row["card_profit"] for row in rows), 2), "expenses": round(sum(row["expenses"] for row in rows), 2), "operating_net": round(sum(row["operating_net"] for row in rows), 2)}
        return {"days": window, "currency": "USD", "rows": rows, "totals": totals, "expenses": sorted(relevant_expenses, key=lambda item: -float(item.get("incurred_at") or 0))}

    def tax_summary(self, year: int) -> dict[str, Any]:
        selected = max(2000, min(2100, int(year))); start = time.mktime((selected, 1, 1, 0, 0, 0, 0, 1, -1)); end = time.mktime((selected + 1, 1, 1, 0, 0, 0, 0, 1, -1)) - 1
        with self._lock: items = [dict(item) for item in self._items.values()]; expenses = [dict(item) for item in self._expenses.values()]
        months = [{"month": index, "revenue": 0.0, "fees": 0.0, "shipping": 0.0, "card_cost": 0.0, "operating_expenses": 0.0, "net_income": 0.0} for index in range(1, 13)]
        for item in items:
            sale = item.get("sale") or {}; sold_at = float(sale.get("sold_at") or 0)
            if start <= sold_at <= end:
                row = months[time.localtime(sold_at).tm_mon - 1]; row["revenue"] += float(sale.get("gross") or 0); row["fees"] += float(sale.get("fees") or 0); row["shipping"] += float(sale.get("shipping_cost") or 0) + float(sale.get("packaging_cost") or 0); row["card_cost"] += float(item.get("cost_basis") or 0)
        for expense in expenses:
            if str(expense.get("currency") or "USD") == "USD":
                for occurred in self._expense_occurrences(expense, start, end): months[time.localtime(occurred).tm_mon - 1]["operating_expenses"] += float(expense.get("amount") or 0)
        for row in months:
            row["net_income"] = row["revenue"] - row["fees"] - row["shipping"] - row["card_cost"] - row["operating_expenses"]
            for key in row:
                if key != "month": row[key] = round(row[key], 2)
        totals = {key: round(sum(row[key] for row in months), 2) for key in ("revenue", "fees", "shipping", "card_cost", "operating_expenses", "net_income")}
        deductions: dict[str, float] = {}
        for expense in expenses:
            occurrences = self._expense_occurrences(expense, start, end)
            if occurrences: deductions[expense.get("tax_category") or self.TAX_CATEGORIES["other"]] = round(deductions.get(expense.get("tax_category") or self.TAX_CATEGORIES["other"], 0) + float(expense.get("amount") or 0) * len(occurrences), 2)
        return {"year": selected, "currency": "USD", "months": months, "totals": totals, "deductions_by_tax_category": deductions}

    def tax_comparison(self, year: int) -> dict[str, Any]:
        current = self.tax_summary(year); previous = self.tax_summary(int(year) - 1)
        keys = ("revenue", "fees", "shipping", "card_cost", "operating_expenses", "net_income")
        changes = {key: round(current["totals"][key] - previous["totals"][key], 2) for key in keys}
        percentages = {key: (round(changes[key] / abs(previous["totals"][key]) * 100, 1) if previous["totals"][key] else None) for key in keys}
        return {"year": current["year"], "current": current["totals"], "previous": previous["totals"], "changes": changes, "change_percent": percentages, "currency": "USD"}

    def get(self, item_id: str) -> dict[str, Any] | None:
        key = str(item_id or "").upper()
        with self._lock:
            item = self._items.get(key)
            return self._public(item) if item else None

    @staticmethod
    def sell_recommendation(item: dict[str, Any], current_market: Any = None, *, fee_percent: Any = 13.25, shipping_cost: Any = 0, packaging_cost: Any = 0, desired_profit_percent: Any = 25) -> dict[str, Any]:
        cost = max(0.0, float(item.get("cost_basis") or 0))
        fee_rate = min(0.95, max(0.0, float(fee_percent or 0) / 100))
        shipping = max(0.0, float(shipping_cost or 0))
        packaging = max(0.0, float(packaging_cost or 0))
        margin = max(0.0, float(desired_profit_percent or 0) / 100)
        fulfillment = shipping + packaging
        break_even = round((cost + fulfillment) / (1 - fee_rate), 2)
        target = round((cost * (1 + margin) + fulfillment) / (1 - fee_rate), 2)
        market = float(current_market) if isinstance(current_market, (int, float)) else None
        recommended = max(target, market) if market is not None else target
        expected_fees = round(recommended * fee_rate, 2)
        expected_net = round(recommended - expected_fees - fulfillment, 2)
        expected_profit = round(expected_net - cost, 2)
        return {"currency": str(item.get("currency") or "USD"), "cost_basis": cost, "verified_market": market, "fee_percent": round(fee_rate * 100, 2), "shipping_cost": shipping, "packaging_cost": packaging, "fulfillment_cost": round(fulfillment, 2), "desired_profit_percent": round(margin * 100, 2), "break_even_price": break_even, "target_price": target, "recommended_price": round(recommended, 2), "expected_fees": expected_fees, "expected_net": expected_net, "expected_profit": expected_profit, "market_premium": round(recommended - market, 2) if market is not None else None}

    def update_listing(self, item_id: str, *, action: str, channel: str = "other", listing_id: str = "", listing_url: str = "", asking_price: Any = None) -> dict[str, Any]:
        key = str(item_id or "").upper(); now = time.time()
        with self._lock:
            item = self._items.get(key)
            if not item: return {"updated": False, "reason": "item_not_found"}
            listings = item.setdefault("listings", [])
            if str(action) == "end":
                match = next((listing for listing in reversed(listings) if listing.get("status") == "active" and (not listing_id or listing.get("listing_id") == str(listing_id)[:160])), None)
                if not match: return {"updated": False, "reason": "active_listing_not_found", "item": self._public(item)}
                match.update({"status": "ended", "ended_at": now}); event = "inventory.listing_ended"
            else:
                if item.get("status") != "in_stock": return {"updated": False, "reason": "item_not_in_stock", "item": self._public(item)}
                for listing in listings:
                    if listing.get("status") == "active" and listing.get("channel") == str(channel): listing.update({"status": "ended", "ended_at": now, "end_reason": "replaced"})
                match = {"listing_record_id": f"LST-{uuid.uuid4().hex[:12].upper()}", "status": "active", "channel": str(channel or "other")[:40], "listing_id": str(listing_id or "")[:160], "listing_url": str(listing_url or "")[:500], "asking_price": None if asking_price in (None, "") else self._money(asking_price), "listed_at": now}
                listings.append(match); event = "inventory.listing_activated"
            item["updated_at"] = now; self._audit(event, "inventory_item", key, {"channel": match.get("channel"), "listing_id": match.get("listing_id")}); self._queue_marketplace_sync(key, match.get("channel") or channel, "end" if str(action) == "end" else "activate", {"listing_id": match.get("listing_id"), "listing_url": match.get("listing_url"), "asking_price": match.get("asking_price")}); self._persist()
            return {"updated": True, "listing": dict(match), "item": self._public(item)}

    def bulk_update_listings(self, item_ids: list[str], *, action: str, price_adjustment_percent: Any = 0) -> dict[str, Any]:
        operation = str(action or "").lower()
        if operation not in {"end", "reprice"}:
            return {"ok": False, "reason": "unsupported_action", "updated": 0, "results": []}
        adjustment = max(-95.0, min(1000.0, float(price_adjustment_percent or 0)))
        results, seen = [], set()
        for raw_item_id in list(item_ids or [])[:500]:
            item_id = str(raw_item_id or "").upper()
            if not item_id or item_id in seen: continue
            seen.add(item_id)
            item = self.get(item_id)
            listing = (item or {}).get("active_listing")
            if not item:
                results.append({"item_id": item_id, "updated": False, "reason": "item_not_found"}); continue
            if not listing:
                results.append({"item_id": item_id, "updated": False, "reason": "active_listing_not_found"}); continue
            if operation == "end":
                result = self.update_listing(item_id, action="end", channel=listing.get("channel") or "other", listing_id=listing.get("listing_id") or "")
            else:
                current = listing.get("asking_price") if isinstance(listing.get("asking_price"), (int, float)) else item.get("asking_price")
                if not isinstance(current, (int, float)):
                    results.append({"item_id": item_id, "updated": False, "reason": "asking_price_unavailable"}); continue
                new_price = round(max(0.0, float(current) * (1 + adjustment / 100)), 2)
                with self._lock:
                    stored = self._items.get(item_id); active = next((entry for entry in reversed((stored or {}).get("listings", [])) if entry.get("status") == "active"), None)
                    if not active:
                        result = {"updated": False, "reason": "active_listing_not_found"}
                    else:
                        previous = active.get("asking_price"); now = time.time(); active.update({"asking_price": new_price, "repriced_at": now}); stored["asking_price"] = new_price; stored["updated_at"] = now
                        self._audit("inventory.listing_repriced", "inventory_item", item_id, {"channel": active.get("channel"), "previous_price": previous, "asking_price": new_price, "adjustment_percent": adjustment}); self._queue_marketplace_sync(item_id, active.get("channel") or "other", "reprice", {"listing_id": active.get("listing_id"), "previous_price": previous, "asking_price": new_price}); self._persist()
                        result = {"updated": True, "listing": dict(active), "item": self._public(stored), "previous_price": previous, "asking_price": new_price}
            results.append({"item_id": item_id, **result})
        updated = sum(1 for result in results if result.get("updated"))
        return {"ok": True, "action": operation, "requested": len(seen), "updated": updated, "failed": len(results) - updated, "price_adjustment_percent": adjustment if operation == "reprice" else None, "results": results}

    def apply_listing_price_targets(self, targets: list[dict[str, Any]]) -> dict[str, Any]:
        results, seen = [], set()
        for target in list(targets or [])[:500]:
            item_id = str((target or {}).get("item_id") or "").upper()
            if not item_id or item_id in seen: continue
            seen.add(item_id)
            try: new_price = self._money((target or {}).get("asking_price"))
            except (TypeError, ValueError):
                results.append({"item_id": item_id, "updated": False, "reason": "invalid_asking_price"}); continue
            with self._lock:
                stored = self._items.get(item_id); active = next((entry for entry in reversed((stored or {}).get("listings", [])) if entry.get("status") == "active"), None)
                if not stored:
                    results.append({"item_id": item_id, "updated": False, "reason": "item_not_found"}); continue
                if not active:
                    results.append({"item_id": item_id, "updated": False, "reason": "active_listing_not_found"}); continue
                previous = active.get("asking_price"); now = time.time(); active.update({"asking_price": new_price, "repriced_at": now, "reprice_source": "smart_reprice"}); stored["asking_price"] = new_price; stored["updated_at"] = now
                detail = {"channel": active.get("channel"), "previous_price": previous, "asking_price": new_price, "expected_profit": (target or {}).get("expected_profit"), "profit_delta": (target or {}).get("profit_delta"), "verified_market": (target or {}).get("verified_market"), "sync_status": "local_only"}
                self._audit("inventory.listing_smart_repriced", "inventory_item", item_id, detail); self._queue_marketplace_sync(item_id, active.get("channel") or "other", "reprice", {"listing_id": active.get("listing_id"), "previous_price": previous, "asking_price": new_price, "smart": True}); self._persist()
                results.append({"item_id": item_id, "updated": True, "previous_price": previous, "asking_price": new_price, "listing": dict(active)})
        updated = sum(1 for row in results if row.get("updated"))
        return {"ok": True, "requested": len(seen), "updated": updated, "failed": len(results) - updated, "results": results}

    def listing_reprice_history(self, limit: int = 100) -> dict[str, Any]:
        actions = {"inventory.listing_repriced", "inventory.listing_smart_repriced"}
        with self._lock:
            rolled_back = {str((entry.get("detail") or {}).get("source_audit_id")) for entry in self._audit_log if entry.get("action") == "inventory.listing_reprice_rolled_back"}
            entries = []
            for entry in reversed(self._audit_log):
                if entry.get("action") not in actions: continue
                detail = dict(entry.get("detail") or {}); item = self._items.get(str(entry.get("entity_id") or "").upper()); active = next((listing for listing in reversed((item or {}).get("listings", [])) if listing.get("status") == "active"), None)
                current = active.get("asking_price") if active else None; target = detail.get("asking_price")
                available = entry.get("audit_id") not in rolled_back and active is not None and isinstance(current, (int, float)) and isinstance(target, (int, float)) and abs(float(current) - float(target)) < .005
                entries.append({**dict(entry), "detail": detail, "card_name": (item or {}).get("english_name") or (item or {}).get("card_name"), "current_price": current, "rollback_available": available, "sync_status": detail.get("sync_status") or "local_only"})
                if len(entries) >= max(1, min(500, int(limit or 100))): break
        return {"entries": entries, "total": len(entries)}

    def rollback_listing_reprice(self, audit_id: str) -> dict[str, Any]:
        source_id = str(audit_id or "")
        with self._lock:
            source = next((entry for entry in self._audit_log if entry.get("audit_id") == source_id and entry.get("action") in {"inventory.listing_repriced", "inventory.listing_smart_repriced"}), None)
            if not source: return {"rolled_back": False, "reason": "reprice_event_not_found"}
            if any((entry.get("detail") or {}).get("source_audit_id") == source_id for entry in self._audit_log if entry.get("action") == "inventory.listing_reprice_rolled_back"): return {"rolled_back": False, "reason": "already_rolled_back"}
            item_id = str(source.get("entity_id") or "").upper(); item = self._items.get(item_id); active = next((listing for listing in reversed((item or {}).get("listings", [])) if listing.get("status") == "active"), None); detail = source.get("detail") or {}
            if not item or not active: return {"rolled_back": False, "reason": "active_listing_not_found"}
            current, expected = active.get("asking_price"), detail.get("asking_price")
            if not isinstance(current, (int, float)) or not isinstance(expected, (int, float)) or abs(float(current) - float(expected)) >= .005: return {"rolled_back": False, "reason": "newer_price_exists", "current_price": current}
            previous = detail.get("previous_price")
            if not isinstance(previous, (int, float)): return {"rolled_back": False, "reason": "previous_price_unavailable"}
            restored = self._money(previous); now = time.time(); active.update({"asking_price": restored, "repriced_at": now, "reprice_source": "rollback"}); item["asking_price"] = restored; item["updated_at"] = now
            self._audit("inventory.listing_reprice_rolled_back", "inventory_item", item_id, {"source_audit_id": source_id, "previous_price": current, "asking_price": restored, "sync_status": "local_only"}); self._queue_marketplace_sync(item_id, active.get("channel") or "other", "reprice_rollback", {"listing_id": active.get("listing_id"), "previous_price": current, "asking_price": restored}); self._persist()
            return {"rolled_back": True, "item": self._public(item), "asking_price": restored, "source_audit_id": source_id}

    def sell(self, item_id: str, *, sale_price: Any, fees: Any = 0, shipping_cost: Any = 0, packaging_cost: Any = 0, channel: str = "", order_reference: str = "") -> dict[str, Any]:
        key = str(item_id or "").upper()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return {"sold": False, "reason": "item_not_found"}
            if item.get("status") != "in_stock":
                return {"sold": False, "reason": "item_not_in_stock", "item": self._public(item)}
            gross = self._money(sale_price)
            fee_total = self._money(fees)
            shipping = self._money(shipping_cost)
            packaging = self._money(packaging_cost)
            cost = self._money(item.get("cost_basis"))
            sold_at = time.time()
            item["status"] = "sold"; item["updated_at"] = sold_at
            for listing in item.setdefault("listings", []):
                if listing.get("status") == "active": listing.update({"status": "sold", "ended_at": sold_at, "end_reason": "inventory_sold"})
            acquisition = item.get("acquisition_valuation") if isinstance(item.get("acquisition_valuation"), dict) else {}
            item["sale"] = {"gross": gross, "fees": fee_total, "shipping_cost": shipping, "packaging_cost": packaging, "net_proceeds": round(gross-fee_total-shipping-packaging, 2), "profit": round(gross-fee_total-shipping-packaging-cost, 2), "channel": str(channel or "")[:80], "order_reference": str(order_reference or "")[:120], "sold_at": sold_at, "pricing_resolution_id": item.get("pricing_resolution_id"), "acquisition_market": acquisition.get("market"), "acquisition_market_currency": acquisition.get("currency"), "acquisition_market_provider": acquisition.get("provider")}
            self._audit("inventory.sold", "inventory_item", key, {"gross": gross, "fees": fee_total, "shipping": shipping, "packaging": packaging, "profit": item["sale"]["profit"]})
            self._persist()
            return {"sold": True, "item": self._public(item)}

    def void_sale(self, item_id: str, reason: str = "operator_void") -> dict[str, Any]:
        key = str(item_id or "").upper()
        with self._lock:
            item = self._items.get(key)
            if not item:
                return {"voided": False, "reason": "item_not_found"}
            if item.get("status") != "sold" or not isinstance(item.get("sale"), dict):
                return {"voided": False, "reason": "item_not_sold", "item": self._public(item)}
            now = time.time()
            history = item.setdefault("sale_history", [])
            history.append(dict(item["sale"]) | {"voided_at": now, "void_reason": str(reason or "operator_void")[:200]})
            item["sale"] = None; item["status"] = "in_stock"; item["updated_at"] = now
            self._audit("inventory.sale_voided", "inventory_item", key, {"reason": str(reason or "operator_void")[:200]})
            self._persist()
            return {"voided": True, "item": self._public(item)}

    def sales_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            sold = [dict(item) for item in self._items.values() if item.get("status") == "sold" and isinstance(item.get("sale"), dict)]
        rows = []
        for item in sold:
            sale = item["sale"]
            rows.append({"item_id": item["item_id"], "card_name": item.get("english_name") or item.get("card_name"), "set_name": item.get("set_name") or item.get("set_code"), "collector_number": item.get("collector_number"), "cost_basis": item.get("cost_basis"), "gross_sale": sale.get("gross"), "fees": sale.get("fees"), "shipping_cost": sale.get("shipping_cost"), "packaging_cost": sale.get("packaging_cost"), "net_proceeds": sale.get("net_proceeds"), "profit": sale.get("profit"), "channel": sale.get("channel"), "order_reference": sale.get("order_reference"), "sold_at": sale.get("sold_at"), "currency": item.get("currency"), "pricing_resolution_id": item.get("pricing_resolution_id"), "acquisition_market": sale.get("acquisition_market"), "acquisition_market_currency": sale.get("acquisition_market_currency"), "acquisition_market_provider": sale.get("acquisition_market_provider")})
        return sorted(rows, key=lambda row: -float(row.get("sold_at") or 0))

    def dashboard(self) -> dict[str, Any]:
        with self._lock:
            items = [self._public(item) for item in self._items.values()]
        stock = [item for item in items if item["status"] == "in_stock"]
        sold = [item for item in items if item["status"] == "sold"]
        return {"items": sorted(items, key=lambda item: -float(item["updated_at"])), "in_stock": len(stock), "sold_count": len(sold), "inventory_cost": round(sum(float(item.get("cost_basis") or 0) for item in stock), 2), "asking_value": round(sum(float(item.get("asking_price") or 0) for item in stock), 2), "gross_sales": round(sum(float((item.get("sale") or {}).get("gross") or 0) for item in sold), 2), "net_profit": round(sum(float((item.get("sale") or {}).get("profit") or 0) for item in sold), 2)}

    def listing_dashboard(self, stale_days: int = 30) -> dict[str, Any]:
        threshold_days = max(1, min(365, int(stale_days or 30))); now = time.time()
        with self._lock: items = [self._public(item) for item in self._items.values() if item.get("status") == "in_stock"]
        rows: list[dict[str, Any]] = []
        exposure: dict[str, dict[str, Any]] = {}
        for item in items:
            listing = item.get("active_listing")
            if not listing: continue
            age_days = max(0.0, (now - float(listing.get("listed_at") or now)) / 86400)
            asking = listing.get("asking_price") if isinstance(listing.get("asking_price"), (int, float)) else item.get("asking_price")
            channel = str(listing.get("channel") or "other")
            bucket = exposure.setdefault(channel, {"channel": channel, "active": 0, "asking_value": 0.0})
            bucket["active"] += 1
            if isinstance(asking, (int, float)): bucket["asking_value"] += float(asking)
            rows.append({"item_id": item["item_id"], "card_name": item.get("english_name") or item.get("card_name"), "set_name": item.get("set_name") or item.get("set_code"), "collector_number": item.get("collector_number"), "channel": channel, "listing_id": listing.get("listing_id"), "listing_url": listing.get("listing_url"), "asking_price": asking, "currency": item.get("currency") or "USD", "listed_at": listing.get("listed_at"), "age_days": round(age_days, 1), "stale": age_days >= threshold_days, "profile_url": item.get("profile_url")})
        rows.sort(key=lambda row: (-int(row["stale"]), -float(row["age_days"])))
        channels = [{**row, "asking_value": round(float(row["asking_value"]), 2)} for row in exposure.values()]
        channels.sort(key=lambda row: (-row["active"], row["channel"]))
        listed_ids = {row["item_id"] for row in rows}
        return {"stale_days": threshold_days, "active": len(rows), "stale": sum(1 for row in rows if row["stale"]), "unlisted": len(items) - len(listed_ids), "asking_exposure": round(sum(float(row["asking_value"]) for row in channels), 2), "currency": "USD", "channels": channels, "listings": rows}

    def qr_png(self, item_id: str, scale: int = 8) -> bytes | None:
        item = self.get(item_id)
        if not item:
            return None
        import cv2
        from PIL import Image
        matrix = cv2.QRCodeEncoder_create().encode(item["item_id"])
        image = Image.fromarray(matrix).convert("L").resize((matrix.shape[1] * scale, matrix.shape[0] * scale), Image.Resampling.NEAREST)
        output = io.BytesIO(); image.save(output, format="PNG"); return output.getvalue()

    def label_png(self, item_id: str) -> bytes | None:
        item = self.get(item_id)
        if not item:
            return None
        from PIL import Image, ImageDraw, ImageFont
        qr = Image.open(io.BytesIO(self.qr_png(item_id, 6))).convert("RGB")
        canvas = Image.new("RGB", (700, 260), "white"); canvas.paste(qr.resize((220, 220)), (20, 20))
        draw = ImageDraw.Draw(canvas); font = ImageFont.load_default(size=24); small = ImageFont.load_default(size=18)
        name = re.sub(r"\s+", " ", str(item.get("english_name") or "Unknown card"))[:30]
        draw.text((265, 28), name, fill="black", font=font); draw.text((265, 72), f"{item.get('set_name') or item.get('set_code') or '--'}  #{item.get('collector_number') or '--'}", fill="black", font=small)
        draw.text((265, 112), item["item_id"], fill="black", font=font); draw.text((265, 158), f"Cost ${float(item.get('cost_basis') or 0):.2f}  Ask {('$%.2f' % item['asking_price']) if item.get('asking_price') is not None else '--'}", fill="black", font=small)
        output = io.BytesIO(); canvas.save(output, format="PNG"); return output.getvalue()
