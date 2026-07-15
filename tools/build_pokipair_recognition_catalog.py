from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.pokipair_recognition_catalog_service import (
    PokiPairRecognitionCatalogService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build RareIQ recognition records "
            "from the imported PokiPair card library."
        )
    )

    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help=(
            "Include Gem Pack Vol 2 and Vol 3."
        ),
    )

    parser.add_argument(
        "--no-master-merge",
        action="store_true",
        help=(
            "Build standalone recognition files "
            "without modifying master_cards.json."
        ),
    )

    args = parser.parse_args()

    project_root = Path(
        __file__
    ).resolve().parents[1]

    service = (
        PokiPairRecognitionCatalogService(
            project_root=project_root
        )
    )

    report = service.build(
        include_incomplete=(
            args.include_incomplete
        ),
        merge_master=(
            not args.no_master_merge
        ),
    )

    print()
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
