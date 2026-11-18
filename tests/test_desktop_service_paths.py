"""Synthetic resources/profile checks; no application singleton or devices start."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def isolated_services(monkeypatch, tmp_path):
    bundle, profile = tmp_path / "bundled-resources", tmp_path / "desktop-profile"
    monkeypatch.setenv("PRODUCER_DESKTOP", "1")
    monkeypatch.setenv("PRODUCER_DESKTOP_DATA_ROOT", str(profile))
    modules = {}
    for name in ("overlay_state", "multi_card_recognition", "artwork_index", "live_catalog", "set_catalog", "cardgrader"):
        module = importlib.import_module(f"rareiq.services.{name}_service")
        monkeypatch.setattr(module, "__file__", str(bundle / "rareiq" / "services" / f"{name}_service.py"))
        modules[name] = module
    # CardGrader's external credentials/provider behavior is outside this path test.
    class EmptySecrets:
        def __init__(self, path): self.path = path
        def reload(self): pass
        def get(self, key): return None
    monkeypatch.setattr(modules["cardgrader"], "SecretsManager", EmptySecrets)
    seed = bundle / "rareiq" / "data" / "set_catalog.json"
    seed.parent.mkdir(parents=True)
    seed.write_text(json.dumps({"version": 1, "sets": [{"id": "fixture-set", "name": "Synthetic set"}], "active_set_id": "all-loaded", "selection_mode": "auto"}), encoding="utf-8")
    return SimpleNamespace(modules=modules, bundle=bundle, profile=profile, seed=seed)


class Prototype:
    artwork_index = None
    def isolated_copy(self, callback): return SimpleNamespace()


def test_desktop_defaults_write_only_profile_and_leave_bundled_seed_unchanged(isolated_services):
    f = isolated_services
    seed = f.seed.read_bytes()
    overlay = f.modules["overlay_state"].OverlayStateService()
    overlay.update({"pokedex_on_air": False})
    multi = f.modules["multi_card_recognition"].MultiCardRecognitionService(Prototype())
    multi._persist_temporal_history()
    multi._persist_presentation()
    artwork = f.modules["artwork_index"].ArtworkIndexService()
    assert artwork.rebuild()["ok"] is True
    catalog_cache = f.modules["live_catalog"].LiveCatalogService(artwork)
    catalog = f.modules["set_catalog"].SetCatalogService()
    assert catalog.list_sets() == [{"id": "fixture-set", "name": "Synthetic set"}]
    assert not catalog.catalog_path.exists(), "Reading a bundled seed must not copy developer state"
    catalog.set_active("fixture-set")
    grader_module = f.modules["cardgrader"]
    grader = grader_module.CardGraderService()
    synthetic = grader.save_frame(grader_module.np.zeros((16, 16, 3), dtype="uint8"), "synthetic")
    written = [overlay._state_path, multi._temporal_history_path, multi._presentation_path,
               artwork.index_path, catalog.catalog_path, synthetic]
    assert all(path.is_file() and path.is_relative_to(f.profile) for path in written)
    for directory in (artwork.reference_dir, catalog_cache.images_dir, catalog_cache.metadata_dir, grader.capture_dir):
        assert directory.is_dir() and directory.is_relative_to(f.profile)
    assert artwork.transition_model_path.is_relative_to(f.profile)
    assert artwork.transition_backup_dir.is_relative_to(f.profile)
    assert grader.secrets_path.is_relative_to(f.profile)
    assert f.seed.read_bytes() == seed
    assert [path for path in f.bundle.rglob("*") if path.is_file()] == [f.seed]


def test_explicit_service_paths_are_preserved_in_desktop_mode(isolated_services, tmp_path):
    f = isolated_services
    custom = tmp_path / "explicit-destinations"
    custom.mkdir()
    overlay = f.modules["overlay_state"].OverlayStateService(custom / "overlay.json")
    multi = f.modules["multi_card_recognition"].MultiCardRecognitionService(Prototype(), custom / "history.json", custom / "presentation.json")
    artwork = f.modules["artwork_index"].ArtworkIndexService(custom / "artwork.json")
    live = f.modules["live_catalog"].LiveCatalogService(artwork, custom / "cache")
    catalog = f.modules["set_catalog"].SetCatalogService(custom / "catalog.json")
    grader = f.modules["cardgrader"].CardGraderService(custom / "grading")
    assert overlay._state_path == custom / "overlay.json"
    assert multi._temporal_history_path == custom / "history.json"
    assert multi._presentation_path == custom / "presentation.json"
    assert artwork.index_path == custom / "artwork.json"
    assert artwork.transition_model_path == custom / "pack_transition_model.json"
    assert live.cache_root == custom / "cache"
    assert catalog.catalog_path == custom / "catalog.json" and catalog._seed_path is None
    assert grader.project_root == custom / "grading"
    assert artwork.reference_dir.is_relative_to(f.profile), "Independent writable reference default remains profile-owned"


def test_desktop_catalog_uses_existing_profile_without_overwriting_or_fallback(isolated_services):
    f = isolated_services
    catalog = f.modules["set_catalog"].SetCatalogService()
    catalog.configure(mode="pack", set_id="operator-selection", set_name="Saved profile selection")
    restored = f.modules["set_catalog"].SetCatalogService()
    assert restored.status()["active_set_id"] == "operator-selection"
    assert restored.status()["selection_mode"] == "pack"
    restored.catalog_path.write_text("invalid profile json", encoding="utf-8")
    invalid = f.modules["set_catalog"].SetCatalogService()
    assert invalid.list_sets() == [] and invalid.status()["ok"] is False
    assert invalid.catalog_path.read_text(encoding="utf-8") == "invalid profile json"


@pytest.mark.parametrize("desktop", [None, "0"])
def test_non_desktop_defaults_remain_source_relative(isolated_services, monkeypatch, desktop):
    f = isolated_services
    if desktop is None:
        monkeypatch.delenv("PRODUCER_DESKTOP")
    else:
        monkeypatch.setenv("PRODUCER_DESKTOP", desktop)
    data = f.bundle / "rareiq" / "data"
    overlay = f.modules["overlay_state"].OverlayStateService()
    multi = f.modules["multi_card_recognition"].MultiCardRecognitionService(Prototype())
    artwork = f.modules["artwork_index"].ArtworkIndexService()
    live = f.modules["live_catalog"].LiveCatalogService(artwork)
    catalog = f.modules["set_catalog"].SetCatalogService()
    grader = f.modules["cardgrader"].CardGraderService()
    assert overlay._state_path == data / "overlay_presentation.json"
    assert multi._temporal_history_path == data / "temporal_multi_card_history.json"
    assert multi._presentation_path == data / "multi_card_presentation.json"
    assert artwork.index_path == data / "artwork_index.json"
    assert artwork.reference_dir == data / "reference_cards"
    assert live.cache_root == f.bundle / "catalog_cache"
    assert catalog.catalog_path == f.seed and catalog._seed_path is None
    assert grader.project_root == f.bundle
