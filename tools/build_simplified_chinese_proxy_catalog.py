from __future__ import annotations

import argparse
import json
from pathlib import Path

from rareiq.services.simplified_chinese_proxy_catalog_service import (
    SimplifiedChineseProxyCatalogService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the RareIQ Simplified Chinese "
            "cross-language proxy catalog."
        )
    )

    parser.add_argument(
        "--init-registry",
        action="store_true",
        help=(
            "Create the starter Simplified Chinese "
            "registry file."
        ),
    )

    parser.add_argument(
        "--overwrite-registry",
        action="store_true",
        help=(
            "Replace the existing registry with "
            "a fresh starter template."
        ),
    )

    parser.add_argument(
        "--build",
        action="store_true",
        help=(
            "Build proxy matches and download "
            "reference images."
        ),
    )

    args = parser.parse_args()

    project_root = Path(
        __file__
    ).resolve().parents[1]

    service = SimplifiedChineseProxyCatalogService(
        project_root=project_root,
    )

    if args.init_registry:
        result = service.initialize_registry(
            overwrite=args.overwrite_registry,
        )

    elif args.build:
        result = service.build()

    else:
        result = {
            "ok": True,
            "status": service.status(),
            "registry_path": str(
                service.registry_path
            ),
            "catalog_path": str(
                service.catalog_path
            ),
            "manifest_path": str(
                service.manifest_path
            ),
        }

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
