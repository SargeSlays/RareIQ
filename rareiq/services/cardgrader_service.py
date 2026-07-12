from __future__ import annotations

import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np


class CardGraderService:
    BASE_URL = "https://cardgrader.ai/v1"

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.secrets_path = self.project_root / "rareiq_secrets.json"
        self.capture_dir = self.project_root / "grading_captures"
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._api_key: str | None = None
        self._agent: dict[str, Any] | None = None
        self._last_scan: dict[str, Any] | None = None
        self._last_result: dict[str, Any] | None = None
        self._error: str | None = None
        self._load_secrets()

    def _load_secrets(self) -> None:
        try:
            payload = json.loads(self.secrets_path.read_text(encoding="utf-8"))
            self._api_key = payload.get("cardgrader_api_key")
            self._agent = payload.get("cardgrader_agent")
        except FileNotFoundError:
            pass
        except Exception as exc:
            self._error = str(exc)

    def _save_secrets(self) -> None:
        self.secrets_path.write_text(
            json.dumps(
                {
                    "cardgrader_api_key": self._api_key,
                    "cardgrader_agent": self._agent,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": bool(self._api_key),
                "agent": self._agent,
                "last_scan": self._last_scan,
                "last_result": self._last_result,
                "error": self._error,
            }

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise RuntimeError("CardGrader API key is not configured.")
        return {"Authorization": f"Bearer {self._api_key}"}

    def register_agent(
        self,
        name: str,
        contact_email: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name.strip() or "RareIQ"}
        if contact_email and contact_email.strip():
            payload["contactEmail"] = contact_email.strip()

        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{self.BASE_URL}/agents", json=payload)
            response.raise_for_status()
            result = response.json()

        api_key = result.get("apiKey")
        if not api_key:
            raise RuntimeError("Registration succeeded but no API key was returned.")

        with self._lock:
            self._api_key = api_key
            self._agent = {
                "agentId": result.get("agentId"),
                "tier": result.get("tier"),
                "credits": result.get("credits"),
                "name": payload["name"],
                "contactEmail": payload.get("contactEmail"),
            }
            self._error = None
            self._save_secrets()

        return {
            "ok": True,
            "agent": self._agent,
            "api_key_saved": True,
            "message": result.get("message"),
        }

    def configure_key(self, api_key: str) -> dict[str, Any]:
        api_key = api_key.strip()
        if not api_key.startswith("cgk_"):
            raise ValueError("CardGrader API keys must start with cgk_.")
        with self._lock:
            self._api_key = api_key
            self._save_secrets()
        return self.verify_account()

    def verify_account(self) -> dict[str, Any]:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(
                f"{self.BASE_URL}/agents/me",
                headers=self._headers(),
            )
            response.raise_for_status()
            result = response.json()

        with self._lock:
            self._agent = result
            self._error = None
            self._save_secrets()

        return {"ok": True, "agent": result}

    def save_frame(self, frame: np.ndarray, label: str) -> Path:
        timestamp = int(time.time() * 1000)
        path = self.capture_dir / f"{label}_{timestamp}.jpg"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"Failed to save {label} image.")
        return path

    def submit_scan(
        self,
        front_path: Path,
        back_path: Path | None = None,
        module: str = "grade",
    ) -> dict[str, Any]:
        if module not in {"identify", "grade", "market", "full"}:
            raise ValueError("Invalid grading module.")

        headers = self._headers()
        headers["Idempotency-Key"] = f"rareiq_{secrets.token_hex(12)}"

        files: dict[str, Any] = {
            "front": (front_path.name, front_path.read_bytes(), "image/jpeg")
        }
        if back_path and back_path.exists():
            files["back"] = (
                back_path.name,
                back_path.read_bytes(),
                "image/jpeg",
            )

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{self.BASE_URL}/scans",
                headers=headers,
                files=files,
                data={"modules": module},
            )
            response.raise_for_status()
            result = response.json()

        with self._lock:
            self._last_scan = {
                **result,
                "front_path": str(front_path),
                "back_path": str(back_path) if back_path else None,
                "submitted_at": time.time(),
            }
            self._error = None

        return {"ok": True, "scan": result}

    def poll_scan(self, scan_id: int | str) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self.BASE_URL}/scans/{scan_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            result = response.json()

        with self._lock:
            self._last_scan = {**(self._last_scan or {}), **result}
            if result.get("status") == "completed":
                self._last_result = result
            self._error = None

        return {"ok": True, "scan": result}
