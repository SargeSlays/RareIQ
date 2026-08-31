from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
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
        "identity_consistent": verified,
        "recognition_locked": verified,
        "result_current": True,
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


@pytest.mark.parametrize(
    ("unsafe_field", "unsafe_value"),
    (
        ("identity_consistent", False),
        ("recognition_locked", False),
        ("result_current", False),
        ("has_reference_evidence", False),
    ),
)
def test_automatic_capture_requires_authoritative_identity(
    service,
    unsafe_field,
    unsafe_value,
):
    service.save_settings({**service.default_settings(), "enabled": True})
    snapshot = _snapshot()
    snapshot[unsafe_field] = unsafe_value

    result = service.evaluate_recognition(snapshot)

    assert result == {
        "ok": False,
        "captured": False,
        "reason": "identity_not_exact",
    }
    assert service.list_events() == []


def test_manual_capture_strips_disputed_catalog_identity(service):
    snapshot = _snapshot()
    snapshot["identity_consistent"] = False
    snapshot["identity_conflicts"] = [{
        "field": "language",
        "observed": "Chinese",
        "catalog": "Japanese",
    }]

    result = service.capture(trigger="manual", snapshot=snapshot)
    event = service.get_event(result["eventId"])

    assert result["captured"] is True
    assert event["identity"]["identity_verdict"] == "provisional"
    assert event["identity"]["card_id"] is None
    assert event["identity"]["english_name"] is None
    assert event["recognition"]["verdict"] == "provisional"


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


def test_concurrent_automatic_capture_atomically_claims_one_generation(service, monkeypatch):
    service.save_settings({**service.default_settings(), "enabled": True})
    entered = threading.Event()
    release = threading.Event()
    original_write = service._write_image

    def slow_write(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(service, "_write_image", slow_write)
    with ThreadPoolExecutor(max_workers=8) as executor:
        first = executor.submit(service.evaluate_recognition, _snapshot(21))
        assert entered.wait(timeout=5)
        rest = [
            executor.submit(service.evaluate_recognition, _snapshot(21))
            for _ in range(7)
        ]
        release.set()
        results = [first.result(timeout=5), *(item.result(timeout=5) for item in rest)]

    assert sum(result.get("captured") is True for result in results) == 1
    assert sum(result.get("duplicate") is True for result in results) == 7
    assert len(service.list_events()) == 1


def test_failed_automatic_claim_is_released_for_controlled_retry(service, monkeypatch):
    service.save_settings({**service.default_settings(), "enabled": True})
    original_write = service._write_image
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("transient write failure")
        return original_write(*args, **kwargs)

    monkeypatch.setattr(service, "_write_image", fail_once)
    failed = service.evaluate_recognition(_snapshot(22))
    retried = service.evaluate_recognition(_snapshot(22))
    assert failed["captured"] is False
    assert retried["captured"] is True
    assert len(service.list_events()) == 1


def test_new_generation_card_and_active_source_are_independent(tmp_path):
    context = {"slot_id": 1, "source_id": "camera-a", "display_name": "Camera A"}
    service = ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="test",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: dict(context),
    )
    service.save_settings({**service.default_settings(), "enabled": True})
    first = service.evaluate_recognition(_snapshot(30))
    second_snapshot = _snapshot(31)
    second_snapshot["primary_candidate"]["id"] = "card-b"
    second_snapshot["primary_candidate"]["english_name"] = "Card B"
    second = service.evaluate_recognition(second_snapshot)
    context.update({"slot_id": 2, "source_id": "camera-b", "display_name": "Camera B"})
    third = service.evaluate_recognition(_snapshot(32))
    assert [first["captured"], second["captured"], third["captured"]] == [True, True, True]
    assert [event["camera"]["source_id"] for event in reversed(service.list_events())] == [
        "camera-a", "camera-a", "camera-b"
    ]


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


def test_provenance_preserves_native_active_4k_frame(tmp_path):
    frame = _frame(width=3840, height=2160)
    service = ProvenanceCaptureService(
        tmp_path / "provenance",
        server_session_id="4k-test",
        frame_provider=lambda: frame.copy(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: {
            "slot_id": 1,
            "source_id": "camera-insta360",
            "display_name": "Insta360 Link",
        },
    )
    result = service.capture(trigger="manual", snapshot=_snapshot())
    asset = result["event"]["assets"][0]
    assert (asset["width"], asset["height"]) == (3840, 2160)


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


def test_new_storage_root_keeps_legacy_events_assets_and_settings_visible(tmp_path):
    legacy_root = tmp_path / "repository" / "rareiq" / "data" / "provenance"
    legacy = ProvenanceCaptureService(
        legacy_root,
        server_session_id="legacy-server",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: {"slot_id": 1, "source_id": "legacy-camera"},
    )
    legacy.save_settings({
        **legacy.default_settings(),
        "workflowMode": "pack-ripping",
        "customerId": "customer-legacy",
    })
    old_capture = legacy.capture(trigger="manual", snapshot=_snapshot(40))
    old_event = old_capture["event"]
    old_asset = old_event["assets"][0]

    primary_root = tmp_path / "external-drive" / "provenance"
    current = ProvenanceCaptureService(
        primary_root,
        legacy_roots=(legacy_root,),
        server_session_id="current-server",
        frame_provider=lambda: _frame(),
        crop_provider=lambda: None,
        camera_context_provider=lambda: {"slot_id": 1, "source_id": "current-camera"},
    )

    assert current.settings()["customerId"] == "customer-legacy"
    assert current.get_event(old_event["event_id"])["event_id"] == old_event["event_id"]
    assert current.asset_path(old_event["event_id"], old_asset["asset_id"]).is_file()
    storage_status = current.capability()["storage"]
    assert storage_status["root"] == str(primary_root.resolve())
    assert storage_status["legacy_event_count"] == 1

    new_capture = current.capture(trigger="manual", snapshot=_snapshot(41))
    new_event = new_capture["event"]
    new_asset = new_event["assets"][0]
    assert current.asset_path(new_event["event_id"], new_asset["asset_id"]).is_file()
    assert (primary_root / "events.jsonl").is_file()
    assert new_event["event_id"] not in (legacy_root / "events.jsonl").read_text(encoding="utf-8")


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


def _reopen(service, session_id=None):
    return ProvenanceCaptureService(
        service.root,
        server_session_id=session_id or service.server_session_id,
        frame_provider=service._frame_provider,
        crop_provider=service._crop_provider,
        camera_context_provider=service._camera_context_provider,
    )


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -float("inf"), -0.1, 1.1, "bad", None, True])
def test_invalid_confidence_never_arms_capture_even_at_zero_threshold(service, confidence):
    service.save_settings({"enabled": True, "minimumConfidence": 0})
    snapshot = _snapshot(confidence=confidence)
    snapshot["confidence"] = 1.0

    result = service.evaluate_recognition(snapshot)

    assert result["captured"] is False
    assert result["reason"] == "invalid_confidence"
    assert service.list_events() == []


def test_authoritative_zero_confidence_does_not_fall_back_to_secondary_score(service):
    service.save_settings({"enabled": True})
    snapshot = {**_snapshot(confidence=0), "confidence": 0.99}
    assert service.evaluate_recognition(snapshot)["reason"] == "confidence_below_threshold"
    assert service.list_events() == []


def test_legacy_confidence_is_used_only_when_overall_score_is_absent(service):
    service.save_settings({"enabled": True})
    snapshot = _snapshot()
    del snapshot["overall_confidence"]
    snapshot["confidence"] = 0.99
    assert service.evaluate_recognition(snapshot)["captured"] is True


@pytest.mark.parametrize("qualifying_hit", ["false", "true", 1, [], {}])
def test_qualifying_hit_requires_explicit_backend_boolean(service, qualifying_hit):
    service.save_settings({"enabled": True, "triggerReason": "qualifying-hit"})
    snapshot = _snapshot()
    snapshot["primary_candidate"]["qualifying_hit"] = qualifying_hit
    assert service.evaluate_recognition(snapshot)["reason"] == "qualifying_hit_unavailable"
    assert service.list_events() == []


def test_qualifying_hit_true_can_capture(service):
    service.save_settings({"enabled": True, "triggerReason": "qualifying-hit"})
    snapshot = _snapshot()
    snapshot["primary_candidate"]["qualifying_hit"] = True
    assert service.evaluate_recognition(snapshot)["captured"] is True


def test_verified_flags_without_candidate_do_not_create_exact_match_proof(service):
    service.save_settings({"enabled": True})
    snapshot = {**_snapshot(), "primary_candidate": None}
    assert service.evaluate_recognition(snapshot)["reason"] == "identity_not_exact"
    assert service.capture(snapshot=snapshot)["event"]["identity"]["identity_verdict"] == "unknown"


def test_direct_automatic_capture_cannot_bypass_safety_gate(service):
    assert service.capture(trigger="exact-match", snapshot=_snapshot())["reason"] == "disabled"
    service.save_settings({"enabled": True})
    assert service.capture(trigger="exact-match", snapshot=_snapshot(verified=False))["reason"] == "identity_not_exact"
    assert service.list_events() == []


@pytest.mark.parametrize("enabled", [False, True])
def test_manual_trigger_never_captures_from_recognition_events(service, enabled):
    service.save_settings({"enabled": enabled, "triggerReason": "manual"})
    assert service.evaluate_recognition(_snapshot())["reason"] == ("manual_only" if enabled else "disabled")
    assert service.list_events() == []


def test_automatic_capture_cannot_override_the_configured_trigger(service):
    service.save_settings({"enabled": True, "triggerReason": "value-threshold"})
    result = service.capture(trigger="exact-match", snapshot=_snapshot())
    assert result["reason"] == "trigger_not_armed"
    assert service.list_events() == []


def test_dedupe_reloads_only_within_original_server_session(service):
    service.save_settings({"enabled": True})
    first = service.evaluate_recognition(_snapshot())
    same_session = _reopen(service)
    assert same_session.evaluate_recognition(_snapshot())["eventId"] == first["eventId"]
    assert len(same_session.list_events()) == 1

    new_session = _reopen(service, "new-server")
    second = new_session.evaluate_recognition(_snapshot())
    assert second["captured"] is True
    assert second["eventId"] != first["eventId"]
    assert len(new_session.list_events()) == 2
    assert _reopen(new_session).evaluate_recognition(_snapshot())["duplicate"] is True


def test_capture_context_failure_is_reported_and_retry_is_not_blocked(service, monkeypatch):
    provider = service._camera_context_provider

    def offline():
        raise OSError("camera disconnected")

    monkeypatch.setattr(service, "_camera_context_provider", offline)
    result = service.capture(snapshot=_snapshot())
    assert result["reason"] == "capture_failed"
    assert service.capability()["status"]["state"] == "error"
    assert service.list_events() == []
    monkeypatch.setattr(service, "_camera_context_provider", provider)
    assert service.capture(snapshot=_snapshot())["captured"] is True


@pytest.mark.parametrize("generation", ["not-a-generation", float("inf")])
def test_invalid_generation_returns_failure_without_escaping_capture(service, generation):
    result = service.capture(snapshot=_snapshot(generation=generation))
    assert result["reason"] == "capture_failed"
    assert service.list_events() == []


@pytest.mark.parametrize("payload", [42, "old-settings", {"captureTypes": 42}])
def test_malformed_saved_settings_fail_closed(service, payload):
    service.settings_path.write_text(json.dumps(payload), encoding="utf-8")
    assert service.settings() == service.default_settings()
    assert service.evaluate_recognition(_snapshot())["reason"] == "disabled"


def test_corrupt_primary_settings_do_not_rearm_old_legacy_configuration(service, tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    (legacy_root / "settings.json").write_text('{"enabled": true}', encoding="utf-8")
    service.legacy_roots = (legacy_root,)
    service.settings_path.write_text("{interrupted settings", encoding="utf-8")
    assert service.settings() == service.default_settings()
    assert service.evaluate_recognition(_snapshot())["reason"] == "disabled"


@pytest.mark.parametrize("artwork_index", [None, {"top_score": float("nan")}, {"top_score": float("inf")}])
def test_manual_proof_uses_null_for_unavailable_confidence(service, artwork_index):
    snapshot = {**_snapshot(confidence=float("nan")), "artwork_index": artwork_index}
    result = service.capture(snapshot=snapshot)
    assert result["captured"] is True
    assert result["event"]["recognition"]["recognition_confidence"] is None
    assert result["event"]["recognition"]["visual_confidence"] is None
    json.dumps(result["event"], allow_nan=False)


def test_corrupt_index_record_does_not_hide_valid_history_or_prevent_restart(service):
    first = service.capture(snapshot=_snapshot())
    broken = {**first["event"], "event_id": "broken", "trigger_reason": "exact-match", "recognition_generation": "bad", "camera": 42}
    with service.index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(broken) + "\n")
    second = service.capture(snapshot=_snapshot(8))
    reopened = _reopen(service)
    assert {event["event_id"] for event in reopened.list_events()} == {first["eventId"], second["eventId"]}


def test_partial_index_tail_does_not_swallow_the_next_saved_event(service):
    first = service.capture(snapshot=_snapshot())
    with service.index_path.open("ab") as handle:
        handle.write(b'{"event_id":"interrupted')
    second = service.capture(snapshot=_snapshot(8))
    assert second["captured"] is True
    reopened = _reopen(service)
    assert {event["event_id"] for event in reopened.list_events()} == {first["eventId"], second["eventId"]}


def test_index_sync_failure_does_not_reappear_as_success_after_restart(service, monkeypatch):
    original = service.capture(snapshot=_snapshot())
    index_before = service.index_path.read_bytes()

    def disk_full(_fd):
        raise OSError("index sync failed")

    with monkeypatch.context() as patch:
        patch.setattr("rareiq.services.provenance_capture_service.os.fsync", disk_full)
        result = service.capture(snapshot=_snapshot(8))
    assert result["captured"] is False
    assert service.index_path.read_bytes() == index_before
    assert [event["event_id"] for event in _reopen(service).list_events()] == [original["eventId"]]
    assert len(list(service.root.rglob("event.json"))) == 1
    assert len(list(service.root.rglob("*.png"))) == 1
    assert service.capture(snapshot=_snapshot(8))["captured"] is True


@pytest.mark.parametrize("failure_point", ["crop", "manifest"])
def test_partial_capture_failure_removes_only_its_own_new_bundle(service, monkeypatch, failure_point):
    original = service.capture(snapshot=_snapshot())["event"]
    image_path = service.asset_path(original["event_id"], original["assets"][0]["asset_id"])
    original_bytes = image_path.read_bytes()
    settings = {"captureTypes": {"fullFrame": True, "cardFocus": True}}

    if failure_point == "crop":
        write_image = service._write_image

        def fail_crop(event_dir, event_id, asset_type, image):
            if asset_type == "card_crop":
                raise OSError("crop write failed")
            return write_image(event_dir, event_id, asset_type, image)

        monkeypatch.setattr(service, "_write_image", fail_crop)
    else:
        def fail_manifest(path, payload):
            path.with_suffix(".json.tmp").write_text("partial", encoding="utf-8")
            raise OSError("manifest write failed")

        monkeypatch.setattr(service, "_atomic_json", fail_manifest)

    result = service.capture(snapshot=_snapshot(8), settings=settings)
    assert result["captured"] is False
    assert image_path.read_bytes() == original_bytes
    assert len(list(service.root.rglob("event.json"))) == 1
    assert len(list(service.root.rglob("*.png"))) == 1
    assert not list(service.root.rglob("*.tmp"))
    assert service.list_events() == [original]


def test_failed_correction_preserves_original_and_leaves_no_revision(service, monkeypatch):
    original = service.capture(snapshot=_snapshot())["event"]
    index_before = service.index_path.read_bytes()

    def disk_full(_fd):
        raise OSError("index sync failed")

    with monkeypatch.context() as patch:
        patch.setattr("rareiq.services.provenance_capture_service.os.fsync", disk_full)
        with pytest.raises(OSError, match="index sync failed"):
            service.correct_event(original["event_id"], {"identity": {"english_name": "Not saved"}})
    assert service.index_path.read_bytes() == index_before
    assert len(list(service.root.rglob("event.json"))) == 1
    assert _reopen(service).list_events() == [original]


def test_event_directory_collision_cannot_delete_existing_evidence(service, monkeypatch):
    from types import SimpleNamespace

    original = service.capture(snapshot=_snapshot())["event"]
    image = service.asset_path(original["event_id"], original["assets"][0]["asset_id"])
    before = image.read_bytes()
    monkeypatch.setattr(
        "rareiq.services.provenance_capture_service.uuid.uuid4",
        lambda: SimpleNamespace(hex=original["event_id"]),
    )
    assert service.capture(snapshot=_snapshot(8))["captured"] is False
    assert image.read_bytes() == before
    assert _reopen(service).list_events() == [original]


def test_short_index_write_is_a_failed_capture_not_confirmed_evidence(service, monkeypatch):
    original = service.capture(snapshot=_snapshot())["event"]
    before = service.index_path.read_bytes()
    path_open = Path.open

    class ShortWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def write(self, data):
            return self.handle.write(data[:len(data) // 2])

    def open_short(path, mode="r", *args, **kwargs):
        handle = path_open(path, mode, *args, **kwargs)
        return ShortWriter(handle) if path == service.index_path and mode == "a+b" else handle

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_short)
        result = service.capture(snapshot=_snapshot(8))
    assert result["captured"] is False
    assert service.index_path.read_bytes() == before
    assert _reopen(service).list_events() == [original]


@pytest.mark.parametrize("workflow,side", [("single-card-sales", None), ("pack-ripping", None), ("pack-battle", "player-2")])
def test_workflow_context_round_trips_with_server_session(service, workflow, side):
    result = service.capture(snapshot=_snapshot(), settings={
        "workflowMode": workflow,
        "customerId": "customer-1",
        "vendorId": "vendor-1",
        "packNumber": 3,
        "turnNumber": 2,
        "playerSide": side,
    })
    event = _reopen(service).get_event(result["eventId"])
    assert event["workflow"] == workflow
    assert event["server_session_id"] == "server-test"
    assert event["context"] == {
        "customer": "customer-1", "vendor": "vendor-1", "pack_id": 3,
        "turn_id": 2, "player_side": side or "player-1",
    }


def test_corrections_preserve_original_manifest_and_image_bytes_across_restart(service):
    original = service.capture(snapshot=_snapshot())["event"]
    image = service.asset_path(original["event_id"], original["assets"][0]["asset_id"])
    manifest = image.parent / "event.json"
    before = (image.read_bytes(), manifest.read_bytes())
    revision = service.correct_event(original["event_id"], {"identity": {"english_name": "Corrected"}})
    reopened = _reopen(service)
    assert (image.read_bytes(), manifest.read_bytes()) == before
    assert reopened.get_event(original["event_id"]) == original
    assert reopened.get_event(revision["event_id"])["revision_of"] == original["event_id"]
