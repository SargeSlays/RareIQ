from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from rareiq.services.pokipair_recognition_catalog_service import (
    PokiPairRecognitionCatalogService,
)


def write_json(
    path: Path,
    payload,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_card_image(
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image = np.full(
        (
            700,
            500,
            3,
        ),
        127,
        dtype=np.uint8,
    )

    assert cv2.imwrite(
        str(
            path
        ),
        image,
    )


def create_card(
    *,
    set_id: str,
    local_path: str,
    source_url: str,
) -> dict:
    return {
        "id": (
            f"{set_id}-0001"
        ),
        "set_id": set_id,
        "set_name": set_id,
        "category": "cards",
        "collector_number": "001/100",
        "label": "Test Card 001/100",
        "source_page": "https://example.com/set",
        "source_url": source_url,
        "local_path": local_path,
        "sha256": "abc",
        "perceptual_hash": "def",
    }


def test_collects_valid_card(
    tmp_path: Path,
) -> None:
    image_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards"
        / "card.webp"
    )

    write_card_image(
        image_path
    )

    relative = str(
        image_path.relative_to(
            tmp_path
        )
    )

    cards_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards.json"
    )

    write_json(
        cards_path,
        [
            create_card(
                set_id="CSV7",
                local_path=relative,
                source_url=(
                    "https://example.com/card.webp"
                ),
            )
        ],
    )

    service = (
        PokiPairRecognitionCatalogService(
            project_root=tmp_path
        )
    )

    records, report = (
        service.collect_records()
    )

    assert len(
        records
    ) == 1

    assert report[
        "records_accepted"
    ] == 1

    assert records[0][
        "set_id"
    ] == "CSV7"


def test_incomplete_sets_are_excluded(
    tmp_path: Path,
) -> None:
    image_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "GEM_PACK_VOL_2"
        / "cards"
        / "card.webp"
    )

    write_card_image(
        image_path
    )

    relative = str(
        image_path.relative_to(
            tmp_path
        )
    )

    cards_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "GEM_PACK_VOL_2"
        / "cards.json"
    )

    write_json(
        cards_path,
        [
            create_card(
                set_id="GEM_PACK_VOL_2",
                local_path=relative,
                source_url=(
                    "https://example.com/card.webp"
                ),
            )
        ],
    )

    service = (
        PokiPairRecognitionCatalogService(
            project_root=tmp_path
        )
    )

    records, report = (
        service.collect_records()
    )

    assert records == []

    assert (
        "GEM_PACK_VOL_2"
        in report[
            "excluded_set_ids"
        ]
    )


def test_visual_index_has_one_reference_per_card() -> None:
    records = [
        {
            "id": "card-1",
            "set_id": "CSV7",
            "set_name": "Blade Awakened",
            "collector_number": "001/100",
            "name": "Test",
            "reference_image": "image.webp",
            "perceptual_hash": "abc",
            "sha256": "def",
        }
    ]

    index = (
        PokiPairRecognitionCatalogService
        .build_visual_index(
            records
        )
    )

    assert index[
        "reference_count"
    ] == 1

    assert index[
        "references"
    ][0][
        "image_path"
    ] == "image.webp"


def test_duplicate_record_is_removed(
    tmp_path: Path,
) -> None:
    image_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards"
        / "card.webp"
    )

    write_card_image(
        image_path
    )

    relative = str(
        image_path.relative_to(
            tmp_path
        )
    )

    card = create_card(
        set_id="CSV7",
        local_path=relative,
        source_url=(
            "https://example.com/card.webp"
        ),
    )

    cards_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards.json"
    )

    write_json(
        cards_path,
        [
            card,
            card,
        ],
    )

    service = (
        PokiPairRecognitionCatalogService(
            project_root=tmp_path
        )
    )

    records, report = (
        service.collect_records()
    )

    assert len(
        records
    ) == 1

    assert report[
        "duplicates_removed"
    ] == 1


def test_build_writes_catalog_and_index(
    tmp_path: Path,
) -> None:
    image_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards"
        / "card.webp"
    )

    write_card_image(
        image_path
    )

    relative = str(
        image_path.relative_to(
            tmp_path
        )
    )

    cards_path = (
        tmp_path
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV7"
        / "cards.json"
    )

    write_json(
        cards_path,
        [
            create_card(
                set_id="CSV7",
                local_path=relative,
                source_url=(
                    "https://example.com/card.webp"
                ),
            )
        ],
    )

    service = (
        PokiPairRecognitionCatalogService(
            project_root=tmp_path
        )
    )

    report = service.build(
        merge_master=False
    )

    assert report[
        "record_count"
    ] == 1

    assert (
        service.catalog_path.exists()
    )

    assert (
        service.visual_index_path.exists()
    )
