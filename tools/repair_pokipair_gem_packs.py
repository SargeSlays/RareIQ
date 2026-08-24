from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import cv2

from rareiq.services.pokipair_import_service import (
    PokiPairImportService,
)


GEM_PACK_IDS = (
    "GEM_PACK_VOL_1",
    "GEM_PACK_VOL_2",
    "GEM_PACK_VOL_3",
    "GEM_PACK_VOL_4",
    "GEM_PACK_VOL_5",
)


def read_json(
    path: Path,
    default: Any,
) -> Any:
    if not path.exists():
        return default

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def write_json(
    path: Path,
    payload: Any,
) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def unique_path(
    destination: Path,
) -> Path:
    if not destination.exists():
        return destination

    counter = 2

    while True:
        candidate = (
            destination.parent
            / (
                f"{destination.stem}_"
                f"{counter}"
                f"{destination.suffix}"
            )
        )

        if not candidate.exists():
            return candidate

        counter += 1


def repair_set(
    project_root: Path,
    set_id: str,
) -> dict[str, int]:
    root = (
        project_root
        / "catalog_master"
        / "pokipair"
        / "sets"
        / set_id
    )

    cards_dir = root / "cards"
    products_dir = root / "products"

    cards_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    cards_path = root / "cards.json"
    products_path = root / "products.json"
    manifest_path = root / "manifest.json"

    cards = read_json(
        cards_path,
        [],
    )

    products = read_json(
        products_path,
        [],
    )

    manifest = read_json(
        manifest_path,
        {},
    )

    repaired_products = []
    moved = 0
    unreadable = 0

    for record in products:
        relative_path = record.get(
            "local_path"
        )

        if not relative_path:
            repaired_products.append(
                record
            )

            continue

        source = (
            project_root
            / relative_path
        )

        image = cv2.imread(
            str(
                source
            )
        )

        if image is None:
            repaired_products.append(
                record
            )

            unreadable += 1
            continue

        category, reason = (
            PokiPairImportService
            .classify(
                image,
                str(
                    record.get(
                        "label",
                        "",
                    )
                ),
                str(
                    record.get(
                        "source_url",
                        "",
                    )
                ),
            )
        )

        if category != "cards":
            repaired_products.append(
                record
            )

            continue

        destination = unique_path(
            cards_dir
            / source.name
        )

        if source.exists():
            shutil.move(
                str(
                    source
                ),
                str(
                    destination
                ),
            )

        updated = dict(
            record
        )

        updated[
            "category"
        ] = "cards"

        updated[
            "classification_reason"
        ] = reason

        updated[
            "local_path"
        ] = str(
            destination.relative_to(
                project_root
            )
        )

        updated[
            "filename"
        ] = destination.name

        cards.append(
            updated
        )

        moved += 1

    write_json(
        cards_path,
        cards,
    )

    write_json(
        products_path,
        repaired_products,
    )

    counts = dict(
        manifest.get(
            "counts",
            {},
        )
    )

    counts[
        "cards"
    ] = len(
        cards
    )

    counts[
        "products"
    ] = len(
        repaired_products
    )

    manifest[
        "counts"
    ] = counts

    write_json(
        manifest_path,
        manifest,
    )

    return {
        "moved_to_cards": moved,
        "cards_after": len(
            cards
        ),
        "products_after": len(
            repaired_products
        ),
        "unreadable": unreadable,
    }


def rebuild_summary(
    project_root: Path,
) -> None:
    root = (
        project_root
        / "catalog_master"
        / "pokipair"
    )

    summary_path = (
        root
        / "import_summary.json"
    )

    summary = read_json(
        summary_path,
        {},
    )

    manifests = []

    for path in sorted(
        root.glob(
            "sets/*/manifest.json"
        )
    ):
        manifests.append(
            read_json(
                path,
                {},
            )
        )

    for path in sorted(
        root.glob(
            "collections/*/manifest.json"
        )
    ):
        manifests.append(
            read_json(
                path,
                {},
            )
        )

    summary[
        "target_count"
    ] = len(
        manifests
    )

    summary[
        "totals"
    ] = {
        key: sum(
            int(
                manifest.get(
                    "counts",
                    {},
                ).get(
                    key,
                    0,
                )
            )
            for manifest in manifests
        )
        for key in (
            "cards",
            "products",
            "rejected",
            "duplicates",
            "failed",
        )
    }

    summary[
        "manifests"
    ] = manifests

    write_json(
        summary_path,
        summary,
    )


def main() -> int:
    project_root = Path(
        __file__
    ).resolve().parents[1]

    total_moved = 0

    for set_id in GEM_PACK_IDS:
        result = repair_set(
            project_root,
            set_id,
        )

        total_moved += result[
            "moved_to_cards"
        ]

        print()
        print(
            set_id
        )

        print(
            json.dumps(
                result,
                indent=2,
            )
        )

    rebuild_summary(
        project_root
    )

    print()
    print(
        f"Total images moved to cards: "
        f"{total_moved}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
