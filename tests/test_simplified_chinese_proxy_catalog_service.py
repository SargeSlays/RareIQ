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

    assert len(
        payload["records"]
    ) == 1


def test_load_registry(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    service.initialize_registry()

    records = service.load_registry()

    assert len(records) == 1
    assert records[0]["id"] == "CSV7C-084"


def test_candidate_score_uses_name_first() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidate = {
        "localId": "106",
        "name": "Greninja",
        "set": {
            "id": "different-set",
            "cardCount": {
                "total": 167,
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

    assert score >= 0.55


def test_candidate_score_rejects_wrong_name() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidate = {
        "localId": "084",
        "name": "Pikachu",
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


def test_candidate_score_rewards_metadata() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "rarity": "Illustration Rare",
        "hp": "170",
        "category": "Pokémon",
        "illustrator": "Test Artist",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidate = {
        "localId": "106",
        "name": "Greninja",
        "rarity": "Illustration Rare",
        "hp": "170",
        "category": "Pokémon",
        "illustrator": "Test Artist",
        "set": {
            "id": "set-a",
            "cardCount": {
                "total": 167,
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

    assert score > 0.75


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
        "localId": "106",
        "name": "Greninja",
        "set": {
            "id": "allowed-set",
            "cardCount": {
                "total": 167,
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

    assert score >= 0.75


def test_choose_best_candidate_prefers_name_match() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "wrong-number-right-name",
            "localId": "106",
            "name": "Greninja",
            "set": {
                "id": "set-one",
                "cardCount": {
                    "total": 167,
                },
            },
        },
        {
            "id": "right-number-wrong-name",
            "localId": "084",
            "name": "Pikachu",
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
    assert candidate["id"] == "wrong-number-right-name"
    assert score >= 0.55


def test_choose_best_candidate_prefers_metadata_match() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "rarity": "Rare",
        "hp": "170",
        "illustrator": "Artist A",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "weak",
            "localId": "106",
            "name": "Greninja",
            "rarity": "Common",
            "hp": "120",
            "illustrator": "Artist B",
            "set": {
                "id": "set-one",
                "cardCount": {
                    "total": 167,
                },
            },
        },
        {
            "id": "strong",
            "localId": "090",
            "name": "Greninja",
            "rarity": "Rare",
            "hp": "170",
            "illustrator": "Artist A",
            "set": {
                "id": "set-two",
                "cardCount": {
                    "total": 66,
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
    assert candidate["id"] == "strong"
    assert score > 0.75


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

    assert candidate is None
    assert score < 0.55
