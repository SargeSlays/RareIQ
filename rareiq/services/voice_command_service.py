"""Opt-in local speech commands borrowing the operator's existing input graph."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import math
import re
import threading
import time
import uuid
import wave
from rareiq.services.windows_voice_keys import WindowsVoiceKeys

MAX_VOICE_BYTES = 192044


def interpret_command(text: str, ended_at: float, *, allow_bare=False):
    words = re.sub(r'[^a-z0-9 ]', '', str(text).lower())
    words = ' '.join(words.split())
    prefixes = ('hey sarge ', 'sarge ') + (('producer please ',) if allow_bare else ())
    prefix = next((item for item in prefixes if words.startswith(item)), None)
    if not prefix and not allow_bare:
        return None
    command = words[len(prefix):] if prefix else words
    cameras = {'one': 1, 'two': 2, 'three': 3, 'four': 4}
    for word, slot in cameras.items():
        if command in (f'camera {word}', f'camera {slot}', f'cam {word}', f'cam {slot}'):
            return 'program.take', {'preview_slot': slot, 'transition': 'cut'}
    durations = {'fifteen': 15, 'thirty': 30, 'sixty': 60, 'one hundred twenty': 120, 'one hundred and twenty': 120}
    if command == 'clip that':
        return 'clip.save', {'seconds': 15, 'name': 'Voice highlight', 'ending_at': ended_at}
    for word, seconds in durations.items():
        if command in (f'save the last {word} seconds', f'save the last {seconds} seconds'):
            return 'clip.save', {'seconds': seconds, 'name': 'Voice highlight', 'ending_at': ended_at}
    return None


def validate_voice_wave(data: bytes) -> None:
    if not 44 < len(data) <= MAX_VOICE_BYTES:
        raise ValueError('invalid_voice_audio')
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE') or not 1600 <= frames <= 96000:
                raise ValueError('invalid_voice_audio')
            if len(audio.readframes(frames)) != frames * 2:
                raise ValueError('invalid_voice_audio')
    except (wave.Error, EOFError) as exc:
        raise ValueError('invalid_voice_audio') from exc


class VoiceCommandService:
    def __init__(self, recognizer, actions, *, emergency_probe=None, key_monitor=None):
        self.recognizer, self.actions = recognizer, actions
        self._lock = threading.RLock()
        self._session = None
        self._cancel = threading.Event()
        self._closed = threading.Event()
        self._watcher = None
        self.keys = key_monitor or WindowsVoiceKeys()
        self._probe = emergency_probe or self.keys.emergency_pressed
        self._mode = 'wake'
        self._state, self._reason, self._busy = 'stopped', '', False
        self._practice = True
        self._open_flow = False
        self._last = None
        self._pending_action = None
        self._sequence, self._digest = -1, ''
        self._previous_command = None
        self._previous_at = 0
        self._heartbeat_at = 0

    def _watch(self):
        while not self._closed.wait(.05):
            with self._lock:
                session = self._session
            if session:
                if self.keys.status().get('available') is False:
                    self.stop(session, reason='voice_shortcut_unavailable')
                elif self._probe():
                    self.stop(session, reason='emergency_stop')
                elif time.monotonic() - self._heartbeat_at > 30:
                    self.stop(session, reason='input_session_expired')

    def status(self, session_id=None):
        with self._lock:
            if session_id and session_id == self._session:
                self._heartbeat_at = time.monotonic()
            if self._pending_action:
                observed = self.actions.observe(self._pending_action)
                if observed.get('state') != 'executing':
                    self._last = self._feedback(observed)
                    self._pending_action = None
                    if self._state == 'recognizing':
                        self._state = 'armed'
            keys = self.keys.status()
            return {'ok': True, 'state': self._state, 'practice': self._practice,
                    'reason': self._reason, 'last_result': deepcopy(self._last),
                    'mode': self._mode, 'open_flow': self._open_flow,
                    'ptt_down': keys.get('ptt_down', False),
                    'diagnostics': {'shortcut_presses': keys.get('press_count', 0),
                                    'last_shortcut_at': keys.get('last_pressed_at'),
                                    'audio_sequence': max(0, self._sequence)},
                    'background_requirement': 'Existing microphone session must remain active'}

    def start(self, *, practice=True, mode='wake', open_flow=False):
        with self._lock:
            if mode not in ('wake', 'ptt'):
                return {'ok': False, 'reason': 'invalid_voice_mode'}
            if type(open_flow) is not bool:
                return {'ok': False, 'reason': 'invalid_open_flow'}
            if self._session or self._busy:
                return {'ok': False, 'reason': 'voice_session_active_or_finishing'}
            capability = self.recognizer.capability()
            if not capability.get('available'):
                return {'ok': False, 'reason': capability.get('reason') or 'speech_unavailable'}
            key_result = self.keys.start(mode)
            if not key_result.get('ok'):
                return {'ok': False, 'reason': key_result.get('reason') or 'voice_shortcut_unavailable'}
            self._mode = mode
            self._session = uuid.uuid4().hex
            self._cancel = threading.Event()
            self._practice = bool(practice)
            self._open_flow = open_flow
            self._state, self._reason, self._last = 'armed', '', None
            self._pending_action = None
            self._sequence, self._digest = -1, ''
            self._previous_command, self._previous_at = None, 0
            self._heartbeat_at = time.monotonic()
            if self._watcher is None:
                self._watcher = threading.Thread(target=self._watch, name='voice-emergency-stop', daemon=True)
                self._watcher.start()
            return {**self.status(), 'session_id': self._session}

    def stop(self, session_id, *, reason='operator_stopped'):
        with self._lock:
            if self._session and session_id != self._session:
                return {'ok': False, 'reason': 'voice_session_mismatch'}
            self._cancel.set()
            self.keys.stop()
            self._session = None
            self._open_flow = False
            self._state, self._reason, self._last = 'stopped', reason, None
            self._pending_action = None
            return self.status()

    @staticmethod
    def _feedback(result):
        state = result.get('state', 'failed')
        payload = result.get('result') or {}
        message = result.get('reason') or payload.get('reason') or 'Command could not be confirmed.'
        if message == 'hold_to_talk_required':
            message = 'Hold Ctrl+Alt+V for the whole command, then release. No action was taken.'
        elif message == 'wake_phrase_required':
            message = 'Start the command with "Sarge" or "Hey Sarge". No action was taken.'
        if state == 'validated':
            message = 'Practice recognized the command. Production was unchanged.'
        elif result.get('ok'):
            if result.get('action_id') == 'clip.save':
                message = f"Saved {payload.get('actual_seconds', 0)} seconds from the silent camera buffer."
                if payload.get('shorter_than_requested'):
                    message += ' Less history was available than requested.'
            else:
                message = f"Program camera {payload.get('program_slot')} selected."
        return {key: value for key, value in {'ok': result.get('ok') is True, 'state': state, 'at': time.time(),
                'action_id': result.get('action_id'), 'reason': result.get('reason') or payload.get('reason'), 'message': message}.items() if value is not None}

    def audio(self, session_id, sequence, ended_at, data, started_at=None):
        if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence < 2**31:
            return {'ok': False, 'reason': 'invalid_voice_sequence'}
        if not isinstance(ended_at, (int, float)) or isinstance(ended_at, bool) or not math.isfinite(ended_at) or not time.time()-10 <= ended_at <= time.time()+1:
            return {'ok': False, 'reason': 'stale_voice_audio'}
        try:
            validate_voice_wave(data)
        except ValueError:
            return {'ok': False, 'reason': 'invalid_voice_audio'}
        digest = hashlib.sha256(data + repr((ended_at, started_at)).encode('ascii')).hexdigest()
        with self._lock:
            if not self._session or session_id != self._session:
                return {'ok': False, 'reason': 'voice_not_armed'}
            if self.keys.status().get('available') is False or self._probe():
                return self.stop(session_id, reason='voice_shortcut_unavailable')
            if sequence == self._sequence and digest == self._digest:
                return self.status()
            if sequence <= self._sequence:
                return {'ok': False, 'reason': 'voice_sequence_conflict'}
            if self._busy or self._pending_action:
                return {'ok': False, 'reason': 'voice_busy'}
            if self._mode == 'ptt' and (not isinstance(started_at, (int, float)) or isinstance(started_at, bool) or not math.isfinite(started_at) or not ended_at-6.1 <= started_at <= ended_at or not self.keys.permits(ended_at, started_at)):
                self._sequence, self._digest = sequence, digest
                self._last = self._feedback({'ok': False, 'state': 'rejected', 'reason': 'hold_to_talk_required'})
                return self.status()
            self._busy, self._state = True, 'recognizing'
            self._heartbeat_at = time.monotonic()
            self._sequence, self._digest = sequence, digest
            cancelled, practice, open_flow = self._cancel, self._practice, self._open_flow
        try:
            recognized = self.recognizer.recognize(data)
            text = recognized.get('text', '')
            command = interpret_command(text, ended_at, allow_bare=open_flow)
            confidence = recognized.get('confidence', 0)
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not .8 <= confidence <= 1:
                result = {'ok': False, 'state': 'rejected', 'reason': 'command_not_recognized'}
            elif not command:
                reason = 'wake_phrase_required' if not open_flow and interpret_command(text, ended_at, allow_bare=True) else 'command_not_recognized'
                result = {'ok': False, 'state': 'rejected', 'reason': reason}
            elif time.time() > ended_at + 15:
                result = {'ok': False, 'state': 'rejected', 'reason': 'voice_command_expired'}
            else:
                with self._lock:
                    if cancelled.is_set():
                        return self.status()
                    signature = (command[0], tuple((key, value) for key, value in command[1].items() if key != 'ending_at'))
                    if signature == self._previous_command and time.monotonic() - self._previous_at < 2:
                        return self.status()
                    self._previous_command, self._previous_at = signature, time.monotonic()
                result = self.actions.dispatch(command[0], command[1], origin='host_voice',
                    request_id=f'voice_{session_id}_{sequence}', expires_at=ended_at+15,
                    practice=practice, cancelled=cancelled.is_set)
            with self._lock:
                if not cancelled.is_set():
                    self._last = self._feedback(result)
                    self._pending_action = result.get('request_id') if result.get('state') == 'executing' else None
                    self._state = 'recognizing' if self._pending_action else 'armed'
            return self.status()
        except Exception:
            with self._lock:
                if not cancelled.is_set():
                    self._state, self._reason = 'error', 'local_recognition_failed'
                    self._last = self._feedback({'ok': False, 'state': 'failed', 'reason': 'local_recognition_failed'})
            return self.status()
        finally:
            with self._lock:
                self._busy = False
                if not cancelled.is_set() and self._state == 'recognizing' and not self._pending_action:
                    self._state = 'armed'

    def close(self):
        with self._lock:
            self.stop(self._session, reason='server_stopped')
        self._closed.set()
        if self._watcher:
            self._watcher.join(timeout=1)
