
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.pokemon_china_collector_service import (
    PokemonChinaCollectorService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect official Pokémon China TCG articles "
            "and locally archive their images."
        )
    )

    parser.add_argument(
        "--pages",
        type=int,
        default=2,
        help=(
            "Number of archive pages to scan. "
            "Defaults to a safe two-page probe."
        ),
    )

    parser.add_argument(
        "--article-limit",
        type=int,
        default=None,
        help=(
            "Optional maximum number of discovered "
            "articles to process."
        ),
    )

    args = parser.parse_args()

    project_root = Path(
        __file__
    ).resolve().parents[1]

    service = PokemonChinaCollectorService(
        project_root=project_root,
    )

    result = service.build(
        pages=max(
            1,
            int(args.pages),
        ),
        article_limit=args.article_limit,
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
