"""Explicit, optional lifecycle for a same-process guest-only loopback listener."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import os
import re

from .guest_ingress import GuestOnlyIngress, create_guest_listener


class GuestIngressLifecycle:
    def __init__(self, shared_app, *, public_origin, environment=None,
                 server_factory=create_guest_listener, startup_timeout=3, shutdown_timeout=7):
        env = os.environ if environment is None else environment
        self.app, self.public_origin, self.factory = shared_app, public_origin, server_factory
        self.startup_timeout, self.shutdown_timeout = startup_timeout, shutdown_timeout
        self.server, self.task = None, None
        self._closing, self._started_once = False, False
        self.port, self.operator_port = None, None
        self.state, self.reason = "disabled", None
        configured = env.get("PRODUCER_GUEST_INGRESS_PORT", "")
        self.configured = bool(configured)
        if not self.configured:
            return
        try:
            operator = env.get("RAREIQ_PORT", "8765")
            if (not isinstance(configured, str) or not re.fullmatch(r"[0-9]{1,5}", configured)
                    or not isinstance(operator, str) or not re.fullmatch(r"[0-9]{1,5}", operator)):
                raise ValueError("invalid_port")
            self.port, self.operator_port = int(configured), int(operator)
            if not 1024 <= self.port <= 65535 or not 1 <= self.operator_port <= 65535 or self.port == self.operator_port:
                raise ValueError("invalid_port")
            GuestOnlyIngress(shared_app, public_origin=public_origin)  # Pure validation; no listener.
            self.state = "configured"
        except (ValueError, TypeError):
            self.state, self.reason = "unavailable", "invalid_host_configuration"

    def snapshot(self):
        return {"configured": self.configured, "state": self.state, "reason": self.reason,
                "available": self.state == "listening", "bind": "loopback", "port": self.port,
                "scope": "guest_only", "public_verified": False}

    def _unavailable(self, reason):
        self.state, self.reason = "unavailable", reason
        logging.getLogger(__name__).warning("Guest-only ingress unavailable: %s", reason)

    async def _close_transports(self):
        # Cancellation during Uvicorn startup can skip its normal shutdown path.
        # Touch only this secondary server's listeners, connections and requests.
        if self.server is None:
            return
        listeners = tuple(getattr(self.server, "servers", ()))
        for listener in listeners:
            with suppress(Exception):
                listener.close()
        state = getattr(self.server, "server_state", None)
        for connection in tuple(getattr(state, "connections", ())):
            with suppress(Exception):
                connection.shutdown()
        requests = tuple(getattr(state, "tasks", ()))
        for task in requests:
            task.cancel()
        waits = [listener.wait_closed() for listener in listeners]
        if requests or waits:
            with suppress(asyncio.TimeoutError, Exception):
                async with asyncio.timeout(.5):
                    await asyncio.gather(*requests, *waits, return_exceptions=True)

    async def _run(self):
        try:
            await self.server.serve()
            if not self._closing:
                self._unavailable("listener_exited")
        except asyncio.CancelledError:
            raise
        except (Exception, SystemExit):
            # Uvicorn uses SystemExit for bind failure; do not let a secondary
            # port failure terminate the primary studio event loop.
            if not self._closing:
                self._unavailable("listener_failed")
        finally:
            await self._close_transports()

    async def start(self):
        if self._started_once:
            return self.snapshot()
        self._started_once = True
        if self.state != "configured":
            if self.configured:
                self._unavailable(self.reason or "invalid_host_configuration")
            return self.snapshot()
        self.state = "starting"
        try:
            self.server = self.factory(self.app, public_origin=self.public_origin,
                                       port=self.port, operator_port=self.operator_port)
            self.task = asyncio.create_task(self._run(), name="guest-only-ingress")
            async with asyncio.timeout(self.startup_timeout):
                while not self.task.done() and not self.server.started:
                    await asyncio.sleep(.01)
            if self.task.done() or self.state == "unavailable":
                if self.state != "unavailable":
                    self._unavailable("listener_exited")
                return self.snapshot()
            self.state, self.reason = "listening", None
            logging.getLogger(__name__).info("Guest-only loopback listener started; public reachability is unverified")
        except asyncio.TimeoutError:
            self._unavailable("listener_start_timeout")
            await self._stop(graceful=False)
        except (Exception, SystemExit):
            self._unavailable("listener_failed")
            await self._stop(graceful=False)
        return self.snapshot()

    async def _stop(self, *, graceful=True):
        self._closing = True
        if self.server is not None:
            self.server.should_exit = True
        if self.task is not None and not self.task.done():
            if not graceful:
                self.server.force_exit = True
                self.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self.task), self.shutdown_timeout if graceful else 1)
            except asyncio.CancelledError:
                if not self.task.cancelled():
                    raise
            except asyncio.TimeoutError:
                self.server.force_exit = True
                self.task.cancel()
                with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(self.task, 1)
        if self.task is not None and self.task.done():
            with suppress(asyncio.CancelledError):
                self.task.result()
        await self._close_transports()

    async def close(self):
        await self._stop()
        if self.state != "unavailable" and self.configured:
            self.state, self.reason = "stopped", None
