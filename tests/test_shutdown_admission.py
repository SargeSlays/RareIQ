"""Actual shutdown handlers and admission with synthetic ASGI state; never import/run the server."""
from __future__ import annotations

import ast
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
import pytest

from rareiq.web.desktop_lifecycle import DesktopAdmission, DesktopAdmissionMiddleware, NativeEncodingState


SERVER = Path(__file__).resolve().parents[1] / "rareiq/web/server.py"
IDENTITY = {"pid": 1234, "server_session_id": "synthetic-server"}
DISABLED = {"enabled": False, "connected": False, "streaming": False, "recording": False}


def fixture(*, desktop=True, obs=None, host="127.0.0.1"):
    guard = DesktopAdmission(desktop)
    guard.native_encoding = NativeEncodingState(pid_probe=lambda _: True)
    session, recorder = {"active": False}, {"active": False, "stopping": False}
    namespace = dict(DESKTOP_ADMISSION=guard, Request=Request, HTTPException=HTTPException,
        MAX_CONTROL_REQUEST_BYTES=65536, Any=Any, json=json, asyncio=asyncio,
        os=SimpleNamespace(getpid=lambda: IDENTITY["pid"]), SERVER_SESSION_ID=IDENTITY["server_session_id"],
        is_loopback_client=lambda value: value == "127.0.0.1", PRODUCTION_SESSION_LOCK=nullcontext(),
        PRODUCTION_SESSION=session, recording=SimpleNamespace(status=lambda: dict(recorder)),
        obs=SimpleNamespace(status=Mock(return_value=DISABLED.copy() if obs is None else obs)),
        _schedule_system_shutdown=Mock())
    names = {"RequestBodyTooLarge", "_read_bounded_body", "_read_bounded_json", "_desktop_idle_reason",
             "_request_idle_shutdown", "system_shutdown", "desktop_stop", "desktop_status"}
    nodes = [node for node in ast.parse(SERVER.read_text(encoding="utf-8")).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), namespace)
    app = FastAPI()
    app.add_middleware(DesktopAdmissionMiddleware, admission=guard)
    app.post("/api/system/shutdown")(namespace["system_shutdown"])
    app.post("/api/desktop/stop")(namespace["desktop_stop"])
    app.get("/api/desktop/status")(namespace["desktop_status"])
    client = AsyncClient(transport=ASGITransport(app=app, client=(host, 55555)), base_url="http://synthetic.invalid")
    return SimpleNamespace(guard=guard, session=session, recorder=recorder, namespace=namespace, app=app,
                           client=client, schedule=namespace["_schedule_system_shutdown"])


@pytest.mark.parametrize("obs,stopping", [
    (DISABLED, True),
    ({"enabled": True, "connected": True, "streaming": False, "recording": False}, True),
    ({"enabled": True, "connected": False, "streaming": False, "recording": False}, False),
    ({"connected": True, "streaming": False, "recording": False}, False),
    ({"enabled": None, "connected": True, "streaming": False, "recording": False}, False),
    ({**DISABLED, "enabled": 0}, False),
    ({**DISABLED, "streaming": True}, False),
    ({**DISABLED, "recording": True}, False),
    ({"enabled": False, "connected": False}, False),
])
@pytest.mark.parametrize("desktop", [True, False])
def test_actual_legacy_shutdown_requires_explicit_idle_outputs_even_when_obs_disabled(obs, stopping, desktop):
    async def exercise():
        f = fixture(desktop=desktop, obs=obs)
        async with f.client as client:
            response = await client.post("/api/system/shutdown")
        assert response.status_code == 200
        result = response.json()
        assert result["ok"] is stopping and result["stopping"] is stopping
        assert f.guard.closing is stopping and f.schedule.call_count == int(stopping)
        if not stopping:
            assert result["reason"] == "obs_not_confirmed_idle"
    asyncio.run(exercise())


@pytest.mark.parametrize("desktop", [True, False])
@pytest.mark.parametrize("busy,reason", [("session", "session_not_idle"), ("recording", "recording_not_idle"),
    ("recording_stopping", "recording_not_idle"), ("native", "native_encoding_active"),
    ("clients", "clients_connected"), ("mutations", "operation_in_progress")])
def test_disabled_obs_never_overrides_any_local_production_reservation(desktop, busy, reason):
    async def exercise():
        f = fixture(desktop=desktop)
        if busy == "session":
            f.session["active"] = True
        elif busy == "recording":
            f.recorder["active"] = True
        elif busy == "recording_stopping":
            f.recorder["stopping"] = True
        elif busy == "native":
            f.guard.native_encoding.update(active=True, owner_pid=42)
        else:
            setattr(f.guard, busy, 1)
        async with f.client as client:
            result = (await client.post("/api/system/shutdown")).json()
        assert result == {"ok": False, "stopping": False, "reason": reason}
        assert not f.guard.closing
        f.schedule.assert_not_called()
        if busy == "native":
            f.namespace["obs"].status.assert_not_called()
    asyncio.run(exercise())


@pytest.mark.parametrize("desktop", [True, False])
def test_generic_shutdown_rechecks_real_mutation_reservation_after_slow_obs_probe(desktop):
    async def exercise():
        f = fixture(desktop=desktop)
        probing, release_probe, mutating, release_mutation = (asyncio.Event() for _ in range(4))
        async def slow_probe(function):
            probing.set()
            await release_probe.wait()
            return function()
        f.namespace["asyncio"] = SimpleNamespace(to_thread=slow_probe, wait_for=asyncio.wait_for)
        @f.app.post("/api/synthetic/mutation")
        async def hold_mutation():
            mutating.set()
            await release_mutation.wait()
            return {"ok": True}
        async with f.client as client:
            stop = asyncio.create_task(client.post("/api/system/shutdown"))
            await asyncio.wait_for(probing.wait(), 5)
            mutation = asyncio.create_task(client.post("/api/synthetic/mutation"))
            try:
                await asyncio.wait_for(mutating.wait(), 5)
                assert f.guard.mutations == 1
                release_probe.set()
                assert (await stop).json() == {"ok": False, "stopping": False, "reason": "operation_in_progress"}
                assert not f.guard.closing
                f.schedule.assert_not_called()
            finally:
                release_probe.set()
                release_mutation.set()
                await mutation
        assert f.guard.mutations == 0
    asyncio.run(exercise())


@pytest.mark.parametrize("desktop", [True, False])
def test_both_modes_seal_clients_and_mutations_and_keep_stop_retries_idempotent(desktop):
    async def exercise():
        f = fixture(desktop=desktop)
        dispatched = Mock()
        @f.app.post("/api/synthetic/mutation")
        async def mutation():
            dispatched()
            return {"ok": True}
        @f.app.get("/api/synthetic/events")
        async def stream():
            dispatched()
            return {"ok": True}
        async with f.client as client:
            assert (await client.post("/api/system/shutdown")).json()["stopping"] is True
            assert (await client.post("/api/system/shutdown")).json()["stopping"] is True
            assert (await client.post("/api/synthetic/mutation")).status_code == 503
            assert (await client.get("/api/synthetic/events")).status_code == 503
            assert (await client.get("/api/desktop/status")).status_code == 200
            desktop_result = (await client.post("/api/desktop/stop", json=IDENTITY)).json()
            assert desktop_result.get("reason") == (None if desktop else "desktop_mode_required")
        dispatched.assert_not_called()
        f.schedule.assert_called_once()
    asyncio.run(exercise())


def test_concurrent_desktop_and_legacy_stop_share_one_atomic_admission_seal():
    async def exercise():
        f = fixture()
        probing, release, count = asyncio.Event(), asyncio.Event(), 0
        async def slow_probe(function):
            nonlocal count
            count += 1
            if count == 2:
                probing.set()
            await release.wait()
            return function()
        f.namespace["asyncio"] = SimpleNamespace(to_thread=slow_probe, wait_for=asyncio.wait_for)
        async with f.client as client:
            first = asyncio.create_task(client.post("/api/desktop/stop", json=IDENTITY))
            second = asyncio.create_task(client.post("/api/system/shutdown"))
            await asyncio.wait_for(probing.wait(), 5)
            release.set()
            results = await asyncio.gather(first, second)
        assert all(response.json()["stopping"] is True for response in results)
        f.schedule.assert_called_once()
        assert f.guard.closing
    asyncio.run(exercise())


def test_failed_shutdown_schedule_unseals_admission_and_exposes_only_constant_reason():
    async def exercise():
        f = fixture()
        f.schedule.side_effect = RuntimeError("synthetic private error")
        async with f.client as client:
            result = (await client.post("/api/system/shutdown")).json()
            assert result == {"ok": False, "stopping": False, "reason": "shutdown_not_confirmed"}
            assert not f.guard.closing
            f.schedule.side_effect = None
            assert (await client.post("/api/system/shutdown")).json()["stopping"] is True
        assert f.guard.closing
    asyncio.run(exercise())


def test_legacy_shutdown_in_desktop_mode_preserves_loopback_boundary():
    async def exercise():
        f = fixture(host="192.0.2.1")
        async with f.client as client:
            result = (await client.post("/api/system/shutdown")).json()
        assert result == {"ok": False, "stopping": False, "reason": "local_request_required"}
        f.schedule.assert_not_called()
    asyncio.run(exercise())
