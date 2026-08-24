from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/instant_replay_service.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
OVERLAY = Path("rareiq/web/static/overlay_replay.html").read_text(encoding="utf-8")


def test_replay_service_uses_bounded_rolling_program_buffer():
    assert "deque(maxlen=fps * buffer_seconds)" in SERVICE
    assert "program_slot_provider" in SERVICE
    assert "frame_provider(slot)" in SERVICE
    assert "buffer_seconds: int = 20" in SERVICE
    assert '"highlights.json"' in SERVICE
    assert "def stop(self)" in SERVICE


def test_replay_api_marks_takes_stops_and_serves_frames_safely():
    assert '@app.get("/api/production/replay")' in SERVER
    assert '@app.post("/api/production/replay/mark")' in SERVER
    assert '@app.post("/api/production/replay/take")' in SERVER
    assert '@app.post("/api/production/replay/stop")' in SERVER
    assert '@app.get("/api/production/replay/{highlight_id}/frame/{index}")' in SERVER
    assert '@app.get("/replay")' in SERVER
    assert "instant_replay.start()" in SERVER
    assert "instant_replay.stop" in SERVER


def test_broadcast_workspace_has_replay_operator_controls_and_output():
    assert 'id="productionReplayLength"' in CONTROL
    assert 'id="productionReplaySpeed"' in CONTROL
    assert 'id="productionReplayMark"' in CONTROL
    assert 'id="productionReplayStop"' in CONTROL
    assert 'id="productionReplayHistory"' in CONTROL
    assert "function loadProductionReplay()" in STUDIO
    assert "function markProductionReplay()" in STUDIO
    assert "function takeProductionReplay" in STUDIO
    assert ".production-replay-history" in CSS
    assert "/api/production/replay" in OVERLAY
    assert "INSTANT REPLAY" in OVERLAY
