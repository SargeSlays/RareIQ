import base64
import io
import os
import subprocess
import wave
from types import SimpleNamespace

import pytest

from rareiq.services.windows_speech_recognizer import WindowsSpeechRecognizer


def wav_audio(*, channels=1, rate=16000, width=2, seconds=0.1):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(b"\0" * int(rate * seconds) * channels * width)
    return stream.getvalue()


@pytest.mark.parametrize("audio", [b"private audio", wav_audio(channels=2), wav_audio(rate=48000), wav_audio(width=1), wav_audio(seconds=6.01), wav_audio()[:-2]], ids=["not-wav", "stereo", "wrong-rate", "wrong-width", "too-long", "truncated"])
def test_invalid_audio_never_starts_process(monkeypatch, audio):
    recognizer = WindowsSpeechRecognizer()
    monkeypatch.setattr(recognizer, "_invoke", lambda *_: pytest.fail("invalid audio reached recognizer"))
    with pytest.raises(ValueError, match="Speech audio"):
        recognizer.recognize(audio)


def test_recognition_uses_hidden_constant_script_and_memory_input(monkeypatch):
    recognizer = WindowsSpeechRecognizer()
    monkeypatch.setattr(recognizer, "_powershell", lambda: "powershell.exe")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok":true,"text":"Sarge camera one","confidence":0.9}', stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    assert recognizer.recognize(wav_audio()) == {"text": "Sarge camera one", "confidence": 0.9}
    command, options = calls[0]
    assert command[-2:] == ["-Mode", "recognize"]
    assert "-File" in command and "-Command" not in command
    assert options["input"].startswith("UklGR")
    assert options["timeout"] == recognizer.PROCESS_TIMEOUT
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert not options.get("shell")


def test_timeout_and_process_failures_never_expose_audio_or_stderr(monkeypatch):
    recognizer = WindowsSpeechRecognizer()
    monkeypatch.setattr(recognizer, "_powershell", lambda: "powershell.exe")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private audio", 12, stderr="private transcript")
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="^Local speech recognition timed out\\.$"):
        recognizer.recognize(wav_audio())
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="private transcript"))
    with pytest.raises(RuntimeError, match="^Local speech recognition failed\\.$"):
        recognizer.recognize(wav_audio())


@pytest.mark.parametrize("reply", [{"ok": False}, {"ok": True, "text": "x" * 181, "confidence": .5}, {"ok": True, "text": "x", "confidence": float("nan")}, {"ok": True, "text": "x", "confidence": True}])
def test_malformed_recognizer_results_fail_closed(monkeypatch, reply):
    recognizer = WindowsSpeechRecognizer()
    monkeypatch.setattr(recognizer, "_invoke", lambda *_: reply)
    with pytest.raises(RuntimeError):
        recognizer.recognize(wav_audio())


def test_capability_is_cached_detached_and_has_no_audio_input(monkeypatch):
    recognizer = WindowsSpeechRecognizer()
    calls = []
    def invoke(mode, payload=""):
        calls.append((mode, payload))
        return {"available": True}
    monkeypatch.setattr(recognizer, "_invoke", invoke)
    first = recognizer.capability()
    first["available"] = False
    assert recognizer.capability()["available"] is True
    assert calls == [("capability", "")]


def test_helper_accepts_only_memory_audio_and_fixed_command_grammar():
    helper = WindowsSpeechRecognizer._HELPER.read_text(encoding="utf-8")
    assert "SetInputToWaveStream($audio)" in helper
    assert "SetInputToDefaultAudioDevice" not in helper
    assert "DictationGrammar" not in helper
    assert "FromSeconds(8)" in helper
    assert "camera four" in helper and "one hundred twenty seconds" in helper


@pytest.mark.skipif(os.name != "nt", reason="Windows in-memory speech proof")
@pytest.mark.parametrize('phrase', ['Producer please save the last thirty seconds', 'camera two'])
def test_installed_recognizer_understands_real_synthetic_wave_without_playback(phrase):
    recognizer = WindowsSpeechRecognizer()
    if not recognizer.capability()["available"]:
        pytest.skip("An English (US) Windows recognizer is not installed")
    # Fail before Speak on any setup failure. Null is the first explicit output;
    # even a failed memory binding can never fall back to the default speaker.
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$memory = [System.IO.MemoryStream]::new()
$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $synth.SetOutputToNull()
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.SetOutputToAudioStream($memory, $format)
    $synth.Speak('Producer please save the last thirty seconds')
    $synth.SetOutputToNull()
    [Convert]::ToBase64String($memory.ToArray())
} finally {
    $synth.Dispose()
    $memory.Dispose()
}
"""
    script = script.replace('Producer please save the last thirty seconds', phrase)
    process = subprocess.run(
        [str(recognizer._powershell()), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, encoding="utf-8", timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.returncode == 0, "In-memory speech synthesis failed"
    memory = io.BytesIO()
    with wave.open(memory, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(base64.b64decode(process.stdout.strip(), validate=True))
    result = recognizer.recognize(memory.getvalue())
    assert result["text"] == phrase
    assert result["confidence"] >= 0.8
