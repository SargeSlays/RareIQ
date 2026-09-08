"""Real synthetic speech -> local recognizer -> HTTP action -> playable clip.

No application lifespan, microphone, speaker, camera or external platform starts.
"""
from pathlib import Path
import argparse
import base64
import ctypes
import io
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from fastapi.testclient import TestClient
from rareiq.services.instant_replay_service import InstantReplayService
from rareiq.services.windows_speech_recognizer import WindowsSpeechRecognizer
from rareiq.web import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-wav', type=Path, help='Use an existing synthetic worklet WAV for the HTTP proof')
    arguments = parser.parse_args()
    recognizer = WindowsSpeechRecognizer()
    assert recognizer.capability()['available'], 'Local Windows speech engine unavailable'
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
} finally { $synth.Dispose(); $memory.Dispose() }
"""
    process = subprocess.run([str(recognizer._powershell()), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, encoding='utf-8', timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert process.returncode == 0, 'Memory-only speech synthesis failed'
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(base64.b64decode(process.stdout.strip(), validate=True))
    synthetic = Path('.tmp/refinish/voice/synthetic-command.wav')
    synthetic.parent.mkdir(parents=True, exist_ok=True)
    if not synthetic.exists():
        synthetic.write_bytes(audio.getvalue())
    if arguments.input_wav:
        assert arguments.input_wav.stat().st_size <= 192044
        audio = io.BytesIO(arguments.input_wav.read_bytes())
    folder = Path('.tmp/refinish/voice-http') / str(time.time_ns())
    replay = InstantReplayService(folder/'clips', lambda _slot: None, lambda: 1)
    jpeg = cv2.imencode('.jpg', np.full((180, 320, 3), (40, 100, 170), dtype=np.uint8))[1].tobytes()
    ended = time.time()
    replay._frames.extend((ended-index/5, 1, jpeg) for index in reversed(range(20)))
    foreground = ctypes.windll.user32.GetForegroundWindow() if os.name == 'nt' else None
    client = TestClient(server.app, client=('127.0.0.1', 50000))
    started = time.perf_counter()
    try:
        with patch.object(server, 'instant_replay', replay):
            session = client.post('/api/production/voice/start', json={'practice': False}).json()['session_id']
            query = {'session_id': session, 'sequence': 1, 'ended_at': ended}
            response = client.post('/api/production/voice/audio', params=query, content=audio.getvalue(), headers={'Content-Type': 'audio/wav'})
            assert response.status_code == 200 and response.json()['last_result']['state'] == 'succeeded', response.json()
            duplicate = client.post('/api/production/voice/audio', params=query, content=audio.getvalue(), headers={'Content-Type': 'audio/wav'})
            assert duplicate.status_code == 200
            highlights = replay.snapshot()['highlights']
            assert len(highlights) == 1
            download = client.get('/api/production/replay/'+highlights[0]['id']+'/download')
            assert download.status_code == 200
            clip = folder/'verified-voice-clip.mp4'
            clip.write_bytes(download.content)
            capture = cv2.VideoCapture(str(clip))
            decoded = 0
            try:
                while capture.read()[0]: decoded += 1
            finally:
                capture.release()
            assert decoded == 20
            assert client.post('/api/production/voice/stop', json={'session_id': session}).json()['state'] == 'stopped'
            report = {'speech': 'real Windows recognizer, synthetic test audio', 'worklet_input': bool(arguments.input_wav), 'http_save': response.status_code,
                      'saved_once': True, 'decoded_frames': decoded, 'actual_seconds': 4, 'requested_seconds': 30,
                      'audio_tracks': 0, 'foreground_window_unchanged': foreground == (ctypes.windll.user32.GetForegroundWindow() if os.name == 'nt' else None),
                      'elapsed_seconds': round(time.perf_counter()-started, 3), 'clip': str(clip.resolve())}
            (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(report))
    finally:
        server.voice_commands.close()
        server.production_actions.close()
        client.close()


if __name__ == '__main__':
    main()
