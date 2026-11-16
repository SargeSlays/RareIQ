"""Lifecycle checks inject fake listeners; no sockets, cameras or server imports."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from rareiq.web.guest_ingress_lifecycle import GuestIngressLifecycle


ORIGIN = "https://guests.example.test"
ENV = {"PRODUCER_GUEST_INGRESS_PORT": "8766", "RAREIQ_PORT": "8765"}


async def app(scope, receive, send):
    pass


class Listener:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True
    async def wait_closed(self):
        assert self.closed


class FakeServer:
    def __init__(self, *, mode="ready"):
        self.mode = mode
        self.started = self.should_exit = self.force_exit = False
        self.finished = False
        self.crash = asyncio.Event()
        self.servers = [Listener()]
        self.server_state = SimpleNamespace(connections=set(), tasks=set())
    async def serve(self):
        try:
            if self.mode == "bind_failure":
                raise SystemExit(1)
            if self.mode == "exception":
                raise OSError("fixture bind failure")
            if self.mode == "early_exit":
                return
            if self.mode == "startup_hang":
                await asyncio.Event().wait()
            self.started = True
            if self.mode == "shutdown_hang":
                await asyncio.Event().wait()
            while not self.should_exit:
                if self.crash.is_set():
                    raise RuntimeError("fixture listener lost")
                await asyncio.sleep(.001)
        finally:
            self.finished = True


def manager(*, environment=ENV, origin=ORIGIN, mode="ready"):
    calls, servers = [], []
    def factory(shared_app, **kwargs):
        calls.append((shared_app, kwargs))
        server = FakeServer(mode=mode)
        servers.append(server)
        return server
    result = GuestIngressLifecycle(app, public_origin=origin, environment=environment,
                                   server_factory=factory, startup_timeout=.04, shutdown_timeout=.04)
    return result, calls, servers


@pytest.mark.parametrize("environment", [{}, {"PRODUCER_GUEST_INGRESS_PORT": ""}])
def test_absent_setting_never_constructs_or_starts_server(environment):
    async def check():
        value, calls, _ = manager(environment=environment)
        assert (await value.start())["state"] == "disabled"
        await value.close()
        assert not calls and value.task is None and not value.snapshot()["public_verified"]
    asyncio.run(check())


@pytest.mark.parametrize("environment,origin", [
    ({"PRODUCER_GUEST_INGRESS_PORT": "8765"}, ORIGIN),
    ({"PRODUCER_GUEST_INGRESS_PORT": "80"}, ORIGIN),
    ({"PRODUCER_GUEST_INGRESS_PORT": "65536"}, ORIGIN),
    ({"PRODUCER_GUEST_INGRESS_PORT": "0.0.0.0:8766"}, ORIGIN),
    ({"PRODUCER_GUEST_INGRESS_PORT": " 8766"}, ORIGIN),
    ({"PRODUCER_GUEST_INGRESS_PORT": "8766", "RAREIQ_PORT": "invalid"}, ORIGIN),
    (ENV, ""), (ENV, "http://guests.example.test"), (ENV, "https://guests.example.test/path"),
])
def test_invalid_explicit_configuration_is_unavailable_without_activation(environment, origin):
    async def check():
        value, calls, _ = manager(environment=environment, origin=origin)
        status = await value.start()
        assert status["state"] == "unavailable" and status["reason"] == "invalid_host_configuration"
        assert not status["available"] and not calls
        await value.close()
    asyncio.run(check())


def test_same_app_starts_once_and_closes_secondary_transports():
    async def check():
        value, calls, servers = manager()
        assert not calls
        status = await value.start()
        assert status["state"] == "listening" and status["available"]
        assert not status["public_verified"] and status["bind"] == "loopback"
        await value.start()
        assert calls == [(app, {"public_origin": ORIGIN, "port": 8766, "operator_port": 8765})]
        await value.close()
        await value.close()
        assert value.snapshot()["state"] == "stopped"
        assert servers[0].finished and servers[0].should_exit and servers[0].servers[0].closed
        assert value.task.done()
    asyncio.run(check())


@pytest.mark.parametrize("mode,reason", [("bind_failure", "listener_failed"), ("exception", "listener_failed"),
    ("early_exit", "listener_exited"), ("startup_hang", "listener_start_timeout")])
def test_start_failure_never_terminates_main_loop_or_claims_ready(mode, reason):
    async def check():
        value, _, servers = manager(mode=mode)
        status = await asyncio.wait_for(value.start(), .5)
        assert status["state"] == "unavailable" and status["reason"] == reason
        assert not status["available"] and not status["public_verified"]
        await value.close()
        assert servers[0].servers[0].closed and value.task.done()
        assert (await asyncio.sleep(0, result="primary still running")) == "primary still running"
    asyncio.run(check())


def test_unexpected_exit_revokes_availability_and_closes_listener():
    async def check():
        value, _, servers = manager()
        await value.start()
        servers[0].crash.set()
        await asyncio.wait_for(value.task, .5)
        assert value.snapshot()["state"] == "unavailable" and not value.snapshot()["available"]
        assert servers[0].servers[0].closed
        await value.close()
    asyncio.run(check())


def test_hung_shutdown_is_bounded_and_cleans_secondary_requests_only():
    async def check():
        value, _, servers = manager(mode="shutdown_hang")
        await value.start()
        primary = asyncio.create_task(asyncio.sleep(10))
        secondary = asyncio.create_task(asyncio.sleep(10))
        servers[0].server_state.tasks.add(secondary)
        try:
            await asyncio.wait_for(value.close(), .5)
            assert servers[0].force_exit and servers[0].servers[0].closed and secondary.cancelled()
            assert not primary.done()
        finally:
            primary.cancel()
            await asyncio.gather(primary, return_exceptions=True)
    asyncio.run(check())


def test_server_lifespan_attaches_same_app_and_closes_before_studio_dependencies():
    # Validate integration without importing the real camera-owning server module.
    path = Path(__file__).parents[1] / "rareiq/web/server.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lifespan = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    text = ast.unparse(lifespan)
    assert "GuestIngressLifecycle(_app, public_origin=greenroom_network.public_origin)" in text
    assert "greenroom_hub.ingress_status = guest_ingress.snapshot" in text
    assert text.index("await guest_ingress.start()") < text.index("yield")
    assert text.index("await guest_ingress.close()") < text.index("await twitch_audience_connector.close()")
