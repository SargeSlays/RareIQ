"""Desktop-only admission and idle checks; no device or application imports."""
from __future__ import annotations

import ctypes
import os


def process_alive(pid):
    """True/False only for observed process state; access/probe errors are unknown."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False if ctypes.get_last_error() == 87 else None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


class NativeEncodingState:
    """Main-process ownership claim, not proof of media or platform receipt.

    No heartbeat expiry: a live or uninspectable owner continues to block close.
    Main must clear its claim only after its encoder has actually stopped.
    """
    def __init__(self, *, pid_probe=process_alive):
        self._pid_probe = pid_probe
        self._owner_pid = None

    def _alive(self, pid):
        try:
            return self._pid_probe(pid)
        except Exception:
            return None

    def snapshot(self):
        alive = self._alive(self._owner_pid) if self._owner_pid is not None else None
        if alive is False:
            self._owner_pid = None
        return {"active": self._owner_pid is not None, "owner_pid": self._owner_pid,
                "owner_alive": alive if self._owner_pid is not None else None}

    def update(self, *, active, owner_pid=None):
        current = self.snapshot()
        reason = None
        if type(active) is not bool or type(owner_pid) is not int or not 0 < owner_pid < 2**32:
            reason = "invalid_encoding_status"
        elif current["active"] and owner_pid != self._owner_pid:
            reason = "encoding_owner_mismatch"
        elif active:
            alive = self._alive(owner_pid)
            if alive is not True:
                reason = "owner_not_running" if alive is False else "owner_state_unknown"
            else:
                self._owner_pid = owner_pid
        else:
            self._owner_pid = None
        result = {"ok": reason is None, "native_encoding": self.snapshot()}
        if reason:
            result["reason"] = reason
        return result


def native_output_readiness(peers, *, output_peer_id, generation, sources, now):
    """Require source and rendered evidence from the specific captured output."""
    result = {"ready": False, "peer_id": output_peer_id,
              "rendered_generation": None, "reason": "output_not_identified"}
    peer = peers.get(output_peer_id) if isinstance(output_peer_id, str) else None
    if peer is None or peer.role != "output":
        return result
    result["reason"] = "output_not_rendered"
    required = {source for source in sources if not source.startswith("camera:")}
    fresh = {source for source, stamp in dict(peer.ready).items() if 0 <= now - stamp < 6}
    if (not required.issubset(fresh) or peer.playback_generation != generation
            or not 0 <= now - peer.playback_reported_at < 6 or peer.audio_blocked
            or not peer.playback_rendered or peer.rendered_generation != generation):
        return result
    return {**result, "ready": True, "rendered_generation": generation, "reason": None}


class DesktopAdmission:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.closing = False
        self.clients = 0
        self.mutations = 0
        self.native_encoding = NativeEncodingState()

    def idle_reason(self, *, session, recording, obs):
        if not self.enabled:
            return "desktop_mode_required"
        if self.native_encoding.snapshot()["active"]:
            return "native_encoding_active"
        if self.clients:
            return "clients_connected"
        if self.mutations:
            return "operation_in_progress"
        if session.get("active") is not False:
            return "session_not_idle"
        if recording.get("active") is not False or recording.get("stopping") is True:
            return "recording_not_idle"
        if (obs.get("connected") is not True
                or obs.get("streaming") is not False
                or obs.get("recording") is not False):
            return "obs_not_confirmed_idle"
        return None


class DesktopAdmissionMiddleware:
    """Count live outputs/guests and mutations; seal admission before shutdown.

    These counters and the close decision live on the server event loop. Ordinary
    page/status GETs are not considered active production. Streaming GETs are
    reserved before dispatch, including while acquiring a camera lease.
    """
    def __init__(self, app, admission):
        self.app, self.admission = app, admission

    async def __call__(self, scope, receive, send):
        guard = self.admission
        kind = scope["type"]
        if not guard.enabled or kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        desktop_control = path in {"/api/desktop/status", "/api/desktop/stop"}
        if guard.closing and not desktop_control:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1012})
            else:
                await send({"type": "http.response.start", "status": 503,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"ok":false,"reason":"desktop_closing"}'})
            return
        client = (kind == "websocket" or path.endswith(("/stream", "/events"))
                  or path == "/api/camera/crop-stream")
        mutation = kind == "http" and scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and not desktop_control
        guard.clients += int(client)
        guard.mutations += int(mutation)

        async def tracked_send(message):
            nonlocal client
            # Also cover future streaming endpoints without relying on a URL list.
            if message["type"] == "http.response.start" and not client:
                content_type = dict(message.get("headers", [])).get(b"content-type", b"")
                if content_type.startswith((b"text/event-stream", b"multipart/x-mixed-replace")):
                    client = True
                    guard.clients += 1
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            guard.clients -= int(client)
            guard.mutations -= int(mutation)
