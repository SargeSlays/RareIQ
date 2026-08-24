from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vision_service_publishes_frame_identity():
    text = (ROOT / "rareiq" / "services" / "vision_service.py").read_text(encoding="utf-8")
    assert '"frame_available": True' in text
    assert '"frame_id": self._frame_id' in text
    assert '"frame_timestamp": frame_timestamp' in text


def test_boot_manager_accepts_stream_without_card():
    text = (ROOT / "rareiq" / "services" / "boot_manager_service.py").read_text(encoding="utf-8")
    assert 'get("vision", {}).get("running")' in text
    assert 'get("vision", {}).get("visible")' not in text


def test_server_runs_boot_in_background():
    text = (ROOT / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")
    assert "asyncio.create_task(boot_in_background())" in text
    assert "orchestrator.boot_manager.run" in text
    assert "real frame heartbeat published by VisionService" in text
