from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class SecretsManager:
    """Loads local-only RareIQ credentials without exposing them to the UI."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        requested_path = Path(path) if path is not None else Path("rareiq_secrets.json")
        self.path = requested_path if requested_path.is_absolute() else self.project_root / requested_path
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            values = self._read_file(strict=False)

            env_key = os.environ.get("POKEMONTCG_API_KEY", "").strip()
            if env_key:
                values["pokemontcg_api_key"] = env_key

            self._values = values

    def update(self, values: dict[str, Any]) -> None:
        """Atomically persist selected values without deleting other credentials."""
        if not isinstance(values, dict) or not values:
            raise ValueError("Secret updates must be a non-empty object.")
        if not all(isinstance(key, str) and key.strip() for key in values):
            raise ValueError("Secret keys must be non-empty strings.")

        with self._lock:
            payload = self._read_file(strict=True)
            payload.update(values)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(
                f"{self.path.stem}.tmp{self.path.suffix}"
            )
            try:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.reload()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def has(self, key: str) -> bool:
        return bool(str(self.get(key) or "").strip())

    def public_status(self) -> dict[str, bool]:
        return {
            "pokemontcg_api_key_loaded": self.has("pokemontcg_api_key"),
        }

    def _read_file(self, *, strict: bool) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            if strict:
                raise ValueError("Secrets file is not valid JSON.") from None
            return {}
        if not isinstance(payload, dict):
            if strict:
                raise ValueError("Secrets file must contain a JSON object.")
            return {}
        return dict(payload)


secrets = SecretsManager()
