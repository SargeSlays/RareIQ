import json
import threading
import time

import cv2
import numpy as np

from rareiq.services.artwork_index_service import ArtworkIndexService
from rareiq.services.catalog_service import CatalogService


def build_index(tmp_path):
    records = []
    for number in range(1, 21):
        image_path = tmp_path / f"card-{number}.png"
        cv2.imwrite(str(image_path), np.full((40, 30, 3), number, dtype=np.uint8))
        records.append({
            "id": f"card-{number}", "fingerprint": "0" * 64,
            "image_path": str(image_path), "printed_code": f"{number:03d}/020",
            "set_id": "me05", "set_name": "Pitch Black", "language": "English",
        })
    path = tmp_path / "artwork_index.json"
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return path


def test_learned_successor_exposes_prefetch_record(tmp_path):
    service = ArtworkIndexService(build_index(tmp_path))
    service.set_active_filter("Pitch Black", "English", "me05")
    service.observe_verified_card("010/020")
    service.observe_verified_card("018/020")
    service.observe_verified_card("010/020")
    service.observe_verified_card("018/020")
    assert [row["printed_code"] for row in service.predicted_transition_records("010/020")] == ["018/020"]


def test_catalog_prediction_prefetch_is_background_and_tracks_status(tmp_path, monkeypatch):
    service = CatalogService(lambda event: None, tmp_path / "catalog")
    completed = threading.Event()

    def lookup(language_code, number):
        completed.set()
        return {"candidates": []}

    monkeypatch.setattr(service, "_lookup_language", lookup)
    queued = service.prefetch_predictions([{"printed_code": "018/020", "language": "English"}])
    assert queued == 1
    assert completed.wait(2)
    deadline = time.time() + 2
    while service.status()["prediction_prefetch"]["active"] and time.time() < deadline:
        time.sleep(0.01)
    status = service.status()["prediction_prefetch"]
    assert status["warmed"] == 1
    assert status["active"] == 0
    service.shutdown()


def test_consumed_prediction_records_estimated_time_saved(tmp_path):
    service = CatalogService(lambda event: None, tmp_path / "catalog")
    service._write_cache("en", "018/020", {"candidates": []})
    service._prefetched_lookup_ms["en|018/020"] = 347.5

    assert service._lookup_language("en", "018/020")["source"] == "cache"
    stats = service.status()["prediction_prefetch"]
    assert stats["consumed"] == 1
    assert stats["estimated_saved_ms"] == 347.5
    assert stats["last_saved_ms"] == 347.5
    assert stats["ready"] == 0
    service.shutdown()
