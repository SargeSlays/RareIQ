from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CollectiblePlugin(ABC):
    plugin_id: str
    display_name: str
    version: str

    @abstractmethod
    def provider_ids(self) -> tuple[str, ...]:
        raise NotImplementedError

    @abstractmethod
    def normalize_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def recognition_signals(self) -> tuple[str, ...]:
        raise NotImplementedError
