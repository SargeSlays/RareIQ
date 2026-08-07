from __future__ import annotations

import asyncio
import hashlib
import json

import numpy as np

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
