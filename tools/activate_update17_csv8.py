from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rareiq.services.pokipair_recognition_catalog_service import (
    PokiPairRecognitionCatalogService,
)
from rareiq.services.recognition_service import RecognitionService
from tools.activate_pokipair_artwork_index import activate
from tools.validate_update17_csv8_integration import (
    CSV8_STABLE_FIELDS,
    IDENTITY_FIELDS,
    VISUAL_STABLE_FIELDS,
    build_proposed_overrides,
    changed_record_count,
    changed_stable_field_count,
    read_json,
    run_dry_run,
)


class ActivationError(RuntimeError):
    pass


AUTHORIZED_PATHS = (
    "catalog_master/pokipair_identity_overrides.json",
    "catalog_master/recognition/pokipair_cards.json",
    "catalog_master/recognition/pokipair_visual_index.json",
    "catalog_master/master_cards.json",
    "rareiq/data/artwork_index.json",
)

MASTER_ALLOWED_CHANGES = set(IDENTITY_FIELDS) | {
    "identity_override_key",
    "name",
    "display_name",
}

VISUAL_ALLOWED_CHANGES = set(IDENTITY_FIELDS) | {
    "identity_override_key",
    "name",
    "display_name",
}

RUNTIME_ALLOWED_CHANGES = set(IDENTITY_FIELDS) | {
    "name",
    "display_name",
}


def json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=path.stem + "_",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def semantic_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def records_from_catalog(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("cards", "records", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
    raise ActivationError("Unsupported master catalog schema.")


def records_by_id(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = {}
    for record in records:
        record_id = str(record.get("id") or "")
        if not record_id or record_id in result:
            raise ActivationError(
                f"Missing or duplicate record id: {record_id!r}"
            )
        result[record_id] = record
    return result


def unexpected_changed_fields(
    before: dict[str, Any],
    after: dict[str, Any],
    allowed: set[str],
) -> set[str]:
    keys = set(before) | set(after)
    return {
        key
        for key in keys
        if before.get(key) != after.get(key) and key not in allowed
    }


def validate_csv8_changes(
    *,
    before_records: list[dict[str, Any]],
    after_records: list[dict[str, Any]],
    allowed_fields: set[str],
    stable_fields: tuple[str, ...],
    expected_count: int = 615,
) -> int:
    before = records_by_id(before_records)
    after = records_by_id(after_records)
    if set(before) != set(after):
        raise ActivationError("CSV8 record ID set changed.")
    if len(after) != expected_count:
        raise ActivationError(
            f"Expected {expected_count} CSV8 records, found {len(after)}."
        )
    stable_changed = changed_stable_field_count(
        before_records,
        after_records,
        stable_fields,
    )
    if stable_changed:
        raise ActivationError(
            f"CSV8 stable fields changed on {stable_changed} records."
        )
    for record_id in before:
        unexpected = unexpected_changed_fields(
            before[record_id],
            after[record_id],
            allowed_fields,
        )
        if unexpected:
            raise ActivationError(
                f"Unexpected CSV8 changes for {record_id}: "
                + ", ".join(sorted(unexpected))
            )
    return stable_changed


def verify_expected_identities(
    records: list[dict[str, Any]],
    proposals: dict[str, dict[str, Any]],
) -> int:
    enriched = 0
    for record in records:
        if record.get("set_id") != "CSV8":
            continue
        local_number = str(record.get("collector_number") or "").zfill(3)
        expected = proposals.get(f"CSV8:{local_number}")
        if expected is None:
            raise ActivationError(
                f"No expected identity for CSV8:{local_number}."
            )
        if any(record.get(field) != expected[field] for field in IDENTITY_FIELDS):
            raise ActivationError(
                f"Identity mismatch for CSV8:{local_number}."
            )
        enriched += 1
    if enriched != 615:
        raise ActivationError(
            f"Expected 615 enriched CSV8 records, found {enriched}."
        )
    return enriched


def runtime_verification(project_root: Path) -> dict[str, Any]:
    service = RecognitionService(lambda *_args, **_kwargs: None)
    records = service.artwork_index._records
    expected = {
        "001": "Exeggcute",
        "065": "Applin",
        "331": "Slither Wing",
    }
    results = {}
    for local_number, english_name in expected.items():
        matches = [
            row
            for row in records
            if row.get("set_id") == "CSV8"
            and str(row.get("collector_number") or "").zfill(3) == local_number
        ]
        if len(matches) != 1:
            raise ActivationError(
                f"Expected one runtime match for CSV8:{local_number}, "
                f"found {len(matches)}."
            )
        record = matches[0]
        if record.get("english_name") != english_name:
            raise ActivationError(
                f"CSV8:{local_number} expected {english_name}, "
                f"found {record.get('english_name')!r}."
            )
        if str(record.get("collector_number") or "").zfill(3) != local_number:
            raise ActivationError(
                f"CSV8:{local_number} lost its local collector number."
            )
        results[f"CSV8:{local_number}"] = {
            "english_name": record.get("english_name"),
            "collector_number": record.get("collector_number"),
            "id": record.get("id"),
            "passed": True,
        }
    results["runtime_index"] = {
        "record_count": len(records),
        "loaded": service.artwork_index.status().get("error") is None,
        "passed": len(records) == 3163,
    }
    if not results["runtime_index"]["passed"]:
        raise ActivationError("Runtime index did not load 3163 records.")
    return results


def activate_csv8(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    paths = {
        relative: project_root / relative
        for relative in AUTHORIZED_PATHS
    }
    originals = {
        relative: path.read_bytes()
        for relative, path in paths.items()
    }
    snapshots = {
        relative: semantic_hash(read_json(path))
        for relative, path in paths.items()
    }
    override_path = paths[
        "catalog_master/pokipair_identity_overrides.json"
    ]
    replacements_started = False

    try:
        dry_report = run_dry_run(project_root=project_root)
        if dry_report["proposed_csv8_override_count"] != 615:
            raise ActivationError("Dry-run proposal count is not 615.")

        existing_overrides = read_json(override_path)
        repaired_payload = read_json(
            project_root / "update17_csv8_repaired_map.json"
        )
        checklist_payload = read_json(
            project_root / "update17_csv8_english_checklist.json"
        )
        source_records = read_json(
            project_root / "catalog_master/pokipair/sets/CSV8/cards.json"
        )
        proposals, _ = build_proposed_overrides(
            project_root=project_root,
            repaired_payload=repaired_payload,
            checklist_payload=checklist_payload,
            source_records=source_records,
        )

        existing_csv8 = {
            key for key in existing_overrides if key.startswith("CSV8:")
        }
        if existing_csv8:
            raise ActivationError(
                f"Expected no existing CSV8 overrides, found {len(existing_csv8)}."
            )
        merged_overrides = copy.deepcopy(existing_overrides)
        merged_overrides.update(proposals)
        existing_changed = sum(
            merged_overrides.get(key) != value
            for key, value in existing_overrides.items()
        )
        removed = set(existing_overrides) - set(merged_overrides)
        added = set(merged_overrides) - set(existing_overrides)
        gem_before = {
            key: value
            for key, value in existing_overrides.items()
            if key.startswith("GEM_PACK_VOL_5:")
        }
        gem_after = {
            key: value
            for key, value in merged_overrides.items()
            if key.startswith("GEM_PACK_VOL_5:")
        }
        if (
            len(added) != 615
            or any(not key.startswith("CSV8:") for key in added)
            or removed
            or existing_changed
            or gem_before != gem_after
        ):
            raise ActivationError("Override diff validation failed.")

        atomic_write_bytes(override_path, json_bytes(merged_overrides))

        service = PokiPairRecognitionCatalogService(
            project_root=project_root
        )
        generated_records, _ = service.collect_records()
        generated_visual = service.build_visual_index(generated_records)
        generated_visual["generated_at"] = service._now()
        generated_catalog = {
            "schema_version": 1,
            "catalog_type": "pokipair_simplified_chinese",
            "generated_at": service._now(),
            "record_count": len(generated_records),
            "records": generated_records,
        }

        active_master_payload = read_json(
            paths["catalog_master/master_cards.json"]
        )
        active_master = records_from_catalog(active_master_payload)
        active_by_id = records_by_id(active_master)
        generated_by_id = records_by_id(generated_records)

        active_non_pokipair = [
            row for row in active_master if row.get("source") != "pokipair"
        ]
        candidate_non_pokipair = copy.deepcopy(active_non_pokipair)
        if changed_record_count(
            active_non_pokipair,
            candidate_non_pokipair,
        ):
            raise ActivationError("Non-PokiPair master records changed.")

        active_non_csv8_pokipair = [
            row
            for row in active_master
            if row.get("source") == "pokipair" and row.get("set_id") != "CSV8"
        ]
        generated_non_csv8_pokipair = [
            row for row in generated_records if row.get("set_id") != "CSV8"
        ]
        non_csv8_master_changed = changed_record_count(
            active_non_csv8_pokipair,
            generated_non_csv8_pokipair,
        )
        if non_csv8_master_changed:
            raise ActivationError(
                "Non-CSV8 PokiPair master records differ from canonical output: "
                f"{non_csv8_master_changed}."
            )

        active_csv8 = [
            row for row in active_master if row.get("set_id") == "CSV8"
        ]
        generated_csv8 = [
            row for row in generated_records if row.get("set_id") == "CSV8"
        ]
        csv8_stable_changed = validate_csv8_changes(
            before_records=active_csv8,
            after_records=generated_csv8,
            allowed_fields=MASTER_ALLOWED_CHANGES,
            stable_fields=CSV8_STABLE_FIELDS,
        )
        master_enriched = verify_expected_identities(
            generated_csv8,
            proposals,
        )

        candidate_master = []
        for row in active_master:
            if row.get("set_id") == "CSV8":
                replacement = generated_by_id.get(str(row.get("id") or ""))
                if replacement is None:
                    raise ActivationError(
                        f"No canonical replacement for master id {row.get('id')}."
                    )
                candidate_master.append(replacement)
            else:
                candidate_master.append(row)
        if len(candidate_master) != len(active_master):
            raise ActivationError("Master record count changed.")
        if not isinstance(active_master_payload, list):
            raise ActivationError(
                "Targeted activation requires the active list master schema."
            )

        active_visual = read_json(
            paths[
                "catalog_master/recognition/pokipair_visual_index.json"
            ]
        )
        active_visual_rows = active_visual.get("references", [])
        generated_visual_rows = generated_visual["references"]
        active_visual_non_csv8 = [
            row for row in active_visual_rows if row.get("set_id") != "CSV8"
        ]
        generated_visual_non_csv8 = [
            row for row in generated_visual_rows if row.get("set_id") != "CSV8"
        ]
        non_csv8_visual_changed = changed_record_count(
            active_visual_non_csv8,
            generated_visual_non_csv8,
        )
        if non_csv8_visual_changed:
            raise ActivationError(
                "Non-CSV8 visual records changed: "
                f"{non_csv8_visual_changed}."
            )
        active_visual_csv8 = [
            row for row in active_visual_rows if row.get("set_id") == "CSV8"
        ]
        generated_visual_csv8 = [
            row for row in generated_visual_rows if row.get("set_id") == "CSV8"
        ]
        validate_csv8_changes(
            before_records=active_visual_csv8,
            after_records=generated_visual_csv8,
            allowed_fields=VISUAL_ALLOWED_CHANGES,
            stable_fields=VISUAL_STABLE_FIELDS,
        )
        visual_enriched = verify_expected_identities(
            generated_visual_csv8,
            proposals,
        )

        with tempfile.TemporaryDirectory(
            prefix="rareiq_csv8_activation_"
        ) as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_visual = temporary_root / "pokipair_visual_index.json"
            temporary_runtime = temporary_root / "artwork_index.json"
            temporary_visual.write_bytes(json_bytes(generated_visual))
            activation_result = activate(
                project_root=project_root,
                source_path=temporary_visual,
                destination_path=temporary_runtime,
            )
            if activation_result.get("record_count") != 3163:
                raise ActivationError(
                    "Temporary runtime record count is not 3163."
                )
            candidate_runtime = read_json(temporary_runtime)
            candidate_runtime["source_path"] = str(
                paths[
                    "catalog_master/recognition/pokipair_visual_index.json"
                ]
            )
            active_runtime = read_json(
                paths["rareiq/data/artwork_index.json"]
            )
            active_runtime_rows = active_runtime.get("records", [])
            candidate_runtime_rows = candidate_runtime.get("records", [])
            active_runtime_non_csv8 = [
                row
                for row in active_runtime_rows
                if row.get("set_id") != "CSV8"
            ]
            candidate_runtime_non_csv8 = [
                row
                for row in candidate_runtime_rows
                if row.get("set_id") != "CSV8"
            ]
            non_csv8_runtime_changed = changed_record_count(
                active_runtime_non_csv8,
                candidate_runtime_non_csv8,
            )
            if non_csv8_runtime_changed:
                raise ActivationError(
                    "Non-CSV8 runtime records changed: "
                    f"{non_csv8_runtime_changed}."
                )
            active_runtime_csv8 = [
                row
                for row in active_runtime_rows
                if row.get("set_id") == "CSV8"
            ]
            candidate_runtime_csv8 = [
                row
                for row in candidate_runtime_rows
                if row.get("set_id") == "CSV8"
            ]
            runtime_stable_fields = tuple(
                sorted(
                    (
                        set(active_runtime_csv8[0])
                        | set(candidate_runtime_csv8[0])
                    )
                    - RUNTIME_ALLOWED_CHANGES
                )
            )
            validate_csv8_changes(
                before_records=active_runtime_csv8,
                after_records=candidate_runtime_csv8,
                allowed_fields=RUNTIME_ALLOWED_CHANGES,
                stable_fields=runtime_stable_fields,
            )
            runtime_enriched = verify_expected_identities(
                candidate_runtime_csv8,
                proposals,
            )

            prepared = {
                "catalog_master/recognition/pokipair_cards.json": (
                    json_bytes(generated_catalog)
                ),
                "catalog_master/recognition/pokipair_visual_index.json": (
                    json_bytes(generated_visual)
                ),
                "catalog_master/master_cards.json": (
                    json_bytes(candidate_master)
                ),
                "rareiq/data/artwork_index.json": temporary_runtime.read_bytes(),
            }
            prepared["rareiq/data/artwork_index.json"] = json_bytes(
                candidate_runtime
            )

        replacements_started = True
        for relative, payload in prepared.items():
            atomic_write_bytes(paths[relative], payload)

        runtime_results = runtime_verification(project_root)
        report = {
            "overrides_added": len(added),
            "existing_overrides_changed": existing_changed,
            "csv8_master_records_enriched": master_enriched,
            "csv8_visual_references_enriched": visual_enriched,
            "csv8_runtime_records_enriched": runtime_enriched,
            "non_csv8_master_records_changed": non_csv8_master_changed,
            "non_csv8_visual_records_changed": non_csv8_visual_changed,
            "non_csv8_runtime_records_changed": non_csv8_runtime_changed,
            "csv8_stable_fields_changed": csv8_stable_changed,
            "total_master_record_count": len(candidate_master),
            "total_visual_reference_count": len(generated_visual_rows),
            "total_runtime_record_count": len(candidate_runtime_rows),
            "tests_passed": 0,
            "tests_failed": 0,
            "runtime_verification_results": runtime_results,
            "files_written": list(AUTHORIZED_PATHS),
            "pre_activation_semantic_hashes": snapshots,
        }
        return report
    except Exception:
        atomic_write_bytes(override_path, originals[
            "catalog_master/pokipair_identity_overrides.json"
        ])
        if replacements_started:
            for relative in AUTHORIZED_PATHS[1:]:
                atomic_write_bytes(paths[relative], originals[relative])
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
    )
    parser.add_argument(
        "--finalize-tests",
        nargs=2,
        metavar=("PASSED", "FAILED"),
        type=int,
    )
    args = parser.parse_args()
    report_path = (
        args.project_root / "update17_csv8_activation_report.json"
    )
    if args.finalize_tests:
        report = read_json(report_path)
        report["tests_passed"], report["tests_failed"] = args.finalize_tests
        report["runtime_verification_results"] = runtime_verification(
            args.project_root
        )
    else:
        report = activate_csv8(args.project_root)
    atomic_write_bytes(report_path, json_bytes(report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
