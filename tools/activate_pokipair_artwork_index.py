from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import cv2

from rareiq.services.artwork_index_service import ArtworkIndexService


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def write_json_atomic(
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    handle, temporary_name = tempfile.mkstemp(
        prefix=path.stem + "_",
        suffix=".tmp",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(
            handle,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as stream:
            json.dump(
                payload,
                stream,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temporary_name,
            path,
        )

    except Exception:
        try:
            os.unlink(
                temporary_name
            )
        except OSError:
            pass
        raise


def resolve_image_path(
    project_root: Path,
    value: str,
) -> Path:
    path = Path(
        value
    )

    if path.is_absolute():
        return path

    return (
        project_root
        / path
    ).resolve()


def activate(
    *,
    project_root: Path,
    source_path: Path,
    destination_path: Path,
) -> dict[str, Any]:
    payload = read_json(
        source_path
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            "The PokiPair visual index must be a JSON object."
        )

    references = payload.get(
        "references",
        []
    )

    if not isinstance(
        references,
        list,
    ):
        raise RuntimeError(
            "The PokiPair visual index has no references list."
        )

    started = time.perf_counter()

    records: list[
        dict[str, Any]
    ] = []

    skipped: list[
        dict[str, Any]
    ] = []

    for index, reference in enumerate(
        references,
        start=1,
    ):
        if not isinstance(
            reference,
            dict,
        ):
            skipped.append({
                "position": index,
                "reason": "reference_not_object",
            })
            continue

        image_value = (
            reference.get(
                "image_path"
            )
            or reference.get(
                "reference_image"
            )
        )

        if not image_value:
            skipped.append({
                "position": index,
                "id": reference.get("id"),
                "reason": "missing_image_path",
            })
            continue

        image_path = resolve_image_path(
            project_root,
            str(
                image_value
            ),
        )

        if not image_path.exists():
            skipped.append({
                "position": index,
                "id": reference.get("id"),
                "reason": "missing_file",
                "image_path": str(image_path),
            })
            continue

        image = cv2.imread(
            str(
                image_path
            )
        )

        if image is None:
            skipped.append({
                "position": index,
                "id": reference.get("id"),
                "reason": "decode_failed",
                "image_path": str(image_path),
            })
            continue

        card_id = str(
            reference.get(
                "card_id"
            )
            or reference.get(
                "id"
            )
            or image_path.stem
        )

        records.append({
            "id": card_id,
            "name": (
                reference.get(
                    "name"
                )
                or card_id
            ),
            "printed_name": reference.get(
                "printed_name"
            ),
            "collector_number": reference.get(
                "collector_number"
            ),
            "language": (
                reference.get(
                    "language"
                )
                or "zh-cn"
            ),
            "set_name": reference.get(
                "set_name"
            ),
            "set_id": reference.get(
                "set_id"
            ),
            "rarity": reference.get(
                "rarity"
            ),
            "image_path": str(
                image_path
            ),
            "fingerprint": (
                ArtworkIndexService
                .fingerprint(
                    image
                )
            ),
            "source": (
                reference.get(
                    "source"
                )
                or "pokipair"
            ),
            "source_url": reference.get(
                "source_url"
            ),
        })

        if (
            index % 250
        ) == 0:
            print(
                f"Processed {index}/"
                f"{len(references)} references..."
            )

    runtime_payload = {
        "version": 3,
        "source": "pokipair_visual_index",
        "source_path": str(
            source_path
        ),
        "generated_at": time.time(),
        "records": records,
    }

    write_json_atomic(
        destination_path,
        runtime_payload,
    )

    report = {
        "ok": True,
        "source_reference_count": len(
            references
        ),
        "record_count": len(
            records
        ),
        "skipped_count": len(
            skipped
        ),
        "latency_ms": round(
            (
                time.perf_counter()
                - started
            )
            * 1000,
            1,
        ),
        "source_path": str(
            source_path
        ),
        "destination_path": str(
            destination_path
        ),
        "skipped": skipped,
    }

    report_path = (
        destination_path.parent
        / "pokipair_artwork_activation_report.json"
    )

    write_json_atomic(
        report_path,
        report,
    )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Activate the PokiPair visual catalog "
            "as RareIQ's runtime artwork index."
        )
    )

    parser.add_argument(
        "--source",
        type=Path,
        default=None,
    )

    parser.add_argument(
        "--destination",
        type=Path,
        default=None,
    )

    args = parser.parse_args()

    project_root = Path(
        __file__
    ).resolve().parents[1]

    source_path = (
        args.source.resolve()
        if args.source
        else (
            project_root
            / "catalog_master"
            / "recognition"
            / "pokipair_visual_index.json"
        )
    )

    destination_path = (
        args.destination.resolve()
        if args.destination
        else (
            project_root
            / "rareiq"
            / "data"
            / "artwork_index.json"
        )
    )

    if not source_path.exists():
        raise SystemExit(
            "Missing PokiPair visual index: "
            f"{source_path}"
        )

    report = activate(
        project_root=project_root,
        source_path=source_path,
        destination_path=destination_path,
    )

    print()
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    if report[
        "record_count"
    ] == 0:
        raise SystemExit(
            "No artwork references were activated."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
