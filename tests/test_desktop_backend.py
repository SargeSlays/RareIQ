from __future__ import annotations

import ast
import asyncio
from contextlib import asynccontextmanager, nullcontext, suppress
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tools import desktop_backend as desktop
from rareiq.web.desktop_lifecycle import DesktopAdmission, DesktopAdmissionMiddleware

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "rareiq/web/server.py"


@pytest.fixture
def backend(tmp_path, monkeypatch):
    for name in desktop.GUEST_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    project = (tmp_path / "project").resolve()
    receipt = tmp_path / "desktop/owner.json"
    managed = tmp_path / "server/state.json"
    running = {"state": "running", "managed": True, "healthy": True,
               "url": desktop.ORIGIN, "bind_host": "127.0.0.1", "remote_access": False,
               "pid": 1234, "server_session_id": "session-one"}
    current = {"state": "stopped"}
    monkeypatch.setattr(desktop.control, "_resolved_paths", lambda *_: (managed, managed.parent))
    monkeypatch.setattr(desktop.control, "_control_lock", lambda *_: nullcontext())
    monkeypatch.setattr(desktop.control, "server_status", lambda *_a, **_k: dict(current))
    started = Mock()

    def fake_start(*args, **kwargs):
        assert os.environ["PRODUCER_DESKTOP"] == "1"
        assert kwargs["open_browser"] is False and kwargs["remote_access"] is False
        assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 8765
        assert kwargs["_lock_held"] is True
        started(*args, **kwargs)
        current.update(running)
        return {**current, "started": True, "stdout_log": "private-path"}

    monkeypatch.setattr(desktop.control, "start_server", fake_start)
    monkeypatch.setattr(desktop.control, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(desktop.control, "_remove_state", Mock())
    stop_request = Mock(return_value={"ok": True, "stopping": True})
    monkeypatch.setattr(desktop, "_request_stop", stop_request)
    return SimpleNamespace(project=project, receipt=receipt, current=current, running=running,
                           started=started, stop_request=stop_request)


def test_start_owns_only_new_managed_loopback_and_restores_environment(backend, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "previous")
    result = desktop.start(backend.project, backend.receipt)
    assert result == {"ok": True, "origin": desktop.ORIGIN, "owned": True, "running": True,
        "state": "running", "reason": "started", "identity": {"pid": 1234, "server_session_id": "session-one"}}
    assert os.environ["PRODUCER_DESKTOP"] == "previous"
    assert desktop.status(backend.project, backend.receipt)["owned"] is True
    assert "private-path" not in json.dumps(result)


def _guest_configuration(backend, **changes):
    value = {"version": 1, "enabled": True, "operator_port": 8765,
             "guest_port": 8766, "https_origin": "https://guests.example.test:8445"}
    value.update(changes)
    path = backend.receipt.parent / 'guest-ingress.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_saved_guest_pair_reaches_child_only_during_fresh_start(backend, monkeypatch):
    _guest_configuration(backend)
    original = desktop.control.start_server
    observed = []
    def child(*args, **kwargs):
        observed.append({name: os.environ.get(name) for name in desktop.GUEST_ENVIRONMENT})
        return original(*args, **kwargs)
    monkeypatch.setattr(desktop.control, 'start_server', child)
    assert desktop.start(backend.project, backend.receipt)['owned'] is True
    assert observed == [dict(zip(desktop.GUEST_ENVIRONMENT, ('8766', 'https://guests.example.test:8445')))]
    assert all(name not in os.environ for name in desktop.GUEST_ENVIRONMENT)
    # Existing backends are reused, even if next-launch configuration is invalid.
    _guest_configuration(backend, guest_port=8765)
    monkeypatch.setenv(desktop.GUEST_ENVIRONMENT[0], 'partial')
    assert desktop.start(backend.project, backend.receipt)['reason'] == 'reused'
    assert len(observed) == 1


@pytest.mark.parametrize('fail', [False, True])
def test_explicit_guest_pair_overrides_file_and_is_restored_after_child(backend, monkeypatch, fail):
    _guest_configuration(backend, operator_port=9999)
    pair = dict(zip(desktop.GUEST_ENVIRONMENT, ('9876', 'https://explicit.example.test:8445/')))
    for name, value in pair.items():
        monkeypatch.setenv(name, value)
    original = desktop.control.start_server
    def child(*args, **kwargs):
        assert os.environ[desktop.GUEST_ENVIRONMENT[0]] == '9876'
        assert os.environ[desktop.GUEST_ENVIRONMENT[1]] == 'https://explicit.example.test:8445'
        if fail:
            raise RuntimeError('synthetic child failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(desktop.control, 'start_server', child)
    if fail:
        with pytest.raises(RuntimeError):
            desktop.start(backend.project, backend.receipt)
    else:
        desktop.start(backend.project, backend.receipt)
    assert {name: os.environ.get(name) for name in desktop.GUEST_ENVIRONMENT} == pair


def test_saved_guest_pair_is_removed_after_failed_child(backend, monkeypatch):
    _guest_configuration(backend)
    def child(*_args, **_kwargs):
        assert os.environ[desktop.GUEST_ENVIRONMENT[0]] == '8766'
        raise RuntimeError('synthetic child failure')
    monkeypatch.setattr(desktop.control, 'start_server', child)
    with pytest.raises(RuntimeError):
        desktop.start(backend.project, backend.receipt)
    assert all(name not in os.environ for name in desktop.GUEST_ENVIRONMENT)


@pytest.mark.parametrize('origin,fail', [(None, False), ('', False), ('https://stale.example.test:8445', True)])
def test_explicit_empty_guest_port_disables_saved_pair_and_restores_environment(backend, monkeypatch, origin, fail):
    _guest_configuration(backend)
    monkeypatch.setenv(desktop.GUEST_ENVIRONMENT[0], '')
    if origin is not None:
        monkeypatch.setenv(desktop.GUEST_ENVIRONMENT[1], origin)
    previous = {name: os.environ.get(name) for name in desktop.GUEST_ENVIRONMENT}
    original = desktop.control.start_server
    def child(*args, **kwargs):
        assert all(name not in os.environ for name in desktop.GUEST_ENVIRONMENT)
        if fail:
            raise RuntimeError('synthetic child failure')
        return original(*args, **kwargs)
    monkeypatch.setattr(desktop.control, 'start_server', child)
    if fail:
        with pytest.raises(RuntimeError):
            desktop.start(backend.project, backend.receipt)
    else:
        desktop.start(backend.project, backend.receipt)
    assert {name: os.environ.get(name) for name in desktop.GUEST_ENVIRONMENT} == previous


@pytest.mark.parametrize('enabled', [None, False])
def test_guest_configuration_absent_or_disabled_adds_no_environment(backend, monkeypatch, enabled):
    if enabled is False:
        _guest_configuration(backend, enabled=False)
    original = desktop.control.start_server
    def child(*args, **kwargs):
        assert all(name not in os.environ for name in desktop.GUEST_ENVIRONMENT)
        return original(*args, **kwargs)
    monkeypatch.setattr(desktop.control, 'start_server', child)
    desktop.start(backend.project, backend.receipt)


@pytest.mark.parametrize('name', desktop.GUEST_ENVIRONMENT)
def test_partial_explicit_guest_pair_rejects_before_start(backend, monkeypatch, name):
    _guest_configuration(backend)
    monkeypatch.setenv(name, '8766' if name.endswith('PORT') else 'https://guests.example.test')
    with pytest.raises(ValueError, match='pair_required'):
        desktop.start(backend.project, backend.receipt)
    backend.started.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'operator_port': 8767}, {'operator_port': True}, {'version': True}, {'version': 2},
    {'guest_port': 8765}, {'guest_port': 1023}, {'guest_port': 65536}, {'guest_port': True}, {'guest_port': '8766'},
    {'enabled': 'yes'}, {'https_origin': 'http://guests.example.test'},
    {'https_origin': 'https://user:password@guests.example.test'},
    {'https_origin': 'https://guests.example.test/path'}, {'https_origin': 'https://guests.example.test?q=1'},
    {'https_origin': 'https://guests.example.test#fragment'}, {'https_origin': 'https://guests.example.test:70000'},
    {'https_origin': None}, {'unexpected': 'field'},
])
def test_invalid_saved_guest_configuration_never_spawns(backend, changes):
    _guest_configuration(backend, **changes)
    with pytest.raises(ValueError, match='invalid_guest_ingress_configuration'):
        desktop.start(backend.project, backend.receipt)
    backend.started.assert_not_called()


def test_relaunch_reuses_and_never_inherits_old_shutdown_authority(backend):
    desktop.start(backend.project, backend.receipt)
    reused = desktop.start(backend.project, backend.receipt)
    assert reused["owned"] is False and reused["reason"] == "reused"
    assert backend.started.call_count == 1
    result = desktop.stop(backend.project, backend.receipt)
    assert result["running"] is True and result["reason"] == "not_owned"
    backend.stop_request.assert_not_called()


@pytest.mark.parametrize("changed", [{"pid": 9999}, {"server_session_id": "other"},
    {"state": "unmanaged"}, {"state": "conflict"}, {"state": "unhealthy"}])
def test_stop_never_touches_replaced_or_unverified_server(backend, changed):
    desktop.start(backend.project, backend.receipt)
    backend.current.update(changed)
    assert desktop.stop(backend.project, backend.receipt)["owned"] is False
    backend.stop_request.assert_not_called()


@pytest.mark.parametrize("changed", [{"url": "http://127.0.0.1:9999"},
    {"bind_host": "0.0.0.0"}, {"remote_access": True}])
def test_start_rejects_managed_non_loopback_or_other_port(backend, changed):
    backend.current.update(backend.running, **changed)
    assert desktop.start(backend.project, backend.receipt)["ok"] is False
    backend.started.assert_not_called()


@pytest.mark.parametrize("state", ["unmanaged", "conflict", "unhealthy"])
def test_start_does_not_attempt_to_replace_unverified_port_owner(backend, state):
    backend.current.update(state=state, healthy=True)
    result = desktop.start(backend.project, backend.receipt)
    assert result["ok"] is False and result["running"] is True
    backend.started.assert_not_called()


def test_owned_idle_stop_is_one_use_and_removes_only_managed_state(backend):
    desktop.start(backend.project, backend.receipt)
    stopped = desktop.stop(backend.project, backend.receipt)
    assert stopped["state"] == "stopped" and stopped["owned"] is False and stopped["running"] is False
    backend.stop_request.assert_called_once_with({"pid": 1234, "server_session_id": "session-one"}, 8.0, port=8765)
    desktop.control._remove_state.assert_called_once()
    assert json.loads(backend.receipt.read_text())["consumed"] is True
    desktop.stop(backend.project, backend.receipt)
    assert backend.stop_request.call_count == 1


@pytest.mark.parametrize("response,reason", [(None, "shutdown_not_confirmed"),
    ({"stopping": False, "reason": "clients_connected"}, "clients_connected"),
    ({"stopping": False, "reason": "obs_not_confirmed_idle"}, "obs_not_confirmed_idle"),
    ({"stopping": False, "reason": "native_encoding_active"}, "native_encoding_active"),
    ({"stopping": False, "reason": "secret-private-data"}, "shutdown_not_confirmed")])
def test_busy_unknown_and_private_errors_keep_backend_running(backend, response, reason):
    desktop.start(backend.project, backend.receipt)
    backend.stop_request.return_value = response
    result = desktop.stop(backend.project, backend.receipt)
    assert result["running"] is True and result["reason"] == reason
    desktop.control._remove_state.assert_not_called()
    assert desktop.status(backend.project, backend.receipt)["owned"] is False


def test_cli_stdout_is_exactly_sanitized_json(backend, monkeypatch, capsys):
    def noisy(*_a, **_k):
        print("normal storage initialization private-path")
        raise RuntimeError("credential-value")
    monkeypatch.setattr(desktop, "start", noisy)
    assert desktop.main(["start", "--state-path", str(backend.receipt)]) == 1
    out = capsys.readouterr().out
    assert json.loads(out)["reason"] == "backend_control_failed"
    assert len(out.splitlines()) == 1 and "private" not in out and "credential" not in out


def _idle(guard, **changes):
    values = {"session": {"active": False}, "recording": {"active": False},
              "obs": {"enabled": True, "connected": True, "streaming": False, "recording": False}}
    values.update(changes)
    return guard.idle_reason(**values)


@pytest.mark.parametrize("values,reason", [({}, None),
    ({"session": {}}, "session_not_idle"), ({"session": {"active": True}}, "session_not_idle"),
    ({"recording": {"active": True}}, "recording_not_idle"),
    ({"recording": {"active": False, "stopping": True}}, "recording_not_idle"),
    ({"obs": {"connected": False, "streaming": False, "recording": False}}, "obs_not_confirmed_idle"),
    ({"obs": {"connected": True, "streaming": True, "recording": False}}, "obs_not_confirmed_idle")])
def test_idle_requires_explicit_production_and_obs_evidence(values, reason):
    assert _idle(DesktopAdmission(True), **values) == reason


@pytest.mark.parametrize("scope", [
    {"type": "websocket", "path": "/guest/ws"},
    {"type": "websocket", "path": "/ws/output/camera/1"},
    {"type": "http", "method": "GET", "path": "/api/camera-slots/1/stream"},
    {"type": "http", "method": "GET", "path": "/api/output/soundboard/events"},
    {"type": "http", "method": "POST", "path": "/api/production/session/start"},
])
def test_clients_and_commands_reserve_before_dispatch_and_release_on_cancel(scope):
    async def exercise():
        guard, entered = DesktopAdmission(True), asyncio.Event()
        async def application(*_args):
            entered.set()
            await asyncio.Future()
        middleware = DesktopAdmissionMiddleware(application, guard)
        task = asyncio.create_task(middleware(scope, AsyncMock(), AsyncMock()))
        await entered.wait()
        assert _idle(guard) in {"clients_connected", "operation_in_progress"}
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert _idle(guard) is None
    asyncio.run(exercise())


def test_closing_rejects_new_output_and_mutation_in_both_desktop_and_legacy_modes():
    async def exercise():
        application, send = AsyncMock(), AsyncMock()
        guard = DesktopAdmission(True)
        guard.closing = True
        middleware = DesktopAdmissionMiddleware(application, guard)
        await middleware({"type": "http", "method": "POST", "path": "/api/production/session/start"}, AsyncMock(), send)
        assert send.call_args_list[0].args[0]["status"] == 503
        await middleware({"type": "websocket", "path": "/guest/ws"}, AsyncMock(), send)
        assert send.call_args.args[0]["type"] == "websocket.close"
        application.assert_not_called()
        guard.enabled = False
        await middleware({"type": "websocket", "path": "/guest/ws"}, AsyncMock(), send)
        application.assert_not_called()
    asyncio.run(exercise())


def _server_functions(names, namespace):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(selected) == len(names)
    for node in selected:
        node.decorator_list = []
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SERVER), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("desktop_mode", [True, False])
def test_real_lifespan_skips_only_desktop_eager_work(monkeypatch, desktop_mode):
    monkeypatch.setenv("PRODUCER_DESKTOP", "1" if desktop_mode else "0")
    fake = lambda: SimpleNamespace(start=Mock(), stop=Mock(), close=AsyncMock())
    orchestrator = SimpleNamespace(set_loop=Mock(), boot_manager=SimpleNamespace(run=Mock()),
        recognition=SimpleNamespace(warm_ocr=Mock()), camera_manager=SimpleNamespace(shutdown=Mock()),
        master_database_builder=SimpleNamespace(refresh_new_releases=Mock()))
    ingress = SimpleNamespace(start=AsyncMock(), close=AsyncMock(), snapshot=Mock())
    namespace = dict(os=os, asyncio=asyncio, FastAPI=object, suppress=suppress,
        orchestrator=orchestrator, greenroom_service=SimpleNamespace(reset_runtime=Mock()),
        production_scene_store=SimpleNamespace(snapshot=lambda: {"scenes": []}), PRODUCTION_SCENES=[],
        instant_replay=fake(), auto_clip=fake(), recording=fake(), voice_commands=SimpleNamespace(close=Mock()),
        GuestIngressLifecycle=lambda *_a, **_k: ingress, greenroom_network=SimpleNamespace(public_origin=None),
        greenroom_hub=SimpleNamespace(), twitch_audience_connector=fake(), youtube_audience_connector=fake(),
        kick_audience_connector=fake(), viewer_chat_service=SimpleNamespace(set_listening=Mock()),
        twitch_account_service=fake(), youtube_account_service=fake(), kick_account_service=fake(), CATALOG_REFRESH_INTERVAL_SECONDS=3600)
    created = []
    def create_task(coroutine):
        created.append(coroutine.cr_code.co_name)
        return asyncio.create_task(coroutine)
    namespace["asyncio"] = SimpleNamespace(create_task=create_task, sleep=asyncio.sleep,
        to_thread=asyncio.to_thread, get_running_loop=asyncio.get_running_loop,
        CancelledError=asyncio.CancelledError)
    _server_functions({"lifespan"}, namespace)
    async def exercise():
        async with asynccontextmanager(namespace["lifespan"])(SimpleNamespace(state=SimpleNamespace())):
            await asyncio.sleep(0.4)
    asyncio.run(exercise())
    expected = 0 if desktop_mode else 1
    assert orchestrator.boot_manager.run.call_count == expected
    assert orchestrator.recognition.warm_ocr.call_count == expected
    assert namespace["instant_replay"].start.call_count == expected
    assert namespace["auto_clip"].start.call_count == expected
    assert created == ([] if desktop_mode else ["boot_in_background", "warm_recognition_ocr", "refresh_new_releases"])
    orchestrator.camera_manager.shutdown.assert_called_once()
    ingress.close.assert_awaited_once()
    namespace["viewer_chat_service"].set_listening.assert_called_once_with(False)
    namespace["twitch_account_service"].close.assert_awaited_once()
    namespace["youtube_account_service"].close.assert_awaited_once()
    namespace["kick_account_service"].close.assert_awaited_once()


def test_real_guarded_stop_rechecks_clients_after_slow_obs_and_seals_admission():
    async def exercise():
        guard = DesktopAdmission(True)
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_probe(function):
            entered.set()
            await release.wait()
            return function()
        identity = {"pid": os.getpid(), "server_session_id": "session-one"}
        namespace = dict(asyncio=SimpleNamespace(wait_for=asyncio.wait_for, to_thread=slow_probe),
            os=os, Request=object, SERVER_SESSION_ID="session-one",
            DESKTOP_ADMISSION=guard, PRODUCTION_SESSION_LOCK=nullcontext(), PRODUCTION_SESSION={"active": False},
            recording=SimpleNamespace(status=lambda: {"active": False}),
            obs=SimpleNamespace(status=lambda: {"enabled": True, "connected": True, "streaming": False, "recording": False}),
            is_loopback_client=lambda host: host == "127.0.0.1",
            _read_bounded_json=AsyncMock(return_value=identity), _schedule_system_shutdown=Mock())
        _server_functions({"_desktop_idle_reason", "_request_idle_shutdown", "desktop_stop"}, namespace)
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        stopping = asyncio.create_task(namespace["desktop_stop"](request))
        await entered.wait()
        guard.clients = 1  # A guest connects while the external status read is pending.
        release.set()
        refused = await stopping
        assert refused["reason"] == "clients_connected" and not guard.closing
        namespace["_schedule_system_shutdown"].assert_not_called()
        guard.clients = 0
        assert (await namespace["desktop_stop"](request))["stopping"] is True
        assert guard.closing
        namespace["_schedule_system_shutdown"].assert_called_once()
    asyncio.run(exercise())
