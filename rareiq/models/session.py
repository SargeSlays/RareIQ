from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
import time
import uuid


@dataclass
class CardPull:
    id: str
    card_name: str
    rarity: str
    raw_value: float
    confidence: float
    timestamp: float

    @classmethod
    def create(cls, card_name: str, rarity: str, raw_value: float, confidence: float = 1.0) -> "CardPull":
        return cls(
            id=str(uuid.uuid4()),
            card_name=card_name,
            rarity=rarity,
            raw_value=float(raw_value),
            confidence=float(confidence),
            timestamp=time.time(),
        )


@dataclass
class Pack:
    number: int
    pulls: list[CardPull] = field(default_factory=list)

    @property
    def total_value(self) -> float:
        return round(sum(card.raw_value for card in self.pulls), 2)

    @property
    def hit_count(self) -> int:
        return sum(1 for card in self.pulls if card.rarity != "COMMON")

    def public(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "card_count": len(self.pulls),
            "hit_count": self.hit_count,
            "total_value": self.total_value,
            "pulls": [asdict(card) for card in self.pulls[-12:]],
        }


@dataclass
class Box:
    number: int
    packs_total: int
    packs: list[Pack] = field(default_factory=list)
    active_pack_index: int = 0

    def ensure_pack(self) -> Pack:
        while len(self.packs) <= self.active_pack_index:
            self.packs.append(Pack(number=len(self.packs) + 1))
        return self.packs[self.active_pack_index]

    @property
    def active_pack(self) -> Pack:
        return self.ensure_pack()

    @property
    def total_value(self) -> float:
        return round(sum(pack.total_value for pack in self.packs), 2)

    def public(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "packs_total": self.packs_total,
            "active_pack_number": self.active_pack_index + 1,
            "packs": [pack.public() for pack in self.packs],
            "total_value": self.total_value,
        }


@dataclass
class BreakSession:
    id: str
    customer: str
    order_number: str
    product_name: str
    boxes_total: int
    packs_per_box: int
    boxes: list[Box] = field(default_factory=list)
    active_box_index: int = 0
    closed: bool = False

    @classmethod
    def create(
        cls,
        customer: str,
        order_number: str,
        product_name: str,
        boxes_total: int,
        packs_per_box: int,
    ) -> "BreakSession":
        session = cls(
            id=str(uuid.uuid4()),
            customer=customer,
            order_number=order_number,
            product_name=product_name,
            boxes_total=max(1, int(boxes_total)),
            packs_per_box=max(1, int(packs_per_box)),
        )
        session.ensure_box()
        return session

    def ensure_box(self) -> Box:
        while len(self.boxes) <= self.active_box_index:
            self.boxes.append(
                Box(number=len(self.boxes) + 1, packs_total=self.packs_per_box)
            )
        return self.boxes[self.active_box_index]

    @property
    def active_box(self) -> Box:
        return self.ensure_box()

    @property
    def total_value(self) -> float:
        return round(sum(box.total_value for box in self.boxes), 2)

    @property
    def card_count(self) -> int:
        return sum(len(pack.pulls) for box in self.boxes for pack in box.packs)

    @property
    def hit_count(self) -> int:
        return sum(pack.hit_count for box in self.boxes for pack in box.packs)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "customer": self.customer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "boxes_total": self.boxes_total,
            "packs_per_box": self.packs_per_box,
            "active_box_number": self.active_box_index + 1,
            "active_pack_number": self.active_box.active_pack_index + 1,
            "card_count": self.card_count,
            "hit_count": self.hit_count,
            "total_value": self.total_value,
            "closed": self.closed,
            "boxes": [box.public() for box in self.boxes],
        }
