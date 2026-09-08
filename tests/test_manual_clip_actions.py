import asyncio
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rareiq.services import instant_replay_service as replay_module
from rareiq.services.instant_replay_service import InstantReplayService


@pytest.fixture
def replay(tmp_path):
    jpeg = cv2.imencode('.jpg', np.full((64, 96, 3), (50, 100, 150), dtype=np.uint8))[1].tobytes()
    service = InstantReplayService(tmp_path/'clips', lambda _slot: None, lambda: 1)
    now = time.time()
    service._frames.extend((now-index/5, 1, jpeg) for index in reversed(range(20)))
    return service


def test_manual_action_saves_decodable_silent_video_once_and_discloses_short_history(replay, monkeypatch):
    from rareiq.web import server
    monkeypatch.setattr(server, 'instant_replay', replay)
    request = server.ReplayMarkRequest(seconds=60, name='Synthetic test clip', request_id='clip-'+str(time.time_ns()), expires_at=time.time()+30)
    first = asyncio.run(server.mark_production_replay(request))
    second = asyncio.run(server.mark_production_replay(request))
    assert first['ok'] and first['highlight']['id'] == second['highlight']['id']
    assert first['actual_seconds'] == 4 and first['shorter_than_requested']
    assert first['highlight']['audio_tracks'] == 0
    assert first['highlight']['source_kind'] == 'program_camera'
    assert len(replay.snapshot()['highlights']) == 1
    path = replay.video(first['highlight']['id'])
    capture = cv2.VideoCapture(str(path))
    try:
        decoded = 0
        while capture.read()[0]:
            decoded += 1
        assert decoded == 20 and capture.get(cv2.CAP_PROP_FPS) == 5
    finally:
        capture.release()
    assert not replay.snapshot()['playback']['active']


def test_anchor_excludes_later_frames_and_expired_history_fails_closed(replay):
    end = replay._frames[-1][0]-2
    result = replay.mark(15, export_video=True, ending_at=end)
    assert result['created'] and result['highlight']['frames'] == 10
    assert replay.mark(15, export_video=True, ending_at=end-60)['reason'] == 'replay_buffer_empty'


def test_encoding_and_disk_failures_never_publish_a_clip(replay, monkeypatch):
    monkeypatch.setattr(replay_module.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=0))
    assert replay.mark(export_video=True)['reason'] == 'insufficient_clip_storage'
    assert not replay.root.exists()
    monkeypatch.setattr(replay_module.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=100_000_000))
    monkeypatch.setattr(replay, '_encode_video', lambda *_args: (_ for _ in ()).throw(ValueError('encoder failed')))
    assert replay.mark(export_video=True)['reason'] == 'clip_encoding_failed'
    assert replay.snapshot()['highlights'] == []
    assert not list(replay.root.iterdir())


def test_program_adapter_reuses_validated_engine_and_rejects_missing_camera(monkeypatch):
    from rareiq.web import server
    monkeypatch.setattr(server, 'orchestrator', SimpleNamespace(camera_manager=SimpleNamespace(camera_slots=lambda: [{'slot_id':2,'source_id':'fixture','connected':True}])))
    monkeypatch.setattr(server, 'PRODUCTION_SWITCHER_STATE', {'preview_slot':2,'program_slot':1,'transition':'fade','duration_ms':500,'generation':0})
    request = server.ProductionSwitcherRequest(preview_slot=2, request_id='camera-'+str(time.time_ns()), expires_at=time.time()+30)
    first = asyncio.run(server.production_switcher_take(request))
    second = asyncio.run(server.production_switcher_take(request))
    assert first['ok'] and second['generation'] == first['generation'] == 1
    failure = asyncio.run(server.production_switcher_take(server.ProductionSwitcherRequest(preview_slot=3)))
    assert failure.status_code == 409 and json.loads(failure.body)['reason'] == 'camera_slot_unavailable'
