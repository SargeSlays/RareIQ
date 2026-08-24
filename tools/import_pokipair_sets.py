from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.pokipair_import_service import (
    TARGETS,
    PokiPairImportService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import PokiPair Simplified "
            "Chinese Pokemon sets."
        )
    )

    parser.add_argument(
        "--target",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--max-images",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--list",
        action="store_true",
    )

    args = parser.parse_args()

    if args.list:
        for target in TARGETS:
            print(
                f"{target['id']:<20} "
                f"{target['name']}"
            )

        return 0

    project_root = Path(
        __file__
    ).resolve().parents[1]

    service = PokiPairImportService(
        project_root
    )

    summary = service.import_all(
        args.target,
        args.max_images,
    )

    print()
    print(
        json.dumps(
            summary["totals"],
            indent=2,
        )
    )

    print()
    print(
        "Summary:"
    )

    print(
        service.output_root
        / "import_summary.json"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
