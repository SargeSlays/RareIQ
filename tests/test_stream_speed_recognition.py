import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from rareiq.services.recognition_service import RecognitionService


def _candidate(score: float, *, card_id: str = "sv4-123", **extra):
    return {"id": card_id, "score": score, **extra}


class _HintedArtworkIndex:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search_hinted(self, card, candidates, *, limit):
        self.calls.append((card, list(candidates), limit))
        return self.result


def test_exact_collector_shortlist_gets_direct_visual_verification():
    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    retrieved = _candidate(
        0.91,
        card_id="me5-53",
        collector_number="053/084",
        retrieval_only=True,
        verification_strong=False,
    )
    verified = {
        **retrieved,
        "score": 0.82,
        "retrieval_only": False,
        "verification_strong": True,
        "homography_inliers": 151,
    }
    service = object.__new__(RecognitionService)
    service.artwork_index = _HintedArtworkIndex(
        {"ok": True, "matches": [verified], "hint_hits": 1}
    )

    merged, result = service._verify_identifier_visual_candidates(
        crop,
        [retrieved],
        [_candidate(0.70, card_id="distractor")],
        limit=4,
    )

    assert service.artwork_index.calls == [(crop, [retrieved], 4)]
    assert result["hint_hits"] == 1
    assert merged[0]["id"] == "me5-53"
    assert merged[0]["verification_strong"] is True
    assert merged[0]["retrieval_only"] is False


def test_exact_collector_shortlist_never_promotes_failed_verification():
    crop = np.zeros((1400, 1000, 3), dtype=np.uint8)
    retrieved = _candidate(
        0.91,
        card_id="me5-53",
        collector_number="053/084",
        retrieval_only=True,
        verification_strong=False,
    )
    service = object.__new__(RecognitionService)
    service.artwork_index = _HintedArtworkIndex(
        {"ok": True, "matches": [], "hint_hits": 1}
    )

    merged, result = service._verify_identifier_visual_candidates(
        crop,
        [retrieved],
        [],
        limit=4,
    )

    assert result["matches"] == []
    assert merged == []


def test_final_candidate_confidence_is_used_by_the_lock_gate():
    assert RecognitionService._decision_confidence(0.64, 0.7313) == 0.7313
    assert RecognitionService._decision_confidence(0.81, 0.7313) == 0.81


def test_frame_handoff_snapshots_each_unique_array_once():
    primary = np.zeros((16, 12, 3), dtype=np.uint8)
    secondary = np.ones((8, 6, 3), dtype=np.uint8)

    frame, ocr_frame, collectors = RecognitionService._snapshot_frame_inputs(
        primary,
        primary,
        [primary, secondary, secondary],
    )

    assert frame is ocr_frame
    assert collectors[0] is frame
    assert collectors[1] is collectors[2]
    assert collectors[1] is not secondary
    assert frame is not primary

    primary[:] = 9
    secondary[:] = 7
    assert np.count_nonzero(frame) == 0
    assert np.all(collectors[1] == 1)


def test_locked_set_with_strong_visual_seed_uses_single_footer_probe():
    assert RecognitionService._early_footer_variant_budget(
        locked_to_set=True, visual_score=0.80, source="auto"
    ) == 1
    assert RecognitionService._early_footer_variant_budget(
        locked_to_set=True, visual_score=0.79, source="auto"
    ) == 2


def test_grid_and_unlocked_scans_keep_safe_footer_budgets():
    assert RecognitionService._early_footer_variant_budget(
        locked_to_set=False, visual_score=0.99, source="six-card-grid"
    ) == 1
    assert RecognitionService._early_footer_variant_budget(
        locked_to_set=False, visual_score=0.99, source="auto"
    ) == 2


def test_fast_path_requires_decisive_cross_index_agreement():
    evidence = RecognitionService._fast_path_evidence(
        [_candidate(0.99), _candidate(0.90, card_id="other")],
        [
            _candidate(
                0.98,
                verification_strong=True,
                image_path="catalog/card.jpg",
            ),
            _candidate(0.90, card_id="runner-up"),
        ],
    )

    assert evidence is not None
    assert evidence["reason"] == "cross_index_decisive_match"
    assert evidence["version_key"] == "id:sv4-123"
    assert evidence["global_margin"] == 0.09
    assert evidence["artwork_margin"] == 0.08


def test_fast_path_rejects_disagreement_or_weak_margin():
    strong_artwork = [
        _candidate(
            0.98,
            verification_strong=True,
            image_path="catalog/card.jpg",
        )
    ]
    assert RecognitionService._fast_path_evidence(
        [_candidate(0.99, card_id="different")], strong_artwork
    ) is None
    assert RecognitionService._fast_path_evidence(
        [_candidate(0.99), _candidate(0.97, card_id="runner-up")],
        strong_artwork,
    ) is None


def test_fast_path_requires_strong_reference_asset():
    assert RecognitionService._fast_path_evidence(
        [_candidate(0.99)],
        [_candidate(0.98, verification_strong=True)],
    ) is None


def test_fast_path_rejects_name_only_agreement_between_versions():
    global_top = _candidate(
        0.99,
        card_id="global-161",
        canonical_name="Crocalor",
        set_id="CSV5",
        collector_number="161",
    )
    artwork_top = _candidate(
        0.98,
        card_id="artwork-159",
        canonical_name="Crocalor",
        set_id="CSV5",
        collector_number="159",
        verification_strong=True,
        image_path="catalog/crocalor-159.jpg",
    )

    assert RecognitionService._fast_path_evidence(
        [global_top], [artwork_top]
    ) is None


def test_fast_path_accepts_shared_set_and_collector_version():
    global_top = _candidate(
        0.99,
        card_id="global-crocalor",
        set_id="CSV5",
        collector_number="161",
    )
    artwork_top = _candidate(
        0.98,
        card_id="artwork-crocalor",
        set_id="CSV5",
        collector_number="161",
        verification_strong=True,
        image_path="catalog/crocalor-161.jpg",
    )

    evidence = RecognitionService._fast_path_evidence(
        [global_top], [artwork_top]
    )

    assert evidence is not None
    assert evidence["version_key"] == "set-number:csv5:161"


def test_locked_set_number_makes_decisive_visual_fast_path_variant_safe():
    evidence = {
        "reason": "cross_index_decisive_match",
        "version_key": "set-number:me05:023/084",
    }
    catalog_match = {
        "set_id": "me05",
        "collector_number": "023/084",
        "set_locked_catalog_lookup": True,
    }

    confirmed = RecognitionService._confirm_locked_set_number_fast_path(
        evidence, catalog_match, "023/084"
    )

    assert confirmed["reason"] == "locked_set_number_visual_consensus"
    assert confirmed["locked_set_number_exact"] is True
    assert RecognitionService._variant_fast_path_is_ocr_safe(confirmed) is True


def test_locked_set_number_never_creates_or_upgrades_weak_evidence():
    catalog_match = {
        "set_id": "me05",
        "collector_number": "023/084",
        "set_locked_catalog_lookup": True,
    }
    assert RecognitionService._confirm_locked_set_number_fast_path(
        None, catalog_match, "023/084"
    ) is None
    evidence = {
        "reason": "cross_index_decisive_match",
        "version_key": "set-number:me05:013/084",
    }
    assert RecognitionService._confirm_locked_set_number_fast_path(
        evidence, catalog_match, "023/084"
    ) == evidence
    assert RecognitionService._variant_fast_path_is_ocr_safe(evidence) is False


def test_visual_preflight_skips_footer_for_unique_art_consensus():
    candidate = {
        "canonical_name": "Goldeen",
        "set_id": "me05",
        "collector_number": "013/084",
        "verification_strong": True,
    }
    assert RecognitionService._visual_preflight_can_skip_footer(
        {"reason": "cross_index_decisive_match"},
        [candidate, dict(candidate)],
        [candidate],
    ) is True


def test_visual_preflight_keeps_footer_for_shared_art_printings():
    first = {
        "canonical_name": "Crocalor",
        "set_id": "csv5",
        "collector_number": "159",
        "verification_strong": True,
    }
    second = {**first, "collector_number": "161"}
    assert RecognitionService._visual_preflight_can_skip_footer(
        {"reason": "cross_index_decisive_match"},
        [first],
        [first, second],
    ) is False
    assert RecognitionService._visual_preflight_can_skip_footer(
        None,
        [first],
        [first],
    ) is False


def test_exact_printed_identifier_requires_visual_and_reference_verification():
    candidate = {
        "printed_code_match": True,
        "verification_strong": True,
        "artwork_verification_strong": True,
    }
    assert RecognitionService._strong_printed_identifier_agreement(
        candidate, "2301/07"
    ) is True
    assert RecognitionService._strong_printed_identifier_agreement(
        {**candidate, "artwork_verification_strong": False}, "2301/07"
    ) is False
    assert RecognitionService._strong_printed_identifier_agreement(
        candidate, None
    ) is False


def test_exact_printed_identifier_has_a_dedicated_safe_lock_threshold():
    candidate = {
        "printed_code_match": True,
        "verification_strong": True,
        "artwork_verification_strong": True,
    }
    assert RecognitionService._strong_printed_identifier_lock_ready(
        candidate, "2303/07", 0.716, "Chinese"
    ) is True
    assert RecognitionService._strong_printed_identifier_lock_ready(
        candidate, "2303/07", 0.67, "Chinese"
    ) is False
    assert RecognitionService._strong_printed_identifier_lock_ready(
        candidate, "2303/07", 0.716, "Unknown"
    ) is False


def test_latency_summary_is_bounded_and_reports_path_rate():
    service = RecognitionService.__new__(RecognitionService)
    service._latency_samples = []
    summary = service._record_latency("full", 100.0)
    summary = service._record_latency("fast", 20.0)

    assert summary == {
        "sample_count": 2,
        "fast_path_count": 1,
        "fast_path_rate": 0.5,
        "p50_ms": 20.0,
        "p95_ms": 20.0,
    }

    summary = service._record_latency("full", 300.0, 420.0)
    summary = service._record_latency("full", 700.0, 1200.0)
    assert summary["capture_sample_count"] == 2
    assert summary["capture_p50_ms"] == 420.0
    assert summary["capture_p95_ms"] == 420.0
    assert summary["under_one_second_count"] == 1
    assert summary["under_one_second_rate"] == 0.5

    for value in range(105):
        summary = service._record_latency("fast", float(value))
    assert summary["sample_count"] == 100


def test_cached_artwork_consensus_can_enter_fast_path_without_global_match():
    evidence = RecognitionService._cached_artwork_fast_path_evidence({
        "fast_return": "cached_printed_identity",
        "matches": [
            {"printed_code": "149/204", "verification_strong": True, "verification_score": 0.79},
            {"printed_code": "149/204", "verification_strong": True, "verification_score": 0.76},
        ],
    })

    assert evidence == {
        "reason": "cached_printed_identity_geometry_consensus",
        "printed_code": "149/204",
        "reference_count": 2,
        "best_verification_score": 0.79,
    }


def test_worker_fast_path_skips_all_ocr_and_reports_end_to_end_latency(
    tmp_path, monkeypatch
):
    emitted = []
    service = RecognitionService(emitted.append, database_path=tmp_path / "missing.json")
    service.global_visual_index = SimpleNamespace(
        search_image=lambda frame, limit: {
            "ok": True,
            "latency_ms": 1.0,
            "matches": [
                _candidate(0.99, source="global_visual_index"),
                _candidate(0.90, card_id="global-runner"),
            ],
        }
    )
    artwork_top = _candidate(
        0.98,
        source="artwork_index",
        verification_strong=True,
        image_path="catalog/card.jpg",
        visual_score=0.98,
    )
    monkeypatch.setattr(
        service.artwork_index,
        "search_hinted",
        lambda frame, hints, limit: {
            "matches": [artwork_top, _candidate(0.90, card_id="art-runner")],
            "query_fingerprint": "fingerprint",
            "latency_ms": 1.0,
            "hint_hits": 2,
        },
    )
    monkeypatch.setattr(
        service.artwork_index,
        "search",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("decisive hinted verification must skip exhaustive search")
        ),
    )
    monkeypatch.setattr(service.artwork_index, "status", lambda: {"ready": True})

    def forbidden(*args, **kwargs):
        raise AssertionError("fast path must not invoke OCR or reference OCR")

    monkeypatch.setattr(service, "_run_ocr", forbidden)
    monkeypatch.setattr(service, "_run_collector_ocr", forbidden)
    monkeypatch.setattr(service, "_annotate_reference_identifiers", forbidden)

    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        frame_id=7,
        captured_at=time.time() - 0.01,
    )

    payload = emitted[-1]["payload"]
    assert payload["error"] is None
    assert payload["recognition_path"] == "fast"
    assert payload["recognition_locked"] is True
    assert payload["stage_timings"]["skipped_stages"] == [
        "reference_identifier",
        "ocr",
    ]
    assert payload["stage_timings"]["queue_ms"] >= 0
    assert payload["capture_to_result_ms"] >= payload["last_latency_ms"]


def test_worker_ambiguous_visual_match_runs_full_ocr(tmp_path, monkeypatch):
    service = RecognitionService(lambda event: None, database_path=tmp_path / "missing.json")
    service.global_visual_index = SimpleNamespace(
        search_image=lambda frame, limit: {
            "ok": True,
            "matches": [_candidate(0.99), _candidate(0.98, card_id="runner")],
        }
    )
    monkeypatch.setattr(
        service.artwork_index,
        "search",
        lambda frame, limit: {"matches": [], "query_fingerprint": None},
    )
    ocr_calls = []
    monkeypatch.setattr(
        service,
        "_run_ocr",
        lambda frame, region, full=False: ocr_calls.append(region) or [],
    )
    monkeypatch.setattr(
        service,
        "_run_collector_ocr",
        lambda frame, region, **_kwargs: ([], []),
    )

    service._recognize_worker(np.zeros((700, 500, 3), dtype=np.uint8))

    assert ocr_calls
    assert service.status()["recognition_path"] == "full"


def test_worker_cached_geometry_path_bypasses_ocr_despite_global_disagreement(
    tmp_path, monkeypatch
):
    emitted = []
    service = RecognitionService(emitted.append, database_path=tmp_path / "missing.json")
    service.global_visual_index = SimpleNamespace(search_image=lambda frame, limit: {
        "ok": True,
        "matches": [_candidate(0.85, card_id="wrong-global", source="global_visual_index")],
    })
    cached_matches = [
        _candidate(
            0.79, card_id="meltan-a", source="artwork_index",
            printed_name="美录坦", printed_code="149/204",
            verification_strong=True, verification_score=0.79,
            image_path="reference-a.jpg",
        ),
        _candidate(
            0.76, card_id="meltan-b", source="artwork_index",
            printed_name="美录坦", printed_code="149/204",
            verification_strong=True, verification_score=0.76,
            image_path="reference-b.jpg",
        ),
    ]
    monkeypatch.setattr(
        service.artwork_index,
        "search_hinted",
        lambda frame, hints, limit: {"ok": True, "matches": [], "latency_ms": 0.1},
    )
    monkeypatch.setattr(
        service.artwork_index,
        "search",
        lambda frame, limit: {
            "ok": True,
            "fast_return": "cached_printed_identity",
            "matches": cached_matches,
            "query_fingerprint": "fingerprint",
        },
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("cached geometry fast path must bypass OCR")

    monkeypatch.setattr(service, "_run_ocr", forbidden)
    monkeypatch.setattr(service, "_run_collector_ocr", forbidden)
    monkeypatch.setattr(service, "_annotate_reference_identifiers", forbidden)
    service._recognize_worker(np.zeros((700, 500, 3), dtype=np.uint8))

    payload = emitted[-1]["payload"]
    assert payload["error"] is None
    assert payload["recognition_path"] == "fast"
    assert payload["fast_path"]["reason"] == (
        "cached_printed_identity_geometry_consensus"
    )
    assert "ocr" in payload["stage_timings"]["skipped_stages"]
    assert payload["stage_timings"]["ocr_ms"] < 5.0


def test_exact_variant_cache_is_quarantined_after_cross_card_failure():
    evidence = RecognitionService._cached_artwork_fast_path_evidence({
        "fast_return": "cached_exact_variant",
        "matches": [{
            "id": "variant-a",
            "verification_strong": True,
            "verification_score": 0.90,
            "artwork_verification_strong": True,
            "variant_marker_score": 0.50,
        }],
    })
    assert evidence is None


def test_studiox_exposes_stream_speed_telemetry():
    root = Path(__file__).resolve().parents[1]
    html = (root / "rareiq/web/static/control.html").read_text(encoding="utf-8")
    javascript = (root / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")

    for element_id in (
        "recognitionPathValue",
        "latencyP95Value",
        "captureLatencyValue",
        "fastPathRateValue",
    ):
        assert f'id="{element_id}"' in html
        assert f'$("{element_id}")' in javascript
    assert "snapshot?.latency_summary" in javascript
    assert "snapshot?.capture_to_result_ms" in javascript


def test_studiox_exact_match_requires_authoritative_backend_lock():
    root = Path(__file__).resolve().parents[1]
    script = (root / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
    assert "function isAuthoritativelyVerified(snapshot={})" in script
    assert "snapshot?.recognition_locked===true" in script
    assert 'state==="VERIFIED"' in script
    assert "snapshot?.result_current!==false" in script
    assert "isAuthoritativelyVerified(snapshot)&&card" in script
    assert '"Candidate only  |  Exact version unresolved"' in script
    assert '"WAITING FOR VERIFIED IDENTITY"' in script
    assert "verified?card:provisionalIdentityCard(card)" in script
    assert "if(image)" in script
    assert '"Provisional candidate reference"' in script
    assert "card.provisional===true" in script
    assert "const actionable=context.verified===true" in script
    assert "button.disabled=!actionable" in script


def test_single_card_temporal_confirmation_requires_two_exact_passes(tmp_path):
    path = tmp_path / "single-temporal.json"
    service = RecognitionService(lambda _event: None, temporal_path=path)
    card = {
        "id": "crocalor-157",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "157",
        "canonical_name": "Crocalor",
    }
    first = {
        "database_match": dict(card),
        "candidates": [dict(card)],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "artwork_fingerprint": "abc123",
    }
    service._apply_single_temporal_confirmation(first)
    assert first["temporal_confirmation"] is False
    assert first["temporal_confirmation_progress"] == 1

    second = dict(first)
    service._apply_single_temporal_confirmation(second)
    assert second["temporal_confirmation"] is True
    assert second["temporal_confirmation_count"] == 2


def test_single_card_temporal_confirmation_restores_after_restart(tmp_path):
    path = tmp_path / "single-temporal.json"
    card = {
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "157",
        "canonical_name": "Crocalor",
    }
    service = RecognitionService(lambda _event: None, temporal_path=path)
    for _ in range(2):
        service._apply_single_temporal_confirmation({
            "database_match": dict(card),
            "candidates": [dict(card)],
            "recognition_locked": True,
            "artwork_fingerprint": "abc123",
        })

    restored = RecognitionService(lambda _event: None, temporal_path=path)
    provisional = {
        "database_match": None,
        "candidates": [{"canonical_name": "Crocalor"}],
        "recognition_locked": False,
        "artwork_fingerprint": "abc123",
    }
    restored._apply_single_temporal_confirmation(provisional)

    assert provisional["recognition_locked"] is True
    assert provisional["database_match"]["collector_number"] == "157"
    assert provisional["temporal_confirmation"] is True


def test_single_card_temporal_confirmation_rejects_conflicting_identity(tmp_path):
    path = tmp_path / "single-temporal.json"
    service = RecognitionService(lambda _event: None, temporal_path=path)
    service._temporal_history = {
        "card": {"canonical_name": "Crocalor", "set_id": "X", "collector_number": "1"},
        "fingerprint": "abc123",
        "confirmations": 3,
    }
    payload = {
        "candidates": [{"canonical_name": "Sunflora"}],
        "recognition_locked": False,
        "artwork_fingerprint": "abc123",
    }

    service._apply_single_temporal_confirmation(payload)

    assert payload["recognition_locked"] is False
    assert payload.get("temporal_confirmation") is not True


def test_single_card_temporal_confirmation_tolerates_small_fingerprint_drift(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "printed_code": "2305/07",
        },
        "fingerprint": "adec44da72341b5b",
        "confirmations": 3,
    }
    payload = {
        "candidates": [{"canonical_name": "Crocalor"}],
        "recognition_locked": False,
        "artwork_fingerprint": "adec44da72341b58",
    }

    service._apply_single_temporal_confirmation(payload)

    assert payload["recognition_locked"] is True
    assert payload["database_match"]["printed_code"] == "2305/07"
    assert payload["temporal_fingerprint_distance"] == 2
    assert payload["temporal_identity_restored"] is True


def test_single_card_temporal_confirmation_rejects_distant_fingerprint(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {"canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "160"},
        "fingerprint": "0000000000000000",
        "confirmations": 3,
    }
    payload = {
        "candidates": [{"canonical_name": "Crocalor"}],
        "recognition_locked": False,
        "artwork_fingerprint": "ffffffffffffffff",
    }

    service._apply_single_temporal_confirmation(payload)

    assert payload["recognition_locked"] is False


def test_locked_set_reconciles_provider_total_with_printed_collector_number():
    candidate = {"collector_number": "042/120", "name": "Mankey"}

    changed = RecognitionService._reconcile_locked_collector_number(
        candidate, "042/084"
    )

    assert changed is True
    assert candidate["collector_number"] == "042/084"
    assert candidate["official_collector_number"] == "042/084"
    assert candidate["provider_collector_number"] == "042/120"
    assert candidate["collector_number_reconciled"] is True


def test_locked_set_reconciled_identity_can_lock_with_strong_visual_match():
    candidate = {
        "official_collector_number": "042/084",
        "collector_number_reconciled": True,
        "set_locked_identity_agreement": True,
    }

    assert RecognitionService._locked_set_reconciled_identity_ready(
        candidate, "042/084", {"id": "pitch-black"}, 0.888
    ) is True


def test_reconciled_identity_never_locks_without_operator_set_lock():
    candidate = {
        "official_collector_number": "042/084",
        "collector_number_reconciled": True,
        "set_locked_identity_agreement": True,
    }

    assert RecognitionService._locked_set_reconciled_identity_ready(
        candidate, "042/084", {}, 0.99
    ) is False


def test_reconciled_identity_rejects_weak_visual_or_wrong_printed_number():
    candidate = {
        "official_collector_number": "042/084",
        "collector_number_reconciled": True,
        "set_locked_identity_agreement": True,
    }

    assert RecognitionService._locked_set_reconciled_identity_ready(
        candidate, "043/084", {"id": "pitch-black"}, 0.99
    ) is False
    assert RecognitionService._locked_set_reconciled_identity_ready(
        candidate, "042/084", {"id": "pitch-black"}, 0.85
    ) is False


def test_reconciled_locked_identity_survives_duplicate_provider_rows():
    payload = {
        "variant_ambiguity": True,
        "locked_set_reconciled_identity": True,
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "ocr_printed_code": None,
        "candidates": [{"printed_code": None}],
        "collector_ocr": {},
    }

    RecognitionService._enforce_payload_printed_code_consistency(payload)

    assert payload["recognition_locked"] is True
    assert payload["verification_state"] == "VERIFIED"


def test_decisive_footer_identifier_accepts_strong_single_read():
    items = [{
        "text": "042/084",
        "score": 0.8,
        "source": "collector_frame_0",
        "variant": "printed_code_2x",
    }]

    assert RecognitionService._decisive_footer_identifier(items, []) == "042/084"


def test_early_footer_fast_pass_uses_two_complementary_variants():
    service = RecognitionService(lambda _event: None)
    service._engine = lambda _image: SimpleNamespace(
        txts=[], scores=[], boxes=[]
    )
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)

    assert service._early_footer_variant_budget(
        locked_to_set=False,
        visual_score=0.0,
        source="auto",
    ) == 2
    _items, diagnostics = service._run_collector_ocr_batched(
        card,
        "collector_frame_0",
        max_variants=2,
    )
    assert [item["variant"] for item in diagnostics] == [
        "printed_code_2x",
        "bottom30_original",
    ]


def test_tight_printed_code_region_excludes_attack_and_weakness_rows():
    card = np.zeros((1000, 700, 3), dtype=np.uint8)

    region = RecognitionService._printed_code_region(card)

    assert region.shape == (105, 284, 3)


def test_batched_footer_canvas_caps_high_resolution_width():
    service = RecognitionService(lambda _event: None)
    observed_shapes = []
    service._engine = lambda image: (
        observed_shapes.append(image.shape)
        or SimpleNamespace(txts=[], scores=[], boxes=[])
    )

    service._run_collector_ocr_batched(
        np.zeros((2800, 2000, 3), dtype=np.uint8),
        "collector_frame_0",
        max_variants=2,
    )

    assert observed_shapes
    assert observed_shapes[0][1] == 900


def test_decisive_footer_identifier_requires_strength_or_variant_agreement():
    items = [{
        "text": "042/084",
        "score": 0.6,
        "source": "collector_frame_0",
        "variant": "printed_code_2x",
    }]
    diagnostics = [{
        "collector_number": "042/084",
        "collector_score": 0.6,
    }]

    assert RecognitionService._decisive_footer_identifier(items, diagnostics) is None


def test_decisive_footer_identifier_accepts_two_variant_votes():
    items = [{
        "text": "042/084",
        "score": 0.6,
        "source": "collector_frame_0",
        "variant": "printed_code_2x",
    }]
    diagnostics = [
        {"collector_number": "042/084", "collector_score": 0.6},
        {"collector_number": "042/084", "collector_score": 0.55},
    ]

    assert RecognitionService._decisive_footer_identifier(items, diagnostics) == "042/084"


def test_locked_set_does_not_reconcile_different_local_number():
    candidate = {"collector_number": "043/120", "name": "Primeape"}

    changed = RecognitionService._reconcile_locked_collector_number(
        candidate, "042/084"
    )

    assert changed is False
    assert candidate == {"collector_number": "043/120", "name": "Primeape"}


def test_single_card_temporal_confirmation_rejects_conflicting_printed_code(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "printed_code": "2305/07",
        },
        "fingerprint": "adec44da72341b5b",
        "confirmations": 3,
    }
    payload = {
        "candidates": [{"canonical_name": "Crocalor", "printed_code": "2306/07"}],
        "recognition_locked": False,
        "artwork_fingerprint": "adec44da72341b58",
    }

    service._apply_single_temporal_confirmation(payload)

    assert payload["recognition_locked"] is False


def test_reference_identifier_cache_persists_across_restart(tmp_path, monkeypatch):
    temporal_path = tmp_path / "single-temporal.json"
    image_path = tmp_path / "reference.png"
    image_path.write_bytes(b"placeholder")
    service = RecognitionService(lambda _event: None, temporal_path=temporal_path)
    monkeypatch.setattr("rareiq.services.recognition_service.cv2.imread", lambda *_args, **_kwargs: np.zeros((400, 280, 3), dtype=np.uint8))
    monkeypatch.setattr(
        service,
        "_run_collector_ocr",
        lambda *_args, **_kwargs: ([{"text": "2304/07", "score": 0.99}], []),
    )

    assert service._reference_printed_code(image_path) == "2304/07"

    restored = RecognitionService(lambda _event: None, temporal_path=temporal_path)
    monkeypatch.setattr(
        restored,
        "_run_collector_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("persisted cache must bypass OCR")),
    )
    assert restored._reference_printed_code(image_path) == "2304/07"


def test_temporal_shortlist_evidence_requires_close_fingerprint_and_family(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {"canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "159"},
        "fingerprint": "adec44da72341b5b",
        "confirmations": 3,
    }
    result = {
        "query_fingerprint": "adec44da72341b58",
        "matches": [{"canonical_name": "Crocalor", "verification_strong": True}],
    }

    evidence = service._temporal_shortlist_evidence(result)

    assert evidence["reason"] == "temporal_fingerprint_continuity"
    assert evidence["fingerprint_distance"] == 2


def test_temporal_shortlist_evidence_rejects_wrong_family_or_distant_card(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {"canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "159"},
        "fingerprint": "0000000000000000",
        "confirmations": 3,
    }
    wrong_family = {
        "query_fingerprint": "0000000000000001",
        "matches": [{"canonical_name": "Sunflora", "verification_strong": True}],
    }
    distant = {
        "query_fingerprint": "ffffffffffffffff",
        "matches": [{"canonical_name": "Crocalor", "verification_strong": True}],
    }

    assert service._temporal_shortlist_evidence(wrong_family) is None
    assert service._temporal_shortlist_evidence(distant) is None


def test_temporal_shortlist_prefers_stable_artwork_fingerprint(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    service._temporal_history = {
        "card": {"canonical_name": "Crocalor"},
        "fingerprint": "adec44da72341b5b",
        "confirmations": 3,
    }
    result = {
        "query_fingerprint": "ffffffffffffffff",
        "continuity_fingerprint": "adec44da72341b58",
        "matches": [{"canonical_name": "Crocalor", "verification_strong": True}],
    }

    evidence = service._temporal_shortlist_evidence(result)

    assert evidence["fingerprint_distance"] == 2


def test_frame_vote_winner_requires_two_unopposed_frames():
    assert RecognitionService._frame_vote_winner({"2304/07": 2, "2504/07": 1}) == ("2304/07", 2)
    assert RecognitionService._frame_vote_winner({"2304/07": 1}) == (None, 1)
    assert RecognitionService._frame_vote_winner({"2304/07": 2, "2504/07": 2}) == (None, 2)


def test_frame_consensus_outranks_reference_biased_single_read():
    code, source = RecognitionService._select_printed_code(
        observed_code="2301/07",
        matched_reference_code="2301/07",
        frame_vote_code="2304/07",
        cross_job_code=None,
    )

    assert code == "2304/07"
    assert source == "frame-consensus"


def test_cross_job_consensus_outranks_reference_match_without_frame_winner():
    code, source = RecognitionService._select_printed_code(
        observed_code="2301/07",
        matched_reference_code="2301/07",
        frame_vote_code=None,
        cross_job_code="2304/07",
    )

    assert code == "2304/07"
    assert source == "cross-job-consensus"


def test_consensus_code_can_replace_noisy_ocr_candidate_set():
    candidates = {"2301/07", "2304/07", "2364/07"}
    frame_code, _ = RecognitionService._frame_vote_winner({"2304/07": 2})
    if frame_code:
        candidates = {frame_code}

    assert candidates == {"2304/07"}


def test_reference_match_must_resolve_to_one_code():
    common = {"verification_strong": True, "printed_code_match": True}
    assert RecognitionService._unique_matched_reference_code([
        {**common, "printed_code": "2304/07"},
    ]) == "2304/07"
    assert RecognitionService._unique_matched_reference_code([
        {**common, "printed_code": "2301/07"},
        {**common, "printed_code": "2304/07"},
    ]) is None


def test_repeated_code_promotes_matching_verified_variant():
    candidates = [
        {"collector_number": "156", "printed_code": "2301/07", "verification_strong": True},
        {"collector_number": "159", "printed_code": "2304/07", "verification_strong": True},
    ]
    promoted = RecognitionService._promote_printed_code_candidate(
        candidates, "2304/07"
    )
    assert promoted[0]["collector_number"] == "159"


def test_final_payload_guard_unlocks_shared_art_code_mismatch():
    payload = {
        "variant_ambiguity": True,
        "ocr_printed_code": "2304/07",
        "candidates": [{"printed_code": "2301/07"}],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "lock_reason": "temporal",
    }
    RecognitionService._enforce_payload_printed_code_consistency(payload)
    assert payload["recognition_locked"] is False
    assert payload["verification_state"] == "SEARCHING"
    assert payload["identity_conflict"] == {
        "observed": "2304/07",
        "selected": "2301/07",
        "reason": "printed codes disagree",
    }


def test_final_payload_guard_rejects_shared_art_without_repeated_footer_evidence():
    payload = {
        "variant_ambiguity": True,
        "ocr_printed_code": "2301/07",
        "candidates": [{"printed_code": "2301/07"}],
        "collector_ocr": {
            "frame_vote_winner": None,
            "cross_job_winner": None,
        },
        "recognition_locked": True,
        "verification_state": "VERIFIED",
    }
    RecognitionService._enforce_payload_printed_code_consistency(payload)
    assert payload["recognition_locked"] is False
    assert payload["identity_conflict"]["reason"] == (
        "shared-art identity lacks repeated footer evidence"
    )


def test_non_applied_temporal_correction_does_not_count_as_repeated_evidence():
    payload = {
        "variant_ambiguity": True,
        "ocr_printed_code": "2301/07",
        "candidates": [{"printed_code": "2301/07"}],
        "collector_ocr": {
            "reference_aware_correction": {
                "applied": False,
                "observed": "2301/07",
                "corrected": "2301/07",
            }
        },
        "recognition_locked": True,
        "verification_state": "VERIFIED",
    }
    RecognitionService._enforce_payload_printed_code_consistency(payload)
    assert payload["recognition_locked"] is False


def test_reference_annotation_reuses_catalog_printed_code_without_ocr(monkeypatch):
    service = RecognitionService(lambda _event: None)
    monkeypatch.setattr(
        service,
        "_reference_printed_code",
        lambda _path: (_ for _ in ()).throw(AssertionError("reference OCR ran")),
    )
    candidate = {
        "verification_strong": True,
        "printed_code": "2304/07",
        "image_path": "unused.png",
    }

    annotated = service._annotate_reference_identifiers(
        [candidate], {"2304/07"}, limit=1
    )

    assert annotated[0]["printed_code"] == "2304/07"
    assert annotated[0]["printed_code_match"] is True
    assert annotated[0]["printed_code_match_mode"] == "exact"


def test_artwork_index_printed_code_lookup_is_exact_and_returns_copies():
    service = RecognitionService(lambda _event: None)
    service.artwork_index._records = [
        {"id": "a", "printed_code": "2304/07"},
        {"id": "b", "printed_code": "2305/07"},
    ]

    matches = service.artwork_index.records_for_printed_code("2304/07")

    assert matches == [{"id": "a", "printed_code": "2304/07"}]
    matches[0]["id"] = "changed"
    assert service.artwork_index._records[0]["id"] == "a"


def test_printed_code_lookup_preserves_gem_pack_identity_fields():
    service = RecognitionService(lambda _event: None)
    service.artwork_index._records = [{
        "id": "crocalor-159",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "159",
        "printed_code": "2304/07",
    }]
    records = service.artwork_index.records_for_printed_code("2304/07")
    assert any(
        item.get("set_id") == "GEM_PACK_VOL_5"
        and str(item.get("collector_number")) == "159"
        for item in records
    )


def test_catalog_visual_correction_requires_missing_code_unique_neighbor_and_visual_support():
    service = RecognitionService(lambda _event: None)
    service.artwork_index._records = [{
        "id": "crocalor-159",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "159",
        "printed_code": "2304/07",
    }]
    visual = [{
        "id": "crocalor-159",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "159",
        "printed_code": "2304/07",
        "verification_strong": True,
        "artwork_verification_strong": True,
    }]

    corrected, evidence = service._catalog_visual_printed_code_correction(
        "2104/07", visual
    )

    assert corrected == "2304/07"
    assert evidence["applied"] is True


def test_catalog_visual_correction_never_rewrites_valid_or_visually_unsupported_code():
    service = RecognitionService(lambda _event: None)
    service.artwork_index._records = [
        {"id": "a", "printed_code": "2104/07"},
        {"id": "b", "printed_code": "2304/07"},
    ]
    assert service._catalog_visual_printed_code_correction("2104/07", [])[0] == "2104/07"
    service.artwork_index._records = [{"id": "b", "printed_code": "2304/07"}]
    assert service._catalog_visual_printed_code_correction("2104/07", [])[0] == "2104/07"


def test_reference_aware_code_correction_requires_temporal_and_visual_agreement(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    expected = {
        "canonical_name": "Crocalor",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "159",
        "printed_code": "2304/07",
    }
    service._temporal_history = {"card": expected, "fingerprint": "a" * 16, "confirmations": 3}
    candidates = [{**expected, "verification_strong": True, "score": 0.72}]

    corrected, evidence = service._reference_aware_printed_code_correction("2504/07", candidates)

    assert corrected == "2304/07"
    assert evidence["applied"] is True
    assert evidence["distance"] == 1


def test_reference_aware_code_correction_rejects_wrong_version_or_large_error(tmp_path):
    service = RecognitionService(lambda _event: None, temporal_path=tmp_path / "single-temporal.json")
    expected = {
        "canonical_name": "Crocalor",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "159",
        "printed_code": "2304/07",
    }
    service._temporal_history = {"card": expected, "fingerprint": "a" * 16, "confirmations": 3}
    wrong = [{**expected, "collector_number": "160", "printed_code": "2305/07", "verification_strong": True, "score": 0.8}]

    assert service._reference_aware_printed_code_correction("2504/07", wrong)[0] == "2504/07"
    assert service._reference_aware_printed_code_correction("9999/07", [{**expected, "verification_strong": True, "score": 0.8}])[0] == "9999/07"


def test_isolated_worker_does_not_inherit_primary_exact_reference_resolver():
    service = RecognitionService(lambda _event: None)
    service.set_exact_reference_resolver(lambda crop, name: {"collector_number": "157"})

    isolated = service.isolated_copy(lambda _event: None)

    assert isolated.exact_reference_resolver is None


def test_follow_up_state_updates_diagnostics_without_losing_evidence():
    service = RecognitionService(lambda event: None)
    service._status["exact_reference_diagnostics"] = {
        "status": "ambiguous",
        "score_gap": 4.5,
    }

    service.update_exact_reference_follow_up("waiting-for-fresh-foil-sample")

    diagnostics = service.status()["exact_reference_diagnostics"]
    assert diagnostics["status"] == "ambiguous"
    assert diagnostics["score_gap"] == 4.5
    assert diagnostics["follow_up_state"] == "waiting-for-fresh-foil-sample"


def test_early_exact_resolution_skips_ocr_for_picked_card(monkeypatch):
    events = []
    service = RecognitionService(events.append)
    service.global_visual_index = type("Visual", (), {
        "search_image": lambda self, frame, limit=15: {
            "matches": [{"canonical_name": "Crocalor", "score": 0.99}],
            "latency_ms": 0.1,
        }
    })()
    monkeypatch.setattr(service.artwork_index, "search_hinted", lambda *args, **kwargs: {
        "matches": [{"canonical_name": "Crocalor", "score": 0.99, "verification_strong": True}],
        "latency_ms": 0.1,
        "hint_hits": 1,
    })
    monkeypatch.setattr(service, "_fast_path_evidence", lambda *args: None)
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR ran")))
    service.set_exact_reference_resolver(lambda crop, name: {
        "card": {"canonical_name": name, "collector_number": "157"},
        "diagnostics": {"status": "resolved"},
    })

    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="manual-picked-slot-1",
    )

    payload = events[-1]["payload"]
    assert payload["recognition_locked"] is True
    assert payload["database_match"]["collector_number"] == "157"
    assert payload["stage_timings"]["ocr_ms"] < 5
    assert "ocr" in payload["stage_timings"]["skipped_stages"]


def test_shared_artwork_family_requires_printed_version_evidence():
    candidates = [
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "157",
            "score": 0.98,
        },
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "score": 0.97,
        },
    ]

    assert RecognitionService._variant_family_ambiguous(candidates) is True


def test_one_printing_repeated_across_indexes_is_not_variant_ambiguity():
    candidates = [
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "score": 0.99,
        },
        {
            "english_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "score": 0.98,
        },
    ]

    assert RecognitionService._variant_family_ambiguous(candidates) is False


def test_cached_geometry_cannot_skip_footer_for_variant_family():
    candidates = [
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "156",
            "score": 0.91,
        },
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "159",
            "score": 0.89,
        },
    ]
    assert RecognitionService._variant_family_ambiguous(candidates) is True
    assert RecognitionService._variant_fast_path_is_ocr_safe({
        "reason": "cached_printed_identity_geometry_consensus",
    }) is False
    assert RecognitionService._variant_fast_path_is_ocr_safe({
        "reason": "temporal_fingerprint_continuity",
    }) is False


def test_retrieval_only_guess_cannot_hide_local_variant_ambiguity():
    candidates = [
        {
            "canonical_name": "Champions Festival",
            "source": "global_visual_index",
            "retrieval_only": True,
            "verification_strong": False,
        },
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "157",
            "verification_strong": True,
        },
        {
            "canonical_name": "Crocalor",
            "set_id": "GEM_PACK_VOL_5",
            "collector_number": "160",
            "verification_strong": True,
        },
    ]

    assert RecognitionService._variant_family_ambiguous(candidates) is True


def test_conflicting_footer_requests_one_fresh_frame_retry():
    candidates = [{
        "canonical_name": "Crocalor",
        "verification_strong": True,
        "printed_code": "2301/07",
    }]
    assert RecognitionService._collector_retry_needed(
        artwork_candidates=candidates,
        fast_path_evidence=None,
        strong_printed_identifier_match=False,
    ) is True
    assert RecognitionService._collector_retry_needed(
        artwork_candidates=candidates,
        fast_path_evidence=None,
        strong_printed_identifier_match=True,
    ) is False


def test_printed_code_expands_visually_omitted_variant(monkeypatch):
    service = RecognitionService(lambda event: None)
    candidates = [{
        "id": "157",
        "canonical_name": "Crocalor",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "157",
        "verification_strong": True,
        "artwork_verification_strong": True,
        "score": 0.81,
    }]
    monkeypatch.setattr(service.artwork_index, "family_records", lambda *args, **kwargs: [
        {"id": "157", "canonical_name": "Crocalor", "collector_number": "157"},
        {"id": "159", "canonical_name": "Crocalor", "collector_number": "159"},
    ])
    monkeypatch.setattr(service, "_annotate_reference_identifiers", lambda family, codes, limit: [
        {**family[0], "printed_code": "2302/07", "printed_code_match": False},
        {**family[1], "printed_code": "2304/07", "printed_code_match": True},
    ])

    expanded = service._expand_variant_family_for_printed_code(
        candidates, {"2304/07"}
    )

    assert expanded[0]["id"] == "159"
    assert expanded[0]["variant_family_expanded"] is True
    assert expanded[0]["verification_strong"] is True


def test_indexed_family_marks_single_cached_candidate_ambiguous(monkeypatch):
    service = RecognitionService(lambda event: None)
    cached = [{
        "canonical_name": "Crocalor",
        "set_id": "GEM_PACK_VOL_5",
        "collector_number": "156",
        "verification_strong": True,
    }]
    monkeypatch.setattr(service.artwork_index, "family_records", lambda *args, **kwargs: [
        {"canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "156"},
        {"canonical_name": "Crocalor", "set_id": "GEM_PACK_VOL_5", "collector_number": "159"},
    ])

    assert service._variant_family_ambiguous(cached) is False
    assert service._indexed_variant_family_ambiguous(cached) is True


def test_footer_observations_reach_consensus_across_retry_jobs():
    service = RecognitionService(lambda event: None)
    first = service._record_footer_observations(
        generation=7,
        fingerprint="abcdef",
        codes={"2304/07", "2104/07"},
    )
    second = service._record_footer_observations(
        generation=7,
        fingerprint="abcdef",
        codes={"2304/07"},
    )

    assert first[0] is None
    assert second[0] == "2304/07"
    assert second[1] == 2
    assert second[2]["2104/07"] == 1


def test_footer_observations_do_not_cross_generation_or_artwork():
    service = RecognitionService(lambda event: None)
    service._record_footer_observations(
        generation=2, fingerprint="card-a", codes={"2304/07"}
    )
    winner, count, votes = service._record_footer_observations(
        generation=3, fingerprint="card-b", codes={"2304/07"}
    )

    assert winner is None
    assert count == 1
    assert votes == {"2304/07": 1}


def test_visual_interim_publishes_before_background_enrichment():
    events = []
    service = RecognitionService(events.append)
    service._current_generation = 3
    service._publish_visual_interim(
        generation=3,
        frame_id=8,
        source="manual-picked-slot-1",
        candidates=[{"canonical_name": "Crocalor", "score": 0.81}],
        fingerprint="abc",
        resolution={"diagnostics": {"status": "ambiguous", "score_gap": 5.2}},
        started=time.perf_counter(),
        stage_timings={"exact_reference_ms": 300.0},
    )

    payload = events[-1]["payload"]
    assert payload["background_enrichment"] is True
    assert payload["recognition_path"] == "visual-interim"
    assert payload["candidates"][0]["canonical_name"] == "Crocalor"
    assert payload["exact_reference_diagnostics"]["score_gap"] == 5.2
    assert service.status()["busy"] is True


def test_global_visual_candidate_publishes_before_exhaustive_artwork_search(monkeypatch):
    events = []
    service = RecognitionService(events.append)
    service.global_visual_index = type("Visual", (), {
        "search_image": lambda self, frame, limit=15: {
            "matches": [{"canonical_name": "Crocalor", "score": 0.88}],
            "latency_ms": 0.1,
        }
    })()
    service.set_exact_reference_resolver(lambda crop, name: {
        "card": None,
        "diagnostics": {"status": "ambiguous", "score_gap": 5.0},
    })
    observed = []

    def exhaustive(*args, **kwargs):
        observed.append(any(event.get("payload", {}).get("background_enrichment") for event in events))
        return {"matches": [], "query_fingerprint": None}

    monkeypatch.setattr(service.artwork_index, "search", exhaustive)
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: [])
    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="manual-picked-slot-1",
    )

    assert observed == [True]
    interim = next(event["payload"] for event in events if event["payload"].get("background_enrichment"))
    assert interim["candidates"][0]["canonical_name"] == "Crocalor"


def test_multi_card_source_publishes_cached_visual_candidate_before_slow_stages(monkeypatch):
    events = []
    service = RecognitionService(events.append)
    service.global_visual_index = SimpleNamespace(search_image=lambda frame, limit: {
        "matches": [{"canonical_name": "Crocalor", "score": 0.91}],
        "latency_ms": 0.2,
    })
    observed = []

    def exhaustive(*args, **kwargs):
        observed.append(any(
            event.get("payload", {}).get("recognition_path") == "visual-interim"
            for event in events
        ))
        return {"matches": [], "query_fingerprint": None}

    monkeypatch.setattr(service.artwork_index, "search", exhaustive)
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: [])
    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="six-card-grid",
    )

    assert observed == [True]
    interim = next(
        event["payload"] for event in events
        if event.get("payload", {}).get("recognition_path") == "visual-interim"
    )
    assert interim["last_latency_ms"] < 1000
    assert interim["candidates"][0]["canonical_name"] == "Crocalor"


def test_multi_card_ocr_uses_one_footer_call_and_skips_top_and_full(monkeypatch):
    service = RecognitionService(lambda event: None)
    service.global_visual_index = SimpleNamespace(search_image=lambda frame, limit: {
        "matches": [], "latency_ms": 0.1,
    })
    monkeypatch.setattr(service.artwork_index, "search", lambda *args, **kwargs: {
        "matches": [], "query_fingerprint": None,
    })
    general_calls = []
    footer_calls = []
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: general_calls.append(args) or [])
    monkeypatch.setattr(service, "_run_collector_ocr_batched", lambda *args, **kwargs: footer_calls.append((args, kwargs)) or ([], []))
    monkeypatch.setattr(service, "_annotate_reference_identifiers", lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("grid workers must not OCR catalog reference images")))

    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="six-card-grid",
    )

    assert len(footer_calls) == 1
    assert footer_calls[0][1]["max_variants"] == 1
    assert general_calls == []
    assert service.status()["stage_timings"]["ocr_mode"] == "single-shot-footer"
    assert "reference_identifier" in service.status()["stage_timings"]["skipped_stages"]


def test_recent_family_cache_requires_two_strong_local_references():
    service = RecognitionService(lambda event: None)
    service._remember_trusted_family([{
        "canonical_name": "Wrong",
        "verification_strong": False,
        "image_path": "wrong.png",
    }])
    assert service._trusted_recent_family_hints() == []

    service._remember_trusted_family([
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "156.png"},
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "157.png"},
    ])
    hints = service._trusted_recent_family_hints()
    assert len(hints) == 2
    assert {item["canonical_name"] for item in hints} == {"Crocalor"}


def test_isolated_workers_share_recent_trusted_family_cache():
    service = RecognitionService(lambda event: None)
    worker = service.isolated_copy(lambda event: None)
    service._remember_trusted_family([
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "156.png"},
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "157.png"},
    ])
    assert len(worker._trusted_recent_family_hints()) == 2


def test_verified_recent_family_shortlist_skips_exhaustive_search(monkeypatch):
    service = RecognitionService(lambda event: None)
    service.global_visual_index = SimpleNamespace(search_image=lambda frame, limit: {
        "matches": [{"canonical_name": "Untrusted global", "score": .85}],
        "latency_ms": .1,
    })
    hints = [
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "156.png"},
        {"canonical_name": "Crocalor", "verification_strong": True, "image_path": "157.png"},
    ]
    service._recent_family_hints[:] = hints
    monkeypatch.setattr(service.artwork_index, "search_hinted", lambda *args, **kwargs: {
        "matches": hints,
        "hint_hits": 2,
        "query_fingerprint": "family",
        "latency_ms": 2.0,
    })
    monkeypatch.setattr(service.artwork_index, "search", lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("verified family shortlist must skip exhaustive search")))
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_run_collector_ocr_batched", lambda *args, **kwargs: ([], []))

    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="six-card-grid",
    )

    timings = service.status()["stage_timings"]
    assert timings["artwork_fallback"] is False
    assert timings["family_shortlist_verified"] is True


def test_reference_feature_cache_is_large_and_single_flight(monkeypatch):
    service = RecognitionService(lambda event: None)
    index = service.artwork_index
    calls = []
    monkeypatch.setattr(index, "_verification_features", lambda image: calls.append(1) or (image, [], None))
    image = np.zeros((50, 40, 3), dtype=np.uint8)

    first = index._cached_reference_features("same-reference.png", image)
    second = index._cached_reference_features("same-reference.png", image)

    assert first is second
    assert calls == [1]
    assert index._reference_feature_cache_limit >= 512


def test_batch_shortlists_traverse_catalog_once_for_multiple_cards():
    service = RecognitionService(lambda event: None)
    index = service.artwork_index
    index._records = [
        {
            "id": f"card-{number}",
            "fingerprint": f"{number:016x}",
            "artwork_fingerprint": f"{number * 3:016x}",
        }
        for number in range(1, 50)
    ]
    cards = {
        1: np.full((700, 500, 3), 30, dtype=np.uint8),
        2: np.full((700, 500, 3), 180, dtype=np.uint8),
        3: np.full((700, 500, 3), 240, dtype=np.uint8),
    }

    result = index.batch_shortlists(cards)

    assert result["ok"] is True
    assert result["catalog_records_visited"] == 49
    assert result["live_card_count"] == 3
    assert set(result["slots"]) == {1, 2, 3}
    assert all(item["candidate_count"] <= 36 for item in result["slots"].values())


def test_trusted_exact_shortlist_skips_exhaustive_artwork_search(monkeypatch):
    service = RecognitionService(lambda event: None)
    service.global_visual_index = SimpleNamespace(search_image=lambda frame, limit: {
        "matches": [{"canonical_name": "Crocalor", "score": 0.88}],
        "latency_ms": 0.1,
    })
    shortlist = [
        {"set_id": "GEM_PACK_VOL_5", "collector_number": "157", "score": 36.0},
        {"set_id": "GEM_PACK_VOL_5", "collector_number": "160", "score": 31.0},
    ]
    service.set_exact_reference_resolver(lambda crop, name: {
        "card": None,
        "diagnostics": {
            "status": "ambiguous",
            "top_score": 36.0,
            "score_gap": 5.0,
            "candidates": shortlist,
        },
    })
    observed_hints = []
    monkeypatch.setattr(service.artwork_index, "search_hinted", lambda frame, hints, limit: (
        observed_hints.extend(hints) or {
            "matches": [{**shortlist[0], "canonical_name": "Crocalor", "verification_strong": True}],
            "hint_hits": 2,
            "query_fingerprint": "fingerprint",
            "latency_ms": 1.0,
        }
    ))
    monkeypatch.setattr(service.artwork_index, "search", lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("trusted exact shortlist must skip exhaustive search")))
    monkeypatch.setattr(service, "_run_ocr", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_run_collector_ocr", lambda *args, **kwargs: ([], []))

    service._recognize_worker(
        np.zeros((700, 500, 3), dtype=np.uint8),
        generation=0,
        source="manual-picked-slot-1",
    )

    assert observed_hints[:2] == shortlist
    assert service.status()["stage_timings"]["artwork_fallback"] is False
    assert service.status()["stage_timings"]["exact_shortlist_verified"] is True


def test_locked_footer_visual_consensus_accepts_provider_total_mismatch():
    evidence = RecognitionService._locked_footer_visual_consensus(
        {
            "set_id": "me05", "collector_number": "001/084",
            "canonical_name": "Tropius",
        },
        {
            "set_id": "me05", "collector_number": "001/120",
            "canonical_name": "Tropius", "score": 0.918,
        },
        "001/084",
        {"set_id": "me05"},
    )

    assert evidence is not None
    assert evidence["reason"] == "locked_footer_visual_consensus"


def test_locked_footer_visual_consensus_rejects_any_identity_disagreement():
    catalog = {
        "set_id": "me05", "collector_number": "001/084",
        "canonical_name": "Tropius",
    }
    active = {"set_id": "me05"}
    valid_visual = {
        "set_id": "me05", "collector_number": "001/120",
        "canonical_name": "Tropius", "score": 0.918,
    }

    disagreements = [
        {**valid_visual, "set_id": "other"},
        {**valid_visual, "collector_number": "002/120"},
        {**valid_visual, "canonical_name": "Tangela"},
        {**valid_visual, "score": 0.899},
        {**valid_visual, "retrieval_only": True},
    ]
    assert all(
        RecognitionService._locked_footer_visual_consensus(
            catalog, candidate, "001/084", active
        ) is None
        for candidate in disagreements
    )
