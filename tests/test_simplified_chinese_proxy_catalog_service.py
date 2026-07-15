from __future__ import annotations

import json
from pathlib import Path

from rareiq.services.simplified_chinese_proxy_catalog_service import (
    SimplifiedChineseProxyCatalogService,
)


def make_service(
    tmp_path: Path,
) -> SimplifiedChineseProxyCatalogService:
    return SimplifiedChineseProxyCatalogService(
        project_root=tmp_path,
    )


def test_safe_filename() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._safe_filename(
            "CSV7C/card:084?"
        )
        == "CSV7C_card_084"
    )


def test_normalize_name_removes_spacing() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._normalize_name(
            "Greninja ex"
        )
        == "greninjaex"
    )


def test_normalize_name_handles_symbols() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._normalize_name(
            "甲贺忍蛙：ex"
        )
        == "甲贺忍蛙ex"
    )


def test_split_collector_number() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._split_collector_number(
            "084/204"
        )
        == (
            "84",
            "204",
        )
    )


def test_split_collector_number_without_total() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._split_collector_number(
            "007"
        )
        == (
            "7",
            None,
        )
    )


def test_image_url_adds_high_webp() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._image_url({
            "image": "https://example.com/card"
        })
        == "https://example.com/card/high.webp"
    )


def test_image_url_preserves_existing_extension() -> None:
    assert (
        SimplifiedChineseProxyCatalogService._image_url({
            "image": "https://example.com/card.png"
        })
        == "https://example.com/card.png"
    )


def test_card_total_uses_total() -> None:
    card = {
        "set": {
            "cardCount": {
                "total": 204,
                "official": 180,
            }
        }
    }

    assert (
        SimplifiedChineseProxyCatalogService._card_total(
            card
        )
        == "204"
    )


def test_card_total_falls_back_to_official() -> None:
    card = {
        "set": {
            "cardCount": {
                "official": 180,
            }
        }
    }

    assert (
        SimplifiedChineseProxyCatalogService._card_total(
            card
        )
        == "180"
    )


def test_initialize_registry(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    result = service.initialize_registry()

    assert result["ok"]
    assert result["created"]
    assert service.registry_path.exists()

    payload = json.loads(
        service.registry_path.read_text(
            encoding="utf-8"
        )
    )

    assert (
        payload["format"]
        == (
            "RareIQ Simplified Chinese "
            "Proxy Registry v1"
        )
    )

    assert len(
        payload["records"]
    ) == 1


def test_initialize_registry_does_not_overwrite(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    first = service.initialize_registry()
    second = service.initialize_registry()

    assert first["created"]
    assert not second["created"]


def test_load_registry(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    service.initialize_registry()

    records = service.load_registry()

    assert len(records) == 1

    assert (
        records[0]["id"]
        == "CSV7C-084"
    )


def test_candidate_score_matching_card() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidate = {
        "localId": "084",
        "name": "Greninja",
        "set": {
            "id": "set-a",
            "cardCount": {
                "total": 204,
            },
        },
    }

    score = (
        SimplifiedChineseProxyCatalogService._candidate_score(
            registry=registry,
            candidate=candidate,
            language_code="en",
        )
    )

    assert score >= 0.9


def test_candidate_score_rejects_wrong_local_number() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidate = {
        "localId": "085",
        "name": "Greninja",
        "set": {
            "id": "set-a",
            "cardCount": {
                "total": 204,
            },
        },
    }

    score = (
        SimplifiedChineseProxyCatalogService._candidate_score(
            registry=registry,
            candidate=candidate,
            language_code="en",
        )
    )

    assert score == 0.0


def test_candidate_score_rewards_allowed_set() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [
                "allowed-set"
            ],
        },
    }

    candidate = {
        "localId": "084",
        "name": "Greninja",
        "set": {
            "id": "allowed-set",
            "cardCount": {
                "total": 204,
            },
        },
    }

    score = (
        SimplifiedChineseProxyCatalogService._candidate_score(
            registry=registry,
            candidate=candidate,
            language_code="en",
        )
    )

    assert score == 1.0


def test_choose_best_candidate() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "wrong",
            "localId": "084",
            "name": "Pikachu",
            "set": {
                "id": "set-one",
                "cardCount": {
                    "total": 100,
                },
            },
        },
        {
            "id": "right",
            "localId": "084",
            "name": "Greninja",
            "set": {
                "id": "set-two",
                "cardCount": {
                    "total": 204,
                },
            },
        },
    ]

    candidate, score = (
        SimplifiedChineseProxyCatalogService.choose_best_candidate(
            registry=registry,
            candidates=candidates,
            language_code="en",
        )
    )

    assert candidate is not None

    assert (
        candidate["id"]
        == "right"
    )

    assert score >= 0.9


def test_choose_best_candidate_rejects_low_score() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [
                "required-set"
            ],
        },
    }

    candidates = [
        {
            "id": "wrong",
            "localId": "084",
            "name": "Pikachu",
            "set": {
                "id": "wrong-set",
                "cardCount": {
                    "total": 100,
                },
            },
        },
    ]

    candidate, score = (
        SimplifiedChineseProxyCatalogService.choose_best_candidate(
            registry=registry,
            candidates=candidates,
            language_code="en",
        )
    )

    assert candidate is None
    assert score < 0.55
