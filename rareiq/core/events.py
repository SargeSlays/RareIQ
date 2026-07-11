from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: dict[str, Any]) -> None:
        if not self._handlers:
            return
        await asyncio.gather(*(handler(event) for handler in list(self._handlers)), return_exceptions=True)
