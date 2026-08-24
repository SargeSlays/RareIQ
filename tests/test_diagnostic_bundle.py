from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import tools.diagnostic_bundle as diagnostics
from rareiq.core.storage import StorageManager
from tools.diagnostic_bundle import DiagnosticBundleError, create_bundle, verify_bundle


def _project(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    project = tmp_path / "RareIQ"
    project.mkdir()
    roots = {
        key: tmp_path / "runtime" / key
        for key in StorageManager.REQUIRED_PATHS
    }
    (project / "storage_config.json").write_text(
        json.dumps({key: str(value) for key, value in roots.items()}),
        encoding="utf-8",
    )
    (project / "rareiq").mkdir()
    (project / "rareiq/version.py").write_text(
        'def version_payload(): return {"version": "test"}\n',
        encoding="utf-8",
    )
    return project, roots


def test_bundle_dry_run_is_non_mutating_and_excludes_runtime_data(tmp_path, monkeypatch):
    project, roots = _project(tmp_path)
    monkeypatch.setattr(diagnostics, "_git", lambda *_args: "")

    report = create_bundle(project)

    assert report["mode"] == "dry-run"
    assert report["secrets_included"] is False
    assert report["captures_included"] is False
    assert report["databases_included"] is False
    assert Path(report["output"]).exists() is False
    assert not roots["export_path"].joinpath("diagnostics").exists()


def test_bundle_is_redacted_bounded_manifest_backed_and_verified(tmp_path, monkeypatch):
    project, roots = _project(tmp_path)
    manager = StorageManager(project_root=project)
    manager.initialize()
    server_root = manager.get_path("log_path") / "server"
    server_root.mkdir(parents=True)
    (server_root / "server-control.json").write_text(
        json.dumps({"version": 1, "host": "127.0.0.1", "port": 65534, "api_key": "state-secret"}),
        encoding="utf-8",
    )
    secret = "super-secret-value"
    bearer = "Bearer abcdefghijklmnopqrstuvwxyz"
    (server_root / "server-20260823.err.log").write_text(
        f"startup api_key={secret}\nAuthorization: {bearer}\n",
        encoding="utf-8",
    )
    (manager.get_path("capture_path") / "private-card.png").write_bytes(b"never include")
    (manager.get_path("database_root") / "collection.json").write_text("{}", encoding="utf-8")
    (project / "rareiq_secrets.json").write_text(json.dumps({"api_key": secret}), encoding="utf-8")
    monkeypatch.setattr(diagnostics, "_git", lambda *_args: "")
    output = roots["export_path"] / "diagnostics" / "support.zip"

    report = create_bundle(project, output=output, apply=True)

    assert report["verification"]["passed"] is True
    assert verify_bundle(output)["passed"] is True
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        combined = b"\n".join(archive.read(name) for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        payload = json.loads(archive.read("report.json"))
    assert names.count("manifest.json") == 1
    assert manifest["secrets_included"] is False
    assert payload["privacy"]["captures_included"] is False
    assert secret.encode() not in combined
    assert bearer.encode() not in combined
    assert b"[REDACTED]" in combined
    assert not any("private-card" in name or "collection" in name or "secret" in name.casefold() for name in names)
    assert all(name == "report.json" or name == "manifest.json" or name.startswith("logs/") for name in names)


def test_bundle_verification_detects_duplicate_or_unmanifested_entries(tmp_path, monkeypatch):
    project, _roots = _project(tmp_path)
    monkeypatch.setattr(diagnostics, "_git", lambda *_args: "")
    output = tmp_path / "support.zip"
    create_bundle(project, output=output, apply=True)

    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr("unexpected.txt", b"tampered")

    with pytest.raises(DiagnosticBundleError, match="unmanifested"):
        verify_bundle(output)


def test_redaction_handles_nested_sensitive_values_and_bearer_tokens():
    payload = diagnostics._redact({
        "client_secret": {"nested": "value"},
        "message": "password=hunter2 Authorization: Bearer abc.def.ghi",
    })

    assert payload["client_secret"] == "[REDACTED]"
    assert "hunter2" not in payload["message"]
    assert "abc.def.ghi" not in payload["message"]
