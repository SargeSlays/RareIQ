from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import cv2
import httpx
import numpy as np


TARGETS = [
    {
        "id": "CSV4",
        "name": "Reward Round",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "reward-round-csv4-card-list/"
        ),
    },
    {
        "id": "CSV5",
        "name": "Dark Crystal Blaze",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "dark-crystal-blaze-csv5-card-list/"
        ),
    },
    {
        "id": "CSV7",
        "name": "Blade Awakened",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "blade-awakened-csv7-card-list/"
        ),
    },
    {
        "id": "CSV8",
        "name": "Bright Fantasy",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "bright-fantasy-csv8-card-list/"
        ),
    },
    {
        "id": "CSV9_5",
        "name": "Crystal Gathering",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "crystal-gathering-csv95-card-list/"
        ),
    },
    {
        "id": "GEM_PACK_VOL_1",
        "name": "Gem Pack Vol 1",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "gem-pack-volume-one-card-list/"
        ),
    },
    {
        "id": "GEM_PACK_VOL_2",
        "name": "Gem Pack Vol 2",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "gem-pack-vol-2-card-list/"
        ),
    },
    {
        "id": "GEM_PACK_VOL_3",
        "name": "Gem Pack Vol 3",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "gem-pack-vol-3-card-list/"
        ),
    },
    {
        "id": "GEM_PACK_VOL_4",
        "name": "Gem Pack Vol 4",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "gem-pack-vol-4-card-list/"
        ),
    },
    {
        "id": "GEM_PACK_VOL_5",
        "name": "Gem Pack Vol 5",
        "kind": "set",
        "url": (
            "https://www.pokipair.com/"
            "gem-pack-vol-5-card-list/"
        ),
    },
    {
        "id": "EXCLUSIVE_ZH_CN",
        "name": (
            "Exclusive Simplified Chinese "
            "Pokemon Cards"
        ),
        "kind": "collection",
        "url": (
            "https://www.pokipair.com/"
            "exclusive-simplified-chinese-"
            "pokemon-cards/"
        ),
    },
]


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".avif",
}


IGNORE_KEYWORDS = {
    "avatar",
    "cart",
    "emoji",
    "favicon",
    "footer",
    "icon",
    "loading",
    "payment",
    "placeholder",
    "social",
    "spinner",
    "woocommerce-placeholder",
}


PRODUCT_KEYWORDS = {
    "banner",
    "booster",
    "box",
    "bundle",
    "display",
    "gift",
    "jumbo",
    "logo",
    "pack",
    "product",
    "sealed",
}


class PokiPairImageParser(
    HTMLParser
):
    def __init__(
        self,
        base_url: str,
    ) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.base_url = base_url
        self.images = []

    @staticmethod
    def best_srcset(
        value: str,
    ) -> str:
        best_url = ""
        best_width = -1

        for entry in value.split(
            ","
        ):
            parts = entry.strip().split()

            if not parts:
                continue

            url = parts[0]
            width = 0

            if (
                len(
                    parts
                ) > 1
                and parts[1].endswith(
                    "w"
                )
            ):
                try:
                    width = int(
                        parts[1][:-1]
                    )

                except ValueError:
                    width = 0

            if width >= best_width:
                best_width = width
                best_url = url

        return best_url

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        if tag.lower() != "img":
            return

        values = {
            str(
                key
            ).lower(): (
                value
                or ""
            )
            for key, value in attrs
        }

        source = ""

        for key in (
            "data-srcset",
            "srcset",
        ):
            value = values.get(
                key,
                ""
            )

            if value:
                source = self.best_srcset(
                    value
                )

                if source:
                    break

        if not source:
            for key in (
                "data-lazy-src",
                "data-src",
                "data-original",
                "src",
            ):
                source = values.get(
                    key,
                    ""
                ).strip()

                if source:
                    break

        if not source:
            return

        self.images.append(
            {
                "url": urljoin(
                    self.base_url,
                    unescape(
                        source
                    ),
                ),
                "alt": unescape(
                    values.get(
                        "alt",
                        ""
                    )
                ).strip(),
                "title": unescape(
                    values.get(
                        "title",
                        ""
                    )
                ).strip(),
            }
        )


class PokiPairImportService:
    def __init__(
        self,
        project_root: Path,
    ) -> None:
        self.project_root = Path(
            project_root
        ).resolve()

        self.output_root = (
            self.project_root
            / "catalog_master"
            / "pokipair"
        )

    @staticmethod
    def now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def write_json(
        path: Path,
        data: Any,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def canonical_url(
        url: str,
    ) -> str:
        parsed = urlparse(
            url
        )

        path = re.sub(
            (
                r"-\d{2,4}x\d{2,4}"
                r"(?=\.[A-Za-z0-9]+$)"
            ),
            "",
            parsed.path,
        )

        return parsed._replace(
            path=path,
            query="",
            fragment="",
        ).geturl()

    @staticmethod
    def safe_filename(
        value: str,
    ) -> str:
        value = re.sub(
            r"[^\w.-]+",
            "_",
            value,
        )

        value = re.sub(
            r"_+",
            "_",
            value,
        ).strip(
            "._"
        )

        return (
            value[:160]
            or "image"
        )

    @staticmethod
    def decode_image(
        content: bytes,
    ) -> np.ndarray | None:
        image = cv2.imdecode(
            np.frombuffer(
                content,
                dtype=np.uint8,
            ),
            cv2.IMREAD_COLOR,
        )

        if (
            image is None
            or image.size == 0
        ):
            return None

        return image

    @staticmethod
    def image_extension(
        url: str,
        content_type: str,
    ) -> str:
        extension = Path(
            urlparse(
                url
            ).path
        ).suffix.lower()

        if extension in IMAGE_EXTENSIONS:
            if extension == ".jpeg":
                return ".jpg"

            return extension

        guessed = mimetypes.guess_extension(
            content_type.split(
                ";",
                1,
            )[0]
        )

        if guessed in {
            ".jpeg",
            ".jpe",
        }:
            return ".jpg"

        if guessed in IMAGE_EXTENSIONS:
            return guessed

        return ".jpg"

    @staticmethod
    def perceptual_hash(
        image: np.ndarray,
    ) -> str:
        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        small = cv2.resize(
            gray,
            (
                16,
                16,
            ),
            interpolation=cv2.INTER_AREA,
        )

        average = float(
            small.mean()
        )

        bits = (
            small
            >= average
        ).flatten()

        value = 0

        for bit in bits:
            value = (
                value << 1
            ) | int(
                bit
            )

        return f"{value:064x}"

    @staticmethod
    def classify(
        image: np.ndarray,
        label: str,
        url: str,
    ) -> tuple[
        str,
        str,
    ]:
        height, width = image.shape[:2]

        if (
            width < 120
            or height < 120
        ):
            return (
                "rejected",
                "image_too_small",
            )

        searchable = (
            label
            + " "
            + url
        ).lower()

        if any(
            keyword in searchable
            for keyword in PRODUCT_KEYWORDS
        ):
            return (
                "products",
                "product_keyword",
            )

        ratio = (
            width
            / float(
                height
            )
        )

        if (
            0.56
            <= ratio
            <= 0.79
            and height >= 300
        ):
            return (
                "cards",
                "card_aspect_ratio",
            )

        return (
            "products",
            "non_card_aspect_ratio",
        )

    @staticmethod
    def collector_number(
        label: str,
    ) -> str | None:
        match = re.search(
            (
                r"(?<!\d)"
                r"(\d{1,3})"
                r"\s*[/_-]\s*"
                r"(\d{1,3})"
                r"(?!\d)"
            ),
            label,
        )

        if not match:
            return None

        return (
            f"{int(match.group(1)):03d}/"
            f"{int(match.group(2)):03d}"
        )

    @classmethod
    def extract_images(
        cls,
        html: str,
        page_url: str,
    ) -> list[dict[str, str]]:
        parser = PokiPairImageParser(
            page_url
        )

        parser.feed(
            html
        )

        images = {}

        for image in parser.images:
            searchable = (
                image["url"]
                + " "
                + image["alt"]
                + " "
                + image["title"]
            ).lower()

            extension = Path(
                urlparse(
                    image["url"]
                ).path
            ).suffix.lower()

            if (
                extension
                and extension
                not in IMAGE_EXTENSIONS
            ):
                continue

            if any(
                keyword in searchable
                for keyword in IGNORE_KEYWORDS
            ):
                continue

            canonical = cls.canonical_url(
                image["url"]
            )

            image["url"] = canonical

            existing = images.get(
                canonical
            )

            if (
                existing is None
                or len(
                    image["alt"]
                    + image["title"]
                )
                > len(
                    existing["alt"]
                    + existing["title"]
                )
            ):
                images[
                    canonical
                ] = image

        return list(
            images.values()
        )

    def target_directory(
        self,
        target: dict[str, str],
    ) -> Path:
        group = (
            "collections"
            if target["kind"]
            == "collection"
            else "sets"
        )

        return (
            self.output_root
            / group
            / target["id"]
        )

    def import_target(
        self,
        target: dict[str, str],
        client: httpx.Client,
        max_images: int | None,
    ) -> dict[str, Any]:
        root = self.target_directory(
            target
        )

        directories = {
            "cards": root / "cards",
            "products": root / "products",
            "rejected": root / "rejected",
        }

        for directory in directories.values():
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

        response = client.get(
            target["url"]
        )

        response.raise_for_status()

        candidates = self.extract_images(
            response.text,
            target["url"],
        )

        if max_images is not None:
            candidates = candidates[
                :max_images
            ]

        cards = []
        products = []
        rejected = []
        hashes = {}

        counts = {
            "cards": 0,
            "products": 0,
            "rejected": 0,
            "duplicates": 0,
            "failed": 0,
        }

        for index, candidate in enumerate(
            candidates,
            start=1,
        ):
            try:
                time.sleep(
                    0.05
                )

                result = client.get(
                    candidate["url"]
                )

                result.raise_for_status()

                content = result.content

                image = self.decode_image(
                    content
                )

                if image is None:
                    counts["rejected"] += 1

                    rejected.append(
                        {
                            "source_url": (
                                candidate["url"]
                            ),
                            "reason": (
                                "decode_failed"
                            ),
                        }
                    )

                    continue

                digest = hashlib.sha256(
                    content
                ).hexdigest()

                if digest in hashes:
                    counts["duplicates"] += 1

                    rejected.append(
                        {
                            "source_url": (
                                candidate["url"]
                            ),
                            "reason": (
                                "duplicate_content"
                            ),
                            "duplicate_of": (
                                hashes[digest]
                            ),
                        }
                    )

                    continue

                label = " ".join(
                    value
                    for value in (
                        candidate["alt"],
                        candidate["title"],
                        Path(
                            urlparse(
                                candidate["url"]
                            ).path
                        ).stem,
                    )
                    if value
                )

                category, reason = (
                    self.classify(
                        image,
                        label,
                        candidate["url"],
                    )
                )

                extension = (
                    self.image_extension(
                        candidate["url"],
                        result.headers.get(
                            "content-type",
                            "",
                        ),
                    )
                )

                stem = self.safe_filename(
                    Path(
                        urlparse(
                            candidate["url"]
                        ).path
                    ).stem
                )

                filename = (
                    f"{index:04d}_"
                    f"{stem}"
                    f"{extension}"
                )

                destination = (
                    directories[
                        category
                    ]
                    / filename
                )

                destination.write_bytes(
                    content
                )

                relative_path = str(
                    destination.relative_to(
                        self.project_root
                    )
                )

                hashes[
                    digest
                ] = relative_path

                height, width = (
                    image.shape[:2]
                )

                record = {
                    "id": (
                        f"{target['id']}-"
                        f"{index:04d}"
                    ),
                    "set_id": target["id"],
                    "set_name": target["name"],
                    "kind": target["kind"],
                    "category": category,
                    "classification_reason": (
                        reason
                    ),
                    "collector_number": (
                        self.collector_number(
                            label
                        )
                    ),
                    "label": label,
                    "alt": candidate["alt"],
                    "title": candidate["title"],
                    "source_page": target["url"],
                    "source_url": (
                        candidate["url"]
                    ),
                    "local_path": relative_path,
                    "filename": filename,
                    "width": width,
                    "height": height,
                    "aspect_ratio": round(
                        width
                        / float(
                            height
                        ),
                        4,
                    ),
                    "sha256": digest,
                    "perceptual_hash": (
                        self.perceptual_hash(
                            image
                        )
                    ),
                    "downloaded_at": (
                        self.now()
                    ),
                }

                if category == "cards":
                    cards.append(
                        record
                    )

                elif category == "products":
                    products.append(
                        record
                    )

                else:
                    rejected.append(
                        record
                    )

                counts[
                    category
                ] += 1

            except Exception as exc:
                counts["failed"] += 1

                rejected.append(
                    {
                        "source_url": (
                            candidate["url"]
                        ),
                        "reason": (
                            "download_failed"
                        ),
                        "error": str(
                            exc
                        ),
                    }
                )

        manifest = {
            "schema_version": 1,
            "source": "PokiPair",
            "target": target,
            "generated_at": self.now(),
            "page_candidates": len(
                candidates
            ),
            "counts": counts,
        }

        self.write_json(
            root / "cards.json",
            cards,
        )

        self.write_json(
            root / "products.json",
            products,
        )

        self.write_json(
            root / "rejected.json",
            rejected,
        )

        self.write_json(
            root / "manifest.json",
            manifest,
        )

        return manifest

    def import_all(
        self,
        target_ids: list[str],
        max_images: int | None,
    ) -> dict[str, Any]:
        requested = {
            value.upper()
            for value in target_ids
        }

        targets = [
            target
            for target in TARGETS
            if (
                not requested
                or target["id"].upper()
                in requested
            )
        ]

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/124 Safari/537.36 "
                "RareIQ/6.4"
            ),
            "Referer": (
                "https://www.pokipair.com/"
            ),
        }

        manifests = []

        with httpx.Client(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            for target in targets:
                print()
                print(
                    f"Importing {target['id']} "
                    f"- {target['name']}"
                )

                manifest = self.import_target(
                    target,
                    client,
                    max_images,
                )

                print(
                    manifest["counts"]
                )

                manifests.append(
                    manifest
                )

        summary = {
            "generated_at": self.now(),
            "target_count": len(
                manifests
            ),
            "totals": {
                key: sum(
                    manifest[
                        "counts"
                    ][key]
                    for manifest
                    in manifests
                )
                for key in (
                    "cards",
                    "products",
                    "rejected",
                    "duplicates",
                    "failed",
                )
            },
            "manifests": manifests,
        }

        self.write_json(
            self.output_root
            / "import_summary.json",
            summary,
        )

        return summary
