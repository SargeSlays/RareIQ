from types import SimpleNamespace

import cv2
import numpy as np

from rareiq.services.stream_speed_benchmark_service import StreamSpeedBenchmarkService
from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.recognition_service import RecognitionService


def candidate(card_id, score, **extra):
    return {"id": card_id, "score": score, **extra}


def write_image(path):
    assert cv2.imwrite(str(path), np.zeros((700, 500, 3), dtype=np.uint8))


def test_replay_reports_eligible_correct_fast_path(tmp_path):
    image_path = tmp_path / "card.jpg"
    write_image(image_path)
    global_index = SimpleNamespace(search_image=lambda image, limit: {
        "ok": True,
        "matches": [candidate("card-1", 0.99), candidate("other", 0.90)],
    })
    artwork_index = SimpleNamespace(search=lambda image, limit: {
        "ok": True,
        "matches": [candidate(
            "card-1", 0.98, verification_strong=True, image_path="reference.jpg"
        ), candidate("other-2", 0.90)],
    })

    report = StreamSpeedBenchmarkService(global_index, artwork_index).run([
        {"path": str(image_path), "expected": {"id": "card-1"}}
    ])

    assert report["fast_path_eligible_count"] == 1
    assert report["labeled_sample_count"] == 1
    assert report["label_coverage_rate"] == 1.0
    assert report["false_lock_count"] == 0
    assert report["gates"]["zero_false_locks"] == "pass"
    assert report["samples"][0]["fast_path_correct"] is True


def test_replay_refuses_accuracy_claim_for_unlabeled_capture(tmp_path):
    image_path = tmp_path / "card.jpg"
    write_image(image_path)
    top = candidate(
        "card-1", 0.99, verification_strong=True, image_path="reference.jpg"
    )
    service = StreamSpeedBenchmarkService(
        SimpleNamespace(search_image=lambda image, limit: {"ok": True, "matches": [top]}),
        SimpleNamespace(search=lambda image, limit: {"ok": True, "matches": [top]}),
    )

    report = service.run([{"path": str(image_path), "expected": None}])

    assert report["fast_path_eligible_count"] == 1
    assert report["labeled_fast_path_count"] == 0
    assert report["unlabeled_sample_count"] == 1
    assert report["gates"]["zero_false_locks"] == "not_evaluated"
    assert report["gates"]["ready"] is False


def test_replay_counts_cached_geometry_consensus_as_fast_path(tmp_path):
    image_path = tmp_path / "card.jpg"
    write_image(image_path)
    matches = [
        {
            "id": "copy-a", "printed_name": "美录坦", "printed_code": "149/204",
            "verification_strong": True, "verification_score": 0.79,
        },
        {
            "id": "copy-b", "printed_name": "美录坦", "printed_code": "149/204",
            "verification_strong": True, "verification_score": 0.76,
        },
    ]
    service = StreamSpeedBenchmarkService(
        SimpleNamespace(search_image=lambda image, limit: {"ok": True, "matches": []}),
        SimpleNamespace(
            search_hinted=lambda image, hints, limit: {"ok": True, "matches": []},
            search=lambda image, limit: {
                "ok": True,
                "fast_return": "cached_printed_identity",
                "matches": matches,
            },
        ),
    )

    report = service.run([{
        "path": str(image_path),
        "expected": {"printed_name": "美录坦", "printed_code": "149/204"},
    }])

    assert report["fast_path_eligible_count"] == 1
    assert report["false_lock_count"] == 0
    assert report["samples"][0]["recognition_path"] == "fast"
    assert report["samples"][0]["fast_path_reason"] == (
        "cached_printed_identity_geometry_consensus"
    )


def test_replay_counts_false_lock_and_unreadable_sample(tmp_path):
    image_path = tmp_path / "card.jpg"
    write_image(image_path)
    top = candidate(
        "wrong", 0.99, verification_strong=True, image_path="reference.jpg"
    )
    service = StreamSpeedBenchmarkService(
        SimpleNamespace(search_image=lambda image, limit: {"ok": True, "matches": [top]}),
        SimpleNamespace(search=lambda image, limit: {"ok": True, "matches": [top]}),
    )

    report = service.run([
        {"path": str(image_path), "expected": {"id": "right"}},
        {"path": str(tmp_path / "missing.jpg"), "expected": None},
    ])

    assert report["successful_count"] == 1
    assert report["false_lock_count"] == 1
    assert report["gates"]["zero_false_locks"] == "fail"
    assert report["samples"][1]["error"] == "unreadable_image"


def test_artwork_index_loads_existing_identity_override_as_bridge(tmp_path, monkeypatch):
    index_path = tmp_path / "artwork.json"
    index_path.write_text(
        '{"records":[{"id":"local-1","set_id":"CSV5",'
        '"collector_number":"8","fingerprint":"0000000000000000"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ArtworkIndexService,
        "_load_identity_overrides",
        staticmethod(lambda: {
            "CSV5:008": {
                "english_name": "Crocalor",
                "canonical_name": "Crocalor",
            }
        }),
    )

    service = ArtworkIndexService(index_path=index_path)

    assert service._records[0]["english_name"] == "Crocalor"
    assert service._records[0]["identity_override_key"] == "CSV5:008"
    assert service.status()["identity_bridge_count"] == 1


def test_canonical_name_bridges_global_and_artwork_namespaces():
    global_card = {"id": "sv-card", "english_name": "Crocalor"}
    artwork_card = {
        "id": "pokipair-csv5-local",
        "canonical_name": "crocalor",
    }

    assert (
        RecognitionService._candidate_identity_keys(global_card)
        & RecognitionService._candidate_identity_keys(artwork_card)
    ) == {"canonical-name:crocalor"}


def test_duplicate_printed_identity_consensus_beats_singleton_near_match():
    candidates = [
        {"id": "a", "printed_code": "149/204", "score": 0.69, "verification_strong": True},
        {"id": "b", "printed_code": "149/204", "score": 0.63, "verification_strong": True},
        {"id": "wrong", "score": 0.70, "verification_strong": True},
    ]

    ArtworkIndexService._apply_identity_consensus(candidates)
    candidates.sort(key=lambda item: -item["score"])

    assert candidates[0]["id"] == "a"
    assert candidates[0]["identity_consensus_count"] == 2
    assert "identity_consensus_count" not in candidates[2]


def test_recent_identity_cache_accepts_near_frame_and_rejects_new_card():
    service = ArtworkIndexService.__new__(ArtworkIndexService)
    service._recent_identity_cache = __import__("collections").OrderedDict()
    service._fast_cache_stats = {
        "lookups": 0,
        "hits": 0,
        "misses": 0,
        "geometry_rejections": 0,
        "stores": 0,
        "invalidations": 0,
    }
    service._remember_printed_identity("0000000000000000", "149/204")

    assert service._nearby_printed_identity("0000000000000003") == "149/204"
    assert service._nearby_printed_identity("ffffffffffffffff") is None


def test_filter_change_invalidates_recent_identity_cache(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    service._remember_printed_identity("0000000000000000", "149/204")
    before = service.status()["fast_identity_cache"]

    service.set_active_filter("Blade Awakened", "zh-cn")
    after = service.status()["fast_identity_cache"]

    assert before["identity_entries"] == 1
    assert after["identity_entries"] == 0
    assert after["invalidations"] == before["invalidations"] + 1


def test_verified_live_reference_agreement_seeds_cold_identity_cache(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)

    seeded = service.seed_verified_identity("0000000000000000", [{
        "verification_strong": True,
        "verification_score": 0.74,
        "printed_code_match": True,
        "printed_code": "149/204",
    }])

    assert seeded is True
    assert service._nearby_printed_identity("0000000000000001") == "149/204"
    assert service.status()["fast_identity_cache"]["stores"] == 1


def test_cold_identity_seed_rejects_weak_or_malformed_evidence(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)

    assert service.seed_verified_identity("abc", [{
        "verification_strong": True,
        "verification_score": 0.69,
        "printed_code_match": True,
        "printed_code": "149/204",
    }]) is False
    assert service.seed_verified_identity("abc", [{
        "verification_strong": True,
        "verification_score": 0.80,
        "printed_code_match": True,
        "printed_code": "2304/07",
    }]) is False
    assert service.status()["fast_identity_cache"]["identity_entries"] == 0


def test_decisive_variant_marker_seeds_exact_identity_cache(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    candidates = [
        {"id": "card-161", "variant_resolved": True, "verification_strong": True,
         "verification_score": 0.72, "artwork_verification_strong": True,
         "variant_marker_score": 0.207},
        {"id": "card-159", "variant_resolved": True, "verification_strong": True,
         "verification_score": 0.77, "artwork_verification_strong": True,
         "variant_marker_score": 0.154},
    ]

    assert service._seed_decisive_variant("0000000000000000", candidates) is False
    assert service._seed_decisive_variant("0000000000000001", candidates) is True
    assert service._nearby_printed_identity("0000000000000001") == "id:card-161"


def test_variant_marker_seed_rejects_narrow_margin(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    candidates = [
        {"id": "a", "variant_resolved": True, "verification_strong": True,
         "verification_score": 0.75, "artwork_verification_strong": True,
         "variant_marker_score": 0.21},
        {"id": "b", "variant_resolved": True, "verification_strong": True,
         "verification_score": 0.75, "artwork_verification_strong": True,
         "variant_marker_score": 0.19},
    ]
    assert service._seed_decisive_variant("abc", candidates) is False


def test_variant_disagreement_resets_temporal_seed(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    def candidate(card_id, marker):
        return {"id": card_id, "variant_resolved": True, "verification_strong": True,
                "verification_score": 0.75, "artwork_verification_strong": True,
                "variant_marker_score": marker}

    assert service._seed_decisive_variant("a", [candidate("161", 0.24), candidate("159", 0.18)]) is False
    assert service._seed_decisive_variant("b", [candidate("164", 0.25), candidate("161", 0.17)]) is False
    assert service._seed_decisive_variant("c", [candidate("161", 0.24), candidate("159", 0.18)]) is False
    assert service.status()["fast_identity_cache"]["identity_entries"] == 0


def test_variant_confirmation_requires_distinct_fingerprint_and_ranked_winner(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    winner = {"id": "161", "variant_resolved": True, "verification_strong": True,
              "verification_score": 0.75, "artwork_verification_strong": True,
              "variant_marker_score": 0.24}
    other = {"id": "159", "variant_resolved": True, "verification_strong": True,
             "verification_score": 0.75, "artwork_verification_strong": True,
             "variant_marker_score": 0.18}

    assert service._seed_decisive_variant("same", [winner, other]) is False
    assert service._seed_decisive_variant("same", [winner, other]) is False
    assert service._seed_decisive_variant("different", [other, winner]) is False
    assert service.status()["fast_identity_cache"]["identity_entries"] == 0


def test_family_expansion_prioritizes_known_artwork_variants(tmp_path):
    index_path = tmp_path / "empty.json"
    index_path.write_text('{"records":[]}', encoding="utf-8")
    service = ArtworkIndexService(index_path=index_path)
    service.ARTWORK_STAGE_LIMIT = 2
    records = [
        {"id": "near-a", "artwork_fingerprint": "0000000000000001"},
        {"id": "near-b", "artwork_fingerprint": "0000000000000002"},
        {"id": "correct-variant", "artwork_fingerprint": "ffffffffffffffff"},
    ]

    siblings = service._family_siblings(
        records, set(), {"ffffffffffffffff"}, "0000000000000000"
    )

    assert siblings[0]["id"] == "correct-variant"
