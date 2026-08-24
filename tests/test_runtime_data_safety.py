from __future__ import annotations

import json
from pathlib import Path

import pytest

from rareiq.core.secrets import SecretsManager
from rareiq.core.storage import StorageManager
from rareiq.services.cardgrader_service import CardGraderService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _storage_payload(prefix: str = "runtime") -> dict[str, str]:
    return {
        key: f"{prefix}/{key}"
        for key in StorageManager.REQUIRED_PATHS
    }


def test_storage_manager_seeds_local_config_and_resolves_relative_paths(tmp_path):
    example = tmp_path / "storage_config.example.json"
    example.write_text(json.dumps(_storage_payload()), encoding="utf-8")
    manager = StorageManager(project_root=tmp_path)

    manager.initialize()

    assert manager.config_file == tmp_path / "storage_config.json"
    assert manager.config_file.read_bytes() == example.read_bytes()
    for key in StorageManager.REQUIRED_PATHS:
        assert manager.get_path(key) == (tmp_path / "runtime" / key).resolve()
        assert manager.get_path(key).is_dir()


def test_storage_manager_rejects_non_string_paths(tmp_path):
    payload = _storage_payload()
    payload["capture_path"] = 42
    (tmp_path / "storage_config.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="capture_path"):
        StorageManager(project_root=tmp_path).initialize()


def test_secret_updates_preserve_unrelated_credentials_and_are_atomic(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEMONTCG_API_KEY", raising=False)
    path = tmp_path / "rareiq_secrets.json"
    path.write_text(json.dumps({"pokemontcg_api_key": "keep-me"}), encoding="utf-8")
    manager = SecretsManager(path)

    manager.update({"cardgrader_api_key": "cgk_example"})

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted == {
        "pokemontcg_api_key": "keep-me",
        "cardgrader_api_key": "cgk_example",
    }
    assert not path.with_name("rareiq_secrets.tmp.json").exists()
    assert manager.public_status() == {"pokemontcg_api_key_loaded": True}
    assert "keep-me" not in str(manager.public_status())


def test_secret_update_refuses_to_overwrite_malformed_file(tmp_path):
    path = tmp_path / "rareiq_secrets.json"
    path.write_text("not-json", encoding="utf-8")
    manager = SecretsManager(path)

    with pytest.raises(ValueError, match="valid JSON"):
        manager.update({"cardgrader_api_key": "cgk_example"})

    assert path.read_text(encoding="utf-8") == "not-json"


def test_cardgrader_secret_save_preserves_provider_key(tmp_path, monkeypatch):
    monkeypatch.delenv("POKEMONTCG_API_KEY", raising=False)
    path = tmp_path / "rareiq_secrets.json"
    path.write_text(json.dumps({"pokemontcg_api_key": "provider-key"}), encoding="utf-8")
    service = CardGraderService(project_root=tmp_path)
    service._api_key = "cgk_cardgrader"
    service._agent = {"agentId": "agent-1"}

    service._save_secrets()

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["pokemontcg_api_key"] == "provider-key"
    assert persisted["cardgrader_api_key"] == "cgk_cardgrader"
    assert persisted["cardgrader_agent"] == {"agentId": "agent-1"}


def test_local_runtime_and_sensitive_files_have_ignore_rules():
    patterns = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for expected in (
        "storage_config.json",
        "rareiq_secrets*.json",
        "runtime/",
        "captures/",
        "rareiq/data/artwork_index.json",
        "rareiq/data/provenance/",
    ):
        assert expected in patterns
    assert "!rareiq_secrets.example.json" in patterns
