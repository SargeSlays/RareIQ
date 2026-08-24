from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.build_release import ReleaseBuildError, build_release, smoke_release, verify_release


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "RareIQ"
    (project / "rareiq").mkdir(parents=True)
    (project / "rareiq/version.py").write_text(
        'VERSION = "6.4.17-test"\n', encoding="utf-8"
    )
    (project / "rareiq/__init__.py").write_bytes(b"")
    (project / "app.py").write_text('print("RareIQ")\n', encoding="utf-8")
    (project / "storage_config.example.json").write_text("{}\n", encoding="utf-8")
    (project / "rareiq_secrets.example.json").write_text("{}\n", encoding="utf-8")
    _git(project, "init")
    _git(project, "config", "user.email", "tests@rareiq.local")
    _git(project, "config", "user.name", "RareIQ Tests")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "fixture")
    return project


def test_release_build_is_dry_run_first_and_uses_only_committed_tree(tmp_path):
    project = _project(tmp_path)
    output = tmp_path / "release.zip"

    report = build_release(project, output=output)

    assert report["mode"] == "dry-run"
    assert report["release_version"] == "6.4.17-test"
    assert report["files"] == 5
    assert report["runtime_data_included"] is False
    assert report["secrets_included"] is False
    assert output.exists() is False


def test_release_is_deterministic_manifest_backed_and_verified(tmp_path):
    project = _project(tmp_path)
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_report = build_release(project, output=first, apply=True)
    second_report = build_release(project, output=second, apply=True)

    assert first.read_bytes() == second.read_bytes()
    assert first_report["archive_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert first_report["verification"]["passed"] is True
    assert verify_release(second)["source_commit"] == first_report["source_commit"]
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        manifest_name = next(name for name in names if name.endswith("/release-manifest.json"))
        manifest = json.loads(archive.read(manifest_name))
    assert all(name.startswith("RareIQ-6.4.17-test/") for name in names)
    assert manifest["runtime_data_included"] is False
    assert manifest["secrets_included"] is False
    assert len(manifest["files"]) == 5


def test_failed_post_build_verification_removes_published_archive(tmp_path, monkeypatch):
    import tools.build_release as builder

    project = _project(tmp_path)
    output = tmp_path / "release.zip"
    monkeypatch.setattr(
        builder,
        "verify_release",
        lambda _path: (_ for _ in ()).throw(ReleaseBuildError("simulated verification failure")),
    )

    with pytest.raises(ReleaseBuildError, match="simulated verification failure"):
        builder.build_release(project, output=output, apply=True)

    assert output.exists() is False


def test_release_build_refuses_dirty_worktree(tmp_path):
    project = _project(tmp_path)
    (project / "app.py").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ReleaseBuildError, match="clean Git worktree"):
        build_release(project, output=tmp_path / "release.zip")


@pytest.mark.parametrize(
    "path",
    [
        "storage_config.json",
        "rareiq_secrets.json",
        ".env",
        "captures/card.png",
        "runtime/state.json",
        "package/__pycache__/module.pyc",
    ],
)
def test_release_build_fails_closed_if_sensitive_or_runtime_path_is_tracked(tmp_path, path):
    project = _project(tmp_path)
    candidate = project / path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("sensitive", encoding="utf-8")
    _git(project, "add", "-f", path)
    _git(project, "commit", "-m", "bad fixture")

    with pytest.raises(ReleaseBuildError, match="cannot enter a release"):
        build_release(project, output=tmp_path / "release.zip")


def test_release_verification_rejects_unmanifested_payload(tmp_path):
    project = _project(tmp_path)
    output = tmp_path / "release.zip"
    build_release(project, output=output, apply=True)
    with zipfile.ZipFile(output, "a") as archive:
        archive.writestr("RareIQ-6.4.17-test/unexpected.txt", b"tampered")

    with pytest.raises(ReleaseBuildError, match="unmanifested"):
        verify_release(output)


def test_clean_install_smoke_extracts_safely_seeds_config_and_cleans_up(tmp_path):
    project = _project(tmp_path)
    archive = tmp_path / "release.zip"
    build_release(project, output=archive, apply=True)
    work_root = tmp_path / "smoke"
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        assert (Path(kwargs["cwd"]) / "storage_config.json").is_file()
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        return SimpleNamespace(returncode=0, stdout="passed", stderr="")

    report = smoke_release(
        archive,
        python=Path(__import__("sys").executable),
        work_root=work_root,
        runner=runner,
    )

    assert report["passed"] is True
    assert report["external_runtime_data_required"] is False
    assert [item["name"] for item in report["checks"]] == [
        "source_syntax", "application_import", "canonical_tests"
    ]
    assert len(calls) == 3
    assert list(work_root.iterdir()) == []


def test_failed_clean_install_smoke_also_removes_disposable_install(tmp_path):
    project = _project(tmp_path)
    archive = tmp_path / "release.zip"
    build_release(project, output=archive, apply=True)
    work_root = tmp_path / "smoke"

    def runner(_command, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="simulated failure")

    with pytest.raises(ReleaseBuildError, match="simulated failure"):
        smoke_release(
            archive,
            python=Path(__import__("sys").executable),
            work_root=work_root,
            runner=runner,
        )

    assert list(work_root.iterdir()) == []
