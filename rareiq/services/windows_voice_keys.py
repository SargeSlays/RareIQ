"""Observe fixed voice-control chords without recording or injecting keyboard input."""
from collections import deque
import ctypes
from ctypes import wintypes
import math
import os
import threading
import time


class _NativeKeys:
    ID, MESSAGE = 0x5251, 0x0312

    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]

    def register(self):
        return bool(self.user.RegisterHotKey(None, self.ID, 0x4003, 0x56))  # Ctrl+Alt+V, MOD_NOREPEAT

    def unregister(self):
        self.user.UnregisterHotKey(None, self.ID)

    def hotkey(self):
        message, found = wintypes.MSG(), False
        for _ in range(32):
            if not self.user.PeekMessageW(ctypes.byref(message), None, self.MESSAGE, self.MESSAGE, 1):
                break
            found = found or message.wParam == self.ID
        return found

    def pressed(self, key):
        return bool(self.user.GetAsyncKeyState(key) & 0x8000)


class WindowsVoiceKeys:
    def __init__(self, *, api=None, clock=time.time, poll_seconds=.02):
        try:
            self._api = api if api is not None else _NativeKeys() if os.name == "nt" else None
        except (AttributeError, OSError):
            self._api = None
        self._clock, self._poll_seconds = clock, max(.01, poll_seconds)
        self._lock, self._lifecycle = threading.RLock(), threading.RLock()
        self._stop, self._ready = threading.Event(), threading.Event()
        self._thread, self._mode = None, "wake"
        self._running = self._down = self._emergency = False
        self._reason = "native_keys_unavailable"
        self._windows = deque(maxlen=8)

    def start(self, mode="wake"):
        with self._lifecycle:
            if mode not in ("wake", "ptt"):
                return {"ok": False, "reason": "invalid_voice_key_mode"}
            if self._api is None:
                return {"ok": False, "reason": "native_keys_unavailable"}
            if self._thread and self._thread.is_alive():
                return {"ok": False, "reason": "voice_keys_already_active"}
            with self._lock:
                self._mode, self._reason = mode, "native_keys_start_failed"
                self._windows.clear()
                self._running = self._down = self._emergency = False
            self._stop.clear()
            self._ready.clear()
            self._thread = threading.Thread(target=self._run, name="voice-fixed-keys", daemon=True)
            self._thread.start()
            if not self._ready.wait(2):
                self.stop()
                return {"ok": False, "reason": "native_keys_start_timeout"}
            with self._lock:
                result = {"ok": self._running, "reason": self._reason}
            if not result["ok"]:
                self._thread.join(timeout=2)
            return result

    def _run(self):
        registered = False
        try:
            if self._mode == "ptt":
                registered = self._api.register()
                if not registered:
                    with self._lock:
                        self._reason = "ptt_hotkey_unavailable"
                    return
            if self._stop.is_set():
                return
            with self._lock:
                self._running, self._reason = True, ""
            self._ready.set()
            while not self._stop.wait(self._poll_seconds):
                self._poll_once()
        except Exception:
            with self._lock:
                self._reason = "native_key_observer_failed"
        finally:
            try:
                if registered:
                    self._api.unregister()
            except Exception:
                with self._lock:
                    self._reason = "native_key_cleanup_failed"
            finally:
                with self._lock:
                    self._running = self._down = self._emergency = False
                    self._windows.clear()
                self._ready.set()

    def _poll_once(self):
        now = self._clock()
        control, alt = self._api.pressed(0x11), self._api.pressed(0x12)
        emergency = control and alt and self._api.pressed(0x08)
        message = self._api.hotkey() if self._mode == "ptt" else False
        held = control and alt and self._api.pressed(0x56) if self._mode == "ptt" else False
        with self._lock:
            if not self._running or self._stop.is_set():
                return
            self._emergency = emergency
            while self._windows and self._windows[0][1] is not None and self._windows[0][1] < now - 30:
                self._windows.popleft()
            if message and held and not self._down:
                self._windows.append([now, None])
                self._down = True
            elif self._down and not held:
                self._windows[-1][1] = now
                self._down = False

    def permits(self, ended_at, started_at=None):
        with self._lock:
            now = self._clock()
            started_at = ended_at if started_at is None else started_at
            if (not self._running or self._stop.is_set() or self._mode != "ptt" or self._emergency
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                           for value in (started_at, ended_at))
                    or not now - 30 <= started_at <= ended_at <= now + .1):
                return False
            return any(start - .1 <= started_at <= ended_at <= (now if end is None else end) + .1 for start, end in self._windows)

    def emergency_pressed(self):
        with self._lock:
            return self._running and not self._stop.is_set() and self._emergency

    def status(self):
        with self._lock:
            return {"available": self._running and not self._stop.is_set(), "reason": self._reason,
                    "ptt_down": self._running and not self._stop.is_set() and self._down and not self._emergency}

    def stop(self):
        with self._lifecycle:
            self._stop.set()
            if self._thread and self._thread is not threading.current_thread():
                self._thread.join(timeout=2)
            with self._lock:
                self._running = self._down = self._emergency = False
                self._windows.clear()

    close = stop
