from __future__ import annotations

import numpy as np

from rareiq.services.pokipair_import_service import (
    PokiPairImportService,
)


def make_image(
    width: int = 500,
    height: int = 700,
) -> np.ndarray:
    return np.full(
        (
            height,
            width,
            3,
        ),
        127,
        dtype=np.uint8,
    )


def test_extracts_lazy_images() -> None:
    html = """
    <main>
        <img
            data-src="/uploads/card-a.webp"
            alt="001/100"
        >
        <img
            srcset="
                /uploads/card-b-300x420.webp 300w,
                /uploads/card-b.webp 1000w
            "
        >
    </main>
    """

    images = (
        PokiPairImportService
        .extract_images(
            html,
            "https://www.pokipair.com/test/",
        )
    )

    assert len(
        images
    ) == 2

    assert images[1][
        "url"
    ].endswith(
        "card-b.webp"
    )


def test_canonical_url() -> None:
    value = (
        PokiPairImportService
        .canonical_url(
            (
                "https://x.com/"
                "card-300x420.webp"
            )
        )
    )

    assert value.endswith(
        "card.webp"
    )


def test_card_classification() -> None:
    category, _ = (
        PokiPairImportService
        .classify(
            make_image(),
            "084/204 Greninja",
            "https://x/card.webp",
        )
    )

    assert category == "cards"


def test_pack_classification() -> None:
    category, _ = (
        PokiPairImportService
        .classify(
            make_image(),
            "CSV7 booster pack",
            "https://x/pack.webp",
        )
    )

    assert category == "products"


def test_collector_number() -> None:
    number = (
        PokiPairImportService
        .collector_number(
            "Greninja 084/204"
        )
    )

    assert number == "084/204"
