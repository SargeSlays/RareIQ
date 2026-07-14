from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CatalogProvider(ABC):
    provider_id: str
    display_name: str
    languages: tuple[str, ...]

    @abstractmethod
    def discover_sets(self, language: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_set(self, language: str, set_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_card(
        self,
        language: str,
        card_id: str,
    ) -> dict[str, Any] | None:
        raise NotImplementedError
