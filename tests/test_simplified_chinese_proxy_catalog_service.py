from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from rareiq.services.simplified_chinese_proxy_catalog_service import (
    SimplifiedChineseProxyCatalogService,
)


def make_service(
    tmp_path: Path,
) -> SimplifiedChineseProxyCatalogService:
    return SimplifiedChineseProxyCatalogService(
        project_root=tmp_path,
    )


def make_image(
    seed: int,
) -> np.ndarray:
    return np.random.default_rng(
        seed
    ).integers(
        0,
        256,
        size=(
            700,
            500,
            3,
        ),
        dtype=np.uint8,
    )


def save_image(
    path: Path,
    image: np.ndarray,
) -> None:
    assert cv2.imwrite(
        str(
            path
        ),
        image,
    )


def test_name_only_match_is_rejected() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "det1-9",
            "localId": "9",
            "name": "Greninja",
            "rarity": "Ultra Rare",
            "set": {
                "id": "det1",
                "cardCount": {
                    "total": 18,
                },
            },
        }
    ]

    candidate, score = (
        SimplifiedChineseProxyCatalogService
        .choose_best_candidate(
            registry=registry,
            candidates=candidates,
            language_code="en",
        )
    )

    assert candidate is None
    assert score < 0.82


def test_strong_metadata_match_is_allowed() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "rarity": "Illustration Rare",
        "hp": "170",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "good",
            "localId": "106",
            "name": "Greninja",
            "rarity": "Illustration Rare",
            "hp": "170",
            "set": {
                "id": "set-a",
                "cardCount": {
                    "total": 167,
                },
            },
        }
    ]

    candidate, score = (
        SimplifiedChineseProxyCatalogService
        .choose_best_candidate(
            registry=registry,
            candidates=candidates,
            language_code="en",
        )
    )

    assert candidate is not None
    assert candidate["id"] == "good"
    assert score >= 0.70


def test_close_candidates_are_ambiguous() -> None:
    registry = {
        "collector_number": "084/204",
        "english_name": "Greninja",
        "rarity": "Rare",
        "hp": "170",
        "proxy_set_ids": {
            "en": [],
        },
    }

    candidates = [
        {
            "id": "first",
            "localId": "106",
            "name": "Greninja",
            "rarity": "Rare",
            "hp": "170",
            "set": {
                "id": "set-a",
                "cardCount": {
                    "total": 167,
                },
            },
        },
        {
            "id": "second",
            "localId": "107",
            "name": "Greninja",
            "rarity": "Rare",
            "hp": "170",
            "set": {
                "id": "set-b",
                "cardCount": {
                    "total": 168,
                },
            },
        },
    ]

    candidate, score = (
        SimplifiedChineseProxyCatalogService
        .choose_best_candidate(
            registry=registry,
            candidates=candidates,
            language_code="en",
        )
    )

    assert candidate is None
    assert score >= 0.70


def test_identical_images_match(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"

    image = make_image(
        42
    )

    save_image(
        first,
        image,
    )

    save_image(
        second,
        image,
    )

    similarity = (
        SimplifiedChineseProxyCatalogService
        ._visual_similarity(
            first,
            second,
        )
    )

    assert similarity > 0.99


def test_different_images_do_not_match(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"

    save_image(
        first,
        make_image(
            42
        ),
    )

    save_image(
        second,
        make_image(
            99
        ),
    )

    similarity = (
        SimplifiedChineseProxyCatalogService
        ._visual_similarity(
            first,
            second,
        )
    )

    assert similarity < 0.90


def test_visual_anchor_selects_correct_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = make_service(
        tmp_path
    )

    anchor = tmp_path / "anchor.jpg"
    correct = tmp_path / "correct.jpg"
    wrong = tmp_path / "wrong.jpg"

    anchor_image = make_image(
        42
    )

    save_image(
        anchor,
        anchor_image,
    )

    save_image(
        correct,
        anchor_image,
    )

    save_image(
        wrong,
        make_image(
            99
        ),
    )

    candidates = [
        {
            "id": "wrong",
            "name": "Greninja",
        },
        {
            "id": "correct",
            "name": "Greninja",
        },
    ]

    paths = {
        "wrong": wrong,
        "correct": correct,
    }

    def fake_download(
        *,
        client,
        registry_id,
        language_code,
        card,
    ):
        return {
            "card": card,
            "download": {
                "ok": True,
                "state": "existing",
                "path": str(
                    paths[
                        card["id"]
                    ]
                ),
            },
        }

    monkeypatch.setattr(
        service,
        "_download_candidate_for_comparison",
        fake_download,
    )

    candidate, score, result = (
        service._choose_by_visual_anchor(
            client=None,
            registry={
                "exact_zh_cn_image": str(
                    anchor
                ),
            },
            registry_id="CSV7C-084",
            language_code="en",
            candidates=candidates,
        )
    )

    assert candidate is not None
    assert candidate["id"] == "correct"
    assert score > 0.99
    assert result["path"] == str(
        correct
    )
