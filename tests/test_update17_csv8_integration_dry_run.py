from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import cv2
import numpy as np

from tools.validate_update17_csv8_integration import (
    EXPECTED_CHECKLIST_ONLY,
    build_proposed_overrides,
    run_dry_run,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def identity(number: str, name: str) -> dict:
    return {
        "collector_number": number,
        "english_name": name,
        "canonical_name": name,
        "pokemon_name": name,
        "pricing_lookup_name": name,
    }


def source(local_number: str) -> dict:
    image_path = (
        PROJECT_ROOT
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV8"
        / "cards"
        / f"card-{local_number}.png"
    )
    return {
        "set_id": "CSV8",
        "collector_number": local_number,
        "local_path": str(image_path),
    }


def repaired(local_number: str, official_number: str) -> dict:
    image_path = (
        PROJECT_ROOT
        / "catalog_master"
        / "pokipair"
        / "sets"
        / "CSV8"
        / "cards"
        / f"card-{local_number}.png"
    )
    return {
        "local_number": local_number,
        "official_collector_number": official_number,
        "image_path": str(image_path),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv8_assignments() -> tuple[list[dict], list[int]]:
    checklist = [
        identity(f"{number:03d}/207", f"Card {number}")
        for number in range(1, 265)
    ]
    official_numbers = [
        number
        for number in range(1, 265)
        if f"{number:03d}/207" not in EXPECTED_CHECKLIST_ONLY
    ]
    assignments = (
        official_numbers[:78]
        + [number for number in official_numbers[78:84] for _ in range(2)]
        + [number for number in official_numbers[84:] for _ in range(3)]
    )
    assert len(assignments) == 615
    return checklist, assignments


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_csv8_dry_run_project(root: Path) -> None:
    checklist, assignments = _csv8_assignments()
    cards_root = root / "catalog_master" / "pokipair" / "sets" / "CSV8" / "cards"
    cards_root.mkdir(parents=True, exist_ok=True)
    template = cards_root / "template.png"
    image = np.full((180, 120, 3), (28, 74, 112), dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (111, 171), (235, 235, 235), 4)
    cv2.line(image, (15, 80), (105, 80), (70, 210, 245), 5)
    assert cv2.imwrite(str(template), image)

    sources = []
    repaired_rows = []
    for index, official in enumerate(assignments, start=1):
        local_number = f"{index:03d}"
        path = cards_root / f"card-{local_number}.png"
        try:
            os.link(template, path)
        except OSError:
            shutil.copyfile(template, path)
        relative = path.relative_to(root).as_posix()
        sources.append({
            "id": f"CSV8-{local_number}",
            "set_id": "CSV8",
            "set_name": "Bright Fantasy",
            "category": "cards",
            "collector_number": local_number,
            "label": f"fixture-{local_number}",
            "source_page": "https://example.invalid/csv8",
            "source_url": f"https://example.invalid/csv8/{local_number}.png",
            "local_path": relative,
            "filename": path.name,
            "sha256": "fixture",
            "perceptual_hash": f"{index:016x}",
        })
        repaired_rows.append({
            "local_number": local_number,
            "official_collector_number": f"{official:03d}/207",
            "image_path": relative,
            **({"sequence_correction": True} if index <= 8 else {}),
        })
    template.unlink()

    _write_json(root / "update17_csv8_repaired_map.json", {"results": repaired_rows})
    _write_json(root / "update17_csv8_english_checklist.json", {"cards": checklist})
    _write_json(root / "catalog_master/pokipair/sets/CSV8/cards.json", sources)
    _write_json(root / "catalog_master/pokipair_identity_overrides.json", {
        "GEM_PACK_VOL_5:001": {"canonical_name": "Preserved fixture"},
    })
    for relative, payload in (
        ("catalog_master/master_cards.json", []),
        ("catalog_master/recognition/pokipair_cards.json", {"records": []}),
        ("catalog_master/recognition/pokipair_visual_index.json", {"references": []}),
        ("rareiq/data/artwork_index.json", {"records": []}),
    ):
        _write_json(root / relative, payload)


def test_variant_and_single_image_mapping_without_fake_records() -> None:
    checklist, assignments = _csv8_assignments()
    official_numbers = [
        number
        for number in range(1, 265)
        if f"{number:03d}/207" not in EXPECTED_CHECKLIST_ONLY
    ]

    sources = [
        source(f"{index:03d}")
        for index in range(1, 616)
    ]
    repaired_rows = [
        repaired(f"{index:03d}", f"{official:03d}/207")
        for index, official in enumerate(assignments, start=1)
    ]
    for row in repaired_rows[:8]:
        row["sequence_correction"] = True

    proposals, details = build_proposed_overrides(
        project_root=PROJECT_ROOT,
        repaired_payload={"results": repaired_rows},
        checklist_payload={"cards": checklist},
        source_records=sources,
    )

    assert len(proposals) == 615
    three_image_name = f"Card {official_numbers[84]}"
    assert sum(
        proposal["english_name"] == three_image_name
        for proposal in proposals.values()
    ) == 3
    assert sum(
        proposal["english_name"] == "Card 1"
        for proposal in proposals.values()
    ) == 1
    assert details["checklist_only"] == sorted(
        EXPECTED_CHECKLIST_ONLY,
        key=lambda value: int(value.split("/", 1)[0]),
    )


def test_real_dry_run_preserves_active_files_and_gem_pack_overrides(tmp_path) -> None:
    project_root = tmp_path / "project"
    _build_csv8_dry_run_project(project_root)
    active_paths = [
        project_root / "catalog_master/master_cards.json",
        project_root / "catalog_master/pokipair_identity_overrides.json",
        project_root / "catalog_master/recognition/pokipair_cards.json",
        project_root / "catalog_master/recognition/pokipair_visual_index.json",
        project_root / "rareiq/data/artwork_index.json",
    ]
    before_hashes = {
        path: sha256(path)
        for path in active_paths
        if path.exists()
    }
    overrides_before = json.loads(
        (
            project_root
            / "catalog_master/pokipair_identity_overrides.json"
        ).read_text(encoding="utf-8-sig")
    )
    gem_pack_before = {
        key: copy.deepcopy(value)
        for key, value in overrides_before.items()
        if key.startswith("GEM_PACK_VOL_5:")
    }

    report = run_dry_run(project_root=project_root)

    after_hashes = {
        path: sha256(path)
        for path in active_paths
        if path.exists()
    }
    overrides_after = json.loads(
        (
            project_root
            / "catalog_master/pokipair_identity_overrides.json"
        ).read_text(encoding="utf-8-sig")
    )
    gem_pack_after = {
        key: value
        for key, value in overrides_after.items()
        if key.startswith("GEM_PACK_VOL_5:")
    }

    assert report["proposed_csv8_override_count"] == 615
    assert report["distinct_official_identities_applied"] == 259
    assert report["csv8_identity_enriched_records"] == 615
    assert report["csv8_visual_references_enriched"] == 615
    assert gem_pack_after == gem_pack_before
    assert after_hashes == before_hashes
