from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rareiq.core.secrets import SecretsManager
from rareiq.core.storage import StorageManager
from rareiq.services.cardgrader_service import CardGraderService
from tools.runtime_recovery import FileSet, create_snapshot


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
    capture_root = manager.get_path("capture_path")
    assert manager.get_path("provenance_path") == capture_root / "provenance"
    assert manager.get_path("replay_path") == capture_root / "replays"
    assert manager.get_path("recording_path") == capture_root / "recordings"


def test_storage_manager_allows_explicit_runtime_media_roots(tmp_path):
    payload = _storage_payload()
    payload.update({
        "provenance_path": "media/evidence",
        "replay_path": "media/replays",
        "recording_path": "media/recordings",
    })
    (tmp_path / "storage_config.json").write_text(json.dumps(payload), encoding="utf-8")

    manager = StorageManager(project_root=tmp_path)
    manager.initialize()

    assert manager.get_path("provenance_path") == (tmp_path / "media/evidence").resolve()
    assert manager.get_path("replay_path") == (tmp_path / "media/replays").resolve()
    assert manager.get_path("recording_path") == (tmp_path / "media/recordings").resolve()


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


def test_example_config_exposes_large_runtime_media_roots():
    payload = json.loads((PROJECT_ROOT / "storage_config.example.json").read_text(encoding="utf-8"))

    assert payload["provenance_path"].endswith("captures/provenance")
    assert payload["replay_path"].endswith("captures/replays")
    assert payload["recording_path"].endswith("captures/recordings")


def test_storage_status_reports_manifest_verified_recovery_health(tmp_path):
    (tmp_path / "storage_config.json").write_text(json.dumps(_storage_payload()), encoding="utf-8")
    manager = StorageManager(project_root=tmp_path)
    manager.initialize()
    state = manager.get_path("database_root") / "state.json"
    state.write_text("{}", encoding="utf-8")
    report = create_snapshot(
        {"database": FileSet(manager.get_path("database_root"), (state,))},
        manager.get_path("backup_path") / "runtime-snapshots",
        apply=True,
    )

    recovery = manager.status()["recovery"]

    assert recovery["state"] == "healthy"
    assert recovery["valid_snapshot_count"] == 1
    assert recovery["invalid_snapshot_count"] == 0
    assert recovery["latest_snapshot_id"] == report["snapshot_id"]
    assert recovery["verification_scope"] == "manifest"


def test_storage_status_distinguishes_missing_stale_and_invalid_snapshots(tmp_path):
    (tmp_path / "storage_config.json").write_text(json.dumps(_storage_payload()), encoding="utf-8")
    manager = StorageManager(project_root=tmp_path)
    manager.initialize()
    assert manager.recovery_status()["state"] == "missing"

    state = manager.get_path("database_root") / "state.json"
    state.write_text("{}", encoding="utf-8")
    report = create_snapshot(
        {"database": FileSet(manager.get_path("database_root"), (state,))},
        manager.get_path("backup_path") / "runtime-snapshots",
        apply=True,
    )
    snapshot = Path(report["snapshot_path"])
    manifest_path = snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    import hashlib
    (snapshot / "manifest.sha256").write_text(hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "\n", encoding="ascii")
    assert manager.recovery_status()["state"] == "stale"
    stale_health = manager.health()
    assert stale_health["healthy"] is True
    assert stale_health["state"] == "warning"

    (snapshot / "manifest.sha256").write_text("0" * 64, encoding="ascii")
    invalid = manager.recovery_status()
    assert invalid["state"] == "invalid"
    assert invalid["valid_snapshot_count"] == 0
    assert invalid["invalid_snapshot_count"] == 1
    invalid_health = manager.health()
    assert invalid_health["healthy"] is False
    assert invalid_health["state"] == "error"


def test_storage_health_is_truthful_without_treating_first_run_as_failure(tmp_path, monkeypatch):
    (tmp_path / "storage_config.json").write_text(json.dumps(_storage_payload()), encoding="utf-8")
    manager = StorageManager(project_root=tmp_path)
    manager.initialize()

    first_run = manager.health()
    assert first_run["healthy"] is True
    assert first_run["state"] == "warning"
    assert first_run["recovery"]["state"] == "missing"

    monkeypatch.setattr(
        manager,
        "status",
        lambda: {
            "root": str(tmp_path),
            "free_bytes": manager.MIN_FREE_BYTES - 1,
            "recovery": {"state": "healthy"},
        },
    )
    low_space = manager.health()
    assert low_space["healthy"] is False
    assert low_space["state"] == "error"
    assert "2 GiB" in low_space["message"]
