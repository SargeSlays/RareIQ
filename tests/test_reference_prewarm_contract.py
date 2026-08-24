import json
import time
import threading
from pathlib import Path

import cv2
import numpy as np

from rareiq.services.artwork_index_service import ArtworkIndexService


def build_index(tmp_path, count=3):
    records = []
    for index in range(count):
        image_path = tmp_path / f"card-{index}.png"
        image = np.full((280, 200, 3), 40 + (index * 37) % 180, dtype=np.uint8)
        cv2.rectangle(image, (20, 30), (180, 220), (220, 80, 40), 5)
        assert cv2.imwrite(str(image_path), image)
        records.append({
            "id": f"card-{index}", "set_id": "me05",
            "set_name": "Pitch Black", "language": "English",
            "fingerprint": f"{index + 1:016x}", "image_path": str(image_path),
            "printed_code": f"{index + 1:03d}/{count:03d}",
        })
    index_path = tmp_path / "artwork.json"
    index_path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return index_path


def test_active_set_prewarm_populates_reference_feature_cache(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path))
    service.set_active_filter("Pitch Black", "English", "me05")
    deadline = time.monotonic() + 3
    while service.status()["reference_prewarm"]["state"] != "ready":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    status = service.status()
    assert status["reference_prewarm"]["warmed"] == 3
    assert status["reference_prewarm"]["skipped"] == 0
    assert status["reference_prewarm"]["key"] == ("me05", "pitch black", "english")
    assert status["fast_identity_cache"]["reference_feature_entries"] == 3
    assert status["fast_identity_cache"]["reference_image_entries"] == 3


def test_reference_prewarm_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(ArtworkIndexService, "REFERENCE_PREWARM_LIMIT", 2)
    service = ArtworkIndexService(build_index(tmp_path, count=3))
    generation = service._reference_prewarm_generation
    result = service._prewarm_reference_features(
        tuple(service._records), ("me05", "pitch black", "english"), generation
    )
    assert result == {"warmed": 2, "skipped": 0}
    assert len(service._reference_feature_cache) == 2
    assert len(service._reference_image_cache) == 2


def test_stale_prewarm_cannot_publish_status(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=1))
    stale_generation = service._reference_prewarm_generation
    service._reference_prewarm_generation += 1
    service._prewarm_reference_features(
        tuple(service._records), ("old", "old", "english"), stale_generation
    )
    assert service.status()["reference_prewarm"]["key"] is None


def test_verified_card_prioritizes_nearby_collector_numbers(tmp_path, monkeypatch):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    captured = []
    completed = threading.Event()

    def capture(records, generation):
        captured.extend(row["id"] for row in records)
        completed.set()

    monkeypatch.setattr(service, "_prewarm_neighbor_features", capture)
    assert service.prewarm_collector_neighbors("010/020") == 12
    assert completed.wait(2)
    assert captured[:5] == ["card-9", "card-8", "card-10", "card-7", "card-11"]
    assert service.prewarm_collector_neighbors("010/020") == 0


def test_cache_timing_reports_cold_cost_and_warm_savings(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=1))
    record = service._records[0]
    image_path = record["image_path"]
    image = service._cached_reference_image(image_path)
    assert image is not None
    assert service._cached_reference_features(image_path, image) is not None
    assert service._cached_reference_image(image_path) is image
    assert service._cached_reference_features(image_path) is not None
    timing = service.status()["reference_cache_timing"]
    assert timing["image_misses"] == 1
    assert timing["feature_misses"] == 1
    assert timing["image_hits"] == 1
    assert timing["feature_hits"] == 1
    assert timing["average_image_decode_ms"] >= 0
    assert timing["average_feature_build_ms"] >= 0
    assert timing["estimated_saved_ms"] >= 0
    assert timing["warm_hits"] == 2
    assert timing["recognition_hits"] == 2
    assert timing["recognition_misses"] == 2


def test_background_prewarm_does_not_pollute_live_hit_rate(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=2))
    service.set_active_filter("Pitch Black", "English", "me05")
    deadline = time.monotonic() + 3
    while service.status()["reference_prewarm"]["state"] != "ready":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    timing = service.status()["reference_cache_timing"]
    assert timing["image_misses"] == 2
    assert timing["feature_misses"] == 2
    assert timing["recognition_hits"] == 0
    assert timing["recognition_misses"] == 0


def test_neighbor_window_adapts_only_after_enough_live_samples(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=1))
    assert service._adaptive_neighbor_limit(3, 3) == 12
    assert service._adaptive_neighbor_limit(2, 8) == 24
    assert service._adaptive_neighbor_limit(8, 2) == 8
    assert service._adaptive_neighbor_limit(5, 5) == 12


def test_verified_pack_transitions_rank_a_learned_next_card_first(tmp_path, monkeypatch):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    assert service.observe_verified_card("010/020") is True
    assert service.observe_verified_card("018/020") is True
    assert service.observe_verified_card("010/020") is True
    assert service.observe_verified_card("018/020") is True
    assert service.observe_verified_card("018/020") is False
    assert service._predicted_collector_numbers(10) == [18]
    assert service.status()["pack_transition_learning"]["observations"] == 3

    captured = []
    completed = threading.Event()
    monkeypatch.setattr(
        service,
        "_prewarm_neighbor_features",
        lambda records, generation: (captured.extend(row["id"] for row in records), completed.set()),
    )
    service._reference_prewarm_stats["neighbor_anchor"] = None
    assert service.prewarm_collector_neighbors("010/020") == 12
    assert completed.wait(2)
    assert captured[0] == "card-17"


def test_pack_transition_learning_survives_restart(tmp_path):
    index_path = build_index(tmp_path, count=20)
    service = ArtworkIndexService(index_path)
    service.set_active_filter("Pitch Black", "English", "me05")
    service.observe_verified_card("010/020")
    service.observe_verified_card("018/020")
    service.observe_verified_card("010/020")
    service.observe_verified_card("018/020")
    service._save_pack_transition_model()

    restored = ArtworkIndexService(index_path)
    restored.set_active_filter("Pitch Black", "English", "me05")
    assert restored._predicted_collector_numbers(10) == [18]
    assert restored.status()["pack_transition_learning"]["persistence_error"] is None


def test_expired_pack_transition_learning_is_not_restored(tmp_path):
    index_path = build_index(tmp_path, count=20)
    model_path = index_path.with_name("pack_transition_model.json")
    model_path.write_text(json.dumps({
        "version": 1,
        "entries": [{
            "set_key": ["me05", "pitch black", "english"],
            "from": 10, "to": 18, "count": 4,
            "updated_at": time.time() - ArtworkIndexService.PACK_TRANSITION_TTL_SECONDS - 1,
        }],
    }), encoding="utf-8")

    service = ArtworkIndexService(index_path)
    service.set_active_filter("Pitch Black", "English", "me05")
    assert service._predicted_collector_numbers(10) == []
    assert service.status()["pack_transition_learning"]["contexts"] == 0


def test_low_confidence_verified_card_does_not_poison_pack_transitions(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    assert service.observe_verified_card("010/020", confidence=0.79) is False
    assert service.observe_verified_card("018/020", confidence=79) is False
    assert service._predicted_collector_numbers(10) == []
    learning = service.status()["pack_transition_learning"]
    assert learning["observations"] == 0
    assert learning["low_confidence_rejections"] == 2
    assert learning["minimum_confidence"] == 0.80


def test_confident_verified_card_can_teach_pack_transition(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    assert service.observe_verified_card("010/020", confidence=0.80) is True
    assert service.observe_verified_card("018/020", confidence=92) is True
    assert service._predicted_collector_numbers(10) == []
    assert service.observe_verified_card("010/020", confidence=0.91) is True
    assert service.observe_verified_card("018/020", confidence=91) is True
    assert service._predicted_collector_numbers(10) == [18]


def test_single_transition_observation_remains_pending(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    service.observe_verified_card("010/020", confidence=0.95)
    service.observe_verified_card("018/020", confidence=0.95)
    assert service._predicted_collector_numbers(10) == []
    learning = service.status()["pack_transition_learning"]
    assert learning["minimum_observations"] == 2
    assert learning["pending_transitions"] == 1
    assert learning["promoted_transitions"] == 0


def test_evenly_competing_pack_transitions_are_suppressed(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for target in (18, 18, 19, 19):
        service.observe_verified_card("010/020", confidence=.95)
        service.observe_verified_card(f"{target:03d}/020", confidence=.95)
    assert service._predicted_collector_numbers(10) == []
    learning = service.status()["pack_transition_learning"]
    assert learning["competing_contexts"] >= 1
    assert learning["suppressed_ambiguous_contexts"] >= 1
    assert learning["minimum_dominance"] == .60


def test_dominant_pack_transition_ranks_ahead_of_competitor(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for target in (18, 18, 18, 18, 19, 19):
        service.observe_verified_card("010/020", confidence=.95)
        service.observe_verified_card(f"{target:03d}/020", confidence=.95)
    assert service._predicted_collector_numbers(10) == [18, 19]


def test_recent_pack_behavior_can_outrank_stale_higher_count(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    set_key = service._transition_scope_key()
    context = (set_key, 10)
    now = time.time()
    service._pack_transition_counts[context] = {18: 3, 19: 2}
    service._pack_transition_updated_at[context] = now
    service._pack_transition_edge_updated_at[(context, 18)] = now - 21 * 86400
    service._pack_transition_edge_updated_at[(context, 19)] = now
    assert service._predicted_collector_numbers(10) == [19, 18]
    assert service.status()["pack_transition_learning"]["recency_half_life_days"] == 7


def test_pack_product_contexts_do_not_share_transition_learning(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    service.set_pack_context("wrapper-art-a", "Pitch Black · Apple artwork")
    for _ in range(2):
        service.observe_verified_card("010/020", confidence=.95)
        service.observe_verified_card("018/020", confidence=.95)
    assert service._predicted_collector_numbers(10) == [18]

    service.set_pack_context("wrapper-art-b")
    assert service._predicted_collector_numbers(10) == []
    for _ in range(2):
        service.observe_verified_card("010/020", confidence=.95)
        service.observe_verified_card("019/020", confidence=.95)
    assert service._predicted_collector_numbers(10) == [19]

    service.set_pack_context("wrapper-art-a")
    assert service._predicted_collector_numbers(10) == [18]
    assert service.status()["pack_transition_learning"]["active_pack_context"] == "wrapper-art-a"
    assert service.transition_context_status()["context_label"] == "Pitch Black · Apple artwork"
    assert service.export_transition_context()["metadata"]["product_label"] == "Pitch Black · Apple artwork"
    renamed = service.rename_active_pack_context("Pitch Black · Lapras wrapper")
    assert renamed["context"] == "wrapper-art-a"
    assert service.transition_context_status()["context_label"] == "Pitch Black · Lapras wrapper"


def test_operator_can_disable_and_reset_only_active_pack_context(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    service.set_pack_context("wrapper-a")
    for _ in range(2):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card("018/020", .95)
    assert service._predicted_collector_numbers(10) == [18]
    assert service.set_transition_context_enabled(False)["enabled"] is False
    assert service._predicted_collector_numbers(10) == []
    assert service.observe_verified_card("010/020", .95) is False
    assert service.set_transition_context_enabled(True)["enabled"] is True
    assert service._predicted_collector_numbers(10) == [18]
    result = service.reset_transition_context()
    assert result["removed_contexts"] > 0
    assert result["context_count"] == 0
    assert service._predicted_collector_numbers(10) == []


def test_operator_can_remove_one_bad_transition_without_resetting_context(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    service.set_pack_context("wrapper-a")
    for target in (18, 18, 19, 19):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card(f"{target:03d}/020", .95)
    result = service.remove_transition(10, 19)
    assert result["removed_count"] == 2
    assert service._predicted_collector_numbers(10) == [18]
    evidence = service.transition_context_status()["contexts"]
    assert next(row for row in evidence if row["from"] == 10)["successors"] == {18: 2}
    assert service.remove_transition(10, 17)["removed_count"] == 0


def test_operator_can_undo_transition_removal_once(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for _ in range(2):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card("018/020", .95)
    assert service.remove_transition(10, 18)["undo_available"] is True
    assert service._predicted_collector_numbers(10) == []
    assert service.undo_transition_removal()["restored_count"] == 2
    assert service._predicted_collector_numbers(10) == [18]
    assert service.undo_transition_removal()["restored_count"] == 0


def test_active_product_learning_export_import_round_trip(tmp_path):
    source = ArtworkIndexService(build_index(tmp_path, count=20))
    source.set_active_filter("Pitch Black", "English", "me05")
    source.set_pack_context("wrapper-a")
    for _ in range(2):
        source.observe_verified_card("010/020", .95)
        source.observe_verified_card("018/020", .95)
    model = source.export_transition_context()
    assert model["checksum"]["algorithm"] == "sha256"
    assert len(model["checksum"]["value"]) == 64
    assert model["metadata"]["positions"] >= 1
    assert model["metadata"]["transitions"] >= 1
    assert model["metadata"]["observations"] >= 2
    assert source.preview_transition_import(model)["compatible"] is True
    source.reset_transition_context()
    result = source.import_transition_context(model)
    assert result["imported_entries"] >= 1
    assert source._predicted_collector_numbers(10) == [18]


def test_pack_learning_import_rejects_wrong_product_scope(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    model = service.export_transition_context()
    model["scope"][-1] = "different-wrapper"
    model["checksum"]["value"] = service._backup_checksum(model)
    preview = service.preview_transition_import(model)
    assert preview["compatible"] is False
    assert "scope does not match" in preview["reason"]
    try:
        service.import_transition_context(model)
    except ValueError as exc:
        assert "scope does not match" in str(exc)
    else:
        raise AssertionError("wrong-scope backup should fail closed")


def test_pack_learning_backup_tampering_fails_integrity_preview(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    model = service.export_transition_context()
    model["enabled"] = not model["enabled"]
    preview = service.preview_transition_import(model)
    assert preview["compatible"] is False
    assert preview["integrity_valid"] is False
    assert "integrity check failed" in preview["reason"]
    try:
        service.import_transition_context(model)
    except ValueError as exc:
        assert "integrity check failed" in str(exc)
    else:
        raise AssertionError("tampered backup should fail closed")


def test_reset_archives_active_product_model_before_deletion(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for _ in range(2):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card("018/020", .95)
    result = service.reset_transition_context()
    backup = Path(result["backup_path"])
    assert backup.exists()
    payload = json.loads(backup.read_text(encoding="utf-8"))
    assert payload["archive_reason"] == "before-reset"
    assert service.preview_transition_import(payload)["integrity_valid"] is True


def test_automatic_product_backups_rotate_to_five(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for _ in range(2):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card("018/020", .95)
    for _ in range(7):
        assert service._archive_transition_context("test") is not None
    assert len(list(service.transition_backup_dir.glob("*.json"))) == 5


def test_operator_can_list_and_restore_scoped_recovery_backup(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=20))
    service.set_active_filter("Pitch Black", "English", "me05")
    for _ in range(2):
        service.observe_verified_card("010/020", .95)
        service.observe_verified_card("018/020", .95)
    reset = service.reset_transition_context()
    backups = service.list_transition_backups()
    assert backups[0]["backup_id"] == Path(reset["backup_path"]).name
    assert backups[0]["integrity_valid"] is True
    assert backups[0]["compatible"] is True
    restored = service.restore_transition_backup(backups[0]["backup_id"])
    assert restored["restored_backup_id"] == backups[0]["backup_id"]
    assert service._predicted_collector_numbers(10) == [18]


def test_recovery_restore_rejects_path_traversal(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path, count=2))
    try:
        service.restore_transition_backup("../other.json")
    except ValueError as exc:
        assert "Invalid recovery backup identifier" in str(exc)
    else:
        raise AssertionError("path traversal should fail closed")
