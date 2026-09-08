import ctypes
from ctypes import wintypes
import os
import threading

import pytest

from rareiq.services.windows_voice_keys import WindowsVoiceKeys


class FakeNative:
    def __init__(self, available=True):
        self.available, self.keys, self.message = available, set(), False
        self.registrations, self.unregistrations, self.queries = [], [], []
        self.cleaned = threading.Event()

    def register(self):
        self.registrations.append(threading.get_ident())
        return self.available

    def unregister(self):
        self.unregistrations.append(threading.get_ident())
        self.cleaned.set()

    def hotkey(self):
        message, self.message = self.message, False
        return message

    def pressed(self, key):
        self.queries.append(key)
        return key in self.keys


@pytest.fixture
def ptt():
    native, clock = FakeNative(), [100.0]
    helper = WindowsVoiceKeys(api=native, clock=lambda: clock[0], poll_seconds=3600)
    assert helper.start('ptt')['ok']
    yield helper, native, clock
    helper.close()


def press(fixture, timestamp):
    helper, native, clock = fixture
    clock[0] = timestamp
    native.keys, native.message = {0x11, 0x12, 0x56}, True
    helper._poll_once()


def release(fixture, timestamp):
    helper, native, clock = fixture
    clock[0] = timestamp
    native.keys = set()
    helper._poll_once()


def test_ptt_requires_registered_message_and_complete_utterance_inside_one_hold(ptt):
    helper, native, clock = ptt
    native.keys = {0x11, 0x12, 0x56}
    helper._poll_once()
    assert not helper.status()['ptt_down'] and not helper.permits(100)
    press(ptt, 100)
    clock[0] = 101
    assert helper.status()['ptt_down'] and helper.permits(100.9, 100.1)
    assert not helper.permits(100.9, 99.8)
    release(ptt, 102)
    assert not helper.status()['ptt_down']
    assert helper.permits(102.05, 100.1)
    assert not helper.permits(102.2, 100.1)
    press(ptt, 103)
    release(ptt, 104)
    assert helper.permits(103.9, 103.1)
    assert not helper.permits(103.9, 100.1)


def test_recent_intervals_are_bounded_and_repeated_hotkey_message_does_not_split_hold(ptt):
    helper, native, clock = ptt
    press(ptt, 100)
    native.message = True
    helper._poll_once()
    assert len(helper._windows) == 1
    release(ptt, 100.5)
    for index in range(1, 10):
        press(ptt, 100 + index)
        release(ptt, 100.5 + index)
    assert len(helper._windows) == 8
    assert not helper.permits(100.2) and helper.permits(109.2)
    clock[0] = 141
    helper._poll_once()
    assert not helper._windows and not helper.permits(109.2)


def test_fresh_physical_chord_without_hotkey_message_is_accepted_after_release(ptt):
    helper, native, clock = ptt
    # A chord held before the first observation cannot silently arm PTT.
    native.keys = {0x11, 0x12, 0x56}
    helper._poll_once()
    assert not helper.status()['ptt_down']
    release(ptt, 100.2)
    clock[0] = 100.5
    native.keys = {0x11, 0x12, 0x56}
    helper._poll_once()  # no WM_HOTKEY
    assert helper.status()['ptt_down']
    assert helper.status()['press_count'] == 1
    clock[0] = 101
    assert helper.permits(100.9, 100.6)
    assert not helper.permits(100.9, 100.2)
    helper._poll_once()
    assert helper.status()['press_count'] == 1
    release(ptt, 101.5)
    assert not helper.status()['ptt_down']
    assert helper.status()['last_pressed_at'] == 100.5


@pytest.mark.parametrize('ended,started', [(True, None), (float('nan'), None), (float('inf'), None), ('100', None), (100, False), (100, 101), (100, 'bad')])
def test_malformed_timestamps_fail_closed(ptt, ended, started):
    press(ptt, 100)
    assert not ptt[0].permits(ended, started)


def test_emergency_is_cached_only_while_armed_and_blocks_ptt(ptt):
    helper, native, _ = ptt
    press(ptt, 100)
    native.keys.add(0x08)
    helper._poll_once()
    assert helper.emergency_pressed()
    assert not helper.status()['ptt_down'] and not helper.permits(100)
    queries = len(native.queries)
    helper.emergency_pressed()
    helper.status()
    helper.permits(100)
    assert len(native.queries) == queries
    helper.stop()
    assert not helper.emergency_pressed() and not helper.permits(100)


def test_registration_and_cleanup_share_worker_and_restart_discards_old_windows(ptt):
    helper, native, _ = ptt
    press(ptt, 100)
    assert helper.start('ptt')['reason'] == 'voice_keys_already_active'
    helper.stop()
    assert native.registrations == native.unregistrations
    assert native.registrations[0] != threading.get_ident()
    assert not helper.status()['ptt_down'] and not helper.permits(100)
    native.keys = set()
    assert helper.start('wake')['ok']
    native.keys = {0x11, 0x12, 0x08}
    native.queries.clear()
    helper._poll_once()
    assert helper.emergency_pressed() and not helper.permits(100)
    assert set(native.queries) == {0x11, 0x12, 0x08}
    assert len(native.registrations) == 1


def test_conflict_and_unsupported_platform_fail_without_unregistering_another_owner(monkeypatch):
    native = FakeNative(available=False)
    helper = WindowsVoiceKeys(api=native)
    try:
        assert helper.start('ptt') == {'ok': False, 'reason': 'ptt_hotkey_unavailable'}
        assert not native.unregistrations and not helper.status()['ptt_down']
    finally:
        helper.close()
    from rareiq.services import windows_voice_keys
    monkeypatch.setattr(windows_voice_keys.os, 'name', 'non-windows')
    assert WindowsVoiceKeys().start()['reason'] == 'native_keys_unavailable'


def test_native_observer_error_fails_closed_and_unregisters():
    native = FakeNative()
    def fail(_key):
        raise OSError('unavailable')
    native.pressed = fail
    helper = WindowsVoiceKeys(api=native, poll_seconds=.01)
    try:
        assert helper.start('ptt')['ok']
        assert native.cleaned.wait(1)
        assert not helper.status()['ptt_down'] and not helper.emergency_pressed()
        assert not helper.permits(100)
    finally:
        helper.close()
    assert native.registrations == native.unregistrations


@pytest.mark.skipif(os.name != 'nt', reason='Windows registration capability only')
def test_actual_windows_register_unregister_without_key_injection_or_focus_change():
    user = ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype = wintypes.HWND
    before = user.GetForegroundWindow()
    helper = WindowsVoiceKeys()
    try:
        result = helper.start('ptt')
        if not result['ok']:
            pytest.skip(result['reason'])
    finally:
        helper.close()
    assert helper._thread is not None and not helper._thread.is_alive()
    assert not helper.status()['ptt_down']
    assert user.GetForegroundWindow() == before
