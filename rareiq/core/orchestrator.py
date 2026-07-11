from __future__ import annotations
import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from rareiq.core.events import EventBus
from rareiq.services.session_service import SessionService
from rareiq.services.experience_service import ExperienceService
from rareiq.services.vision_service import VisionService


class RareIQOrchestrator:
    def __init__(self, event_bus: EventBus, capture_dir: Path) -> None:
        self.event_bus = event_bus
        self.sessions = SessionService()
        self.experiences = ExperienceService()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.vision = VisionService(self._emit_from_thread, capture_dir)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def _emit_from_thread(self, event: dict[str, Any]) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.event_bus.publish(event), self.loop)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {"type": event_type, "event_id": str(uuid.uuid4()), "timestamp": time.time(), "payload": payload}
        await self.event_bus.publish(event)
        return event

    async def start_session(self, **kwargs: Any) -> dict[str, Any]:
        session = self.sessions.start(**kwargs)
        await self.publish("session_started", {"session": session})
        await self.publish("pack_started", {"session": session})
        return session

    async def next_pack(self): 
        s = self.sessions.next_pack(); await self.publish("pack_started", {"session": s}); return s
    async def previous_pack(self):
        s = self.sessions.previous_pack(); await self.publish("pack_changed", {"session": s}); return s
    async def next_box(self):
        s = self.sessions.next_box(); await self.publish("box_started", {"session": s}); return s
    async def previous_box(self):
        s = self.sessions.previous_box(); await self.publish("box_changed", {"session": s}); return s
    async def add_demo_card(self, card):
        s = self.sessions.add_card(card)
        await self.publish("card_reveal", {"session": s, "card": card, "experience": self.experiences.for_card(card)})
        return s
    async def undo(self):
        s, removed = self.sessions.undo(); await self.publish("session_updated", {"session": s, "removed": removed}); return s
    async def close_session(self):
        s = self.sessions.close(); await self.publish("session_closed", {"session": s}); return s
