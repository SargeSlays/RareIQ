from rareiq.core.recognition_state import RecognitionStateStore


def test_snapshot_keeps_ocr_identifier_separate_from_catalog_candidate() -> None:
    store = RecognitionStateStore()
    snapshot = store.update_recognition({
        "ocr_collector_number": "157/198",
        "ocr_printed_code": "2302/07",
        "confidence": 0.82,
        "collector_ocr": {"reference_match": True},
        "candidates": [{
            "id": "catalog-161",
            "collector_number": "161",
            "name": "Crocalor",
            "source": "pokipair",
            "image_path": "reference.png",
            "score": 0.74,
        }],
    })

    assert snapshot["collector_number"] == "161"
    assert snapshot["ocr_collector_number"] == "157/198"
    assert snapshot["ocr_printed_code"] == "2302/07"
    assert snapshot["ocr_confidence"] == 0.82
    assert snapshot["identifier_reference_match"] is True


def test_snapshot_replaces_wrong_language_reference_with_requested_variant() -> None:
    store = RecognitionStateStore()
    snapshot = store.refresh(
        recognition={
            "language": "English",
            "collector_number": "029/084",
            "candidates": [{
                "id": "it-me05-029", "name": "Slowpoke",
                "collector_number": "029/084", "language": "Italian",
                "reference_image_url": "/italian.webp", "source": "pokipair",
                "verification_strong": True, "score": 0.90,
            }],
        },
        catalog={
            "query": {"language": "English"},
            "candidates": [
                {"id": "it-me05-029", "name": "Slowpoke", "collector_number": "029/084", "language": "Italian", "reference_image_url": "/italian.webp"},
                {"id": "en-me05-029", "name": "Slowpoke", "collector_number": "029/084", "language": "English", "language_code": "en", "reference_image_url": "/english.webp"},
            ],
        },
    )

    assert snapshot["primary_candidate"]["language"] == "English"
    assert snapshot["primary_candidate"]["reference_image_url"] == "/english.webp"


def test_snapshot_does_not_invent_ocr_identifier_from_candidate() -> None:
    store = RecognitionStateStore()
    snapshot = store.update_recognition({
        "candidates": [{
            "id": "catalog-161",
            "collector_number": "161",
            "name": "Crocalor",
            "source": "pokipair",
            "image_path": "reference.png",
            "score": 0.74,
        }],
    })

    assert snapshot["collector_number"] == "161"
    assert snapshot["ocr_collector_number"] is None
    assert snapshot["ocr_printed_code"] is None
    assert snapshot["identifier_reference_match"] is False


def test_snapshot_exposes_single_card_temporal_confirmation() -> None:
    store = RecognitionStateStore()
    snapshot = store.update_recognition({
        "temporal_confirmation": True,
        "temporal_confirmation_count": 3,
        "temporal_confirmation_progress": 2,
        "temporal_confirmation_required": 2,
    })

    assert snapshot["temporal_confirmation"] is True
    assert snapshot["temporal_confirmation_count"] == 3
    assert snapshot["temporal_confirmation_progress"] == 2
    assert snapshot["temporal_confirmation_required"] == 2


def test_state_id_is_stable_across_refreshes_for_the_same_card() -> None:
    store = RecognitionStateStore()
    store.set_continuous_state("STABLE", generation=4, card_present=True)
    payload = {
        "generation": 4,
        "artwork_fingerprint": "abcd1234",
        "candidates": [{
            "id": "me05-047",
            "name": "Koraidon",
            "collector_number": "047/084",
            "source": "pokipair",
            "image_path": "koraidon.webp",
            "verification_strong": True,
        }],
    }
    first = store.update_recognition(payload)
    second = store.refresh(recognition=payload)
    assert second["revision"] > first["revision"]
    assert second["state_id"] == first["state_id"]


def test_state_id_changes_when_recognition_generation_changes() -> None:
    store = RecognitionStateStore()
    payload = {"candidates": [{"id": "card-1", "source": "pokipair", "image_path": "card.webp", "verification_strong": True}]}
    store.set_continuous_state("STABLE", generation=1, card_present=True)
    first = store.update_recognition({**payload, "generation": 1})
    store.set_continuous_state("STABLE", generation=2, card_present=True)
    second = store.update_recognition({**payload, "generation": 2})
    assert second["state_id"] != first["state_id"]


def test_snapshot_exposes_exact_reference_decision_diagnostics() -> None:
    store = RecognitionStateStore()
    diagnostics = {
        "status": "ambiguous",
        "reason": "Top references are too close.",
        "score_gap": 6.0,
        "candidates": [
            {"collector_number": "157", "score": 36.0},
            {"collector_number": "159", "score": 30.0},
        ],
    }
    snapshot = store.update_recognition({"exact_reference_diagnostics": diagnostics})

    assert snapshot["exact_reference_diagnostics"] == diagnostics


def test_snapshot_does_not_promote_global_retrieval_guess_to_primary() -> None:
    store = RecognitionStateStore()
    snapshot = store.update_recognition({
        "name_candidate": "Alph Lithograph",
        "has_reference_evidence": True,
        "overall_confidence": 0.95,
        "candidates": [{
            "id": "hgss4-FOUR",
            "name": "Alph Lithograph",
            "source": "global_visual_index",
            "local_image": "alph.webp",
            "score": 0.95,
        }],
    })

    assert snapshot["primary_candidate"] is None
    assert snapshot["has_reference_evidence"] is False
    assert snapshot["phase"] == "SEARCHING"
    assert snapshot["auto_add"]["candidate_available"] is False


def test_snapshot_promotes_evidence_backed_artwork_candidate_over_global_guess() -> None:
    store = RecognitionStateStore()
    snapshot = store.update_recognition({
        "has_reference_evidence": True,
        "candidates": [
            {
                "id": "wrong-global",
                "name": "Alph Lithograph",
                "source": "global_visual_index",
                "local_image": "alph.webp",
                "score": 0.99,
            },
            {
                "id": "crocalor-160",
                "name": "Crocalor",
                "source": "pokipair",
                "image_path": "crocalor.webp",
                "verification_strong": True,
                "score": 0.72,
            },
        ],
    })

    assert snapshot["primary_candidate"]["id"] == "crocalor-160"
    assert snapshot["name_candidate"] == "Crocalor"


def test_snapshot_promotes_verified_set_locked_global_identity() -> None:
    store = RecognitionStateStore()
    store.set_continuous_state("STABLE", generation=5, card_present=True)
    snapshot = store.update_recognition({
        "generation": 5,
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "overall_confidence": 0.59,
        "candidates": [{
            "id": "me05-023",
            "name": "Electrike",
            "collector_number": "023/084",
            "set_name": "Pitch Black",
            "source": "global_visual_index",
            "reference_image_url": "/card.webp",
            "provisional": True,
            "retrieval_only": False,
            "set_locked_identity_agreement": True,
            "signals": {"collector_number": 1.0},
            "score": 0.925,
        }],
    })

    assert snapshot["primary_candidate"]["name"] == "Electrike"
    assert snapshot["has_reference_evidence"] is True
    assert snapshot["recognition_locked"] is True
    assert snapshot["verification_state"] == "VERIFIED"
    assert snapshot["result_current"] is True


def test_snapshot_promotes_directly_verified_exact_fraction_global_identity() -> None:
    store = RecognitionStateStore()
    store.set_continuous_state("STABLE", generation=6, card_present=True)
    snapshot = store.update_recognition({
        "generation": 6,
        "recognition_locked": True,
        "verification_state": "VERIFIED",
        "has_reference_evidence": True,
        "overall_confidence": 0.79,
        "candidates": [{
            "id": "me5-29",
            "name": "Slowpoke",
            "collector_number": "29/84",
            "source": "global_visual_index",
            "reference_image_url": "/slowpoke.png",
            "retrieval_only": False,
            "verification_strong": True,
            "artwork_verification_strong": True,
            "collector_fraction_exact": True,
            "signals": {"collector_number": 1.0},
            "score": 0.90,
        }],
    })

    assert snapshot["primary_candidate"]["id"] == "me5-29"
    assert snapshot["has_reference_evidence"] is True
    assert snapshot["recognition_locked"] is True
    assert snapshot["verification_state"] == "VERIFIED"
    assert snapshot["result_current"] is True


def test_snapshot_surfaces_set_locked_catalog_preview_without_verifying_it() -> None:
    store = RecognitionStateStore()
    store.set_continuous_state("STABLE", generation=7, card_present=True)
    snapshot = store.update_recognition({
        "generation": 7,
        "recognition_locked": False,
        "verification_state": "SEARCHING",
        "candidates": [{
            "id": "me05-023",
            "name": "Electrike",
            "collector_number": "023/084",
            "set_name": "Pitch Black",
            "source": "live_catalog",
            "reference_image_url": "/card.webp",
            "provisional": True,
            "retrieval_only": False,
            "set_locked_catalog_lookup": True,
            "signals": {"collector_number": 1.0},
            "score": 0.89,
        }],
    })

    assert snapshot["primary_candidate"]["name"] == "Electrike"
    assert snapshot["recognition_locked"] is False
    assert snapshot["verification_state"] == "REFERENCE NEEDED"
    assert snapshot["auto_add"]["candidate_available"] is True
    assert snapshot["auto_add"]["production_ready"] is False
