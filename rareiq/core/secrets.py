from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SecretsManager:
    """Loads local-only RareIQ credentials without exposing them to the UI."""

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        self.path = self.project_root / "rareiq_secrets.json"
        self._values: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        values: dict[str, Any] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    values.update(payload)
            except Exception:
                pass

        env_key = os.environ.get("POKEMONTCG_API_KEY", "").strip()
        if env_key:
            values["pokemontcg_api_key"] = env_key

        self._values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def has(self, key: str) -> bool:
        return bool(str(self._values.get(key) or "").strip())

    def public_status(self) -> dict[str, bool]:
        return {
            "pokemontcg_api_key_loaded": self.has("pokemontcg_api_key"),
        }


secrets = SecretsManager()
