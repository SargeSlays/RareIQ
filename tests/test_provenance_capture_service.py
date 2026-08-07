from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from rareiq.services.provenance_capture_service import ProvenanceCaptureService


def _frame(width=320, height=180):
    image = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (40, 15), (280, 165), (10, 90, 220), -1)
    cv2.putText(image, "RareIQ", (80, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return image


def _snapshot(generation=7, verified=True, confidence=0.96):
    return {
        "generation": generation,
        "state_id": f"state-{generation}",
        "verification_state": "VERIFIED" if verified else "PROVISIONAL",
        "has_reference_evidence": verified,
        "overall_confidence": confidence,
        "primary_candidate": {
            "id": "card-water-horsea",
            "printed_name": "墨海马",
            "english_name": "Horsea",
            "set_id": "gem-pack-vol-5",
            "set_name": "Gem Pack Vol. 5",
            "collector_number": "029/100",
            "language": "Simplified Chinese",
            "rarity": "Rare",
        },
        "artwork_index": {"top_score": 0.94},
    }


@pytest.fixture
def service(tmp_path):
    frame = _frame()
    crop = cv2.resize(frame, (1000, 1400))
    return ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="server-test",
        frame_provider=lambda: frame.copy(),
        crop_provider=lambda: crop.copy(),
        camera_context_provider=lambda: {
            "slot_id": 1,
            "source_id": "camera-insta360",
            "display_name": "Insta360 Link",
            "player_side": "player-1",
            "frame_id": 42,
            "frame_timestamp": 123.5,
            "card_crop_valid": True,
        },
    )


def test_settings_default_off_persist_and_validate(service):
    assert service.settings()["enabled"] is False
    saved = service.save_settings({
        **service.default_settings(),
        "enabled": True,
        "workflowMode": "pack-ripping",
        "minimumConfidence": 0.85,
    })
    assert saved["enabled"] is True
    assert service.settings() == saved
    with pytest.raises(ValueError):
        service.save_settings({"workflowMode": "invented"})
    with pytest.raises(ValueError):
        service.save_settings({"minimumConfidence": 1.5})


def test_disabled_and_low_confidence_do_not_capture(service):
    assert service.evaluate_recognition(_snapshot())["reason"] == "disabled"
    service.save_settings({**service.default_settings(), "enabled": True, "minimumConfidence": 0.99})
    result = service.evaluate_recognition(_snapshot(confidence=0.80))
    assert result == {"ok": False, "captured": False, "reason": "confidence_below_threshold"}
    assert service.list_events() == []


def test_unsupported_truthful_triggers_do_not_fabricate(service):
    for trigger, reason in (("value-threshold", "value_trigger_unavailable"), ("qualifying-hit", "qualifying_hit_unavailable")):
        service.save_settings({**service.default_settings(), "enabled": True, "triggerReason": trigger})
        assert service.evaluate_recognition(_snapshot())["reason"] == reason
    service.save_settings({**service.default_settings(), "enabled": True, "triggerReason": "rarity-threshold"})
    assert service.evaluate_recognition(_snapshot())["reason"] == "rarity_trigger_unavailable"


def test_automatic_capture_dedupes_generation_and_new_generation_captures(service):
    settings = service.save_settings({**service.default_settings(), "enabled": True, "workflowMode": "pack-ripping"})
    first = service.evaluate_recognition(_snapshot(7))
    duplicate = service.evaluate_recognition(_snapshot(7))
    second = service.evaluate_recognition(_snapshot(8))
    assert first["captured"] is True
    assert duplicate["duplicate"] is True
    assert duplicate["eventId"] == first["eventId"]
    assert second["captured"] is True
    assert len(service.list_events()) == 2
    assert settings["enabled"] is True


def test_full_frame_crop_checksum_dimensions_and_metadata(service):
    settings = {**service.default_settings(), "captureTypes": {"fullFrame": True, "cardFocus": True}}
    result = service.capture(trigger="manual", snapshot=_snapshot(), settings=settings)
    assert result["ok"] is True
    event = service.get_event(result["eventId"])
    assert event["camera"]["source_id"] == "camera-insta360"
    assert event["camera"]["slot_id"] == 1
    assert event["identity"]["card_id"] == "card-water-horsea"
    assert event["context"]["player_side"] == "player-1"
    assert event["recognition"]["verdict"] == "exact-match"
    assert {asset["type"] for asset in event["assets"]} == {"full_frame", "card_crop"}
    for asset in event["assets"]:
        path = service.root / asset["relative_path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    full = next(item for item in event["assets"] if item["type"] == "full_frame")
    crop = next(item for item in event["assets"] if item["type"] == "card_crop")
    assert (full["width"], full["height"]) == (320, 180)
    assert (crop["width"], crop["height"]) == (1000, 1400)


def test_card_crop_is_not_created_without_valid_geometry(tmp_path):
    service = ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="test",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: cv2.resize(_frame(), (1000, 1400)),
        camera_context_provider=lambda: {"card_crop_valid": False},
    )
    result = service.capture(
        trigger="manual",
        snapshot=_snapshot(),
        settings={
            **service.default_settings(),
            "captureTypes": {"fullFrame": True, "cardFocus": True},
        },
    )
    assert [asset["type"] for asset in result["event"]["assets"]] == ["full_frame"]


def test_manual_capture_works_when_auto_disabled_without_identity_fabrication(service):
    result = service.capture(trigger="manual", snapshot={"generation": 0})
    event = service.get_event(result["eventId"])
    assert result["ok"] is True
    assert event["identity"]["card_id"] is None
    assert event["identity"]["identity_verdict"] == "unknown"


def test_correction_preserves_original_and_creates_linked_revision(service):
    original_result = service.capture(trigger="manual", snapshot=_snapshot())
    original_before = service.get_event(original_result["eventId"])
    revision = service.correct_event(original_result["eventId"], {
        "identity": {"english_name": "Corrected Horsea"},
        "reason": "Operator reviewed reference art",
    })
    assert service.get_event(original_result["eventId"]) == original_before
    assert revision["revision_of"] == original_result["eventId"]
    assert revision["identity"]["english_name"] == "Corrected Horsea"
    assert revision["event_id"] != original_result["eventId"]


def test_missing_frame_creates_no_fake_event(tmp_path):
    service = ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="test",
        frame_provider=lambda: None,
        crop_provider=lambda: None,
        camera_context_provider=lambda: {},
    )
    result = service.capture(trigger="manual", snapshot={})
    assert result["ok"] is False
    assert result["reason"] == "capture_failed"
    assert service.list_events() == []


def test_disk_failure_is_isolated_and_creates_no_indexed_event(service, monkeypatch):
    monkeypatch.setattr(
        service,
        "_write_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = service.capture(trigger="manual", snapshot=_snapshot())
    assert result["ok"] is False
    assert "disk full" in result["error"]
    assert service.list_events() == []


def test_restart_reloads_events_and_asset_api_cannot_escape(service):
    result = service.capture(trigger="manual", snapshot=_snapshot())
    restarted = ProvenanceCaptureService(
        service.root,
        server_session_id="new-server",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: {},
    )
    assert restarted.get_event(result["eventId"])["event_id"] == result["eventId"]
    asset = restarted.get_event(result["eventId"])["assets"][0]
    assert restarted.asset_path(result["eventId"], asset["asset_id"]).is_file()
    assert restarted.asset_path(result["eventId"], "../../settings") is None


def test_promoted_active_source_is_recorded_without_staging_capture(tmp_path):
    context = {"slot_id": 1, "source_id": "camera-a", "display_name": "Camera A"}
    service = ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="test",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: dict(context),
    )
    first = service.capture(trigger="manual", snapshot=_snapshot(1))
    assert first["event"]["camera"]["source_id"] == "camera-a"
    context.update({"slot_id": 2, "source_id": "camera-b", "display_name": "Camera B"})
    second = service.capture(trigger="manual", snapshot=_snapshot(2))
    assert second["event"]["camera"]["slot_id"] == 2
    assert second["event"]["camera"]["source_id"] == "camera-b"
