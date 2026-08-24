from pathlib import Path

from rareiq.services.recording_service import RecordingService


def test_unconfigured_recording_fails_closed(tmp_path: Path):
    service = RecordingService(tmp_path, "")
    result = service.start("session")
    assert result["started"] is False
    assert result["reason"] == "encoder_not_configured"
    assert result["active"] is False


def test_disk_preflight_blocks_encoder(monkeypatch, tmp_path: Path):
    service = RecordingService(tmp_path, "fake-encoder {output}", minimum_free_gb=10)
    monkeypatch.setattr(service, "_free_bytes", lambda: 1)
    result = service.start("session")
    assert result["started"] is False
    assert result["reason"] == "insufficient_disk_space"


def test_status_does_not_claim_unverified_output(tmp_path: Path):
    service = RecordingService(tmp_path, "")
    status = service.status()
    assert status["output_exists"] is False
    assert status["output_bytes"] == 0
    assert status["healthy"] is False


def test_configuration_persists_and_estimates_recording_time(tmp_path: Path):
    config = tmp_path / "settings.json"
    output = tmp_path / "video"
    service = RecordingService(output, "", config_path=config)
    result = service.configure(output_dir=str(output), command_template="encoder {output}", preset="quality", minimum_free_gb=3)
    assert result["updated"] is True
    assert result["preset"] == "quality"
    assert result["estimated_minutes"] >= 0
    restored = RecordingService(tmp_path / "other", "", config_path=config)
    assert restored.settings()["preset"] == "quality"
    assert restored.settings()["command_template"] == "encoder {output}"


def test_capabilities_expose_safe_templates(monkeypatch, tmp_path: Path):
    service = RecordingService(tmp_path, "")
    monkeypatch.setattr("rareiq.services.recording_service.shutil.which", lambda name: f"/tools/{name}" if name == "ffmpeg" else None)
    capabilities = service.capabilities()
    assert capabilities["ffmpeg"]["installed"] is True
    assert "{output}" in capabilities["templates"]["ffmpeg-test"]
    assert "YOUR CAMERA" in capabilities["templates"]["ffmpeg-device"]
