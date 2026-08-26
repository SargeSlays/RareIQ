from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.core.recognition_state import RecognitionStateStore
from rareiq.services.pipeline_state_service import PipelineStateService
from rareiq.services.trigger_manager_service import TriggerManagerService
from rareiq.services.vision_service import MultiFrameAcquisitionBuffer, VisionService
from rareiq.services.vision_service import ConfidenceLockTracker
import cv2


class RecognitionDouble:
    def __init__(self, results: list[str] | None = None):
        self.results = list(results or ["accepted"])
        self.calls: list[dict] = []
        self.invalidated = 0

    def invalidate_before(self, generation):
        self.invalidated = generation

    def submit_frame(self, frame, **metadata):
        self.calls.append({"frame": frame.copy(), **metadata})
        return self.results.pop(0) if self.results else "accepted"

    def status(self):
        return {"enabled": True, "busy": False, "candidates": []}


class VisionDouble:
    def __init__(self):
        self.crop = np.full((1400, 1000, 3), 120, np.uint8)
        self.frame_id = 10
        self.fresh = {"ok": True, "path": "fresh.jpg", "frame_id": 10}
        self.latest_crop_calls = 0

    def latest_crop(self):
        self.latest_crop_calls += 1
        return self.crop.copy()

    def status(self):
        return {"frame_id": self.frame_id}

    def capture_fresh(self, source="manual"):
        return dict(self.fresh)


class CatalogDouble:
    def __init__(self):
        self.submitted = []

    def submit(self, payload):
        self.submitted.append(dict(payload))


class SessionDouble:
    def __init__(self):
        self.cards = []

    def add_card(self, card):
        self.cards.append(dict(card))
        return {"card_count": len(self.cards)}


def coordinator(results=None):
    obj = object.__new__(RareIQOrchestrator)
    obj.vision = VisionDouble()
    obj.recognition = RecognitionDouble(results)
    obj.catalog = CatalogDouble()
    obj.learning_queue = SimpleNamespace(
        correction_match=lambda _fingerprint, _candidate: None
    )
    obj.pipeline_state = PipelineStateService()
    obj.recognition_state = RecognitionStateStore()
    obj._continuous_state = "EMPTY"
    obj._continuous_state_at = 0.0
    obj._recognition_generation = 0
    obj._active_job_generation = None
    obj._pending_recognition = None
    obj._deferred_change_evidence = None
    obj._current_acquisition_epoch = 0
    obj._minimum_capture_frame_id = 0
    obj._current_full_fingerprint = None
    obj._current_artwork_fingerprint = None
    obj._last_submitted_crop_hash = None
    obj._last_recognition_submit_at = 0.0
    obj._recognition_submit_count = 0
    obj._recognition_duplicate_count = 0
    obj._last_trigger_result = "waiting"
    obj._auto_capture_generation = None
    obj._current_stream_session_id = 4
    obj._active_capture_attribution = None
    return obj


def capture_payload(obj, *, source="auto", frame_id=10, epoch=0):
    return {
        "source": source,
        "frame_id": frame_id,
        "acquisition_epoch": epoch,
        "crop": obj.vision.crop.copy(),
        "validation": {"accepted": True},
    }


def test_wrong_stream_session_capture_is_rejected_without_generation_change():
    obj = coordinator()
    payload = capture_payload(obj)
    payload["provenance"] = {
        "stream_session_id": 3,
        "device_sequence_id": 8,
        "content_fingerprint": "aaaa",
    }
    obj._submit_captured_card(payload)
    assert obj._last_trigger_result == "stale_capture_stream_session"
    assert obj._recognition_generation == 0
    assert obj.recognition.calls == []


def test_submission_and_completion_journal_retain_full_attribution():
    obj = coordinator()
    obj._current_recognition_card = lambda: {
        "card_name": "Card B",
        "identity_authoritative": True,
    }
    payload = capture_payload(obj, frame_id=22)
    payload.update({
        "path": "captures/card-b.jpg",
        "crop_path": "captures/card-b.jpg",
        "provenance": {
            "stream_session_id": 4,
            "device_sequence_id": 91,
            "device_timestamp": 12.5,
            "content_fingerprint": "abcdef",
        },
    })
    obj._submit_captured_card(payload)
    obj._apply_recognition_pipeline_update({
        "generation": 1,
        "frame_id": 22,
        "candidates": [{"id": "card-b", "name": "Card B"}],
    })
    submission = next(
        item for item in obj._diagnostic_journal
        if item["event"] == "recognition_submission"
    )
    completion = next(
        item for item in obj._diagnostic_journal
        if item["event"] == "recognition_completion"
    )
    assert submission["crop_path"] == "captures/card-b.jpg"
    assert submission["stream_session_id"] == 4
    assert submission["device_sequence_id"] == 91
    assert completion["candidate_id"] == "card-b"
    assert completion["capture_attribution"]["generation"] == 1


def test_empty_acquiring_stable_recognizing_identified():
    obj = coordinator()
    obj._observe_card_tracking({"visible": True, "stable": False, "frame_id": 1})
    assert obj._continuous_state == "ACQUIRING"
    obj._observe_card_tracking({"visible": True, "stable": True, "frame_id": 2})
    assert obj._continuous_state == "STABLE"
    obj._submit_captured_card(capture_payload(obj, frame_id=2))
    assert obj._continuous_state == "RECOGNIZING"
    obj._current_recognition_card = lambda: {
        "card_name": "Card",
        "identity_authoritative": True,
    }
    obj._apply_recognition_pipeline_update({"generation": 1, "frame_id": 2})
    assert obj._continuous_state == "IDENTIFIED"


def test_handheld_jitter_does_not_retrigger():
    obj = coordinator()
    obj._continuous_state = "IDENTIFIED"
    for frame in range(5):
        obj._observe_card_tracking({"visible": True, "stable": True, "frame_id": frame})
    assert not obj.recognition.calls


def test_small_angle_changes_preserve_same_card_identity():
    buffer = MultiFrameAcquisitionBuffer()
    image = np.full((1400, 1000, 3), 100, np.uint8)
    sample = buffer.add(crop=image, polygon=np.zeros((4, 2)), frame_id=1, detection_confidence=.9)
    buffer.mark_captured(sample)
    changed = image.copy(); changed[:, :3] = 103
    current = buffer.add(crop=changed, polygon=np.zeros((4, 2)), frame_id=2, detection_confidence=.9)
    assert not buffer.observe_replacement(current.fingerprint)


def replacement_payload(**overrides):
    payload = {
        "frame_id": 9,
        "replacement_confirmed": True,
        "decisive": True,
        "geometry_valid": True,
        "changed_frames": 6,
        "full_card_hash_distance": 18,
        "artwork_hash_distance": 16,
        "structural_similarity": 0.55,
    }
    payload.update(overrides)
    return payload


def test_ambiguous_change_during_recognition_is_deferred():
    obj = coordinator()
    obj._continuous_state = "RECOGNIZING"
    obj._recognition_generation = 7

    obj._begin_card_change(replacement_payload(
        decisive=False,
        replacement_confirmed=False,
        changed_frames=4,
    ))

    assert obj._recognition_generation == 7
    assert obj.recognition.invalidated == 0
    assert obj._continuous_state == "RECOGNIZING"
    assert obj._deferred_change_evidence["generation"] == 7


def test_active_result_publishes_and_discards_ambiguous_change():
    obj = coordinator()
    obj._continuous_state = "RECOGNIZING"
    obj._recognition_generation = 3
    obj._deferred_change_evidence = {
        **replacement_payload(decisive=False),
        "generation": 3,
    }
    obj._current_recognition_card = lambda: {"card_name": "Same card"}

    obj._apply_recognition_pipeline_update({"generation": 3, "frame_id": 20})

    assert obj._continuous_state == "IDENTIFIED"
    assert obj._deferred_change_evidence is None
    assert obj._recognition_generation == 3


def test_decisive_replacement_during_recognition_invalidates_generation():
    obj = coordinator()
    obj._continuous_state = "RECOGNIZING"
    obj._recognition_generation = 4

    obj._begin_card_change(replacement_payload())

    assert obj._recognition_generation == 5
    assert obj.recognition.invalidated == 5
    assert obj._continuous_state == "CHANGING"


def test_capture_event_submits_exact_crop_without_latest_crop_fetch():
    obj = coordinator()
    event_crop = np.arange(1400 * 1000 * 3, dtype=np.uint8).reshape(1400, 1000, 3)
    payload = capture_payload(obj)
    payload["crop"] = event_crop

    obj._submit_captured_card(payload)

    assert obj.vision.latest_crop_calls == 0
    assert np.array_equal(obj.recognition.calls[0]["frame"], event_crop)


def test_stale_epoch_and_frame_capture_events_do_not_change_generation():
    obj = coordinator()
    obj._continuous_state = "CHANGING"
    obj._current_acquisition_epoch = 4
    obj._minimum_capture_frame_id = 50
    before = obj._recognition_generation

    obj._submit_captured_card(capture_payload(obj, epoch=3, frame_id=60))
    assert obj._last_trigger_result == "stale_capture_epoch"
    obj._submit_captured_card(capture_payload(obj, epoch=4, frame_id=49))
    assert obj._last_trigger_result == "stale_capture_frame"
    assert obj._recognition_generation == before
    assert not obj.recognition.calls


def test_rejected_capture_event_does_not_increment_generation():
    obj = coordinator()
    payload = capture_payload(obj)
    payload["validation"] = {
        "accepted": False,
        "rejection_reason": "insufficient_sharpness",
    }
    obj._submit_captured_card(payload)
    assert obj._recognition_generation == 0
    assert not obj.recognition.calls


def test_direct_replacement_creates_fresh_generation():
    obj = coordinator(); obj._recognition_generation = 3
    obj._begin_card_change({"frame_id": 9, "full_card_fingerprint": "b"})
    assert obj._recognition_generation == 4


def test_artwork_branch_is_decisive_during_recognition():
    obj = coordinator()
    obj._continuous_state = "RECOGNIZING"
    obj._recognition_generation = 3
    obj._current_acquisition_epoch = 2
    obj._begin_card_change(replacement_payload(
        full_card_hash_distance=7,
        artwork_hash_distance=18,
        structural_similarity=.50,
        acquisition_epoch=3,
    ))
    assert obj._recognition_generation == 4
    assert obj._continuous_state == "CHANGING"
    assert obj._deferred_change_evidence is None
    assert obj._continuous_state == "CHANGING"


def test_confirmed_replacement_is_one_shot_and_clears_card_a():
    obj = coordinator()
    obj._recognition_generation = 4
    obj._current_acquisition_epoch = 2
    obj._continuous_state = "IDENTIFIED"
    obj.recognition_state.update_recognition({
        "generation": 4, "candidates": [{"id": "card-a"}]
    })
    event = replacement_payload(
        frame_id=40, acquisition_epoch=3,
        polygon_iou=.98, corner_movement=.002,
    )
    obj._begin_card_change(event)
    obj._begin_card_change({**event, "frame_id": 41})
    state = obj.recognition_state.snapshot()
    assert obj._recognition_generation == 5
    assert obj._continuous_state == "CHANGING"
    assert state["candidates"] == []
    increments = [item for item in obj._diagnostic_journal
                  if item["event"] == "generation_increment"]
    assert len(increments) == 1


def test_card_b_auto_capture_submits_once_per_generation():
    obj = coordinator()
    obj._recognition_generation = 5
    obj._current_acquisition_epoch = 3
    obj._continuous_state = "CHANGING"
    payload = capture_payload(obj, frame_id=50, epoch=3)
    obj._submit_captured_card(payload)
    obj._submit_captured_card({**payload, "frame_id": 51})
    assert len(obj.recognition.calls) == 1
    assert obj._recognition_generation == 5
    assert obj._last_trigger_result == "duplicate_generation_capture"


def test_diagnostic_journal_records_transition_submission_and_discard():
    obj = coordinator()
    obj._observe_card_tracking({"visible": True, "frame_id": 1})
    obj._submit_captured_card(capture_payload(obj, frame_id=2))
    obj._apply_recognition_pipeline_update({"generation": 0, "frame_id": 1})
    events = [item["event"] for item in obj._diagnostic_journal]
    assert "state_transition" in events
    assert "recognition_submission" in events
    assert "recognition_discarded" in events
    assert len(obj._diagnostic_journal) <= 64


def test_similar_variant_requires_confirmed_change_event():
    obj = coordinator(); obj._begin_card_change({"replacement_confirmed": True})
    assert obj._continuous_state == "CHANGING"


def test_short_obstruction_can_return_without_generation_change():
    obj = coordinator(); obj._continuous_state = "IDENTIFIED"; obj._recognition_generation = 2
    obj._observe_card_tracking({"visible": False, "frame_id": 3})
    obj._observe_card_tracking({"visible": True, "frame_id": 4})
    assert obj._recognition_generation == 2


def test_confirmed_removal_clears_visible_result_fields():
    obj = coordinator(); obj.recognition_state.update_recognition({"candidates": [{"id": "old"}]})
    obj._confirm_card_removed({"frame_id": 4})
    state = obj.recognition_state.snapshot()
    assert state["continuous_state"] == "EMPTY"
    assert state["candidates"] == []


def test_verified_card_is_finalized_once_when_removed():
    obj = coordinator()
    obj.sessions = SessionDouble()
    events = []
    obj._emit_from_thread = events.append
    obj._removal_finalize_card = {
        "card_name": "Crocalor",
        "collector_number": "158",
        "recognition_signature": "gem5:158:2303/07",
        "identity_authoritative": True,
    }
    obj._removal_finalize_generation = obj._recognition_generation
    obj._recognition_decision_generation = None

    obj._confirm_card_removed({"frame_id": 4})
    obj._confirm_card_removed({"frame_id": 5})

    assert [card["collector_number"] for card in obj.sessions.cards] == ["158"]
    assert events[0]["type"] == "card_confirmed"
    assert events[0]["payload"]["reason"] == "verified_card_removed"


def test_rejected_generation_is_not_auto_finalized_on_removal():
    obj = coordinator()
    obj.sessions = SessionDouble()
    obj._emit_from_thread = lambda _event: None
    obj._removal_finalize_card = {"card_name": "Crocalor"}
    obj._removal_finalize_generation = obj._recognition_generation
    obj._recognition_decision_generation = obj._recognition_generation

    obj._confirm_card_removed({"frame_id": 4})

    assert obj.sessions.cards == []


def test_decision_uses_retained_verified_card_during_transient_empty_refresh():
    obj = coordinator()
    obj._current_recognition_card = lambda: None
    obj._removal_finalize_card = {
        "card_name": "Electrike",
        "collector_number": "023/084",
    }
    obj._removal_finalize_generation = obj._recognition_generation

    assert obj._decision_recognition_card() == {
        "card_name": "Electrike",
        "collector_number": "023/084",
    }


def test_decision_rejects_retained_card_from_prior_generation():
    obj = coordinator()
    obj._current_recognition_card = lambda: None
    obj._removal_finalize_card = {"card_name": "Old Card"}
    obj._removal_finalize_generation = obj._recognition_generation - 1

    assert obj._decision_recognition_card() is None


def test_verified_unified_state_clears_legacy_candidate_provisional_flag():
    obj = coordinator()
    obj.catalog.status = lambda: {}
    obj.recognition_state = SimpleNamespace(refresh=lambda **_kwargs: {
        "primary_candidate": {
            "id": "me05-023",
            "name": "Electrike",
            "collector_number": "023/084",
            "set_id": "me05",
            "set_name": "Pitch Black",
            "language": "English",
            "source": "global_visual_index",
            "provisional": True,
            "score": 0.92,
        },
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "identity_consistent": True,
        "result_current": True,
        "has_reference_evidence": True,
        "overall_confidence": 0.92,
        "revision": 3,
    })

    card = obj._current_recognition_card()

    assert card["card_name"] == "Electrike"
    assert card["provisional"] is False
    assert card["identity_authoritative"] is True


def test_current_recognition_card_does_not_fabricate_missing_market_value():
    obj = coordinator()
    obj.catalog.status = lambda: {}
    obj.recognition_state = SimpleNamespace(refresh=lambda **_kwargs: {
        "primary_candidate": {
            "id": "me5-53",
            "name": "Nickit",
            "collector_number": "53/84",
            "set_id": "me5",
            "set_name": "Pitch Black",
            "language": "English",
            "fused_score": 0.81,
        },
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "identity_consistent": True,
        "result_current": True,
        "has_reference_evidence": True,
        "revision": 4,
    })

    card = obj._current_recognition_card()

    assert card["market_price"] is None
    assert card["raw_market"] is None
    assert card["raw_value"] is None


def test_review_candidate_is_not_retained_as_current_card() -> None:
    obj = coordinator()
    obj._recognition_generation = 1
    obj._current_recognition_card = lambda: {
        "card_name": "Disputed candidate",
        "identity_authoritative": False,
    }

    obj._apply_recognition_pipeline_update({
        "generation": 1,
        "frame_id": 15,
        "candidates": [{"id": "candidate-a"}],
        "verification_state": "REVIEW_NEEDED",
        "identity_consistent": False,
        "recognition_locked": False,
    })

    stages = {
        item["key"]: item
        for item in obj.pipeline_state.snapshot()["stages"]
    }
    assert stages["current_card"]["state"] == "waiting"
    assert obj._last_trigger_result == "identity_review_required"
    assert getattr(obj, "_removal_finalize_card", None) is None


def test_removed_and_returned_card_starts_fresh_cycle():
    obj = coordinator(); obj._confirm_card_removed({}); generation = obj._recognition_generation
    obj._observe_card_tracking({"visible": True, "frame_id": 7})
    obj._submit_captured_card(capture_payload(
        obj, epoch=obj._current_acquisition_epoch
    ))
    assert obj._recognition_generation == generation + 1


def test_generation_n_cannot_overwrite_generation_n_plus_one():
    obj = coordinator(); obj._recognition_generation = 2; obj._continuous_state = "RECOGNIZING"
    obj._apply_recognition_pipeline_update({"generation": 1, "candidates": [{"id": "old"}]})
    assert obj._continuous_state == "RECOGNIZING"


def test_busy_recognition_retains_newest_pending_crop():
    obj = coordinator(["busy_queued", "busy_queued"])
    obj._submit_captured_card(capture_payload(obj, source="manual")); first = obj._pending_recognition
    obj.vision.crop.fill(200); obj._submit_captured_card(capture_payload(obj, source="manual"))
    assert obj._pending_recognition["generation"] > first["generation"]
    assert int(obj._pending_recognition["crop"].mean()) == 200


def test_only_orchestrator_submits_recognition_jobs(tmp_path: Path):
    vision = VisionDouble(); recognition = RecognitionDouble()
    trigger = TriggerManagerService(vision, recognition, PipelineStateService())
    vision.status = lambda: {"last_capture_path": "one.jpg", "frame_id": 1}
    assert trigger.tick() is False
    assert not recognition.calls


def test_same_unchanged_card_is_not_repeatedly_recognized():
    obj = coordinator(); obj._continuous_state = "IDENTIFIED"
    obj._observe_card_tracking({"visible": True, "stable": True})
    assert not obj.recognition.calls


def test_manual_capture_bypasses_deduplication():
    obj = coordinator(); obj._submit_captured_card(capture_payload(obj, source="manual")); obj._submit_captured_card(capture_payload(obj, source="manual"))
    assert len(obj.recognition.calls) == 2


def test_manual_capture_uses_fresh_capture_method():
    obj = coordinator(); result = obj.force_manual_capture()
    assert result["crop_path"] == "fresh.jpg"


def test_manual_capture_fails_when_no_current_card():
    obj = coordinator(); obj.vision.fresh = {"ok": False, "reason": "no_current_card"}
    assert obj.force_manual_capture()["reason"] == "no_current_card"


def test_trigger_manager_does_not_submit_recognition():
    test_only_orchestrator_submits_recognition_jobs(Path("."))


def test_state_store_generation_is_monotonic_by_coordinator():
    obj = coordinator(); obj._confirm_card_removed({}); obj._confirm_card_removed({})
    assert obj.recognition_state.snapshot()["generation"] == 2


def test_state_store_revision_increments_for_every_publication():
    store = RecognitionStateStore(); before = store.snapshot()["revision"]
    store.set_continuous_state("ACQUIRING", generation=1, card_present=True)
    assert store.snapshot()["revision"] == before + 1


def test_empty_state_has_no_current_result():
    store = RecognitionStateStore(); store.clear(generation=1)
    state = store.snapshot(); assert not state["result_current"] and not state["card_present"]


def test_out_of_order_result_is_ignored():
    obj = coordinator(); obj._recognition_generation = 5
    obj._apply_recognition_pipeline_update({"generation": 4, "candidates": [{"id": "stale"}]})
    assert obj.recognition_state.snapshot()["candidates"] == []


def test_extended_card_session_keeps_generations_monotonic_and_journal_bounded():
    obj = coordinator()
    obj.sessions = SessionDouble()
    obj._emit_from_thread = lambda _event: None
    completed_generations = []

    for cycle in range(100):
        visible_frame = cycle * 4 + 1
        capture_frame = visible_frame + 1
        obj._observe_card_tracking({
            "visible": True,
            "stable": False,
            "frame_id": visible_frame,
        })
        obj._observe_card_tracking({
            "visible": True,
            "stable": True,
            "frame_id": capture_frame,
        })
        epoch = obj._current_acquisition_epoch
        obj._submit_captured_card(capture_payload(
            obj,
            frame_id=capture_frame,
            epoch=epoch,
        ))
        generation = obj._recognition_generation
        obj._current_recognition_card = lambda generation=generation: {
            "id": f"card-{generation}",
            "card_name": f"Card {generation}",
            "identity_authoritative": True,
        }
        obj._apply_recognition_pipeline_update({
            "generation": generation,
            "frame_id": capture_frame,
            "candidates": [{"id": f"card-{generation}"}],
        })
        completed_generations.append(generation)

        # A late completion from the preceding card must never replace the
        # current generation during a long-running operator session.
        if generation > 1:
            obj._apply_recognition_pipeline_update({
                "generation": generation - 1,
                "frame_id": capture_frame - 2,
                "candidates": [{"id": "obsolete"}],
            })

        obj._confirm_card_removed({"frame_id": capture_frame + 1})
        assert obj._continuous_state == "EMPTY"
        assert obj.recognition_state.snapshot()["candidates"] == []

    # Each capture starts an odd-numbered recognition generation and each
    # confirmed removal advances once more to invalidate the removed card.
    assert completed_generations == list(range(1, 200, 2))
    assert obj._recognition_generation == 200
    assert obj._recognition_submit_count == 100
    assert obj._recognition_duplicate_count == 0
    assert len(obj.sessions.cards) == 100
    assert len(obj._diagnostic_journal) == 64
    assert all(
        later > earlier
        for earlier, later in zip(completed_generations, completed_generations[1:])
    )


def test_fragmented_outer_card_reaches_lock_with_full_card_crop():
    frame = np.full((1080, 1920, 3), 28, dtype=np.uint8)
    outer = np.array(
        [[650, 120], [1270, 120], [1270, 980], [1080, 980],
         [1080, 700], [1170, 650], [1080, 600], [1080, 250],
         [840, 250], [840, 600], [750, 650], [840, 700],
         [840, 980], [650, 980]],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [outer], (108, 108, 108))
    cv2.polylines(frame, [outer], True, (5, 5, 5), 9)
    cv2.rectangle(frame, (850, 500), (988, 693), (225, 225, 225), -1)
    cv2.rectangle(frame, (850, 500), (988, 693), (8, 8, 8), 5)

    result = VisionService.detect(frame)
    tracker = ConfidenceLockTracker(stable_target=8)
    locked = False
    for _ in range(16):
        visible, locked, _ = tracker.update(result.polygon, result.confidence)

    assert visible and locked
    assert result.crop is not None
    assert result.crop.shape == (1400, 1000, 3)
    assert abs(float(cv2.contourArea(result.polygon))) > 0.20
