from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time
import json
from pathlib import Path
from typing import Any


class RecordingService:
    """Supervises an optional external encoder without invoking a shell."""

    PRESETS = {
        "balanced": {"label": "1080p Balanced", "video_bitrate_kbps": 6000, "audio_bitrate_kbps": 192},
        "quality": {"label": "1080p High Quality", "video_bitrate_kbps": 10000, "audio_bitrate_kbps": 256},
        "archive": {"label": "Archive Master", "video_bitrate_kbps": 18000, "audio_bitrate_kbps": 320},
    }

    def __init__(self, output_dir: Path, command_template: str | None = None, *, minimum_free_gb: float = 2.0, config_path: Path | None = None) -> None:
        self.output_dir = output_dir
        self.config_path = config_path or output_dir.parent / "recording_settings.json"
        self.command_template = (command_template or os.getenv("RAREIQ_RECORDING_COMMAND", "")).strip()
        self.minimum_free_gb = max(0.1, float(os.getenv("RAREIQ_RECORDING_MIN_FREE_GB", minimum_free_gb)))
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._output_path: Path | None = None
        self._started_at = 0.0
        self._last_error = ""
        self._preset = "balanced"
        self._load_config()

    def _load_config(self) -> None:
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8"))
            if value.get("output_dir"): self.output_dir = Path(value["output_dir"]).expanduser().resolve()
            if value.get("command_template") is not None: self.command_template = str(value["command_template"]).strip()
            if value.get("preset") in self.PRESETS: self._preset = value["preset"]
            if value.get("minimum_free_gb") is not None: self.minimum_free_gb = max(.1, float(value["minimum_free_gb"]))
        except (OSError, ValueError, TypeError):
            return

    def configure(self, *, output_dir: str, command_template: str, preset: str, minimum_free_gb: float) -> dict[str, Any]:
        with self._lock:
            if self._process and self._process.poll() is None: return {"updated": False, "reason": "recording_active", **self.settings()}
            target = Path(output_dir).expanduser().resolve()
            target.mkdir(parents=True, exist_ok=True)
            if preset not in self.PRESETS: return {"updated": False, "reason": "invalid_preset", **self.settings()}
            self.output_dir, self.command_template, self._preset, self.minimum_free_gb = target, command_template.strip(), preset, max(.1, float(minimum_free_gb))
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps({"output_dir": str(target), "command_template": self.command_template, "preset": preset, "minimum_free_gb": self.minimum_free_gb}, indent=2), encoding="utf-8")
            return {"updated": True, **self.settings()}

    def settings(self) -> dict[str, Any]:
        preset = self.PRESETS[self._preset]
        free = self._free_bytes(); bits_per_second = (preset["video_bitrate_kbps"] + preset["audio_bitrate_kbps"]) * 1000
        return {"output_dir": str(self.output_dir), "command_template": self.command_template, "preset": self._preset, "presets": self.PRESETS, "minimum_free_gb": self.minimum_free_gb, "free_bytes": free, "estimated_minutes": round(free * 8 / bits_per_second / 60) if bits_per_second else 0, "configured": bool(self.command_template)}

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
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return int(shutil.disk_usage(self.output_dir).free)

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            output = self._output_path
            return {
                "configured": bool(self.command_template),
                "active": running,
                "healthy": running and bool(output),
                "pid": self._process.pid if running and self._process else None,
                "started_at": self._started_at,
                "output_path": str(output) if output else None,
                "output_exists": bool(output and output.is_file()),
                "output_bytes": output.stat().st_size if output and output.is_file() else 0,
                "free_bytes": self._free_bytes(),
                "minimum_free_bytes": int(self.minimum_free_gb * 1024**3),
                "last_error": self._last_error,
            }

    def start(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            current = self.status()
            if current["active"]:
                return {"started": False, "reason": "already_recording", **current}
            if not self.command_template:
                return {"started": False, "reason": "encoder_not_configured", **current}
            if current["free_bytes"] < current["minimum_free_bytes"]:
                return {"started": False, "reason": "insufficient_disk_space", **current}
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._output_path = self.output_dir / f"rareiq-{stamp}-{session_id[:8]}.mkv"
            command = self.command_template.replace("{output}", str(self._output_path)).replace("{session_id}", session_id)
            try:
                args = shlex.split(command, posix=os.name != "nt")
                if not args:
                    raise ValueError("recording command is empty")
                self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
                self._started_at = time.time()
                self._last_error = ""
                return {"started": True, **self.status()}
            except (OSError, ValueError) as exc:
                self._process = None
                self._last_error = str(exc)
                return {"started": False, "reason": "encoder_start_failed", **self.status()}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process and process.poll() is None:
                try:
                    if process.stdin:
                        process.stdin.write(b"q\n"); process.stdin.flush()
                    process.wait(timeout=8)
                except (OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    try: process.wait(timeout=3)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
            self._process = None
            result = self.status()
            result["stopped"] = True
            result["verified"] = bool(result["output_exists"] and result["output_bytes"] > 0)
            return result
