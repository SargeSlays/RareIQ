from __future__ import annotations

import asyncio
import hashlib
import json

import numpy as np
import pytest

from rareiq.services.provenance_capture_service import ProvenanceCaptureService
from rareiq.web import server


def _active_frame():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[120:960, 260:1660] = (30, 100, 220)
    return frame


def _service(root, frame_provider):
    return ProvenanceCaptureService(
        root,
        server_session_id="manual-api-test",
        frame_provider=frame_provider,
        crop_provider=lambda: None,
        camera_context_provider=lambda: {
            "slot_id": 1,
            "source_id": "camera-insta360",
            "display_name": "Insta360 Link",
            "frame_id": 91,
            "frame_timestamp": 123.5,
            "card_crop_valid": False,
        },
    )


def test_manual_endpoint_persists_from_settings_only_directory(tmp_path, monkeypatch):
    root = tmp_path / "provenance"
    capture = _service(root, _active_frame)
    capture.save_settings(capture.default_settings())
    assert [item.name for item in root.iterdir()] == ["settings.json"]

    monkeypatch.setattr(server, "provenance_capture", capture)
    monkeypatch.setattr(
        server.orchestrator.recognition_state,
        "snapshot",
        lambda: {"generation": 12, "state_id": "manual-card-context"},
    )

    response = asyncio.run(server.capture_provenance_screenshot())
    assert response["ok"] is True
    assert response["captured"] is True
    event_id = response["eventId"]

    assert (root / "events.jsonl").is_file()
    persisted = capture.get_event(event_id)
    assert persisted is not None
    assert persisted["event_id"] == event_id
    assert persisted["trigger_reason"] == "manual"

    event_dir = root / persisted["assets"][0]["relative_path"]
    event_dir = event_dir.parent
    full_frame = event_dir / "full-frame.png"
    manifest = event_dir / "event.json"
    assert full_frame.is_file()
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["event_id"] == event_id
    assert hashlib.sha256(full_frame.read_bytes()).hexdigest() == persisted["assets"][0]["sha256"]
    assert (persisted["assets"][0]["width"], persisted["assets"][0]["height"]) == (1920, 1080)


def test_manual_endpoint_without_frame_returns_explicit_failure(tmp_path, monkeypatch):
    capture = _service(tmp_path / "provenance", lambda: None)
    monkeypatch.setattr(server, "provenance_capture", capture)
    monkeypatch.setattr(server.orchestrator.recognition_state, "snapshot", lambda: {})

    response = asyncio.run(server.capture_provenance_screenshot())
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["ok"] is False
    assert payload["captured"] is False
    assert payload["reason"] == "capture_failed"
    assert capture.list_events() == []


@pytest.mark.parametrize("settings", [{"captureTypes": 42}, {"minimumConfidence": float("inf")}])
def test_settings_endpoint_rejects_invalid_nested_configuration(tmp_path, monkeypatch, settings):
    capture = _service(tmp_path / "provenance", _active_frame)
    monkeypatch.setattr(server, "provenance_capture", capture)
    response = asyncio.run(server.update_provenance_settings(server.ProvenanceSettingsRequest(settings=settings)))
    assert response.status_code == 422
    assert json.loads(response.body)["error"] == "invalid_settings"
    assert capture.settings()["enabled"] is False


def test_settings_disk_failure_is_structured_and_keeps_previous_settings(tmp_path, monkeypatch):
    capture = _service(tmp_path / "provenance", _active_frame)
    before = capture.save_settings({"customerId": "existing-customer"})
    monkeypatch.setattr(server, "provenance_capture", capture)

    def disk_full(*_args):
        raise OSError("settings disk full")

    monkeypatch.setattr(capture, "_atomic_json", disk_full)
    response = asyncio.run(server.update_provenance_settings(server.ProvenanceSettingsRequest(enabled=True)))
    assert response.status_code == 409
    assert json.loads(response.body)["error"] == "settings_save_failed"
    assert capture.settings() == before


def test_correction_disk_failure_is_structured_and_preserves_original(tmp_path, monkeypatch):
    capture = _service(tmp_path / "provenance", _active_frame)
    original = capture.capture()["event"]
    monkeypatch.setattr(server, "provenance_capture", capture)

    def disk_full(_fd):
        raise OSError("revision disk full")

    monkeypatch.setattr("rareiq.services.provenance_capture_service.os.fsync", disk_full)
    response = asyncio.run(server.correct_provenance_event(
        original["event_id"], server.ProvenanceCorrectionRequest(identity={"english_name": "Not saved"})
    ))
    assert response.status_code == 409
    assert json.loads(response.body)["error"] == "correction_save_failed"
    assert capture.list_events() == [original]


def test_capture_read_asset_and_correction_endpoints_round_trip(tmp_path, monkeypatch):
    capture = _service(tmp_path / "provenance", _active_frame)
    monkeypatch.setattr(server, "provenance_capture", capture)
    monkeypatch.setattr(server.orchestrator.recognition_state, "snapshot", lambda: {"generation": 12})
    result = asyncio.run(server.capture_provenance_screenshot())
    event_id = result["eventId"]
    original = asyncio.run(server.provenance_event(event_id))["event"]
    asset = original["assets"][0]
    response = asyncio.run(server.provenance_asset(event_id, asset["asset_id"]))
    assert response.path.read_bytes() == (capture.root / asset["relative_path"]).read_bytes()
    assert response.headers["cache-control"] == "private, no-store"
    revision = asyncio.run(server.correct_provenance_event(
        event_id,
        server.ProvenanceCorrectionRequest(identity={"english_name": "Operator correction"}, reason="Reviewed evidence"),
    ))["revision"]
    assert revision["revision_of"] == event_id
    assert revision["identity"]["english_name"] == "Operator correction"
    assert asyncio.run(server.provenance_event(event_id))["event"] == original
    assert len(asyncio.run(server.provenance_events())["events"]) == 2
    assert asyncio.run(server.provenance_event("missing")).status_code == 404
    assert asyncio.run(server.provenance_asset(event_id, "missing")).status_code == 404
