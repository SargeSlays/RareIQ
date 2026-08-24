from __future__ import annotations

import asyncio
from pathlib import Path

from rareiq.web import server


class _BootManagerDouble:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def run(self, force: bool) -> None:
        self.calls.append(force)


class _CameraManagerDouble:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _OrchestratorDouble:
    def __init__(self) -> None:
        self.loop = None
        self.boot_manager = _BootManagerDouble()
        self.camera_manager = _CameraManagerDouble()

    def set_loop(self, loop) -> None:
        self.loop = loop


def test_lifespan_starts_boot_and_shuts_down_camera(monkeypatch) -> None:
    orchestrator = _OrchestratorDouble()
    monkeypatch.setattr(server, "orchestrator", orchestrator)

    async def exercise() -> None:
        async with server.lifespan(server.app):
            await asyncio.sleep(0.2)

    asyncio.run(exercise())

    assert orchestrator.loop is not None
    assert orchestrator.boot_manager.calls == [False]
    assert orchestrator.camera_manager.shutdown_calls == 1


def test_server_uses_lifespan_instead_of_deprecated_event_hooks() -> None:
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert 'lifespan=lifespan' in source
    assert '@app.on_event("startup")' not in source
    assert '@app.on_event("shutdown")' not in source
