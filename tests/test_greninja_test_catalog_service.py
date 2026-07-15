
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from rareiq.services.greninja_test_catalog_service import (
    GreninjaTestCatalogService,
)


def make_service(
    tmp_path: Path,
) -> GreninjaTestCatalogService:
    return GreninjaTestCatalogService(
        project_root=tmp_path,
    )


def test_matches_english_greninja(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert service._matches_target(
        "Greninja ex"
    )


def test_matches_traditional_chinese_greninja(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert service._matches_target(
        "甲賀忍蛙"
    )


def test_matches_simplified_chinese_greninja(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert service._matches_target(
        "甲贺忍蛙"
    )


def test_matches_froakie_family(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert service._matches_target(
        "Froakie"
    )

    assert service._matches_target(
        "Frogadier"
    )

    assert service._matches_target(
        "呱呱泡蛙"
    )


def test_rejects_unrelated_card(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert not service._matches_target(
        "Pikachu ex"
    )


def test_safe_name_removes_invalid_characters(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert (
        service._safe_name(
            "zh-tw/test:card?"
        )
        == "zh-tw_test_card"
    )


def test_collector_number_uses_set_total(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    card = {
        "localId": "084",
    }

    set_payload = {
        "cardCount": {
            "total": 204,
        },
    }

    assert (
        service._collector_number(
            card,
            set_payload,
        )
        == "084/204"
    )


def test_image_url_adds_high_webp(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert (
        service._image_url({
            "image": "https://example.com/card"
        })
        == "https://example.com/card/high.webp"
    )


def test_image_url_preserves_file_extension(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    assert (
        service._image_url({
            "image": "https://example.com/card.png"
        })
        == "https://example.com/card.png"
    )


def test_verify_valid_image(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    image_path = tmp_path / "card.webp"

    rng = np.random.default_rng(42)

    image = rng.integers(
        0,
        256,
        size=(700, 500, 3),
        dtype=np.uint8,
    )

    assert cv2.imwrite(
        str(image_path),
        image,
    )

    valid, reason = service._verify_image(
        image_path
    )

    assert valid
    assert reason is None


def test_verify_missing_image(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)

    valid, reason = service._verify_image(
        tmp_path / "missing.webp"
    )

    assert not valid
    assert reason == "missing"


def test_manifest_loads_existing_catalog(
    tmp_path: Path,
) -> None:
    root = (
        tmp_path
        / "catalog_master"
        / "greninja_test"
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "cards": 14,
        "images": 13,
        "coverage_percent": 92.86,
        "built_at": 1234.0,
    }

    (
        root / "manifest.json"
    ).write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    service = make_service(tmp_path)
    status = service.status()

    assert status["phase"] == "READY"
    assert status["greninja_cards"] == 14
    assert status["images_downloaded"] == 13
    assert status["coverage_percent"] == 92.86
