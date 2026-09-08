"""Local served Practice acceptance using synthetic memory audio, never device capture.

Requires an idle local studio. Never enables action mode, stream or recording.
"""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rareiq.services.windows_speech_recognizer import WindowsSpeechRecognizer

ORIGIN = 'http://127.0.0.1:9040'


def request(path, payload=None, *, audio=False):
    data = payload if audio else json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'audio/wav' if audio else 'application/json'}
    with urllib.request.urlopen(urllib.request.Request(ORIGIN + path, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def synthesize(phrase):
    # Phrases below are fixed synthetic fixtures, not input from files or users.
    script = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Speech
$memory=[IO.MemoryStream]::new()
$synth=[System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
  $synth.SetOutputToNull()
  $format=[System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
  $synth.SetOutputToAudioStream($memory,$format)
  $synth.Speak('FIXED_PHRASE')
  $synth.SetOutputToNull()
  [Convert]::ToBase64String($memory.ToArray())
} finally { $synth.Dispose(); $memory.Dispose() }
""".replace('FIXED_PHRASE', phrase)
    result = subprocess.run([str(WindowsSpeechRecognizer._powershell()), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, 'Memory speech synthesis failed'
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes(base64.b64decode(result.stdout.strip(), validate=True))
    return stream.getvalue()


def main():
    voice = request('/api/production/voice/status')
    show = request('/api/production/session')['session']
    obs = request('/api/production/obs')['obs']
    assert voice['state'] == 'stopped' and voice['open_flow'] is False
    assert show['active'] is False and show['recording']['active'] is False
    assert obs['streaming'] is False and obs['recording'] is False
    cases = [
        ('cam two', False, 'wake_phrase_required'),
        ('Sarge cam two', False, 'validated'),
        ('Hey Sarge camera three', False, 'validated'),
        ('Producer please camera two', False, 'wake_phrase_required'),
        ('cam two', True, 'validated'),
    ]
    rows = []
    for phrase, open_flow, expected in cases:
        audio = synthesize(phrase)
        assert request('/api/production/voice/status')['state'] == 'stopped', 'Voice session appeared; leave it untouched'
        started = request('/api/production/voice/start', {'practice': True, 'mode': 'wake', 'open_flow': open_flow})
        session = started['session_id']
        try:
            assert started['practice'] is True and started['open_flow'] is open_flow
            result = request(f'/api/production/voice/audio?session_id={session}&sequence=1&ended_at={time.time()}', audio, audio=True)['last_result']
            assert (result.get('reason') if expected == 'wake_phrase_required' else result['state']) == expected
            rows.append({'phrase': phrase, 'open_flow': open_flow, 'outcome': expected})
        finally:
            stopped = request('/api/production/voice/stop', {'session_id': session})
            assert stopped['state'] == 'stopped' and stopped['open_flow'] is False
    report = {'layer': 'Running local HTTP server + installed Windows recognizer + synthetic audio', 'practice_only': True, 'physical_capture': False, 'playback': False, 'cases': rows}
    output = Path('.tmp/refinish/sarge-live-practice.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
