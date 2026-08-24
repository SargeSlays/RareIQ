from __future__ import annotations
from dataclasses import asdict
from typing import Any
import json
import os
import tempfile
import time
from pathlib import Path

from rareiq.models.session import BreakSession, CardPull


class SessionService:
    ATOMIC_REPLACE_ATTEMPTS = 5
    ATOMIC_REPLACE_RETRY_SECONDS = 0.02

    def __init__(self, archive_dir: Path | None = None) -> None:
        self.archive_dir = archive_dir
        if self.archive_dir:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.rejected: list[dict[str, Any]] = []
        self.last_added_signature: str | None = None
        self.last_added_at = 0.0
        self.state_path = (
            self.archive_dir / "active_session.json"
            if self.archive_dir
            else None
        )
        self.current = self._load_active_session() or BreakSession.create(
            customer="Demo Customer",
            order_number="RIQ-0001",
            product_name="Greninja Jumbo Box",
            boxes_total=1,
            packs_per_box=5,
        )
        self._persist_active()

    def _load_active_session(self) -> BreakSession | None:
        if not self.state_path or not self.state_path.exists():
            return None
        try:
            payload = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
            return BreakSession.from_public(payload)
        except Exception:
            return None

    def _persist_active(self) -> None:
        if not self.state_path:
            return
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    self.current.public(),
                    temporary,
                    indent=2,
                    ensure_ascii=False,
                )
                temporary.flush()
                os.fsync(temporary.fileno())
            for attempt in range(self.ATOMIC_REPLACE_ATTEMPTS):
                try:
                    os.replace(temporary_path, self.state_path)
                    break
                except PermissionError:
                    if attempt + 1 >= self.ATOMIC_REPLACE_ATTEMPTS:
                        raise
                    time.sleep(self.ATOMIC_REPLACE_RETRY_SECONDS * (attempt + 1))
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def start(
        self,
        customer: str,
        order_number: str,
        product_name: str,
        boxes_total: int,
        packs_per_box: int,
    ) -> dict[str, Any]:
        self.current = BreakSession.create(
            customer=customer,
            order_number=order_number,
            product_name=product_name,
            boxes_total=boxes_total,
            packs_per_box=packs_per_box,
        )
        self._persist_active()
        return self.current.public()

    def next_pack(self) -> dict[str, Any]:
        box = self.current.active_box
        if box.active_pack_index + 1 < box.packs_total:
            box.active_pack_index += 1
            box.ensure_pack()
        elif self.current.active_box_index + 1 < self.current.boxes_total:
            self.current.active_box_index += 1
            self.current.ensure_box()
        self._persist_active()
        return self.current.public()

    def previous_pack(self) -> dict[str, Any]:
        box = self.current.active_box
        if box.active_pack_index > 0:
            box.active_pack_index -= 1
        elif self.current.active_box_index > 0:
            self.current.active_box_index -= 1
            previous_box = self.current.active_box
            previous_box.active_pack_index = max(0, previous_box.packs_total - 1)
            previous_box.ensure_pack()
        self._persist_active()
        return self.current.public()

    def next_box(self) -> dict[str, Any]:
        if self.current.active_box_index + 1 < self.current.boxes_total:
            self.current.active_box_index += 1
            self.current.ensure_box()
        self._persist_active()
        return self.current.public()

    def previous_box(self) -> dict[str, Any]:
        if self.current.active_box_index > 0:
            self.current.active_box_index -= 1
        self._persist_active()
        return self.current.public()

    def add_card(self, card: dict[str, Any]) -> dict[str, Any]:
        signature = str(card.get("recognition_signature") or "")
        now = time.time()
        if (
            signature
            and signature == self.last_added_signature
            and now - self.last_added_at < 30.0
        ):
            snapshot = self.current.public()
            snapshot["duplicate_suppressed"] = True
            return snapshot

        pull = CardPull.create(
            card_name=card["card_name"],
            rarity=card.get("rarity") or "UNKNOWN",
            raw_value=float(card.get("raw_value") or 0.0),
            confidence=float(card.get("confidence", 1.0)),
            collector_number=card.get("collector_number"),
            language=card.get("language"),
            set_name=card.get("set_name"),
            source=card.get("source"),
            reference_image_url=card.get("reference_image_url"),
            recognition_signature=signature or None,
            printed_name=card.get("printed_name"),
            english_name=card.get("english_name"),
        )
        self.current.active_box.active_pack.pulls.append(pull)
        self.last_added_signature = signature or None
        self.last_added_at = now
        snapshot = self.current.public()
        snapshot["last_added_card"] = asdict(pull)
        snapshot["duplicate_suppressed"] = False
        self._persist_active()
        return snapshot

    def reject_card(self, card: dict[str, Any]) -> dict[str, Any]:
        rejected = dict(card)
        rejected["rejected_at"] = time.time()
        self.rejected.append(rejected)
        self._persist_active()
        return {
            "session": self.current.public(),
            "rejected": rejected,
            "rejected_count": len(self.rejected),
        }

    def recent_cards(self, limit: int = 8) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for box in self.current.boxes:
            for pack in box.packs:
                cards.extend(asdict(card) for card in pack.pulls)
        cards.sort(key=lambda item: item.get("timestamp", 0), reverse=True)
        return cards[:max(1, int(limit))]

    def export(self) -> dict[str, Any]:
        payload = self.current.public()
        payload["recent_cards"] = self.recent_cards(1000)
        payload["rejected"] = list(self.rejected)
        return payload

    def archive(self) -> Path | None:
        if not self.archive_dir:
            return None
        payload = self.export()
        safe_order = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in (self.current.order_number or "session")
        )
        path = self.archive_dir / f"{safe_order}_{int(time.time())}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def undo(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        pulls = self.current.active_box.active_pack.pulls
        removed = asdict(pulls.pop()) if pulls else None
        self._persist_active()
        return self.current.public(), removed

    def close(self) -> dict[str, Any]:
        self.current.closed = True
        path = self.archive()
        snapshot = self.current.public()
        snapshot["archive_path"] = str(path) if path else None
        self._persist_active()
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        return self.current.public()
