from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.card_scan_importer_service import (
    CardScanImporterService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and import full-card "
            "reference scans into RareIQ."
        )
    )

    parser.add_argument(
        "source",
        type=Path,
    )

    parser.add_argument(
        "--language",
        default="Simplified Chinese",
    )

    parser.add_argument(
        "--language-code",
        default="zh-cn",
    )

    parser.add_argument(
        "--set-id",
        default=None,
    )

    parser.add_argument(
        "--set-name",
        default=None,
    )

    parser.add_argument(
        "--move",
        action="store_true",
    )

    parser.add_argument(
        "--no-normalize",
        action="store_true",
    )

    args = parser.parse_args()

    project_root = Path(
        __file__
    ).resolve().parents[1]

    service = CardScanImporterService(
        project_root=project_root,
    )

    result = service.import_directory(
        args.source,
        language=args.language,
        language_code=args.language_code,
        set_id=args.set_id,
        set_name=args.set_name,
        move_files=args.move,
        normalize=(
            not args.no_normalize
        ),
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

    return (
        0
        if result.get(
            "ok"
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
