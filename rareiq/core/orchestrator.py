from __future__ import annotations
import time
import uuid
from typing import Any

from rareiq.core.events import EventBus
from rareiq.services.session_service import SessionService
from rareiq.services.experience_service import ExperienceService


class RareIQOrchestrator:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.sessions = SessionService()
        self.experiences = ExperienceService()

    async def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "type": event_type,
            "event_id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "payload": payload,
        }
        await self.event_bus.publish(event)
        return event

    async def start_session(
        self,
        customer: str,
        order_number: str,
        product_name: str,
        boxes_total: int,
        packs_per_box: int,
    ) -> dict[str, Any]:
        session = self.sessions.start(
            customer=customer,
            order_number=order_number,
            product_name=product_name,
            boxes_total=boxes_total,
            packs_per_box=packs_per_box,
        )
        await self.publish("session_started", {"session": session})
        await self.publish("pack_started", {
            "session": session,
            "box_number": session["active_box_number"],
            "pack_number": session["active_pack_number"],
        })
        return session

    async def next_pack(self) -> dict[str, Any]:
        session = self.sessions.next_pack()
        await self.publish("pack_started", {
            "session": session,
            "box_number": session["active_box_number"],
            "pack_number": session["active_pack_number"],
        })
        return session

    async def previous_pack(self) -> dict[str, Any]:
        session = self.sessions.previous_pack()
        await self.publish("pack_changed", {"session": session})
        return session

    async def next_box(self) -> dict[str, Any]:
        session = self.sessions.next_box()
        await self.publish("box_started", {
            "session": session,
            "box_number": session["active_box_number"],
        })
        await self.publish("pack_started", {
            "session": session,
            "box_number": session["active_box_number"],
            "pack_number": session["active_pack_number"],
        })
        return session

    async def previous_box(self) -> dict[str, Any]:
        session = self.sessions.previous_box()
        await self.publish("box_changed", {"session": session})
        return session

    async def add_demo_card(self, card: dict[str, Any]) -> dict[str, Any]:
        session = self.sessions.add_card(card)
        experience = self.experiences.for_card(card)
        await self.publish("card_reveal", {
            "session": session,
            "card": card,
            "experience": experience,
        })
        return session

    async def undo(self) -> dict[str, Any]:
        session, removed = self.sessions.undo()
        await self.publish("session_updated", {"session": session, "removed": removed})
        return session

    async def close_session(self) -> dict[str, Any]:
        session = self.sessions.close()
        await self.publish("session_closed", {"session": session})
        return session
