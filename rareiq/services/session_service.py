from __future__ import annotations
from dataclasses import asdict
from typing import Any

from rareiq.models.session import BreakSession, CardPull


class SessionService:
    def __init__(self) -> None:
        self.current = BreakSession.create(
            customer="Demo Customer",
            order_number="RIQ-0001",
            product_name="Greninja Jumbo Box",
            boxes_total=1,
            packs_per_box=5,
        )

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
        return self.current.public()

    def next_pack(self) -> dict[str, Any]:
        box = self.current.active_box
        if box.active_pack_index + 1 < box.packs_total:
            box.active_pack_index += 1
            box.ensure_pack()
        elif self.current.active_box_index + 1 < self.current.boxes_total:
            self.current.active_box_index += 1
            self.current.ensure_box()
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
        return self.current.public()

    def next_box(self) -> dict[str, Any]:
        if self.current.active_box_index + 1 < self.current.boxes_total:
            self.current.active_box_index += 1
            self.current.ensure_box()
        return self.current.public()

    def previous_box(self) -> dict[str, Any]:
        if self.current.active_box_index > 0:
            self.current.active_box_index -= 1
        return self.current.public()

    def add_card(self, card: dict[str, Any]) -> dict[str, Any]:
        pull = CardPull.create(
            card_name=card["card_name"],
            rarity=card["rarity"],
            raw_value=float(card["raw_value"]),
            confidence=float(card.get("confidence", 1.0)),
        )
        self.current.active_box.active_pack.pulls.append(pull)
        return self.current.public()

    def undo(self) -> tuple[dict[str, Any], dict[str, Any] | None]:
        pulls = self.current.active_box.active_pack.pulls
        removed = asdict(pulls.pop()) if pulls else None
        return self.current.public(), removed

    def close(self) -> dict[str, Any]:
        self.current.closed = True
        return self.current.public()

    def snapshot(self) -> dict[str, Any]:
        return self.current.public()
