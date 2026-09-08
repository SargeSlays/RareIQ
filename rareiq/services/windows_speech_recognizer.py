from __future__ import annotations

import base64
import io
import json
import math
import os
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Any


class WindowsSpeechRecognizer:
    """Finite, local command recognition from supplied audio; never owns a device."""

    MAX_SECONDS = 6
    SAMPLE_RATE = 16000
    MAX_WAV_BYTES = SAMPLE_RATE * MAX_SECONDS * 2 + 4096
    PROCESS_TIMEOUT = 12.0  # Includes Windows PowerShell/engine startup.
    CAPABILITY_TTL = 30.0
    _HELPER = Path(__file__).with_name("windows_speech_recognizer.ps1")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capability: dict[str, Any] | None = None
        self._capability_at = 0.0

    @staticmethod
    def _powershell() -> Path | None:
        if os.name != "nt":
            return None
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        return executable if executable.is_file() else None

    def _invoke(self, mode: str, payload: str = "") -> dict[str, Any]:
        executable = self._powershell()
        if executable is None:
            raise RuntimeError("Windows speech recognition is unavailable on this host.")
        try:
            result = subprocess.run(
                [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self._HELPER), "-Mode", mode],
                input=payload,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.PROCESS_TIMEOUT,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Local speech recognition timed out.") from None
        except (OSError, UnicodeError):
            raise RuntimeError("Local speech recognition could not start.") from None
        if result.returncode or len(result.stdout) > 4096:
            raise RuntimeError("Local speech recognition failed.")
        try:
            value = json.loads(result.stdout.lstrip("\ufeff"))
        except (ValueError, TypeError):
            raise RuntimeError("Local speech recognition returned an invalid response.") from None
        if not isinstance(value, dict):
            raise RuntimeError("Local speech recognition returned an invalid response.")
        return value

    def capability(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if self._capability is not None and now - self._capability_at < self.CAPABILITY_TTL:
                return dict(self._capability)
            try:
                value = self._invoke("capability")
                available = value.get("available") is True
                result = {"available": available, "reason": "Installed English (US) local command recognizer." if available else "An English (US) Windows speech recognizer is not installed."}
                if available:
                    result["engine"] = "Windows System.Speech (en-US)"
            except RuntimeError as error:
                result = {"available": False, "reason": str(error)}
            self._capability, self._capability_at = result, now
            return dict(result)

    @classmethod
    def _validate_wav(cls, audio: bytes) -> None:
        if not isinstance(audio, bytes) or not 44 <= len(audio) <= cls.MAX_WAV_BYTES:
            raise ValueError("Speech audio must be a bounded PCM WAV recording.")
        try:
            with wave.open(io.BytesIO(audio), "rb") as source:
                frames = source.getnframes()
                if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != cls.SAMPLE_RATE or source.getcomptype() != "NONE" or not 0 < frames <= cls.SAMPLE_RATE * cls.MAX_SECONDS:
                    raise ValueError
                if len(source.readframes(frames)) != frames * 2:
                    raise ValueError
        except (wave.Error, EOFError, ValueError):
            raise ValueError("Speech audio must be mono 16 kHz PCM16 WAV, at most six seconds.") from None

    def recognize(self, wav: bytes) -> dict[str, Any]:
        self._validate_wav(wav)
        with self._lock:
            value = self._invoke("recognize", base64.b64encode(wav).decode("ascii"))
        if value.get("ok") is not True:
            raise RuntimeError("Local speech recognition failed.")
        text, confidence = value.get("text"), value.get("confidence")
        if not isinstance(text, str) or len(text) > 180 or not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise RuntimeError("Local speech recognition returned an invalid response.")
        return {"text": text, "confidence": float(confidence)}
