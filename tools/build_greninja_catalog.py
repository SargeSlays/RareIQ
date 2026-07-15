
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.greninja_test_catalog_service import (
    GreninjaTestCatalogService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the RareIQ focused Greninja test catalog."
        )
    )

    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Discover available sets without downloading card images.",
    )

    parser.add_argument(
        "--max-sets",
        type=int,
        default=None,
        help="Optional limit for testing the catalog builder.",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]

    service = GreninjaTestCatalogService(
        project_root=project_root,
    )

    if args.discover_only:
        discovered = service.discover_sets()

        print()
        print("Greninja catalog discovery complete")
        print(f"Sets discovered: {len(discovered)}")
        print()

        for index, item in enumerate(
            discovered,
            start=1,
        ):
            print(
                f"{index:4}. "
                f"{item.get('language')} | "
                f"{item.get('set_id')} | "
                f"{item.get('set_name')} | "
                f"{item.get('card_count') or '?'} cards"
            )

        print()
        print(
            "Discovery file:"
            f" {service.discovery_path}"
        )

        return 0

    result = service.build(
        max_sets=args.max_sets,
    )

    print()
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    print()

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
