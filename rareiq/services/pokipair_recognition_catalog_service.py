from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2


DEFAULT_EXCLUDED_SET_IDS = {
    "GEM_PACK_VOL_2",
    "GEM_PACK_VOL_3",
}


class PokiPairRecognitionCatalogService:
    def __init__(
        self,
        *,
        project_root: Path,
    ) -> None:
        self.project_root = Path(
            project_root
        ).resolve()

        self.pokipair_root = (
            self.project_root
            / "catalog_master"
            / "pokipair"
        )

        self.output_root = (
            self.project_root
            / "catalog_master"
            / "recognition"
        )

        self.catalog_path = (
            self.output_root
            / "pokipair_cards.json"
        )

        self.visual_index_path = (
            self.output_root
            / "pokipair_visual_index.json"
        )

        self.report_path = (
            self.output_root
            / "pokipair_build_report.json"
        )

        self.master_catalog_path = (
            self.project_root
            / "catalog_master"
            / "master_cards.json"
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _read_json(
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

    @staticmethod
    def _write_json(
        path: Path,
        payload: Any,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_path(
        value: str,
    ) -> str:
        return str(
            Path(
                value
            )
        ).replace(
            "\\",
            "/",
        )

    @staticmethod
    def _stable_id(
        *,
        set_id: str,
        source_url: str,
        local_path: str,
    ) -> str:
        source = (
            f"{set_id}|"
            f"{source_url}|"
            f"{local_path}"
        )

        digest = hashlib.sha1(
            source.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        return (
            f"pokipair-"
            f"{set_id.lower()}-"
            f"{digest}"
        )

    def _discover_card_files(
        self,
    ) -> list[Path]:
        paths = []

        sets_root = (
            self.pokipair_root
            / "sets"
        )

        collections_root = (
            self.pokipair_root
            / "collections"
        )

        if sets_root.exists():
            paths.extend(
                sorted(
                    sets_root.glob(
                        "*/cards.json"
                    )
                )
            )

        if collections_root.exists():
            paths.extend(
                sorted(
                    collections_root.glob(
                        "*/cards.json"
                    )
                )
            )

        return paths

    def _validate_image(
        self,
        relative_path: str,
    ) -> tuple[
        bool,
        dict[str, Any],
    ]:
        absolute_path = (
            self.project_root
            / relative_path
        )

        if not absolute_path.exists():
            return (
                False,
                {
                    "reason": "missing_file",
                    "path": relative_path,
                },
            )

        image = cv2.imread(
            str(
                absolute_path
            )
        )

        if image is None:
            return (
                False,
                {
                    "reason": "image_decode_failed",
                    "path": relative_path,
                },
            )

        height, width = image.shape[:2]

        if (
            width < 120
            or height < 180
        ):
            return (
                False,
                {
                    "reason": "image_too_small",
                    "path": relative_path,
                    "width": width,
                    "height": height,
                },
            )

        return (
            True,
            {
                "width": width,
                "height": height,
                "aspect_ratio": round(
                    width
                    / float(
                        height
                    ),
                    4,
                ),
            },
        )

    def _normalize_record(
        self,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        set_id = str(
            source.get(
                "set_id",
                "UNKNOWN",
            )
        )

        set_name = str(
            source.get(
                "set_name",
                set_id,
            )
        )

        local_path = (
            self._normalize_path(
                str(
                    source.get(
                        "local_path",
                        "",
                    )
                )
            )
        )

        source_url = str(
            source.get(
                "source_url",
                "",
            )
        )

        collector_number = (
            source.get(
                "collector_number"
            )
        )

        label = str(
            source.get(
                "label",
                "",
            )
        ).strip()

        # PokiPair records frequently omit structured collector metadata,
        # while the card-list position is embedded at the end of the label,
        # URL, or local filename.
        if not collector_number:
            number_sources = (
                label,
                source_url,
                local_path,
            )

            for number_source in number_sources:
                number_match = re.search(
                    r"(?:^|[-_])(\d{1,3})(?:\.[A-Za-z0-9]+)?$",
                    str(number_source or "").strip(),
                )

                if number_match:
                    collector_number = (
                        number_match.group(1).zfill(3)
                    )
                    break

        record_id = self._stable_id(
            set_id=set_id,
            source_url=source_url,
            local_path=local_path,
        )

        return {
            "id": record_id,
            "source": "pokipair",
            "language": "zh-cn",
            "set_id": set_id,
            "set_name": set_name,
            "collector_number": (
                collector_number
            ),
            "name": label,
            "display_name": label,
            "variant": None,
            "rarity": None,
            "category": "card",
            "reference_image": local_path,
            "reference_images": [
                local_path
            ],
            "source_page": source.get(
                "source_page"
            ),
            "source_url": source_url,
            "sha256": source.get(
                "sha256"
            ),
            "perceptual_hash": source.get(
                "perceptual_hash"
            ),
            "width": source.get(
                "width"
            ),
            "height": source.get(
                "height"
            ),
            "aspect_ratio": source.get(
                "aspect_ratio"
            ),
            "original_record_id": (
                source.get(
                    "id"
                )
            ),
        }

    @staticmethod
    def _record_key(
        record: dict[str, Any],
    ) -> tuple[
        str,
        str,
        str,
    ]:
        return (
            str(
                record.get(
                    "set_id",
                    ""
                )
            ),
            str(
                record.get(
                    "source_url",
                    ""
                )
            ),
            str(
                record.get(
                    "reference_image",
                    ""
                )
            ),
        )

    def collect_records(
        self,
        *,
        include_incomplete: bool = False,
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        excluded_sets = (
            set()
            if include_incomplete
            else DEFAULT_EXCLUDED_SET_IDS
        )

        records = []
        rejected = []
        skipped_sets = set()
        duplicate_count = 0
        seen_keys = set()

        source_files = (
            self._discover_card_files()
        )

        for cards_path in source_files:
            source_records = self._read_json(
                cards_path,
                [],
            )

            if not isinstance(
                source_records,
                list,
            ):
                rejected.append(
                    {
                        "reason": "cards_json_not_list",
                        "path": str(
                            cards_path
                        ),
                    }
                )

                continue

            for source in source_records:
                if not isinstance(
                    source,
                    dict,
                ):
                    rejected.append(
                        {
                            "reason": "record_not_object",
                            "path": str(
                                cards_path
                            ),
                        }
                    )

                    continue

                set_id = str(
                    source.get(
                        "set_id",
                        "",
                    )
                )

                if set_id in excluded_sets:
                    skipped_sets.add(
                        set_id
                    )

                    continue

                if (
                    source.get(
                        "category"
                    )
                    != "cards"
                ):
                    continue

                local_path = str(
                    source.get(
                        "local_path",
                        "",
                    )
                )

                valid, image_info = (
                    self._validate_image(
                        local_path
                    )
                )

                if not valid:
                    rejected.append(
                        {
                            "set_id": set_id,
                            "source_record_id": (
                                source.get(
                                    "id"
                                )
                            ),
                            **image_info,
                        }
                    )

                    continue

                record = self._normalize_record(
                    source
                )

                record.update(
                    image_info
                )

                key = self._record_key(
                    record
                )

                if key in seen_keys:
                    duplicate_count += 1
                    continue

                seen_keys.add(
                    key
                )

                records.append(
                    record
                )

        records.sort(
            key=lambda record: (
                str(
                    record.get(
                        "set_id",
                        ""
                    )
                ),
                str(
                    record.get(
                        "collector_number",
                        ""
                    )
                ),
                str(
                    record.get(
                        "name",
                        ""
                    )
                ),
                str(
                    record.get(
                        "id",
                        ""
                    )
                ),
            )
        )

        report = {
            "source_files": len(
                source_files
            ),
            "records_accepted": len(
                records
            ),
            "records_rejected": len(
                rejected
            ),
            "duplicates_removed": (
                duplicate_count
            ),
            "excluded_set_ids": sorted(
                skipped_sets
            ),
            "rejected": rejected,
        }

        return (
            records,
            report,
        )

    @staticmethod
    def build_visual_index(
        records: list[
            dict[str, Any]
        ],
    ) -> dict[str, Any]:
        references = []

        for record in records:
            references.append(
                {
                    "id": record["id"],
                    "card_id": record["id"],
                    "set_id": record["set_id"],
                    "set_name": record["set_name"],
                    "collector_number": (
                        record.get(
                            "collector_number"
                        )
                    ),
                    "name": record.get(
                        "name"
                    ),
                    "language": "zh-cn",
                    "image_path": (
                        record[
                            "reference_image"
                        ]
                    ),
                    "perceptual_hash": (
                        record.get(
                            "perceptual_hash"
                        )
                    ),
                    "sha256": record.get(
                        "sha256"
                    ),
                    "enabled": True,
                }
            )

        return {
            "schema_version": 1,
            "index_type": (
                "visual_reference_catalog"
            ),
            "source": "pokipair",
            "language": "zh-cn",
            "reference_count": len(
                references
            ),
            "references": references,
        }

    def _merge_into_master_catalog(
        self,
        records: list[
            dict[str, Any]
        ],
    ) -> dict[str, Any]:
        if not self.master_catalog_path.exists():
            return {
                "merged": False,
                "reason": (
                    "master_cards_missing"
                ),
                "records_added": 0,
            }

        payload = self._read_json(
            self.master_catalog_path,
            None,
        )

        list_reference = None
        container_type = None

        if isinstance(
            payload,
            list,
        ):
            list_reference = payload
            container_type = "list"

        elif isinstance(
            payload,
            dict,
        ):
            for key in (
                "cards",
                "records",
                "items",
            ):
                value = payload.get(
                    key
                )

                if isinstance(
                    value,
                    list,
                ):
                    list_reference = value
                    container_type = key
                    break

        if list_reference is None:
            return {
                "merged": False,
                "reason": (
                    "unsupported_master_schema"
                ),
                "records_added": 0,
            }

        backup_path = (
            self.master_catalog_path
            .with_suffix(
                ".pre_pokipair_10_5.json"
            )
        )

        if not backup_path.exists():
            shutil.copy2(
                self.master_catalog_path,
                backup_path,
            )

        existing = [
            record
            for record in list_reference
            if not (
                isinstance(
                    record,
                    dict,
                )
                and record.get(
                    "source"
                )
                == "pokipair"
            )
        ]

        existing.extend(
            records
        )

        if container_type == "list":
            merged_payload = existing

        else:
            merged_payload = dict(
                payload
            )

            merged_payload[
                container_type
            ] = existing

        self._write_json(
            self.master_catalog_path,
            merged_payload,
        )

        return {
            "merged": True,
            "container": container_type,
            "records_added": len(
                records
            ),
            "master_record_count": len(
                existing
            ),
            "backup_path": str(
                backup_path.relative_to(
                    self.project_root
                )
            ),
        }

    def build(
        self,
        *,
        include_incomplete: bool = False,
        merge_master: bool = True,
    ) -> dict[str, Any]:
        records, collection_report = (
            self.collect_records(
                include_incomplete=(
                    include_incomplete
                )
            )
        )

        visual_index = (
            self.build_visual_index(
                records
            )
        )

        catalog_payload = {
            "schema_version": 1,
            "catalog_type": (
                "pokipair_simplified_chinese"
            ),
            "generated_at": self._now(),
            "record_count": len(
                records
            ),
            "records": records,
        }

        visual_index[
            "generated_at"
        ] = self._now()

        self._write_json(
            self.catalog_path,
            catalog_payload,
        )

        self._write_json(
            self.visual_index_path,
            visual_index,
        )

        merge_report = {
            "merged": False,
            "reason": "merge_disabled",
            "records_added": 0,
        }

        if merge_master:
            merge_report = (
                self._merge_into_master_catalog(
                    records
                )
            )

        set_counts = {}

        for record in records:
            set_id = record[
                "set_id"
            ]

            set_counts[
                set_id
            ] = (
                set_counts.get(
                    set_id,
                    0,
                )
                + 1
            )

        report = {
            "ok": True,
            "generated_at": self._now(),
            "catalog_path": str(
                self.catalog_path.relative_to(
                    self.project_root
                )
            ),
            "visual_index_path": str(
                self.visual_index_path.relative_to(
                    self.project_root
                )
            ),
            "record_count": len(
                records
            ),
            "reference_count": (
                visual_index[
                    "reference_count"
                ]
            ),
            "set_counts": set_counts,
            "collection": collection_report,
            "master_catalog": merge_report,
        }

        self._write_json(
            self.report_path,
            report,
        )

        return report
