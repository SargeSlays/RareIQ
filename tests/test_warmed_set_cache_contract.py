import json

from rareiq.services.artwork_index_service import ArtworkIndexService


def build_index(tmp_path, count=4):
    path = tmp_path / "artwork.json"
    records = [
        {
            "id": f"pitch-{index}",
            "set_id": "me05",
            "set_name": "Pitch Black",
            "language": "English",
            "fingerprint": f"{index + 1:016x}",
        }
        for index in range(count)
    ]
    records.append({
        "id": "other-1",
        "set_id": "other",
        "set_name": "Other Set",
        "language": "English",
        "fingerprint": "ffffffffffffffff",
    })
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return path


def test_active_set_is_warmed_once_and_reused(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path))
    service.set_active_filter("Pitch Black", "English", "me05")
    warm = service.status()["warmed_set_cache"]
    assert warm["ready"] is True
    assert warm["record_count"] == 4
    first = service._records_for_active_filter()
    second = service._records_for_active_filter()
    assert {row["set_id"] for row in first} == {"me05"}
    assert first == second
    assert service.status()["warmed_set_cache"]["hits"] == 2


def test_cache_never_truncates_large_active_set(tmp_path, monkeypatch):
    monkeypatch.setattr(ArtworkIndexService, "ACTIVE_SET_CACHE_LIMIT", 2)
    service = ArtworkIndexService(build_index(tmp_path, count=4))
    service.set_active_filter("Pitch Black", "English", "me05")
    assert service.status()["warmed_set_cache"]["ready"] is False
    assert len(service._records_for_active_filter()) == 4


def test_changing_set_invalidates_and_rebuilds_cache(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path))
    service.set_active_filter("Pitch Black", "English", "me05")
    first_key = service.status()["warmed_set_cache"]["key"]
    service.set_active_filter("Other Set", "English", "other")
    status = service.status()["warmed_set_cache"]
    assert status["ready"] is True
    assert status["record_count"] == 1
    assert status["key"] != first_key
