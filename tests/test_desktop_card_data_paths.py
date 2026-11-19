"""Reference data remains private profile data, separate from bundled resources."""
import json
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rareiq.services import artwork_index_service as artwork
from rareiq.services import multi_card_recognition_service as multi


def _catalog(root, label):
    catalog = root / "catalog_master"
    (catalog / "recognition").mkdir(parents=True)
    (catalog / "pokipair_identity_overrides.json").write_text(json.dumps({
        "SYNTHETIC:7": {"canonical_name": label, "english_name": label},
        "SHARED:1": {"canonical_name": "first override"},
    }), encoding="utf-8")
    (catalog / "stream_speed_identity_overrides.json").write_text(json.dumps({
        "SHARED:1": {"canonical_name": "second override"},
    }), encoding="utf-8")
    (catalog / "recognition/pokipair_cards.json").write_text(json.dumps({"records": [
        {"set_id": "SYNTHETIC", "collector_number": "7", "english_name": "unresolved synthetic"},
    ]}), encoding="utf-8")
    return catalog


@pytest.fixture
def roots(tmp_path, monkeypatch):
    resources = tmp_path / "resources/backend"
    profile = tmp_path / "profile/backend"
    service_dir = resources / "rareiq/services"
    service_dir.mkdir(parents=True)
    monkeypatch.setattr(artwork, "__file__", str(service_dir / "artwork_index_service.py"))
    monkeypatch.setattr(multi, "__file__", str(service_dir / "multi_card_recognition_service.py"))
    _catalog(resources, "resource copy must stay private")
    _catalog(profile, "profile synthetic identity")
    return SimpleNamespace(resources=resources, profile=profile)


def test_bundled_loaders_read_profile_catalog_and_never_read_or_write_resource_data(roots, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    snapshots = {path: path.read_bytes() for path in roots.resources.rglob("*") if path.is_file()}
    path_type = type(roots.resources)
    original_read = path_type.read_text

    def read(path, *args, **kwargs):
        assert not path.is_relative_to(roots.resources), "bundled service read resource catalog"
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(path_type, "read_text", read)
    overrides = artwork.ArtworkIndexService._load_identity_overrides()
    assert overrides["SYNTHETIC:7"]["canonical_name"] == "profile synthetic identity"
    assert overrides["SHARED:1"]["canonical_name"] == "second override", "existing override precedence is preserved"
    cards = multi.MultiCardRecognitionService._load_reference_cards()
    assert cards[0]["canonical_name"] == "profile synthetic identity"
    assert cards[0]["identity_override_key"] == "SYNTHETIC:7"
    assert {path: path.read_bytes() for path in roots.resources.rglob("*") if path.is_file()} == snapshots


@pytest.mark.parametrize("desktop, explicit_root", [("0", True), ("1", False)])
def test_web_and_desktop_without_explicit_data_root_keep_repository_relative_catalogs(roots, monkeypatch, desktop, explicit_root):
    monkeypatch.setenv("PRODUCER_DESKTOP", desktop)
    if explicit_root:
        monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    else:
        monkeypatch.delenv("PRODUCER_DESKTOP_DATA_ROOT", raising=False)
    assert artwork.ArtworkIndexService._load_identity_overrides()["SYNTHETIC:7"]["canonical_name"] == "resource copy must stay private"
    assert multi.MultiCardRecognitionService._load_reference_cards()[0]["canonical_name"] == "resource copy must stay private"


def test_missing_profile_catalog_does_not_fall_back_to_bundled_operator_data(roots, tmp_path, monkeypatch):
    empty = tmp_path / "fresh-profile/backend"
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(empty))
    assert artwork.ArtworkIndexService._load_identity_overrides() == {}
    assert multi.MultiCardRecognitionService._load_reference_cards() == []
    assert not empty.exists(), "read-only reference loading must not initialize or migrate user data"


def test_explicit_artwork_history_and_presentation_paths_still_win_over_defaults(roots, tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    custom = tmp_path / "custom"
    custom.mkdir()
    index = custom / "explicit-index.json"
    index.write_text('{"records": []}', encoding="utf-8")
    service = artwork.ArtworkIndexService(index_path=index)
    assert service.index_path == index
    assert service.reference_dir == roots.profile / "rareiq/data/reference_cards"
    history, presentation = custom / "history.json", custom / "presentation.json"
    prototype = SimpleNamespace(isolated_copy=lambda _callback: SimpleNamespace())
    recognition = multi.MultiCardRecognitionService(prototype, history_path=history, presentation_path=presentation)
    assert recognition._temporal_history_path == history
    assert recognition._presentation_path == presentation


def _image(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.full((8, 8, 3), value, dtype=np.uint8))
    return path


def _feature_loader(monkeypatch):
    service = multi.MultiCardRecognitionService.__new__(multi.MultiCardRecognitionService)
    service._reference_feature_cache = {}
    service._reference_feature_cache_lock = threading.RLock()
    # Exercise real file lookup/PNG decoding, without a model or recognition run.
    service._sift_descriptors = lambda image, *, treatment: int(image[0, 0, 0])
    monkeypatch.setattr(artwork.ArtworkIndexService, "variant_marker_fingerprint", staticmethod(lambda image: str(int(image[0, 0, 0]))))
    return service


def test_migrated_relative_images_and_all_internal_default_bases_use_profile_not_resource_decoys(roots, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    relative = "catalog_master/reference_cards/synthetic.png"
    profile_image = _image(roots.profile, relative, 100)
    decoy = _image(roots.resources, relative, 3)
    decoy_before = decoy.read_bytes()
    read = cv2.imread
    observed = []

    def guarded_read(path, *args, **kwargs):
        observed.append(path)
        assert path == str(profile_image), "default reference lookup used bundled resources"
        return read(path, *args, **kwargs)
    monkeypatch.setattr(cv2, "imread", guarded_read)
    service = _feature_loader(monkeypatch)
    record = {"canonical_name": "Synthetic", "set_id": "SYNTHETIC", "reference_image": relative}
    service._reference_cards = [record]
    service._crop_cache = {1: np.full((8, 8, 3), 100, dtype=np.uint8), 2: np.full((8, 8, 3), 100, dtype=np.uint8)}
    service._descriptor_score = lambda _live, reference: float(reference)
    service._variant_marker_score = lambda _live, _reference: 0.0
    assert int(service._reference_features(record)["image"][0, 0, 0]) == 100
    assert len(service._named_reference_matches_crop("Synthetic", service._crop_cache[1])) == 1
    assert service._best_artwork_family(1) == "Synthetic"
    service._state = {"slots": [{"slot": 1, "card": dict(record)}, {"slot": 2, "card": dict(record)}]}
    service._resolve_visual_variant_families()
    assert len(observed) == 2, "cached feature lookups and the direct family lookup both decoded profile data"
    assert decoy.read_bytes() == decoy_before


def test_explicit_reference_root_and_absolute_image_paths_are_preserved_in_bundled_mode(roots, tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    relative = "reference_cards/custom.png"
    custom = tmp_path / "explicit-reference-root"
    _image(custom, relative, 77)
    _image(roots.profile, relative, 3)
    absolute = _image(tmp_path / "absolute-reference", "exact.png", 88)
    service = _feature_loader(monkeypatch)
    assert int(service._reference_features({"reference_image": relative}, project_root=custom)["image"][0, 0, 0]) == 77
    assert int(service._reference_features({"reference_image": str(absolute)}, project_root=custom)["image"][0, 0, 0]) == 88


@pytest.mark.parametrize("desktop, explicit_root", [("0", True), ("1", False)])
def test_relative_image_default_keeps_repository_root_without_desktop_data_opt_in(roots, monkeypatch, desktop, explicit_root):
    monkeypatch.setenv("PRODUCER_DESKTOP", desktop)
    if explicit_root:
        monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(roots.profile))
    else:
        monkeypatch.delenv("PRODUCER_DESKTOP_DATA_ROOT", raising=False)
    relative = "catalog_master/reference_cards/synthetic.png"
    _image(roots.resources, relative, 33)
    _image(roots.profile, relative, 99)
    service = _feature_loader(monkeypatch)
    assert int(service._reference_features({"reference_image": relative})["image"][0, 0, 0]) == 33
