from __future__ import annotations

import threading
import time
from typing import Any

from rareiq.core.secrets import secrets


class ProviderDiagnosticsService:
    def __init__(self, providers: dict[str, Any]) -> None:
        self.providers = providers
        self._lock = threading.RLock()
        self._status: dict[str, Any] = {
            "running": False,
            "checked_at": None,
            "providers": {},
            "secrets": secrets.public_status(),
        }

    def run(self) -> dict[str, Any]:
        with self._lock:
            self._status["running"] = True

        results: dict[str, Any] = {}
        for provider_id, provider in self.providers.items():
            try:
                results[provider_id] = provider.health()
            except Exception as exc:
                results[provider_id] = {
                    "online": False,
                    "error": str(exc),
                }

        with self._lock:
            self._status = {
                "running": False,
                "checked_at": time.time(),
                "providers": results,
                "secrets": secrets.public_status(),
            }
            return dict(self._status)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)
