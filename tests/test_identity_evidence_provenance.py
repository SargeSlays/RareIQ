import asyncio
from pathlib import Path
from types import SimpleNamespace

from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.core.recognition_state import RecognitionStateStore
from rareiq.services.backend_test_service import BackendTestService
from rareiq.services.recognition_service import RecognitionService


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(
    encoding="utf-8"
)


def _catalog_candidate(language: str = "English") -> dict:
    return {
        "id": "me5-29",
        "name": "Slowpoke",
        "printed_name": "Slowpoke",
        "english_name": "Slowpoke",
        "collector_number": "29/84",
        "language": language,
        "set_id": "me5",
        "set_name": "Pitch Black",
        "source": "global_visual_index",
        "reference_image_url": "/reference/slowpoke.png",
        "verification_strong": True,
        "artwork_verification_strong": True,
        "collector_fraction_exact": True,
        "signals": {
            "collector_number": 1.0,
            "language": 0.0,
        },
    }


def test_normalized_card_keeps_observed_and_catalog_identity_separate() -> None:
    service = object.__new__(BackendTestService)
    service.orchestrator = None
    candidate = _catalog_candidate()

    card = service.normalize_current_card(
        recognition={
            "language": "Chinese",
            "ocr_collector_number": "029/084",
            "overall_confidence": 0.801,
            "recognition_locked": True,
            "verification_state": "VERIFIED",
            "candidates": [candidate],
        },
        state={"candidates": [candidate]},
    )

    assert card is not None
    assert card["language"] == "English"
    assert card["observed_language"] == "Chinese"
    assert card["catalog_language"] == "English"
    assert card["observed_collector_number"] == "029/084"
    assert card["catalog_collector_number"] == "29/84"
    assert card["identity_evidence"]["agreements"] == {
        "collector_number": True,
        "language": False,
    }
    assert card["identity_conflicts"] == [{
        "field": "language",
        "observed": "Chinese",
        "catalog": "English",
        "reason": "observed_catalog_mismatch",
    }]
    assert card["identity_consistent"] is False
    assert card["recognition_locked"] is False
    assert card["verification_state"] == "REVIEW_NEEDED"


def test_chinese_language_aliases_do_not_create_a_false_conflict() -> None:
    service = object.__new__(BackendTestService)
    service.orchestrator = None
    candidate = _catalog_candidate("zh_cn")

    card = service.normalize_current_card(
        recognition={
            "language": "Simplified Chinese",
            "ocr_collector_number": "029/084",
            "recognition_locked": True,
            "verification_state": "VERIFIED",
            "candidates": [candidate],
        },
        state={"candidates": [candidate]},
    )

    assert card is not None
    assert card["identity_consistent"] is True
    assert card["identity_conflicts"] == []
    assert card["recognition_locked"] is True
    assert card["verification_state"] == "VERIFIED"


def test_disputed_identity_is_not_published_as_authoritative_current_card() -> None:
    service = object.__new__(BackendTestService)
    service.orchestrator = None
    candidate = _catalog_candidate()
    recognition = {
        "language": "Chinese",
        "ocr_collector_number": "029/084",
        "overall_confidence": 0.801,
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "candidates": [candidate],
    }
    state = {
        "candidates": [candidate],
        "result_current": True,
        "identity_evidence": {
            "observed": {
                "collector_number": "029/084",
                "language": "Chinese",
            },
            "catalog": {
                "collector_number": "29/84",
                "language": "English",
            },
        },
    }

    assert service.authoritative_current_card(recognition, state) is None
    assert state["identity_evidence"]["observed"]["language"] == "Chinese"
    assert state["identity_evidence"]["catalog"]["language"] == "English"


def test_verified_consistent_identity_remains_authoritative() -> None:
    service = object.__new__(BackendTestService)
    service.orchestrator = None
    candidate = _catalog_candidate("zh-cn")

    card = service.authoritative_current_card(
        recognition={
            "language": "Simplified Chinese",
            "ocr_collector_number": "029/084",
            "overall_confidence": 0.93,
            "recognition_locked": True,
            "verification_state": "VERIFIED",
            "candidates": [candidate],
        },
        state={
            "candidates": [candidate],
            "result_current": True,
            "has_reference_evidence": True,
        },
    )

    assert card is not None
    assert card["card_id"] == "me5-29"
    assert card["identity_consistent"] is True
    assert card["verification_state"] == "VERIFIED"
    assert card["recognition_locked"] is True


def test_final_recognition_payload_routes_language_conflict_to_review() -> None:
    payload = {
        "name_candidate": None,
        "language": "Chinese",
        "ocr_collector_number": "029/084",
        "collector_number": "029/084",
        "candidates": [_catalog_candidate()],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "lock_reason": "OCR, Language, Database or artwork",
        "pipeline_stages": [
            {"key": "verify", "label": "Final verification", "state": "done"}
        ],
        "identity_conflict": None,
    }

    RecognitionService._enforce_payload_identity_consistency(payload)

    assert payload["identity_consistent"] is False
    assert payload["recognition_locked"] is False
    assert payload["verification_state"] == "REVIEW_NEEDED"
    assert payload["lock_reason"] is None
    assert payload["pipeline_stages"][0]["state"] == "waiting"
    assert payload["identity_evidence"]["agreements"] == {
        "collector_number": True,
        "language": False,
    }


def test_final_recognition_payload_preserves_verified_matching_identity() -> None:
    payload = {
        "language": "Chinese",
        "ocr_collector_number": "029/084",
        "candidates": [_catalog_candidate("zh-cn")],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "identity_conflict": None,
    }

    RecognitionService._enforce_payload_identity_consistency(payload)

    assert payload["identity_consistent"] is True
    assert payload["identity_conflicts"] == []
    assert payload["recognition_locked"] is True
    assert payload["verification_state"] == "VERIFIED"


def _reference_lookup_service(*results: dict) -> RecognitionService:
    service = object.__new__(RecognitionService)
    service._cards = []
    service.artwork_index = SimpleNamespace(
        text_search=lambda _query, *, limit: list(results)[:limit]
    )
    service.global_visual_index = None
    return service


def test_catalog_gap_marks_observed_identity_missing_from_local_references() -> None:
    payload = {
        "language": "Chinese",
        "ocr_collector_number": "029/084",
        "candidates": [_catalog_candidate("Italian")],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "has_reference_evidence": True,
        "pipeline_stages": [{"key": "verify", "state": "done"}],
    }
    service = _reference_lookup_service(_catalog_candidate("Italian"))

    RecognitionService._enforce_payload_identity_consistency(payload)
    result = service._search_local_identity_references(payload)
    service._apply_catalog_gap_result(payload, result)

    assert result["status"] == "missing"
    assert result["query"]["collector_key"] == "29/84"
    assert result["query"]["language_key"] == "zh-cn"
    assert payload["verification_state"] == "REFERENCE_MISSING"
    assert payload["recognition_locked"] is False
    assert payload["has_reference_evidence"] is False
    assert payload["catalog_gap"]["match_count"] == 0
    assert payload["catalog_recovery_candidates"] == []
    assert payload["pipeline_stages"][0]["detail"] == (
        "No matching local catalog reference"
    )


def test_catalog_gap_surfaces_normalized_local_recovery_without_auto_approval() -> None:
    recovered = {
        **_catalog_candidate("zh_cn"),
        "id": "me5-cn-029",
        "collector_number": "029/084",
        "reference_image_url": "/reference/slowpoke-cn.png",
    }
    payload = {
        "language": "Simplified Chinese",
        "ocr_collector_number": "29/84",
        "candidates": [_catalog_candidate("Italian")],
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "pipeline_stages": [{"key": "verify", "state": "done"}],
    }
    service = _reference_lookup_service(recovered)

    RecognitionService._enforce_payload_identity_consistency(payload)
    result = service._search_local_identity_references(payload)
    service._apply_catalog_gap_result(payload, result)

    assert result["status"] == "available"
    assert result["match_count"] == 1
    assert payload["verification_state"] == "REVIEW_NEEDED"
    assert payload["recognition_locked"] is False
    assert payload["catalog_recovery_candidates"][0]["id"] == "me5-cn-029"
    assert payload["catalog_recovery_candidates"][0][
        "catalog_recovery_source"
    ] == "artwork_index"
    assert payload["pipeline_stages"][0]["detail"] == (
        "Matching local reference available for operator selection"
    )


def test_recognition_state_propagates_identity_provenance() -> None:
    store = RecognitionStateStore()
    conflict = {
        "field": "language",
        "observed": "Chinese",
        "catalog": "English",
        "reason": "observed_catalog_mismatch",
    }
    snapshot = store.update_recognition({
        "language": "Chinese",
        "candidates": [_catalog_candidate()],
        "identity_evidence": {
            "observed": {"language": "Chinese"},
            "catalog": {"language": "English"},
        },
        "identity_conflicts": [conflict],
        "identity_consistent": False,
        "recognition_locked": False,
        "verification_state": "REVIEW_NEEDED",
    })

    assert snapshot["identity_consistent"] is False
    assert snapshot["identity_conflicts"] == [conflict]
    assert snapshot["identity_evidence"]["observed"]["language"] == "Chinese"
    assert snapshot["verification_state"] == "REVIEW_NEEDED"


def test_recognition_state_preserves_reference_missing_and_recovery_metadata() -> None:
    store = RecognitionStateStore()
    candidate = _catalog_candidate("Italian")
    snapshot = store.update_recognition({
        "candidates": [candidate],
        "recognition_locked": False,
        "has_reference_evidence": True,
        "verification_state": "REFERENCE_MISSING",
        "catalog_gap": {
            "status": "missing",
            "query": {
                "collector_number": "029/084",
                "language": "Chinese",
            },
            "match_count": 0,
        },
        "catalog_recovery_candidates": [],
    })

    assert snapshot["primary_candidate"]["id"] == candidate["id"]
    assert snapshot["verification_state"] == "REFERENCE_MISSING"
    assert snapshot["has_reference_evidence"] is False
    assert snapshot["auto_add"]["reference_available"] is False
    assert snapshot["catalog_gap"]["status"] == "missing"
    assert snapshot["catalog_recovery_candidates"] == []


def test_approval_is_blocked_until_conflicting_identity_is_reviewed() -> None:
    conflict = {
        "field": "language",
        "observed": "Chinese",
        "catalog": "English",
        "reason": "observed_catalog_mismatch",
    }
    fake = SimpleNamespace(
        _decision_recognition_card=lambda: {"card_name": "Slowpoke"},
        recognition_state=SimpleNamespace(
            refresh=lambda **_kwargs: {
                "identity_consistent": False,
                "identity_conflicts": [conflict],
                "overall_confidence": 0.801,
            }
        ),
        vision=SimpleNamespace(status=lambda: {}),
        recognition=SimpleNamespace(status=lambda: {}),
        catalog=SimpleNamespace(status=lambda: {}),
    )

    result = asyncio.run(RareIQOrchestrator.confirm_recognition(fake))

    assert result["ok"] is False
    assert result["reason"] == "identity_evidence_conflict"
    assert result["identity_conflicts"] == [conflict]


def test_authoritative_identity_requires_every_trust_signal() -> None:
    safe = {
        "verification_state": "VERIFIED",
        "identity_consistent": True,
        "recognition_locked": True,
        "result_current": True,
        "has_reference_evidence": True,
    }
    assert RareIQOrchestrator._identity_is_authoritative(safe) is True

    for field in (
        "identity_consistent",
        "recognition_locked",
        "result_current",
        "has_reference_evidence",
    ):
        assert RareIQOrchestrator._identity_is_authoritative({
            **safe,
            field: False,
        }) is False
    assert RareIQOrchestrator._identity_is_authoritative({
        **safe,
        "verification_state": "REVIEW_NEEDED",
    }) is False


def test_automatic_add_rejects_unlocked_candidate() -> None:
    fake = SimpleNamespace(
        _decision_recognition_card=lambda: {"card_name": "Candidate"},
        recognition_state=SimpleNamespace(
            refresh=lambda **_kwargs: {
                "verification_state": "VERIFIED",
                "identity_consistent": True,
                "recognition_locked": False,
                "result_current": True,
                "has_reference_evidence": True,
                "overall_confidence": 0.93,
            }
        ),
        vision=SimpleNamespace(status=lambda: {}),
        recognition=SimpleNamespace(status=lambda: {}),
        catalog=SimpleNamespace(status=lambda: {}),
    )

    result = asyncio.run(
        RareIQOrchestrator.confirm_recognition(fake, automatic=True)
    )

    assert result["ok"] is False
    assert result["reason"] == "identity_not_authoritative"


def test_studiox_routes_identity_conflict_to_review_without_exact_match() -> None:
    assert "function hasIdentityEvidenceConflict" in SCRIPT
    assert "identitySafe&&(canonicalVerified" in SCRIPT
    assert 'title:"REVIEW NEEDED"' in SCRIPT
    assert "Observed collector number" in SCRIPT
    assert "Catalog collector number" in SCRIPT
    assert "Observed language" in SCRIPT
    assert "Catalog language" in SCRIPT
    assert "Conflict — review required" in SCRIPT
    assert "Capture stable across" in SCRIPT


def test_studiox_distinguishes_missing_reference_and_reuses_correction_flow() -> None:
    presentation = SCRIPT.split(
        "function deriveRecognitionPresentation", 1
    )[1].split("function stabilizeRecognitionPresentation", 1)[0]
    assert 'verificationState==="REFERENCE_MISSING"' in presentation
    assert 'title:"REFERENCE MISSING"' in presentation
    assert "catalogGapPresentationDetail(snapshot)" in presentation
    assert "function referenceCorrectionCandidates" in SCRIPT
    assert "catalog_recovery_candidates" in SCRIPT
    assert SCRIPT.count("/api/intelligence/catalog-search") == 1
