from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from rareiq.services.artwork_index_service import ArtworkIndexService


def patterned_card(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    card = np.full((700, 500, 3), 225, dtype=np.uint8)
    cv2.rectangle(card, (24, 24), (475, 675), (30, 80, 170), 8)
    cv2.rectangle(card, (48, 100), (452, 360), (190, 130, 40), -1)
    for _ in range(90):
        x, y = rng.integers([55, 110], [445, 350])
        cv2.circle(card, (int(x), int(y)), 3, (20, 20, 20), -1)
    cv2.putText(card, "CARD NAME 60", (55, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.putText(card, "050/107", (55, 640), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.circle(card, (330, 510), 105, (120, 190, 240), 16)
    return card


def service_with_records(tmp_path: Path, records: list[dict]) -> ArtworkIndexService:
    index = tmp_path / "artwork.json"
    index.write_text(json.dumps({"records": records}), encoding="utf-8")
    return ArtworkIndexService(index)


def record(card_id: str, image_path: Path, fingerprint: str) -> dict:
    return {
        "id": card_id,
        "name": card_id,
        "image_path": str(image_path),
        "fingerprint": fingerprint,
    }


def enriched_record(
    card_id: str,
    image_path: Path,
    fingerprint: str,
    artwork_fingerprint: str,
) -> dict:
    return {
        **record(card_id, image_path, fingerprint),
        "artwork_fingerprint": artwork_fingerprint,
        "variant_marker_fingerprint": ArtworkIndexService.variant_marker_fingerprint(
            cv2.imread(str(image_path))
        ),
    }


def horsea_variant_fixture(marker: str) -> np.ndarray:
    """Create deterministic near-duplicate cards with distinct lower markers."""
    card = patterned_card(31415)
    cv2.rectangle(card, (275, 455), (455, 610), (225, 225, 225), -1)
    cv2.rectangle(card, (275, 455), (455, 610), (35, 35, 35), 3)
    if marker == "water":
        points = np.array([[365, 475], [325, 545], [365, 590], [405, 545]], np.int32)
        cv2.fillConvexPoly(card, points, (210, 105, 25))
        cv2.circle(card, (365, 545), 23, (245, 190, 80), -1)
    elif marker == "poke-ball":
        cv2.circle(card, (365, 535), 50, (20, 20, 190), -1)
        cv2.rectangle(card, (315, 530), (415, 540), (20, 20, 20), -1)
        cv2.circle(card, (365, 535), 16, (245, 245, 245), -1)
    elif marker == "master-ball":
        cv2.circle(card, (365, 535), 50, (180, 40, 170), -1)
        cv2.putText(card, "M", (340, 555), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 5)
    else:
        raise ValueError(marker)
    return card


def deterministic_horsea_service(tmp_path: Path) -> tuple[ArtworkIndexService, np.ndarray]:
    ids = {
        "water": "pokipair-gem_pack_vol_5-94bf1608afd5e88a",
        "poke-ball": "pokipair-gem_pack_vol_5-87e725b2f54ec31f",
        "master-ball": "pokipair-gem_pack_vol_5-master-ball",
    }
    images = {name: horsea_variant_fixture(name) for name in ids}
    paths = {}
    for name, image in images.items():
        paths[name] = tmp_path / f"horsea-{name}.png"
        assert cv2.imwrite(str(paths[name]), image)

    live = images["water"].copy()
    query = ArtworkIndexService.fingerprint(live)
    family = ArtworkIndexService.artwork_fingerprint(live)
    rows = [
        enriched_record(ids["poke-ball"], paths["poke-ball"], query, family),
        enriched_record(
            ids["water"], paths["water"],
            f"{int(query, 16) ^ ((1 << 25) - 1):016x}", family,
        ),
        enriched_record(
            ids["master-ball"], paths["master-ball"],
            f"{int(query, 16) ^ ((1 << 26) - 1):016x}", family,
        ),
    ]
    false_path = tmp_path / "csv5-false.png"
    assert cv2.imwrite(str(false_path), np.full_like(live, 127))
    rows.append(record("pokipair-csv5-859c27e686651bcc", false_path, query))
    for index in range(23):
        path = tmp_path / f"distractor-{index:02d}.png"
        distractor = np.full_like(live, 80 + index)
        assert cv2.imwrite(str(path), distractor)
        rows.append(record(
            f"distractor-{index:02d}", path,
            f"{int(query, 16) ^ (1 << (index % 20)) ^ index:016x}",
        ))
    return service_with_records(tmp_path, rows), live


def test_strong_geometry_overrides_small_hash_difference(tmp_path: Path) -> None:
    live = patterned_card()
    correct = tmp_path / "correct.png"
    wrong = tmp_path / "wrong.png"
    cv2.imwrite(str(correct), live)
    cv2.imwrite(str(wrong), patterned_card(99))
    query = ArtworkIndexService.fingerprint(live)
    false_better_hash = f"{int(query, 16) ^ 1:016x}"
    records = [
        record("wrong", wrong, false_better_hash),
        record("correct", correct, f"{int(query, 16) ^ 3:016x}"),
    ]

    matches = service_with_records(tmp_path, records).search(live)["matches"]

    assert matches[0]["id"] == "correct"
    assert matches[0]["verification_strong"] is True
    assert matches[0]["homography_inliers"] >= 10


def test_missing_image_falls_back_to_hash_order(tmp_path: Path) -> None:
    live = patterned_card()
    query = ArtworkIndexService.fingerprint(live)
    records = [
        record("nearest", tmp_path / "missing-a.png", query),
        record("second", tmp_path / "missing-b.png", f"{int(query, 16) ^ 1:016x}"),
    ]

    matches = service_with_records(tmp_path, records).search(live)["matches"]

    assert [item["id"] for item in matches] == ["nearest", "second"]
    assert not any(item["verification_strong"] for item in matches)


def test_feature_poor_card_does_not_receive_verification_boost(tmp_path: Path) -> None:
    live = np.full((700, 500, 3), 127, dtype=np.uint8)
    reference = tmp_path / "blank.png"
    cv2.imwrite(str(reference), live)
    fingerprint = ArtworkIndexService.fingerprint(live)
    match = service_with_records(
        tmp_path, [record("blank", reference, fingerprint)]
    ).search(live)["matches"][0]

    assert match["verification_strong"] is False
    assert match["retrieval_only"] is True
    assert match["score"] <= ArtworkIndexService.FAILED_VERIFICATION_CAP


def test_failed_geometry_is_demoted_below_verified_match(tmp_path: Path) -> None:
    live = patterned_card()
    correct = tmp_path / "correct.png"
    wrong = tmp_path / "wrong.png"
    cv2.imwrite(str(correct), live)
    cv2.imwrite(str(wrong), np.full_like(live, 127))
    query = ArtworkIndexService.fingerprint(live)
    matches = service_with_records(tmp_path, [
        record("wrong", wrong, query),
        record("correct", correct, f"{int(query, 16) ^ 3:016x}"),
    ]).search(live)["matches"]
    assert matches[0]["id"] == "correct"
    failed = next(item for item in matches if item["id"] == "wrong")
    assert failed["retrieval_only"] is True
    assert failed["score"] <= ArtworkIndexService.FAILED_VERIFICATION_CAP


def test_latest_live_variant_is_recovered_outside_hash_shortlist(tmp_path: Path) -> None:
    service, crop = deterministic_horsea_service(tmp_path)
    matches = service.search(crop)["matches"]
    wanted = "pokipair-gem_pack_vol_5-94bf1608afd5e88a"
    assert wanted in {item["id"] for item in matches}
    wanted_match = next(item for item in matches if item["id"] == wanted)
    assert wanted_match["family_expanded"] is True
    assert wanted_match["verification_strong"] is True
    assert wanted_match["artwork_verification_strong"] is True
    positions = {item["id"]: index for index, item in enumerate(matches)}
    assert positions[wanted] < positions["pokipair-gem_pack_vol_5-87e725b2f54ec31f"]
    assert positions[wanted] < positions["pokipair-gem_pack_vol_5-master-ball"]


def test_search_verifies_24_and_returns_at_most_10(tmp_path: Path, monkeypatch) -> None:
    live = patterned_card()
    fingerprint = ArtworkIndexService.fingerprint(live)
    records = [
        record(f"card-{index:02d}", tmp_path / f"missing-{index}.png", fingerprint)
        for index in range(30)
    ]
    service = service_with_records(tmp_path, records)
    calls = []
    monkeypatch.setattr(
        service,
        "_second_stage_evidence",
        lambda live_card, reference: calls.append(reference) or {
            "verification_strong": False,
            "verification_score": 0.0,
            "orb_matches": 0,
            "homography_inliers": 0,
            "inlier_ratio": 0.0,
            "structural_similarity": 0.0,
            "lower_structural_similarity": 0.0,
        },
    )

    matches = service.search(live, limit=50)["matches"]

    assert len(calls) == 24
    assert len(matches) == 10


def test_family_expansion_recovers_siblings_outside_hash_shortlist(
    tmp_path: Path,
) -> None:
    live = patterned_card()
    family = ArtworkIndexService.artwork_fingerprint(live)
    images = []
    for index in range(3):
        variant = live.copy()
        cv2.putText(
            variant,
            f"V{index}",
            (300, 540),
            cv2.FONT_HERSHEY_SIMPLEX,
            2,
            (20 + index * 60, 20, 20),
            8,
        )
        path = tmp_path / f"variant-{index}.png"
        cv2.imwrite(str(path), variant)
        images.append(path)
    query = ArtworkIndexService.fingerprint(live)
    rows = [
        enriched_record("seed", images[0], query, family),
        enriched_record("rank-111", images[1], f"{int(query, 16) ^ ((1 << 21) - 1):016x}", family),
        enriched_record("rank-209", images[2], f"{int(query, 16) ^ ((1 << 22) - 1):016x}", family),
    ]
    for index in range(30):
        path = tmp_path / f"decoy-{index}.png"
        cv2.imwrite(str(path), patterned_card(100 + index))
        rows.append(record(f"decoy-{index:02d}", path, f"{int(query, 16) ^ index:016x}"))

    matches = service_with_records(tmp_path, rows).search(live, limit=10)["matches"]
    ids = {item["id"] for item in matches}

    assert "rank-111" in ids
    assert "rank-209" in ids
    assert len(matches) == 10


def test_missing_family_fields_preserve_hash_fallback(tmp_path: Path) -> None:
    live = patterned_card()
    query = ArtworkIndexService.fingerprint(live)
    path = tmp_path / "reference.png"
    cv2.imwrite(str(path), live)
    matches = service_with_records(
        tmp_path,
        [record("legacy", path, query)],
    ).search(live)["matches"]

    assert matches[0]["id"] == "legacy"
    assert "family_expanded" not in matches[0]


def test_family_expansion_requires_strong_verified_seed(tmp_path: Path) -> None:
    live = np.full((700, 500, 3), 127, dtype=np.uint8)
    family = ArtworkIndexService.artwork_fingerprint(live)
    rows = []
    for index in range(2):
        path = tmp_path / f"blank-{index}.png"
        cv2.imwrite(str(path), live)
        rows.append(enriched_record(str(index), path, f"{index:016x}", family))

    matches = service_with_records(tmp_path, rows).search(live)["matches"]

    assert not any(item.get("family_expanded") for item in matches)


@pytest.mark.parametrize("marker_kind", ["reverse-holo", "stamped"])
def test_structural_variant_fixtures_resolve_correctly(
    tmp_path: Path, marker_kind: str
) -> None:
    base = patterned_card()
    correct = base.copy()
    wrong = base.copy()
    if marker_kind == "reverse-holo":
        for x in range(180, 470, 18):
            cv2.line(correct, (x, 390), (x - 80, 610), (245, 245, 245), 4)
        cv2.circle(wrong, (365, 520), 48, (10, 10, 10), 10)
    else:
        cv2.putText(correct, "STAMP", (270, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (5, 5, 5), 4)
        cv2.putText(wrong, "PLAIN", (270, 600), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (5, 5, 5), 4)
    family = ArtworkIndexService.artwork_fingerprint(base)
    query = ArtworkIndexService.fingerprint(correct)
    rows = []
    for card_id, image in (("correct", correct), ("wrong", wrong)):
        path = tmp_path / f"{card_id}.png"
        cv2.imwrite(str(path), image)
        rows.append(enriched_record(card_id, path, query, family))

    matches = service_with_records(tmp_path, rows).search(correct)["matches"]

    assert matches[0]["id"] == "correct"
    assert matches[0]["variant_marker_score"] > matches[1]["variant_marker_score"]


def test_color_support_cannot_override_structural_marker_evidence() -> None:
    live = patterned_card()
    structural = live.copy()
    wrong = np.empty_like(live)
    wrong[:] = live.mean(axis=(0, 1), dtype=np.float64)
    right_score = ArtworkIndexService._marker_evidence(live, structural)[
        "variant_marker_score"
    ]
    wrong_score = ArtworkIndexService._marker_evidence(live, wrong)[
        "variant_marker_score"
    ]

    assert right_score > wrong_score


def test_lower_card_structure_participates_in_score() -> None:
    live = patterned_card()
    same = ArtworkIndexService._second_stage_evidence(live, live.copy())
    altered = live.copy()
    altered[350:650] = 0
    different = ArtworkIndexService._second_stage_evidence(live, altered)

    assert same["verification_strong"] is True
    assert same["lower_structural_similarity"] > different["lower_structural_similarity"]
    assert same["verification_score"] > different["verification_score"]


def test_saved_horsea_crop_demotes_csv5_false_match(tmp_path: Path) -> None:
    service, crop = deterministic_horsea_service(tmp_path)

    matches = service.search(crop, limit=10)["matches"]
    positions = {item["id"]: index for index, item in enumerate(matches)}

    horsea = "pokipair-gem_pack_vol_5-94bf1608afd5e88a"
    false_csv5 = "pokipair-csv5-859c27e686651bcc"
    assert horsea in positions
    assert positions[horsea] < positions.get(false_csv5, len(matches))
    horsea_match = next(item for item in matches if item["id"] == horsea)
    assert horsea_match["verification_strong"] is True
    false_match = next(item for item in matches if item["id"] == false_csv5)
    assert false_match["retrieval_only"] is True
    assert false_match["score"] <= ArtworkIndexService.FAILED_VERIFICATION_CAP
