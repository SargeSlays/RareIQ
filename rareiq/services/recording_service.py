from __future__ import annotations

import os
import copy
import math
import re
import shlex
import shutil
import subprocess
import threading
import time
import json
import uuid
from pathlib import Path
from typing import Any

from rareiq.services.media_storage import atomic_json


class RecordingService:
    """Supervises an optional external encoder without invoking a shell."""

    PRESETS = {
        "balanced": {"label": "1080p Balanced", "video_bitrate_kbps": 6000, "audio_bitrate_kbps": 192},
        "quality": {"label": "1080p High Quality", "video_bitrate_kbps": 10000, "audio_bitrate_kbps": 256},
        "archive": {"label": "Archive Master", "video_bitrate_kbps": 18000, "audio_bitrate_kbps": 320},
    }

    def __init__(self, output_dir: Path, command_template: str | None = None, *, minimum_free_gb: float = 2.0, config_path: Path | None = None) -> None:
        self.output_dir = output_dir.expanduser().resolve()
        self.config_path = config_path or output_dir.parent / "recording_settings.json"
        self.command_template = (command_template or os.getenv("RAREIQ_RECORDING_COMMAND", "")).strip()
        try:
            self.minimum_free_gb = self._minimum_free(os.getenv("RAREIQ_RECORDING_MIN_FREE_GB", minimum_free_gb))
        except (ValueError, TypeError):
            self.minimum_free_gb = 2.0
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._output_path: Path | None = None
        self._started_at = 0.0
        self._last_error = ""
        self._session_id: str | None = None
        self._exit_code: int | None = None
        self._forced_stop = False
        self._stopping = False
        self._preset = "balanced"
        self._load_config()

    def _load_config(self) -> None:
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return
            target = Path(value.get("output_dir") or self.output_dir).expanduser().resolve()
            command = value.get("command_template", self.command_template)
            preset = value.get("preset", self._preset)
            minimum = self._minimum_free(value.get("minimum_free_gb", self.minimum_free_gb))
            if not isinstance(command, str) or not isinstance(preset, str) or preset not in self.PRESETS:
                return
            self.output_dir, self.command_template, self._preset, self.minimum_free_gb = target, command.strip(), preset, minimum
        except (OSError, ValueError, TypeError):
            return

    @staticmethod
    def _minimum_free(value: Any) -> float:
        amount = float(value)
        if not math.isfinite(amount) or not .1 <= amount <= 1000:
            raise ValueError("invalid_minimum_free_gb")
        return amount

    def configure(self, *, output_dir: str, command_template: str, preset: str, minimum_free_gb: float) -> dict[str, Any]:
        with self._lock:
            if self._stopping or self._process and self._process.poll() is None:
                return {"updated": False, "reason": "recording_active", **self.settings()}
            if not isinstance(preset, str) or preset not in self.PRESETS:
                return {"updated": False, "reason": "invalid_preset", **self.settings()}
            try:
                target = Path(output_dir).expanduser().resolve()
                minimum = self._minimum_free(minimum_free_gb)
                command = command_template.strip()
                if command:
                    self._command_args(command, target / "test.mkv", "test")
            except (ValueError, TypeError):
                return {"updated": False, "reason": "invalid_recording_settings", **self.settings()}
            try:
                target.mkdir(parents=True, exist_ok=True)
                atomic_json(self.config_path, {"output_dir": str(target), "command_template": command, "preset": preset, "minimum_free_gb": minimum})
            except OSError:
                return {"updated": False, "reason": "recording_storage_unavailable", **self.settings()}
            self.output_dir, self.command_template, self._preset, self.minimum_free_gb = target, command, preset, minimum
            return {"updated": True, **self.settings()}

    def settings(self) -> dict[str, Any]:
        with self._lock:
            preset = self.PRESETS[self._preset]
            free, available = self._disk_status()
            bits_per_second = (preset["video_bitrate_kbps"] + preset["audio_bitrate_kbps"]) * 1000
            return {"output_dir": str(self.output_dir), "command_template": self.command_template, "preset": self._preset, "presets": copy.deepcopy(self.PRESETS), "minimum_free_gb": self.minimum_free_gb, "free_bytes": free, "storage_available": available, "estimated_minutes": round(free * 8 / bits_per_second / 60) if bits_per_second else 0, "configured": bool(self.command_template)}

    def capabilities(self) -> dict[str, Any]:
        ffmpeg = shutil.which("ffmpeg")
        obs = shutil.which("obs64") or shutil.which("obs")
        if os.name == "nt" and not obs:
            common = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "obs-studio/bin/64bit/obs64.exe"
            if common.is_file(): obs = str(common)
        return {
            "ffmpeg": {"installed": bool(ffmpeg), "path": ffmpeg},
            "obs": {"installed": bool(obs), "path": obs},
            "templates": {
                "ffmpeg-test": f'"{ffmpeg or "ffmpeg"}" -f lavfi -i testsrc2=size=1920x1080:rate=30 -f lavfi -i anullsrc=r=48000:cl=stereo -t 2 -c:v libx264 -preset veryfast -b:v 6000k -c:a aac -b:a 192k -y {{output}}',
                "ffmpeg-device": f'"{ffmpeg or "ffmpeg"}" -f dshow -i video="YOUR CAMERA":audio="YOUR AUDIO" -c:v libx264 -preset veryfast -b:v 6000k -c:a aac -b:a 192k -y {{output}}',
            },
        }

    def _free_bytes(self) -> int:
        target = self.output_dir
        while not target.exists() and target != target.parent:
            target = target.parent
        if not target.is_dir():
            raise OSError("recording_directory_unavailable")
        return int(shutil.disk_usage(target).free)

    def _disk_status(self) -> tuple[int, bool]:
        try:
            return self._free_bytes(), True
        except OSError:
            return 0, False

    @staticmethod
    def _command_args(template: str, output: Path, session_id: str) -> list[str]:
        if "{output}" not in template or "\x00" in template:
            raise ValueError("recording command requires {output}")
        # Parse the template BEFORE substituting paths; values cannot add arguments.
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            parse = ctypes.windll.shell32.CommandLineToArgvW
            parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
            parse.restype = ctypes.POINTER(wintypes.LPWSTR)
            free = ctypes.windll.kernel32.LocalFree
            free.argtypes = [wintypes.HLOCAL]
            free.restype = wintypes.HLOCAL
            count = ctypes.c_int()
            result = parse(template.strip(), ctypes.byref(count))
            if not result:
                raise ValueError("invalid recording command")
            try:
                args = [result[index] for index in range(count.value)]
            finally:
                free(ctypes.cast(result, wintypes.HLOCAL))
        else:
            args = shlex.split(template)
        if not args or not args[0]:
            raise ValueError("recording command is empty")
        return [arg.replace("{output}", str(output)).replace("{session_id}", session_id) for arg in args]

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._process is not None:
                self._exit_code = self._process.poll()
            running = self._process is not None and self._exit_code is None
            output = self._output_path
            output_exists, output_bytes = False, 0
            try:
                if output and output.is_file():
                    output_bytes = output.stat().st_size
                    output_exists = True
            except OSError:
                pass
            free, available = self._disk_status()
            if self._exit_code not in (None, 0):
                self._last_error = f"Encoder exited with code {self._exit_code}; output is not verified."
            elif self._exit_code == 0 and not output_bytes:
                self._last_error = "Encoder exited without a non-empty recording."
            verified = bool(not running and self._exit_code == 0 and output_bytes > 0 and not self._forced_stop)
            return {
                "configured": bool(self.command_template),
                "active": running,
                "healthy": running and output_bytes > 0 and available and not self._stopping,
                "verified": verified,
                "session_id": self._session_id,
                "exit_code": self._exit_code,
                "stopping": self._stopping,
                "pid": self._process.pid if running and self._process else None,
                "started_at": self._started_at,
                "output_path": str(output) if output else None,
                "output_exists": output_exists,
                "output_bytes": output_bytes,
                "free_bytes": free,
                "storage_available": available,
                "minimum_free_bytes": int(self.minimum_free_gb * 1024**3),
                "last_error": self._last_error or ("Recording storage is unavailable." if not available else ""),
            }

    def start(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            current = self.status()
            if current["active"] or self._stopping:
                return {"started": False, "reason": "already_recording", **current}
            self._close_stdin(self._process)
            self._process, self._output_path, self._exit_code = None, None, None
            self._session_id, self._started_at, self._last_error = session_id, 0.0, ""
            self._forced_stop = False
            current = self.status()
            if not self.command_template:
                return {"started": False, "reason": "encoder_not_configured", **current}
            if not current["storage_available"]:
                return {"started": False, "reason": "recording_storage_unavailable", **current}
            if current["free_bytes"] < current["minimum_free_bytes"]:
                return {"started": False, "reason": "insufficient_disk_space", **current}
            stamp = time.strftime("%Y%m%d-%H%M%S")
            safe_session = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:24] or "session"
            self._output_path = self.output_dir / f"rareiq-{stamp}-{safe_session}-{uuid.uuid4().hex[:12]}.mkv"
            self._session_id, self._exit_code, self._forced_stop = session_id, None, False
            self._started_at = 0.0
            try:
                args = self._command_args(self.command_template, self._output_path, session_id)
                self.output_dir.mkdir(parents=True, exist_ok=True)
                self._close_stdin(self._process)
                self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._started_at = time.time()
                self._last_error = ""
                return {"started": True, **self.status()}
            except (OSError, ValueError) as exc:
                self._process = None
                self._last_error = str(exc)
                return {"started": False, "reason": "encoder_start_failed", **self.status()}

    @staticmethod
    def _close_stdin(process: Any) -> None:
        if process and process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass

    def stop(self, *, expected_session_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            if expected_session_id is not None and expected_session_id != self._session_id:
                return {"stopped": False, "reason": "recording_session_changed", **self.status()}
            if self._stopping:
                return {"stopped": False, "reason": "recording_stop_in_progress", **self.status()}
            process = self._process
            self._stopping = True
        forced = False
        try:
            if process and process.poll() is None:
                try:
                    if process.stdin:
                        process.stdin.write(b"q\n")
                        process.stdin.flush()
                    process.wait(timeout=8)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    for action, timeout in ((process.terminate, 3), (process.kill, 2)):
                        if process.poll() is not None:
                            break
                        forced = True
                        try:
                            action()
                            process.wait(timeout=timeout)
                        except (OSError, subprocess.TimeoutExpired):
                            continue
        finally:
            with self._lock:
                self._stopping = False
                self._forced_stop = self._forced_stop or forced
                if process:
                    self._exit_code = process.poll()
                    if self._exit_code is not None:
                        self._close_stdin(process)
                        self._process = None
                if self._process and self._exit_code is None:
                    self._last_error = "Encoder did not stop; retry Stop before starting another recording."
                elif self._forced_stop:
                    self._last_error = "Encoder required forced shutdown; output is not verified."
                result = self.status()
                result["stopped"] = not result["active"]
                if not result["stopped"]:
                    result["reason"] = "encoder_stop_failed"
        return result
