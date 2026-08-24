from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

from rareiq.version import VERSION
from rareiq.web import server


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _StatusDouble:
    def __init__(self, payload: dict):
        self.payload = payload

    def status(self) -> dict:
        return dict(self.payload)


class _CameraManagerDouble:
    def health(self) -> dict:
        return {
            "healthy": True,
            "state": "running",
            "message": "Fresh frames are advancing.",
        }


def test_app_entrypoint_initializes_storage_before_loading_server():
    source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")

    assert source.index("storage.initialize()") < source.index("from rareiq.web.server import run")
    assert 'if __name__ == "__main__":' in source
    assert "cv2.setNumThreads(1)" in source
    assert "run()" in source


def test_boot_ping_exposes_the_active_release_version():
    payload = asyncio.run(server.boot_ping())

    assert payload["ok"] is True
    assert payload["version"] == VERSION
    assert payload["server_session_id"] == server.SERVER_SESSION_ID
    assert payload["pid"] == os.getpid()
    assert payload["message"] == "Boot API online."


def test_system_health_has_one_route_and_supports_both_frontend_contracts(monkeypatch):
    route_count = sum(
        1
        for route in server.app.routes
        if getattr(route, "path", None) == "/api/system/health"
        and "GET" in (getattr(route, "methods", None) or set())
    )
    assert route_count == 1

    detailed_health = {
        "systems": {"camera": {"ok": True, "status": "online"}},
        "metrics": {"indexed_cards": 42},
        "healthy": True,
    }
    orchestrator = SimpleNamespace(
        camera_manager=_CameraManagerDouble(),
        recognition=_StatusDouble({"error": None}),
        catalog=_StatusDouble({"error": None}),
        index_activation=_StatusDouble({"state": "ready", "error": None}),
        system_health=_StatusDouble(detailed_health),
    )
    monkeypatch.setattr(server, "orchestrator", orchestrator)

    payload = asyncio.run(server.system_health())

    assert payload["ok"] is True
    assert payload["components"]["camera"]["healthy"] is True
    assert payload["components"]["recognition"]["state"] == "ready"
    assert payload["health"] == detailed_health
    assert isinstance(payload["timestamp"], float)
