from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from rareiq.services.card_scan_importer_service import (
    CardScanImporterService,
)


def make_service(
    tmp_path: Path,
) -> CardScanImporterService:
    return CardScanImporterService(
        project_root=tmp_path,
    )


def write_test_image(
    path: Path,
    image: np.ndarray,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    assert cv2.imwrite(
        str(path),
        image,
    )


def make_card_image() -> np.ndarray:
    return np.random.default_rng(
        42
    ).integers(
        0,
        256,
        size=(
            900,
            640,
            3,
        ),
        dtype=np.uint8,
    )


def test_supported_extension(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    path = (
        tmp_path
        / "card.webp"
    )

    path.write_bytes(
        b"test"
    )

    assert service._is_supported(
        path
    )


def test_rejects_unsupported_extension(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    path = (
        tmp_path
        / "card.txt"
    )

    path.write_text(
        "test",
        encoding="utf-8",
    )

    assert not service._is_supported(
        path
    )


def test_ratio_score_prefers_card_ratio(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert service._ratio_score(
        2.5 / 3.5
    ) > service._ratio_score(
        1.0
    )


def test_rejects_landscape_promo(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    image = np.random.default_rng(
        7
    ).integers(
        0,
        256,
        size=(
            500,
            1200,
            3,
        ),
        dtype=np.uint8,
    )

    path = (
        tmp_path
        / "banner.jpg"
    )

    write_test_image(
        path,
        image,
    )

    result = service.validate_image(
        path
    )

    assert not result.accepted

    assert (
        "landscape_or_square"
        in result.reasons
    )


def test_rejects_tiny_thumbnail(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    image = np.random.default_rng(
        9
    ).integers(
        0,
        256,
        size=(
            250,
            180,
            3,
        ),
        dtype=np.uint8,
    )

    path = (
        tmp_path
        / "tiny.jpg"
    )

    write_test_image(
        path,
        image,
    )

    result = service.validate_image(
        path
    )

    assert not result.accepted

    assert (
        "width_too_small"
        in result.reasons
    )

    assert (
        "height_too_small"
        in result.reasons
    )


def test_accepts_synthetic_card(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    path = (
        tmp_path
        / "card.jpg"
    )

    write_test_image(
        path,
        make_card_image(),
    )

    result = service.validate_image(
        path
    )

    assert result.accepted
    assert result.width == 640
    assert result.height == 900


def test_normalizes_card_to_500_by_700(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    source = (
        tmp_path
        / "source.jpg"
    )

    output = (
        tmp_path
        / "normalized.webp"
    )

    write_test_image(
        source,
        make_card_image(),
    )

    assert service.normalize_card_image(
        source,
        output,
    )

    image = cv2.imread(
        str(
            output
        )
    )

    assert image is not None

    height, width = image.shape[:2]

    assert width == 500
    assert height == 700


def test_discovers_supported_files_only(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    source = (
        tmp_path
        / "input"
    )

    source.mkdir()

    write_test_image(
        source
        / "one.jpg",
        make_card_image(),
    )

    (
        source
        / "ignore.txt"
    ).write_text(
        "ignore",
        encoding="utf-8",
    )

    files = service.discover_files(
        source
    )

    assert len(files) == 1

    assert (
        files[0].name
        == "one.jpg"
    )


def test_imports_valid_card(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    source = (
        tmp_path
        / "input"
    )

    source.mkdir()

    write_test_image(
        source
        / "greninja.jpg",
        make_card_image(),
    )

    result = service.import_directory(
        source,
        set_id="TEST1",
        set_name="Test Set",
    )

    assert result["ok"]

    assert (
        result[
            "manifest"
        ][
            "files_accepted"
        ]
        == 1
    )

    assert (
        result[
            "manifest"
        ][
            "files_rejected"
        ]
        == 0
    )

    assert service.catalog_path.exists()


def test_imports_rejected_banner(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    source = (
        tmp_path
        / "input"
    )

    source.mkdir()

    banner = np.random.default_rng(
        33
    ).integers(
        0,
        256,
        size=(
            400,
            1200,
            3,
        ),
        dtype=np.uint8,
    )

    write_test_image(
        source
        / "promotion.jpg",
        banner,
    )

    result = service.import_directory(
        source
    )

    assert result["ok"]

    assert (
        result[
            "manifest"
        ][
            "files_accepted"
        ]
        == 0
    )

    assert (
        result[
            "manifest"
        ][
            "files_rejected"
        ]
        == 1
    )


def test_duplicate_is_not_imported_twice(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    source = (
        tmp_path
        / "input"
    )

    source.mkdir()

    write_test_image(
        source
        / "one.jpg",
        make_card_image(),
    )

    first = service.import_directory(
        source
    )

    assert first["ok"]

    second = service.import_directory(
        source
    )

    assert second["ok"]

    assert (
        second[
            "manifest"
        ][
            "files_duplicate"
        ]
        == 1
    )


def test_safe_filename(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._safe_filename(
            "CSV7C/card:084?"
        )
        == "CSV7C_card_084"
    )
