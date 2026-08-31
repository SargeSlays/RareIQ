"""Camera-free regressions for multi-card failure and interim-result safety."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from rareiq.services.multi_card_recognition_service import MultiCardRecognitionService
import rareiq.services.multi_card_recognition_service as multi_card


class ControlledWorker:
    def __init__(self, emit):
        self.emit = emit
        self.submissions = []
        self.failure = None

    def invalidate_before(self, generation):
        self.generation = generation

    def submit_frame(self, frame, **kwargs):
        if self.failure:
            raise self.failure
        self.submissions.append(kwargs)
        return "accepted"

    def finish(self, generation=None, **payload):
        submitted = self.submissions[-1]
        self.emit({"type": "recognition_update", "payload": {
            "generation": submitted["generation"] if generation is None else generation,
            "frame_id": submitted["frame_id"],
            "recognition_locked": False,
            "database_match": {"canonical_name": "Armarouge"},
            "overall_confidence": .75,
            **payload,
        }})

    def shutdown(self):
        pass


@pytest.fixture
def scan(tmp_path, monkeypatch):
    # Exercise coordinator recovery, never the operator's downloaded catalog.
    monkeypatch.setattr(MultiCardRecognitionService, "_load_reference_cards", staticmethod(lambda: []))
    prototype = SimpleNamespace(isolated_copy=ControlledWorker)
    service = MultiCardRecognitionService(
        prototype, history_path=tmp_path / "temporal.json",
        presentation_path=tmp_path / "presentation.json",
    )
    crop = np.zeros((70, 50, 3), dtype=np.uint8)
    detections = [{"slot": 1, "confidence": .9, "polygon": [], "crop": crop}]
    return SimpleNamespace(service=service, frame=crop, detections=detections,
                           worker=service._workers[1],
                           capture=lambda: service.capture(crop, max_cards=2, detections=detections))


def assert_failed(scan, reason):
    state = scan.service.status()
    assert state["status"] == "error"
    assert state["ok"] is False and state["reason"] == reason
    assert state["pending_count"] == state["verified_count"] == 0
    assert state["slots"][0]["status"] == "error"
    assert state["selected_slots"] == []
    assert not state["slots"][0]["output_ready"]
    saved = json.loads(scan.service._presentation_path.read_text(encoding="utf-8"))
    assert saved["completed_state"] is None
    assert saved["selected_slots"] == []


def test_detection_confidence_is_not_presented_as_identity_confidence(scan):
    slot = scan.capture()["slots"][0]
    assert slot["detection_confidence"] == .9
    assert slot["confidence"] is None
    assert slot["card"] is None and slot["output_ready"] is False


@pytest.mark.parametrize("flags,card_flags,needs_guard", [
    ({"verified": True}, {}, False),
    ({"verified": False}, {}, True),
    ({"verified": True}, {"retrieval_only": True}, True),
    ({"verified": True}, {"source": "global_visual_index"}, True),
    ({"verified": True, "exact_version_unresolved": True}, {}, True),
    ({"verified": True, "family_first_delegated": True}, {}, True),
])
def test_verified_catalog_name_does_not_repeat_exhaustive_family_search(scan, monkeypatch, flags, card_flags, needs_guard):
    item = {"slot": 1, "card": {"name": "Slowpoke", **card_flags}, **flags}
    scan.service._state["slots"] = [item]
    calls = []
    monkeypatch.setattr(scan.service, "_best_artwork_family", lambda slot: calls.append(slot) or None)
    scan.service._reconcile_missing_artwork_families()
    assert calls == ([1] if needs_guard else [])
    assert item["card"]["name"] == "Slowpoke"


@pytest.mark.parametrize("item_flags,card_flags,skip", [
    ({}, {}, True),
    ({"verified": True}, {}, True),
    ({"collector_number": "029/064"}, {}, False),
    ({"collector_number": None}, {}, False),
    ({"name_candidate": "Tropius"}, {}, False),
    ({"language": "Chinese"}, {}, False),
    ({"family_first_delegated": True}, {}, False),
    ({"exact_version_unresolved": True}, {}, False),
    ({"status": "recognizing"}, {}, False),
    ({}, {"retrieval_only": True}, False),
    ({}, {"verification_strong": False}, False),
    ({}, {"artwork_verification_strong": False}, False),
    ({}, {"provisional_reference": True}, False),
    ({}, {"provisional": True}, False),
    ({}, {"image_path": None}, False),
])
def test_crop_verified_fraction_avoids_redundant_family_search_without_promoting(scan, monkeypatch, item_flags, card_flags, skip):
    item = {"slot": 1, "status": "review-needed", "verified": False,
            "collector_number": "029/084", "name_candidate": "Slowpoke", "language": "English",
            "card": {"name": "Slowpoke", "collector_number": "29/84", "language": "en",
                     "source": "global_visual_index", "image_path": "verified.png",
                     "verification_strong": True, "artwork_verification_strong": True, **card_flags}, **item_flags}
    scan.service._state["slots"] = [item]
    calls = []
    monkeypatch.setattr(scan.service, "_best_artwork_family", lambda slot: calls.append(slot) or None)
    scan.service._reconcile_missing_artwork_families()
    assert calls == ([] if skip else [1])
    assert item["verified"] is item_flags.get("verified", False)
    assert item["status"] == item_flags.get("status", "review-needed")


@pytest.mark.parametrize("locked", [False, True])
def test_final_rejected_retrieval_does_not_become_the_card_identity(scan, locked):
    scan.capture()
    wrong = {"name": "Chandelure VMAX", "retrieval_only": True,
             "source": "global_visual_index", "score": .96}
    scan.worker.finish(database_match=None, candidates=[wrong], recognition_locked=locked)
    slot = scan.service.status()["slots"][0]
    assert slot["card"] is None
    assert slot["status"] == "review-needed"
    assert slot["verified"] is False
    assert slot["confidence"] is None
    assert slot["candidate_preview"] == [wrong]


def test_final_eligible_reference_is_selected_after_rejected_search_hit(scan):
    scan.capture()
    wrong = {"name": "Chandelure VMAX", "retrieval_only": True, "score": .99}
    right = {"name": "Armarouge", "verification_strong": True, "score": .8}
    scan.worker.finish(database_match=None, candidates=[wrong, right])
    assert scan.service.status()["slots"][0]["card"] == right


def test_reconciliation_cannot_promote_a_retrieval_only_identity(scan):
    scan.service._state["slots"] = [{"slot": 1, "status": "verified", "verified": True,
                                     "card": {"name": "Wrong", "retrieval_only": True}}]
    scan.service._enforce_exact_identity_safety()
    slot = scan.service.status()["slots"][0]
    assert slot["card"] is None and not slot["output_ready"]


def test_artwork_index_exception_fails_cleanly_and_next_capture_can_run(scan):
    def broken_index(_crops):
        raise RuntimeError("index unavailable")

    scan.service._artwork_index = SimpleNamespace(batch_shortlists=broken_index)
    state = scan.capture()
    assert state["ok"] is False
    assert_failed(scan, "recognition_failed")

    scan.service._artwork_index = None
    assert scan.capture()["status"] == "recognizing"
    scan.worker.finish()
    assert scan.service.status()["status"] == "complete"


def test_worker_submission_exception_does_not_wedge_future_scans(scan):
    scan.worker.failure = RuntimeError("worker unavailable")
    scan.capture()
    assert_failed(scan, "recognition_failed")
    scan.worker.failure = None
    assert scan.capture()["status"] == "recognizing"
    scan.worker.finish()
    assert scan.service.status()["status"] == "complete"


def test_worker_crash_event_fails_closed_instead_of_leaving_grid_analyzing(scan):
    scan.capture()
    scan.worker.finish(recognition_path="worker-error", error="recognition_failed")
    assert_failed(scan, "recognition_failed")
    assert scan.capture()["status"] == "recognizing"


def test_timed_out_shortlist_cannot_resurrect_pending_slots(scan, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(multi_card.time, "monotonic", lambda: now[0])

    def slow_index(_crops):
        now[0] += scan.service.RECOGNITION_TIMEOUT_SECONDS + 1
        assert_failed(scan, "recognition_timeout")
        return {"slots": {1: {"artwork_candidates": [
            {"canonical_name": "Stale family", "source": "pokipair", "image_path": f"{i}.png"}
            for i in range(3)
        ]}}}

    scan.service._artwork_index = SimpleNamespace(batch_shortlists=slow_index)
    scan.capture()
    assert_failed(scan, "recognition_timeout")
    assert scan.service.status()["slots"][0]["card"] is None
    assert scan.worker.submissions == []


def test_result_processing_error_clears_output_and_ignores_late_callback(scan, monkeypatch):
    def broken_reconciliation():
        raise RuntimeError("unavailable catalog")

    original = scan.service._reconcile_dominant_family
    monkeypatch.setattr(scan.service, "_reconcile_dominant_family", broken_reconciliation)
    scan.capture()
    scan.service._selected_slots.add(1)
    scan.worker.finish(recognition_locked=True)
    assert_failed(scan, "result_processing_failed")
    scan.worker.finish(recognition_locked=True)
    assert_failed(scan, "result_processing_failed")

    monkeypatch.setattr(scan.service, "_reconcile_dominant_family", original)
    assert scan.capture()["status"] == "recognizing"
    scan.worker.finish()
    assert scan.service.status()["status"] == "complete"


def test_stalled_scan_expires_and_old_generation_cannot_replace_retry(scan, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(multi_card.time, "monotonic", lambda: now[0])
    first = scan.capture()
    now[0] += scan.service.RECOGNITION_TIMEOUT_SECONDS - 1
    assert scan.service.status()["status"] == "recognizing"
    now[0] += 2
    assert_failed(scan, "recognition_timeout")
    scan.worker.finish()
    assert_failed(scan, "recognition_timeout")

    retry = scan.capture()
    assert retry["status"] == "recognizing"
    assert retry["job_id"] > first["job_id"]
    scan.worker.finish(generation=first["job_id"], database_match={"canonical_name": "Stale Vulpix"})
    assert scan.service.status()["slots"][0]["card"] is None
    scan.worker.finish()
    assert scan.service.status()["slots"][0]["card"]["canonical_name"] == "Armarouge"


@pytest.mark.parametrize("empty_scan", [True, False])
def test_new_scan_does_not_restore_previous_completed_output_after_restart(scan, empty_scan):
    scan.capture()
    scan.worker.finish()
    assert json.loads(scan.service._presentation_path.read_text(encoding="utf-8"))["completed_state"]

    scan.service.capture(scan.frame, max_cards=2, detections=[] if empty_scan else scan.detections)
    restored = MultiCardRecognitionService(
        SimpleNamespace(isolated_copy=ControlledWorker),
        history_path=scan.service._temporal_history_path,
        presentation_path=scan.service._presentation_path,
    )
    assert restored.status()["status"] == "idle"
    assert restored.status()["verified_count"] == 0
    assert all(item.get("card") is None for item in restored.status()["slots"])


@pytest.mark.parametrize("eligible", [None, {"canonical_name": "Armarouge", "score": .75}])
def test_interim_identity_uses_explicit_eligible_candidate_not_raw_shortlist(scan, eligible):
    scan.capture()
    scan.worker.finish(
        recognition_path="visual-interim", background_enrichment=True,
        interim_candidate=eligible,
        database_match=None,
        candidates=[{"canonical_name": "Vulpix", "source": "global_visual_index", "score": .95}],
    )
    result = scan.service.status()
    assert result["status"] == "recognizing" and result["completed_count"] == 0
    assert result["verified_count"] == 0
    assert result["slots"][0]["card"] == eligible
    if eligible is None:
        assert result["slots"][0]["confidence"] is None
    # Keep retrieval candidates available to reconciliation, not presentation.
    assert scan.service._candidate_cache[1][0]["canonical_name"] == "Vulpix"


def test_explicit_zero_confidence_does_not_fall_back_to_an_unrelated_score(scan):
    scan.capture()
    scan.worker.finish(recognition_path="visual-interim", interim_candidate={"name": "Candidate"},
                       overall_confidence=0.0, confidence=.99)
    assert scan.service.status()["slots"][0]["confidence"] == 0.0
