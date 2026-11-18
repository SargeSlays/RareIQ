"""Native desktop contracts without importing the app or accessing devices/PIDs."""
from __future__ import annotations

import ast
import asyncio
from contextlib import nullcontext
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from rareiq.web.desktop_lifecycle import DesktopAdmission, NativeEncodingState, native_output_readiness

SERVER = Path(__file__).resolve().parents[1] / "rareiq/web/server.py"


def functions(names, namespace):
    nodes = [node for node in ast.parse(SERVER.read_text(encoding="utf-8")).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


def peer(**changes):
    values = dict(role="output", ready={"image:one": 99.0}, playback_generation=7,
                  playback_reported_at=99.0, audio_blocked=False,
                  playback_rendered=True, rendered_generation=7)
    values.update(changes)
    return SimpleNamespace(**values)


def output(peers, *, target="captured", sources=None, now=100.0):
    return native_output_readiness(peers, output_peer_id=target, generation=7,
                                   sources=sources or ["image:one"], now=now)


@pytest.mark.parametrize("changes", [{"role": "producer"}, {"ready": {}},
    {"ready": {"image:one": 94.0}}, {"playback_generation": 6},
    {"playback_reported_at": 94.0}, {"playback_reported_at": 101.0},
    {"audio_blocked": True}, {"playback_rendered": False}, {"rendered_generation": 6}])
def test_native_preflight_rejects_stale_incomplete_or_blocked_exact_output(changes):
    assert output({"captured": peer(**changes)})["ready"] is False


def test_native_output_does_not_borrow_receipts_or_sources_from_another_window():
    peers = {"captured": peer(rendered_generation=-1), "other": peer(ready={})}
    assert not output(peers)["ready"]
    assert not output(peers, target="other")["ready"]
    peers["other"] = peer()
    assert not output(peers)["ready"]
    assert output(peers, target="other")["ready"]
    assert not output(peers, target=None)["ready"]


def test_camera_only_output_still_requires_its_fresh_rendered_receipt():
    assert output({"captured": peer(ready={})}, sources=["camera:1"])["ready"]
    assert not output({"captured": peer(ready={}, playback_rendered=False)}, sources=["camera:1"])["ready"]


def test_live_owner_never_expires_and_unknown_probe_does_not_clear_encoding():
    probe = Mock(return_value=True)
    state = NativeEncodingState(pid_probe=probe)
    assert state.update(active=True, owner_pid=42)["ok"]
    assert state.snapshot() == {"active": True, "owner_pid": 42, "owner_alive": True}
    probe.return_value = None
    assert state.snapshot() == {"active": True, "owner_pid": 42, "owner_alive": None}
    probe.side_effect = OSError("not inspectable")
    assert state.snapshot()["active"] is True


def test_confirmed_dead_owner_recovers_but_another_live_main_cannot_clear_claim():
    alive = {42: True, 43: True}
    state = NativeEncodingState(pid_probe=lambda pid: alive.get(pid))
    state.update(active=True, owner_pid=42)
    for active in (True, False):
        assert state.update(active=active, owner_pid=43)["reason"] == "encoding_owner_mismatch"
    alive[42] = False
    assert state.snapshot() == {"active": False, "owner_pid": None, "owner_alive": None}
    assert state.update(active=True, owner_pid=43)["ok"]
    assert state.update(active=False, owner_pid=43)["native_encoding"]["active"] is False


@pytest.mark.parametrize("active,owner", [(1, 42), ("true", 42), (True, None),
    (True, True), (True, 0), (True, -1), (True, 2**32)])
def test_encoding_claim_requires_explicit_boolean_and_bounded_main_pid(active, owner):
    state = NativeEncodingState(pid_probe=lambda _pid: True)
    assert state.update(active=active, owner_pid=owner)["reason"] == "invalid_encoding_status"
    assert not state.snapshot()["active"]


@pytest.mark.parametrize("alive,reason", [(False, "owner_not_running"), (None, "owner_state_unknown")])
def test_unverified_owner_cannot_reserve_encoding(alive, reason):
    assert NativeEncodingState(pid_probe=lambda _pid: alive).update(active=True, owner_pid=42)["reason"] == reason


def test_native_ownership_blocks_real_stop_before_any_obs_probe():
    guard = DesktopAdmission(True)
    guard.native_encoding = NativeEncodingState(pid_probe=lambda _pid: True)
    guard.native_encoding.update(active=True, owner_pid=42)
    ns = functions({"_desktop_idle_reason", "desktop_stop"}, dict(
        DESKTOP_ADMISSION=guard, Request=object, os=os, SERVER_SESSION_ID="backend",
        is_loopback_client=lambda _host: True,
        _read_bounded_json=AsyncMock(return_value={"pid": os.getpid(), "server_session_id": "backend"}),
        system_shutdown=AsyncMock()))
    result = asyncio.run(ns["desktop_stop"](SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))))
    assert result["reason"] == "native_encoding_active" and not guard.closing
    ns["system_shutdown"].assert_not_called()


@pytest.mark.parametrize("changed,host,enabled,closing,reason", [
    ({"pid": 99999}, "127.0.0.1", True, False, "identity_mismatch"),
    ({"server_session_id": "old"}, "127.0.0.1", True, False, "identity_mismatch"),
    ({}, "192.0.2.1", True, False, "local_request_required"),
    ({}, "127.0.0.1", False, False, "desktop_mode_required"),
    ({}, "127.0.0.1", True, True, "desktop_closing"),
])
def test_real_encoding_endpoint_guards_backend_identity_and_local_desktop_mode(changed, host, enabled, closing, reason):
    guard = DesktopAdmission(enabled)
    guard.closing = closing
    guard.native_encoding = Mock()
    payload = {"pid": os.getpid(), "server_session_id": "backend", "active": True, "owner_pid": 42, **changed}
    ns = functions({"desktop_encoding_status"}, dict(DESKTOP_ADMISSION=guard, Request=object,
        os=os, SERVER_SESSION_ID="backend", is_loopback_client=lambda host: host == "127.0.0.1",
        _read_bounded_json=AsyncMock(return_value=payload)))
    result = asyncio.run(ns["desktop_encoding_status"](SimpleNamespace(client=SimpleNamespace(host=host))))
    assert result["reason"] == reason
    guard.native_encoding.update.assert_not_called()


def native_namespace(*, enabled=True):
    guard = DesktopAdmission(enabled)
    guard.native_encoding = NativeEncodingState(pid_probe=lambda _pid: True)
    state = {"generation": 7, "program_slot": 1, "program_sources": ["image:one"]}
    ns = dict(DESKTOP_ADMISSION=guard, Query=lambda **kwargs: kwargs["default"],
        PRODUCTION_SWITCHER_LOCK=nullcontext(), PRODUCTION_SWITCHER_STATE=state,
        composition_state=lambda value: dict(value),
        orchestrator=SimpleNamespace(camera_manager=SimpleNamespace(camera_slots=Mock(return_value=[]))),
        _program_composition_readiness=Mock(return_value={"ready": True, "reason": "composition_ready"}),
        greenroom_hub=SimpleNamespace(peers={"captured": peer()}), native_output_readiness=native_output_readiness,
        time=SimpleNamespace(monotonic=lambda: 100.0))
    return functions({"production_native_preflight"}, ns)


def test_real_native_preflight_is_read_only_exact_output_proof_without_obs_or_card_services():
    ns = native_namespace()
    result = asyncio.run(ns["production_native_preflight"]("captured"))
    assert result["preflight"]["ready"] is True
    assert result["preflight"]["generation"] == 7
    assert result["preflight"]["output"]["peer_id"] == "captured"
    assert result["platform_live_verified"] is False
    assert result["native_encoding"]["active"] is False
    assert not asyncio.run(ns["production_native_preflight"]())["preflight"]["ready"]


def test_existing_web_server_cannot_be_silently_promoted_to_native_mode():
    ns = native_namespace(enabled=False)
    result = asyncio.run(ns["production_native_preflight"]("captured"))
    assert result["reason"] == "desktop_mode_required" and not result["preflight"]["ready"]
    ns["orchestrator"].camera_manager.camera_slots.assert_not_called()


def test_actual_source_availability_and_generation_changes_block_native_start():
    ns = native_namespace()
    ns["_program_composition_readiness"].return_value = {"ready": False, "reason": "image_source_unavailable"}
    result = asyncio.run(ns["production_native_preflight"]("captured"))
    assert "image_source_unavailable" in result["preflight"]["blockers"]
    def change(*_args):
        ns["PRODUCTION_SWITCHER_STATE"]["generation"] = 8
        return {"ready": True}
    ns["_program_composition_readiness"].side_effect = change
    assert "program_changed" in asyncio.run(ns["production_native_preflight"]("captured"))["preflight"]["blockers"]


def test_production_session_exposes_native_reservation_without_changing_business_state():
    guard = DesktopAdmission(True)
    guard.native_encoding = NativeEncodingState(pid_probe=lambda _pid: True)
    guard.native_encoding.update(active=True, owner_pid=42)
    state = {"active": False, "session_id": "show", "recording": {"active": False}}
    ns = functions({"production_session_status"}, dict(DESKTOP_ADMISSION=guard,
        PRODUCTION_SESSION_LOCK=nullcontext(), PRODUCTION_SESSION=state,
        recording=SimpleNamespace(status=lambda: {"active": False, "session_id": "show"})))
    result = asyncio.run(ns["production_session_status"]())
    assert result["native_encoding"] == {"active": True, "owner_pid": 42, "owner_alive": True}
    assert result["session"]["active"] is False
