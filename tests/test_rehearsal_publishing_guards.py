"""Exercise actual publishing boundaries with synthetic collaborators only.

Never import the application singleton, connect to OBS, spawn an encoder, write
media, open a vault, or contact a provider. Extract server functions as in the
existing native-output contract tests so the guards themselves remain real.
"""
from __future__ import annotations

import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import io
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import pytest

from rareiq.services.instant_replay_service import InstantReplayService
from rareiq.services.obs_service import ObsService
from rareiq.services.production_action_service import ActionSpec, ProductionActions
from rareiq.services.recording_service import RecordingService
from rareiq.services.rehearsal_service import RehearsalError, RehearsalService
from rareiq.web.desktop_lifecycle import DesktopAdmission, NativeEncodingState
from rareiq.web.stream_metadata import create_stream_metadata_router


SERVER = Path(__file__).resolve().parents[1] / "rareiq/web/server.py"


def functions(names, namespace):
    nodes = [node for node in ast.parse(SERVER.read_text(encoding="utf-8")).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


def production_actions(room):
    assignments = [node for node in ast.parse(SERVER.read_text(encoding="utf-8")).body
                   if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "production_actions"
                                                          for target in node.targets)]
    assert len(assignments) == 1
    namespace = {"ProductionActions": ProductionActions, "rehearsal_service": room}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace["production_actions"]


def rehearsal(tmp_path, *, active=True):
    room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=lambda: {"ready": True})
    if active:
        asyncio.run(room.enter("fixture-enter", 0))
    return room


def test_recording_start_is_blocked_before_command_process_or_output_creation_and_stop_remains_available(tmp_path, monkeypatch):
    room = rehearsal(tmp_path)
    output = tmp_path / "recordings"
    recorder = RecordingService(output, "synthetic-encoder {output}", config_path=tmp_path / "recording-settings.json")
    recorder.set_publishing_guard(room.publishing_lease)
    spawn = Mock(side_effect=AssertionError("must not spawn an encoder"))
    arguments = Mock(side_effect=AssertionError("must not prepare an encoder command"))
    monkeypatch.setattr("rareiq.services.recording_service.subprocess.Popen", spawn)
    monkeypatch.setattr(recorder, "_command_args", arguments)
    result = recorder.start("synthetic-session")
    assert result["started"] is False and result["reason"] == "rehearsal_publishing_blocked"
    assert not output.exists()
    spawn.assert_not_called()
    arguments.assert_not_called()

    class Process:
        stdin = io.BytesIO()
        returncode = None
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            self.returncode = 0
            return 0
    process = Process()
    recorder._process, recorder._session_id = process, "synthetic-session"
    assert recorder.stop(expected_session_id="synthetic-session")["stopped"]
    assert process.returncode == 0 and process.stdin.closed
    assert not room.publishing_allowed()


def test_obs_start_commands_fail_before_connection_but_both_stop_commands_run(tmp_path, monkeypatch):
    room = rehearsal(tmp_path)
    obs = ObsService(tmp_path / "obs-settings.json")
    obs.set_publishing_guard(room.publishing_lease)
    client = SimpleNamespace(get_stream_status=Mock(return_value=SimpleNamespace(output_active=True)),
                             get_record_status=Mock(return_value=SimpleNamespace(output_active=True)),
                             start_stream=Mock(), start_record=Mock(), stop_stream=Mock(), stop_record=Mock())
    connections = []
    @contextmanager
    def connection():
        connections.append(True)
        yield client
    monkeypatch.setattr(obs, "_connection", connection)
    monkeypatch.setattr(obs, "status", lambda: {"connected": True, "streaming": False, "recording": False})
    for action in ("start-stream", "start-record"):
        with pytest.raises(RehearsalError, match="rehearsal_publishing_blocked"):
            obs.command(action)
    assert connections == []
    client.start_stream.assert_not_called()
    client.start_record.assert_not_called()
    obs.command("stop-stream")
    obs.command("stop-record")
    assert len(connections) == 2
    client.stop_stream.assert_called_once()
    client.stop_record.assert_called_once()


@pytest.mark.parametrize("automatic,export", [(False, False), (False, True), (True, True)])
def test_manual_and_automatic_clip_paths_cannot_write_media_or_call_encoder(tmp_path, monkeypatch, automatic, export):
    room = rehearsal(tmp_path)
    root = tmp_path / "replay"
    capture, slot = Mock(), Mock(return_value=1)
    replay = InstantReplayService(root, capture, slot)
    replay.set_publishing_guard(room.publishing_lease)
    encoder = Mock(side_effect=AssertionError("must not encode media"))
    cancelled = Mock(return_value=False)
    monkeypatch.setattr(replay, "_encode_video", encoder)
    result = replay.save_frames([(time.time(), 1, b"synthetic-frame")], "Synthetic highlight",
                                auto_clip={"reason": "synthetic"} if automatic else None,
                                export_video=export, cancelled=cancelled)
    assert result == {"created": False, "reason": "rehearsal_publishing_blocked"}
    assert not root.exists()
    encoder.assert_not_called()
    cancelled.assert_not_called()
    capture.assert_not_called()


@pytest.mark.parametrize("capability", ["obs.output", "recording.start", "clip.export", "unknown.future-capability"])
def test_actual_action_policy_blocks_nonlocal_and_unknown_capabilities_but_practice_has_zero_effects(tmp_path, capability):
    room = rehearsal(tmp_path)
    actions = production_actions(room)
    execute = Mock(return_value={"ok": True})
    try:
        actions.register(ActionSpec("fixture.action", lambda value: value, execute, capability))
        for origin in ("operator", "host_voice", "host_gesture"):
            result = actions.dispatch("fixture.action", {}, origin=origin)
            assert result["state"] == "rejected" and result["reason"] == "rehearsal_action_blocked"
            practice = actions.dispatch("fixture.action", {}, origin=origin, practice=True)
            assert practice["state"] == "validated" and practice["executed"] is False
        assert actions.dispatch("not.registered", {}, origin="operator")["reason"] == "unknown_action"
        execute.assert_not_called()
        assert actions._requests == {}
    finally:
        actions.close()


@pytest.mark.parametrize("capability", ["program.camera", "program.scene"])
def test_actual_action_policy_retains_local_program_controls_during_rehearsal(tmp_path, capability):
    actions = production_actions(rehearsal(tmp_path))
    execute = Mock(return_value={"ok": True, "local_preview_only": True})
    try:
        actions.register(ActionSpec("fixture.local", lambda value: value, execute, capability))
        result = actions.dispatch("fixture.local", {}, origin="host_voice")
        assert result["state"] == "succeeded" and result["result"]["local_preview_only"]
        execute.assert_called_once_with({})
    finally:
        actions.close()


def test_action_worker_rechecks_mode_after_prequeue_admission_without_executing_stale_action(tmp_path):
    room = rehearsal(tmp_path, active=False)
    actions = production_actions(room)
    guard, checks, worker_waiting, release = actions._capability_guard, [], threading.Event(), threading.Event()
    def capability_guard(action, capability):
        checks.append(True)
        if len(checks) == 2:
            worker_waiting.set()
            assert release.wait(5)
        return guard(action, capability)
    actions._capability_guard = capability_guard
    execute = Mock(return_value={"ok": True})
    actions.register(ActionSpec("fixture.stale", lambda value: value, execute, "obs.output"))
    try:
        with ThreadPoolExecutor(max_workers=1) as dispatcher:
            pending = dispatcher.submit(actions.dispatch, "fixture.stale", {}, origin="host_gesture")
            try:
                assert worker_waiting.wait(5)
                asyncio.run(room.enter("enter-while-queued", 0))
            finally:
                release.set()
            result = pending.result(timeout=5)
        assert result["state"] == "failed" and result["result"]["reason"] == "rehearsal_action_blocked"
        execute.assert_not_called()
    finally:
        release.set()
        actions.close()


def test_guard_failures_fail_closed_before_action_queue(tmp_path):
    room = rehearsal(tmp_path, active=False)
    actions = production_actions(room)
    actions._capability_guard = Mock(side_effect=OSError("synthetic unavailable authority"))
    execute = Mock(return_value={"ok": True})
    try:
        actions.register(ActionSpec("fixture.guard-failure", lambda value: value, execute, "program.camera"))
        result = actions.dispatch("fixture.guard-failure", {}, origin="operator")
        assert result["reason"] == "rehearsal_action_blocked" and not actions._requests
        execute.assert_not_called()
    finally:
        actions.close()


@pytest.mark.parametrize("failed", [False, True])
def test_metadata_await_holds_lease_blocks_entry_then_rehearsal_blocks_new_provider_callback(tmp_path, failed):
    async def scenario():
        room = rehearsal(tmp_path, active=False)
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def apply(*args, **kwargs):
            calls.append(True)
            started.set()
            await release.wait()
            if failed:
                raise ValueError("private provider fixture detail")
            return {"state": "applied", "platform": "twitch"}
        app = FastAPI()
        app.include_router(create_stream_metadata_router(SimpleNamespace(apply=apply), lambda _: True,
                                                       publication_guard=room.publishing_lease))
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
            payload = {"request_id": "metadata-1", "expected_channel_id": "123", "values": {"title": "Synthetic title"}}
            async def request():
                return await client.post("/api/production/stream-metadata/twitch/apply", json=payload,
                                         headers={"Origin": "http://127.0.0.1:8765"})
            pending = asyncio.create_task(request())
            await asyncio.wait_for(started.wait(), 5)
            try:
                assert room.snapshot()["publishing_work_pending"]
                with pytest.raises(RehearsalError, match="rehearsal_production_busy"):
                    await room.enter("enter-during-metadata", 0)
                assert room.snapshot()["mode"] == "production"
            finally:
                release.set()
            completed = await pending
            assert completed.status_code == (409 if failed else 200)
            assert "private provider fixture detail" not in completed.text
            assert not room.snapshot()["publishing_work_pending"]
            await room.enter("enter-after-metadata", 0)
            blocked = await request()
            assert blocked.status_code == 409 and blocked.json()["reason"] == "rehearsal_publishing_blocked"
            assert calls == [True]
    asyncio.run(scenario())


def test_native_rehearsal_claim_requires_exact_owner_mode_generation_to_clear():
    state = NativeEncodingState(pid_probe=lambda _: True)
    generation = "a" * 32
    assert state.update(active=True, owner_pid=42, mode="rehearsal", rehearsal_generation=generation)["ok"]
    for changed in ({"owner_pid": 43}, {"mode": "broadcast"}, {"rehearsal_generation": "b" * 32}):
        for active in (True, False):
            result = state.update(**{"active": active, "owner_pid": 42, "mode": "rehearsal", "rehearsal_generation": generation, **changed})
            assert not result["ok"] and result["reason"] == "encoding_owner_mismatch"
            assert state.snapshot()["active"] and state.snapshot()["rehearsal_generation"] == generation
    assert state.update(active=False, owner_pid=42, mode="rehearsal", rehearsal_generation=generation)["ok"]
    assert not state.snapshot()["active"]


def test_actual_session_and_show_entrypoints_block_before_any_preflight_or_encoder_callback(tmp_path):
    room = rehearsal(tmp_path)
    recorder = SimpleNamespace(start=Mock(), status=Mock())
    preflight = AsyncMock()
    namespace = functions({"start_production_session", "start_production_show", "_start_production_show"}, {
        "ProductionSessionMetadataRequest": object, "StartShowRequest": object, "JSONResponse": JSONResponse,
        "rehearsal_service": room, "PRODUCTION_SESSION_LOCK": nullcontext(), "PRODUCTION_SESSION": {"active": False},
        "PRODUCTION_SHOW_START_LOCK": asyncio.Lock(), "recording": recorder, "production_preflight": preflight,
    })
    for name in ("start_production_session", "start_production_show"):
        with pytest.raises(RehearsalError, match="rehearsal_publishing_blocked"):
            asyncio.run(namespace[name](SimpleNamespace()))
    direct = asyncio.run(namespace["_start_production_show"](SimpleNamespace()))
    assert direct.status_code == 409 and json.loads(direct.body)["reason"] == "rehearsal_publishing_blocked"
    recorder.start.assert_not_called()
    recorder.status.assert_not_called()
    preflight.assert_not_called()
    assert namespace["PRODUCTION_SESSION"] == {"active": False}


def test_actual_native_endpoint_blocks_production_and_stale_rehearsal_claims_but_can_stop_during_recovery(tmp_path):
    room = rehearsal(tmp_path)
    state = room.snapshot()
    admission = DesktopAdmission(True)
    admission.native_encoding = NativeEncodingState(pid_probe=lambda _: True)
    payload = {"pid": os.getpid(), "server_session_id": "synthetic-backend", "active": True, "owner_pid": 42}
    namespace = functions({"desktop_encoding_status"}, {
        "Request": object, "DESKTOP_ADMISSION": admission, "os": os, "SERVER_SESSION_ID": "synthetic-backend",
        "is_loopback_client": lambda host: host == "127.0.0.1", "rehearsal_service": room,
        "_read_bounded_json": AsyncMock(side_effect=lambda *_: dict(payload)),
    })
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    with pytest.raises(RehearsalError, match="rehearsal_publishing_blocked"):
        asyncio.run(namespace["desktop_encoding_status"](request))
    assert not admission.native_encoding.snapshot()["active"]
    payload.update(mode="rehearsal", rehearsal_generation="b" * 32)
    with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
        asyncio.run(namespace["desktop_encoding_status"](request))
    assert not admission.native_encoding.snapshot()["active"]
    payload["rehearsal_generation"] = state["generation"]
    assert asyncio.run(namespace["desktop_encoding_status"](request))["ok"]
    room.path.write_bytes(b"synthetic damaged local state")
    assert room.snapshot()["mode"] == "recovery_required"
    payload.update(active=False, rehearsal_generation="c" * 32)
    assert not asyncio.run(namespace["desktop_encoding_status"](request))["ok"]
    assert admission.native_encoding.snapshot()["active"]
    payload["rehearsal_generation"] = state["generation"]
    assert asyncio.run(namespace["desktop_encoding_status"](request))["ok"]
    assert not admission.native_encoding.snapshot()["active"] and not room.publishing_allowed()


def test_actual_native_endpoint_cannot_reserve_during_entry_even_with_current_generation(tmp_path):
    async def scenario():
        observing, release = asyncio.Event(), asyncio.Event()
        async def idle():
            observing.set()
            await release.wait()
            return {"ready": True}
        room = RehearsalService(tmp_path / "rehearsal.json", idle_provider=idle)
        entry = asyncio.create_task(room.enter("enter-1", 0))
        await asyncio.wait_for(observing.wait(), 5)
        admission = DesktopAdmission(True)
        admission.native_encoding = NativeEncodingState(pid_probe=lambda _: True)
        payload = {"pid": os.getpid(), "server_session_id": "synthetic-backend", "active": True,
                   "owner_pid": 42, "mode": "rehearsal", "rehearsal_generation": room.snapshot()["generation"]}
        namespace = functions({"desktop_encoding_status"}, {
            "Request": object, "DESKTOP_ADMISSION": admission, "os": os, "SERVER_SESSION_ID": "synthetic-backend",
            "is_loopback_client": lambda host: host == "127.0.0.1", "rehearsal_service": room,
            "_read_bounded_json": AsyncMock(side_effect=lambda *_: dict(payload)),
        })
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        try:
            with pytest.raises(RehearsalError, match="rehearsal_generation_conflict"):
                await namespace["desktop_encoding_status"](request)
            payload["mode"] = "broadcast"
            with pytest.raises(RehearsalError, match="rehearsal_publishing_blocked"):
                await namespace["desktop_encoding_status"](request)
            assert not admission.native_encoding.snapshot()["active"]
        finally:
            release.set()
            await entry
    asyncio.run(scenario())
