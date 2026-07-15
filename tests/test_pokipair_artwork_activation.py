from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from rareiq.services.artwork_index_service import (
    ArtworkIndexService,
)
from tools.activate_pokipair_artwork_index import (
    activate,
)


def test_activation_builds_runtime_fingerprints(
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

    image_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    image = np.full(
        (
            700,
            500,
            3,
        ),
        120,
        dtype=np.uint8,
    )

    assert cv2.imwrite(
        str(
            image_path
        ),
        image,
    )

    source_path = (
        tmp_path
        / "catalog_master"
        / "recognition"
        / "pokipair_visual_index.json"
    )

    source_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_path.write_text(
        json.dumps({
            "references": [
                {
                    "id": "card-1",
                    "set_id": "CSV7",
                    "set_name": "Blade Awakened",
                    "language": "zh-cn",
                    "image_path": str(
                        image_path.relative_to(
                            tmp_path
                        )
                    ),
                }
            ]
        }),
        encoding="utf-8",
    )

    destination = (
        tmp_path
        / "rareiq"
        / "data"
        / "artwork_index.json"
    )

    report = activate(
        project_root=tmp_path,
        source_path=source_path,
        destination_path=destination,
    )

    assert report[
        "record_count"
    ] == 1

    payload = json.loads(
        destination.read_text(
            encoding="utf-8"
        )
    )

    assert len(
        payload["records"]
    ) == 1

    assert isinstance(
        payload["records"][0][
            "fingerprint"
        ],
        str,
    )


def test_service_loads_activated_index(
    tmp_path: Path,
) -> None:
    index_path = (
        tmp_path
        / "artwork_index.json"
    )

    index_path.write_text(
        json.dumps({
            "records": [
                {
                    "id": "card-1",
                    "name": "Test",
                    "fingerprint": "0" * 16,
                    "image_path": "card.webp",
                }
            ]
        }),
        encoding="utf-8",
    )

    service = ArtworkIndexService(
        index_path=index_path
    )

    assert service.status()[
        "record_count"
    ] == 1
