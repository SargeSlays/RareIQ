from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rareiq.services.pokipair_recognition_catalog_service import (
    PokiPairRecognitionCatalogService,
)


EXPECTED_CHECKLIST_ONLY = {
    "211/207",
    "241/207",
    "247/207",
    "251/207",
    "261/207",
}

IDENTITY_FIELDS = (
    "english_name",
    "canonical_name",
    "pokemon_name",
    "pricing_lookup_name",
)

CSV8_STABLE_FIELDS = (
    "id",
    "collector_number",
    "reference_image",
    "reference_images",
    "source",
    "source_page",
    "source_url",
    "sha256",
    "perceptual_hash",
    "width",
    "height",
    "aspect_ratio",
    "original_record_id",
)

VISUAL_STABLE_FIELDS = (
    "id",
    "card_id",
    "collector_number",
    "image_path",
    "perceptual_hash",
    "sha256",
    "set_id",
)


class DryRunValidationError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalized_local_number(value: Any) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        raise DryRunValidationError(
            f"Invalid local collector number: {value!r}"
        )
    return text.zfill(3)


def resolved_path(project_root: Path, value: Any) -> Path:
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def source_local_number(source: dict[str, Any]) -> str:
    collector_number = source.get("collector_number")
    if collector_number:
        return normalized_local_number(collector_number)

    for value in (
        source.get("label"),
        source.get("source_url"),
        source.get("local_path"),
    ):
        match = re.search(
            r"(?:^|[-_])(\d{1,3})(?:\.[A-Za-z0-9]+)?$",
            str(value or "").strip(),
        )
        if match:
            return match.group(1).zfill(3)

    raise DryRunValidationError(
        f"Unable to derive local collector number for source {source.get('id')!r}."
    )


def build_proposed_overrides(
    *,
    project_root: Path,
    repaired_payload: dict[str, Any],
    checklist_payload: dict[str, Any],
    source_records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    repaired_rows = repaired_payload.get("results")
    checklist_cards = checklist_payload.get("cards")

    if not isinstance(repaired_rows, list):
        raise DryRunValidationError("Repaired map results must be a list.")
    if not isinstance(checklist_cards, list):
        raise DryRunValidationError("Checklist cards must be a list.")
    if len(repaired_rows) != 615:
        raise DryRunValidationError(
            f"Expected 615 repaired rows, found {len(repaired_rows)}."
        )

    csv8_sources = [
        row
        for row in source_records
        if isinstance(row, dict) and row.get("set_id") == "CSV8"
    ]
    if len(csv8_sources) != 615:
        raise DryRunValidationError(
            f"Expected 615 CSV8 source records, found {len(csv8_sources)}."
        )

    source_by_local: dict[str, dict[str, Any]] = {}
    for source in csv8_sources:
        local_number = source_local_number(source)
        if local_number in source_by_local:
            raise DryRunValidationError(
                f"Duplicate CSV8 source local number: {local_number}"
            )
        source_by_local[local_number] = source

    checklist_by_official: dict[str, dict[str, Any]] = {}
    for card in checklist_cards:
        official_number = str(card.get("collector_number") or "").strip()
        if not official_number:
            raise DryRunValidationError(
                "Checklist card is missing collector_number."
            )
        if official_number in checklist_by_official:
            raise DryRunValidationError(
                f"Duplicate checklist number: {official_number}"
            )
        checklist_by_official[official_number] = card

    proposed: dict[str, dict[str, Any]] = {}
    official_numbers_used: set[str] = set()
    unmatched_local_records: list[str] = []
    missing_checklist_joins: list[str] = []
    image_path_mismatches: list[str] = []
    sequence_corrections: list[dict[str, str]] = []
    repaired_local_numbers: list[str] = []

    for repaired in repaired_rows:
        local_number = normalized_local_number(repaired.get("local_number"))
        repaired_local_numbers.append(local_number)
        source = source_by_local.get(local_number)
        if source is None:
            unmatched_local_records.append(local_number)
            continue

        repaired_image = resolved_path(
            project_root,
            repaired.get("image_path"),
        )
        source_image = resolved_path(
            project_root,
            source.get("local_path"),
        )
        if repaired_image != source_image:
            image_path_mismatches.append(local_number)

        official_number = str(
            repaired.get("official_collector_number") or ""
        ).strip()
        identity = checklist_by_official.get(official_number)
        if identity is None:
            missing_checklist_joins.append(official_number or local_number)
            continue

        override_key = f"CSV8:{local_number}"
        if override_key in proposed:
            raise DryRunValidationError(
                f"Duplicate proposed override key: {override_key}"
            )

        value = {
            field: identity.get(field)
            for field in IDENTITY_FIELDS
        }
        if any(
            not isinstance(value[field], str) or not value[field].strip()
            for field in IDENTITY_FIELDS
        ):
            raise DryRunValidationError(
                f"Incomplete identity fields for {official_number}."
            )

        proposed[override_key] = value
        official_numbers_used.add(official_number)

        if repaired.get("sequence_correction"):
            sequence_corrections.append({
                "local_number": local_number,
                "official_collector_number": official_number,
            })

    duplicate_local_numbers = sorted(
        number
        for number, count in Counter(repaired_local_numbers).items()
        if count > 1
    )
    checklist_only = set(checklist_by_official) - official_numbers_used

    errors = []
    if len(set(repaired_local_numbers)) != 615:
        errors.append("Repaired local numbers are not 615 unique values.")
    if set(repaired_local_numbers) != set(source_by_local):
        errors.append("Repaired and CSV8 source local-number sets differ.")
    if unmatched_local_records:
        errors.append("One or more repaired rows have no CSV8 source record.")
    if missing_checklist_joins:
        errors.append("One or more repaired rows have no checklist identity.")
    if image_path_mismatches:
        errors.append("Repaired and source image paths differ.")
    if len(proposed) != 615:
        errors.append(f"Expected 615 proposals, found {len(proposed)}.")
    if len(official_numbers_used) != 259:
        errors.append(
            "Expected 259 distinct official identities, found "
            f"{len(official_numbers_used)}."
        )
    if checklist_only != EXPECTED_CHECKLIST_ONLY:
        errors.append(
            "Checklist-only identity set differs from the expected five."
        )
    if len(sequence_corrections) != 8:
        errors.append(
            f"Expected 8 sequence corrections, found {len(sequence_corrections)}."
        )
    if duplicate_local_numbers:
        errors.append("Duplicate repaired local numbers were found.")
    if any(not key.startswith("CSV8:") for key in proposed):
        errors.append("A proposed key does not begin with CSV8:.")

    if errors:
        raise DryRunValidationError(" ".join(errors))

    details = {
        "official_numbers_used": sorted(official_numbers_used),
        "checklist_only": sorted(
            checklist_only,
            key=lambda value: int(value.split("/", 1)[0]),
        ),
        "unmatched_local_records": unmatched_local_records,
        "missing_checklist_joins": missing_checklist_joins,
        "image_path_mismatches": image_path_mismatches,
        "duplicate_local_numbers": duplicate_local_numbers,
        "sequence_corrections": sequence_corrections,
    }
    return proposed, details


def keyed_by_id(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = {}
    for record in records:
        record_id = str(record.get("id") or "")
        if not record_id or record_id in result:
            raise DryRunValidationError(
                f"Missing or duplicate normalized record id: {record_id!r}"
            )
        result[record_id] = record
    return result


def changed_record_count(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> int:
    before = keyed_by_id(baseline)
    after = keyed_by_id(candidate)
    return len(set(before) ^ set(after)) + sum(
        before[record_id] != after[record_id]
        for record_id in set(before) & set(after)
    )


def changed_stable_field_count(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> int:
    before = keyed_by_id(baseline)
    after = keyed_by_id(candidate)
    changed = len(set(before) ^ set(after))
    for record_id in set(before) & set(after):
        if any(
            before[record_id].get(field) != after[record_id].get(field)
            for field in fields
        ):
            changed += 1
    return changed


def validate_expected_identity(
    *,
    records: list[dict[str, Any]],
    proposals: dict[str, dict[str, Any]],
) -> int:
    enriched = 0
    for record in records:
        if record.get("set_id") != "CSV8":
            continue
        local_number = normalized_local_number(record.get("collector_number"))
        key = f"CSV8:{local_number}"
        expected = proposals.get(key)
        if expected is None:
            raise DryRunValidationError(f"Missing proposal for {key}.")
        if record.get("identity_override_key") != key:
            raise DryRunValidationError(
                f"Unexpected identity_override_key for {key}."
            )
        if any(record.get(field) != expected[field] for field in IDENTITY_FIELDS):
            raise DryRunValidationError(
                f"Identity fields do not match proposal for {key}."
            )
        enriched += 1
    return enriched


def run_dry_run(
    *,
    project_root: Path,
    tests_run: int = 0,
    tests_passed: int = 0,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    repaired_payload = read_json(
        project_root / "update17_csv8_repaired_map.json"
    )
    checklist_payload = read_json(
        project_root / "update17_csv8_english_checklist.json"
    )
    source_records = read_json(
        project_root / "catalog_master/pokipair/sets/CSV8/cards.json"
    )
    existing_overrides = read_json(
        project_root / "catalog_master/pokipair_identity_overrides.json"
    )

    if not isinstance(existing_overrides, dict):
        raise DryRunValidationError("Existing overrides must be an object.")

    proposed, details = build_proposed_overrides(
        project_root=project_root,
        repaired_payload=repaired_payload,
        checklist_payload=checklist_payload,
        source_records=source_records,
    )

    non_csv8_before = {
        key: copy.deepcopy(value)
        for key, value in existing_overrides.items()
        if not key.startswith("CSV8:")
    }
    injected_overrides = copy.deepcopy(existing_overrides)
    injected_overrides.update(proposed)
    non_csv8_after = {
        key: value
        for key, value in injected_overrides.items()
        if not key.startswith("CSV8:")
    }
    non_csv8_overrides_changed = int(non_csv8_before != non_csv8_after)

    baseline_service = PokiPairRecognitionCatalogService(
        project_root=project_root
    )
    baseline_records, _ = baseline_service.collect_records()

    injected_service = PokiPairRecognitionCatalogService(
        project_root=project_root
    )
    injected_service.identity_overrides = injected_overrides
    enriched_records, _ = injected_service.collect_records()

    baseline_csv8 = [
        row for row in baseline_records if row.get("set_id") == "CSV8"
    ]
    enriched_csv8 = [
        row for row in enriched_records if row.get("set_id") == "CSV8"
    ]
    baseline_non_csv8 = [
        row for row in baseline_records if row.get("set_id") != "CSV8"
    ]
    enriched_non_csv8 = [
        row for row in enriched_records if row.get("set_id") != "CSV8"
    ]

    non_csv8_normalized_records_changed = changed_record_count(
        baseline_non_csv8,
        enriched_non_csv8,
    )
    csv8_stable_fields_changed = changed_stable_field_count(
        baseline_csv8,
        enriched_csv8,
        CSV8_STABLE_FIELDS,
    )
    csv8_identity_enriched_records = validate_expected_identity(
        records=enriched_csv8,
        proposals=proposed,
    )

    baseline_visual = baseline_service.build_visual_index(baseline_records)
    enriched_visual = injected_service.build_visual_index(enriched_records)
    baseline_visual_csv8 = [
        row
        for row in baseline_visual["references"]
        if row.get("set_id") == "CSV8"
    ]
    enriched_visual_csv8 = [
        row
        for row in enriched_visual["references"]
        if row.get("set_id") == "CSV8"
    ]
    baseline_visual_non_csv8 = [
        row
        for row in baseline_visual["references"]
        if row.get("set_id") != "CSV8"
    ]
    enriched_visual_non_csv8 = [
        row
        for row in enriched_visual["references"]
        if row.get("set_id") != "CSV8"
    ]

    visual_non_csv8_changed = changed_record_count(
        baseline_visual_non_csv8,
        enriched_visual_non_csv8,
    )
    visual_stable_changed = changed_stable_field_count(
        baseline_visual_csv8,
        enriched_visual_csv8,
        VISUAL_STABLE_FIELDS,
    )
    csv8_visual_references_enriched = validate_expected_identity(
        records=enriched_visual_csv8,
        proposals=proposed,
    )

    duplicate_override_keys = (
        len(proposed) - len(set(proposed))
    )

    report = {
        "proposed_csv8_override_count": len(proposed),
        "distinct_official_identities_applied": len(
            details["official_numbers_used"]
        ),
        "checklist_identities_without_local_images": details["checklist_only"],
        "unmatched_local_records": details["unmatched_local_records"],
        "missing_checklist_joins": details["missing_checklist_joins"],
        "duplicate_override_keys": duplicate_override_keys,
        "non_csv8_overrides_changed": non_csv8_overrides_changed,
        "non_csv8_normalized_records_changed": (
            non_csv8_normalized_records_changed
        ),
        "csv8_stable_fields_changed": csv8_stable_fields_changed,
        "csv8_identity_enriched_records": csv8_identity_enriched_records,
        "csv8_visual_references_enriched": (
            csv8_visual_references_enriched
        ),
        "sequence_correction_count": len(details["sequence_corrections"]),
        "tests_run": tests_run,
        "tests_passed": tests_passed,
        "sequence_corrections": details["sequence_corrections"],
        "image_path_mismatches": details["image_path_mismatches"],
        "visual_non_csv8_references_changed": visual_non_csv8_changed,
        "csv8_visual_stable_fields_changed": visual_stable_changed,
    }

    expected_zero = {
        "unmatched_local_records": len(report["unmatched_local_records"]),
        "missing_checklist_joins": len(report["missing_checklist_joins"]),
        "duplicate_override_keys": report["duplicate_override_keys"],
        "non_csv8_overrides_changed": report["non_csv8_overrides_changed"],
        "non_csv8_normalized_records_changed": (
            report["non_csv8_normalized_records_changed"]
        ),
        "csv8_stable_fields_changed": report["csv8_stable_fields_changed"],
        "image_path_mismatches": len(report["image_path_mismatches"]),
        "visual_non_csv8_references_changed": (
            report["visual_non_csv8_references_changed"]
        ),
        "csv8_visual_stable_fields_changed": (
            report["csv8_visual_stable_fields_changed"]
        ),
    }
    failures = [
        f"{name}={value}"
        for name, value in expected_zero.items()
        if value != 0
    ]
    if len(baseline_csv8) != 615 or len(enriched_csv8) != 615:
        failures.append("normalized_csv8_record_count")
    if len(enriched_visual_csv8) != 615:
        failures.append("csv8_visual_reference_count")
    if csv8_identity_enriched_records != 615:
        failures.append("csv8_identity_enriched_records")
    if csv8_visual_references_enriched != 615:
        failures.append("csv8_visual_references_enriched")
    if failures:
        raise DryRunValidationError(
            "Dry-run validation failed: " + ", ".join(failures)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate CSV8 identity integration without active writes."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
    )
    parser.add_argument("--tests-run", type=int, default=0)
    parser.add_argument("--tests-passed", type=int, default=0)
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write only update17_csv8_integration_dry_run_report.json.",
    )
    args = parser.parse_args()

    report = run_dry_run(
        project_root=args.project_root,
        tests_run=args.tests_run,
        tests_passed=args.tests_passed,
    )
    if args.write_report:
        report_path = (
            args.project_root
            / "update17_csv8_integration_dry_run_report.json"
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
