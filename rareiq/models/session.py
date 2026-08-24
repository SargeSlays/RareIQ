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
    collector_number: str | None = None
    language: str | None = None
    set_name: str | None = None
    source: str | None = None
    reference_image_url: str | None = None
    recognition_signature: str | None = None
    printed_name: str | None = None
    english_name: str | None = None
    operator_resolution: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        card_name: str,
        rarity: str,
        raw_value: float,
        confidence: float = 1.0,
        collector_number: str | None = None,
        language: str | None = None,
        set_name: str | None = None,
        source: str | None = None,
        reference_image_url: str | None = None,
        recognition_signature: str | None = None,
        printed_name: str | None = None,
        english_name: str | None = None,
        operator_resolution: dict[str, Any] | None = None,
    ) -> "CardPull":
        return cls(
            id=str(uuid.uuid4()),
            card_name=card_name,
            rarity=rarity,
            raw_value=float(raw_value),
            confidence=float(confidence),
            timestamp=time.time(),
            collector_number=collector_number,
            language=language,
            set_name=set_name,
            source=source,
            reference_image_url=reference_image_url,
            recognition_signature=recognition_signature,
            printed_name=printed_name,
            english_name=english_name,
            operator_resolution=(
                dict(operator_resolution)
                if isinstance(operator_resolution, dict)
                else None
            ),
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


    @classmethod
    def from_public(cls, payload: dict[str, Any]) -> "BreakSession":
        session = cls(
            id=str(payload.get("id") or uuid.uuid4()),
            customer=str(payload.get("customer") or "Recovered Session"),
            order_number=str(payload.get("order_number") or "RIQ-RECOVERED"),
            product_name=str(payload.get("product_name") or "Recovered Product"),
            boxes_total=max(1, int(payload.get("boxes_total") or 1)),
            packs_per_box=max(1, int(payload.get("packs_per_box") or 1)),
            boxes=[],
            active_box_index=max(
                0,
                int(payload.get("active_box_number") or 1) - 1,
            ),
            closed=bool(payload.get("closed")),
        )

        for box_payload in payload.get("boxes") or []:
            box = Box(
                number=int(box_payload.get("number") or len(session.boxes) + 1),
                packs_total=max(
                    1,
                    int(
                        box_payload.get("packs_total")
                        or session.packs_per_box
                    ),
                ),
                packs=[],
                active_pack_index=max(
                    0,
                    int(box_payload.get("active_pack_number") or 1) - 1,
                ),
            )

            for pack_payload in box_payload.get("packs") or []:
                pack = Pack(
                    number=int(
                        pack_payload.get("number")
                        or len(box.packs) + 1
                    ),
                    pulls=[],
                )

                for card_payload in pack_payload.get("pulls") or []:
                    pack.pulls.append(
                        CardPull(
                            id=str(
                                card_payload.get("id")
                                or uuid.uuid4()
                            ),
                            card_name=str(
                                card_payload.get("card_name")
                                or "Unknown Card"
                            ),
                            rarity=str(
                                card_payload.get("rarity")
                                or "UNKNOWN"
                            ),
                            raw_value=float(
                                card_payload.get("raw_value")
                                or 0.0
                            ),
                            confidence=float(
                                card_payload.get("confidence")
                                or 0.0
                            ),
                            timestamp=float(
                                card_payload.get("timestamp")
                                or time.time()
                            ),
                            collector_number=card_payload.get(
                                "collector_number"
                            ),
                            language=card_payload.get("language"),
                            set_name=card_payload.get("set_name"),
                            source=card_payload.get("source"),
                            reference_image_url=card_payload.get(
                                "reference_image_url"
                            ),
                            recognition_signature=card_payload.get(
                                "recognition_signature"
                            ),
                            printed_name=card_payload.get(
                                "printed_name"
                            ),
                            english_name=card_payload.get(
                                "english_name"
                            ),
                            operator_resolution=(
                                dict(card_payload["operator_resolution"])
                                if isinstance(
                                    card_payload.get("operator_resolution"),
                                    dict,
                                )
                                else None
                            ),
                        )
                    )
                box.packs.append(pack)

            session.boxes.append(box)

        session.ensure_box()
        session.active_box_index = min(
            session.active_box_index,
            len(session.boxes) - 1,
        )
        session.active_box.ensure_pack()
        return session

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
