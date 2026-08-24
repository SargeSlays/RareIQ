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
