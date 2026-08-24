import time
from collections import deque

from tests.test_automatic_recognition_trigger import capture_event, make_orchestrator


def test_pack_cycle_measures_removal_to_capture_submission():
    obj = make_orchestrator()
    obj._pack_cycle_samples = deque(maxlen=50)
    obj._confirm_card_removed({"frame_id": 70, "timestamp": time.time() - 0.05})
    event = capture_event(obj)
    event["acquisition_epoch"] = obj._current_acquisition_epoch
    event["frame_id"] = 78

    obj._submit_captured_card(event)

    cycle = obj._pack_cycle_snapshot()
    assert cycle["generation"] == obj._recognition_generation
    assert cycle["capture_frame_id"] == 78
    assert cycle["removal_to_capture_ms"] >= 0


def test_pack_cycle_records_first_candidate_and_verified_result():
    obj = make_orchestrator()
    obj._pack_cycle_samples = deque(maxlen=50)
    now = time.time()
    obj._pack_cycle = {
        "cycle_id": "cycle-1",
        "removed_at": now - 0.2,
        "capture_submitted_at": now - 0.1,
        "generation": 3,
    }
    obj._recognition_generation = 3
    obj._current_recognition_card = lambda: {"card_name": "Goldeen"}

    payload = {
        "generation": 3,
        "candidates": [{"id": "me05-013", "name": "Goldeen"}],
        "verification_state": "VERIFIED",
    }
    obj._apply_recognition_pipeline_update(payload)

    timings = payload["pack_cycle_timings"]
    assert timings["capture_to_candidate_ms"] >= 0
    assert timings["capture_to_verified_ms"] >= 0
    assert timings["removal_to_verified_ms"] >= timings["capture_to_verified_ms"]
    assert timings["sample_count"] == 1


def test_pack_cycle_history_is_bounded():
    obj = make_orchestrator()
    obj._pack_cycle_samples = deque(maxlen=50)
    for number in range(60):
        obj._pack_cycle_samples.append({"removal_to_verified_ms": float(number)})
    obj._pack_cycle = {"cycle_id": "current"}

    snapshot = obj._pack_cycle_snapshot()

    assert snapshot["sample_count"] == 50
    assert snapshot["p50_removal_to_verified_ms"] == 34.0
    assert snapshot["p95_removal_to_verified_ms"] == 56.0
