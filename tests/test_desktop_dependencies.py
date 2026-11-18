import csv
import io
import json
from pathlib import Path

import pytest

from tools import desktop_dependencies as dependencies


def distribution(root, name, version="1.0", *, requires=(), files=None, extra_records=(), license="MIT"):
    root.mkdir(parents=True, exist_ok=True)
    directory = root / f"{name}-{version}.dist-info"
    directory.mkdir()
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nLicense: {license}\n"
    metadata += "".join(f"Requires-Dist: {value}\n" for value in requires)
    payload = {f"{name}/__init__.py": b"# synthetic, never imported\n", **(files or {})}
    payload[f"{directory.name}/METADATA"] = metadata.encode()
    payload[f"{directory.name}/licenses/LICENSE"] = b"Synthetic license notice\n"
    for relative, contents in payload.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    record_name = f"{directory.name}/RECORD"
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows([(relative, "", str(len(contents))) for relative, contents in payload.items()]
                                 + [(record_name, "", "")] + [(relative, "", "") for relative in extra_records])
    (root / record_name).write_text(buffer.getvalue(), encoding="utf-8")
    return directory


def requirements(tmp_path, text="application==1.0\n"):
    path = tmp_path / "requirements.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_closure_constraints_markers_and_deterministic_idempotent_inventory(tmp_path):
    packages, target = tmp_path / "packages", tmp_path / "bundle"
    distribution(packages, "application", requires=["dependency>=2,<3", 'absent; python_version < "2"', 'optional; extra == "test"'])
    distribution(packages, "dependency", "2.0", files={"dependency/data/config.json": b"{}"})
    distribution(packages, "unselected")
    (tmp_path / "constraints.txt").write_text("dependency==2.0\n", encoding="utf-8")
    req = requirements(tmp_path, "-c constraints.txt\napplication==1.0\n")
    manifest = dependencies.vendor_dependencies(target, [packages], req, [])
    assert [item["name"] for item in manifest] == ["application", "dependency"]
    assert all(item["license"] == "MIT" and len(item["sha256"]) == 64 and item["file_count"] == len(item["files"]) for item in manifest)
    assert (target / "dependency/data/config.json").read_bytes() == b"{}"
    assert (target / "dependency-2.0.dist-info/licenses/LICENSE").is_file()
    assert not (target / "unselected").exists()
    assert str(tmp_path) not in json.dumps(manifest)
    assert dependencies.vendor_dependencies(target, [packages], req, []) == manifest


def test_explicit_extra_root_supplies_av_and_adjacent_dlls(tmp_path):
    packages, extra, target = tmp_path / "packages", tmp_path / "extra", tmp_path / "bundle"
    distribution(packages, "application")
    distribution(packages, "av", "18.0")
    distribution(extra, "av", "19.0.2", files={"av.libs/codec.dll": b"synthetic DLL"})
    manifest = dependencies.vendor_dependencies(target, [packages], requirements(tmp_path), [extra])
    assert [(item["name"], item["version"]) for item in manifest] == [("application", "1.0"), ("av", "19.0.2")]
    assert (target / "av.libs/codec.dll").read_bytes() == b"synthetic DLL"
    assert not (target / "av-18.0.dist-info").exists()


@pytest.mark.parametrize("required,child,reason", [
    ("application==2.0\n", None, "dependency_version_mismatch"),
    ("application>=1\n", None, "dependency_root_version_required"),
    ("application==1.0\n", "missing>=1", "dependency_missing"),
    ("application==1.0\n", "dependency>=2", "dependency_version_mismatch"),
])
def test_version_or_missing_dependency_fails_before_copy(tmp_path, required, child, reason):
    packages, target = tmp_path / "packages", tmp_path / "bundle"
    distribution(packages, "application", requires=[child] if child else [])
    distribution(packages, "dependency")
    with pytest.raises(dependencies.DependencyVendorError, match=f"^{reason}$"):
        dependencies.vendor_dependencies(target, [packages], requirements(tmp_path, required), [])
    assert not target.exists()


def test_external_record_paths_bytecode_pth_and_scripts_are_not_copied_or_disclosed(tmp_path):
    packages, target = tmp_path / "packages", tmp_path / "bundle"
    secret = tmp_path / "private-token.txt"
    secret.write_text("synthetic-private-value", encoding="utf-8")
    distribution(packages, "application", license="C:\\Users\\private\\secret", files={
        "application/__pycache__/module.pyc": b"bytecode", "unsafe.pth": b"import something", "bin/launcher.exe": b"script"},
        extra_records=["../private-token.txt", str(secret), "../../old-pip-temp/path.pyc"])
    manifest = dependencies.vendor_dependencies(target, [packages], requirements(tmp_path), [])
    assert manifest[0]["license"] == "unspecified"
    inventory = json.dumps(manifest)
    assert "private-token" not in inventory and str(tmp_path) not in inventory
    assert not any(path.suffix in {".pyc", ".pth"} or path.name == "launcher.exe" for path in target.rglob("*"))
    record = (target / "application-1.0.dist-info/RECORD").read_text()
    assert "private-token" not in record and "old-pip-temp" not in record
    assert secret.read_text() == "synthetic-private-value"


def test_different_file_collisions_fail_before_any_copy(tmp_path):
    one, two, target = tmp_path / "one", tmp_path / "two", tmp_path / "bundle"
    distribution(one, "application", requires=["dependency==1.0"], files={"shared/data": b"one"})
    distribution(two, "dependency", files={"shared/data": b"different"})
    with pytest.raises(dependencies.DependencyVendorError, match="^dependency_file_collision$"):
        dependencies.vendor_dependencies(target, [one, two], requirements(tmp_path), [])
    assert not target.exists()


def test_existing_destination_collision_preserves_user_file(tmp_path):
    packages, target = tmp_path / "packages", tmp_path / "bundle"
    distribution(packages, "application")
    existing = target / "application/__init__.py"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"preserve this")
    with pytest.raises(dependencies.DependencyVendorError, match="^dependency_file_collision$"):
        dependencies.vendor_dependencies(target, [packages], requirements(tmp_path), [])
    assert existing.read_bytes() == b"preserve this"
    assert not (target / "application-1.0.dist-info").exists()


@pytest.mark.parametrize("escape_target", [False, True])
def test_resolved_symlink_escapes_fail_closed_without_platform_symlink_privilege(tmp_path, monkeypatch, escape_target):
    packages, target = tmp_path / "packages", tmp_path / "bundle"
    distribution(packages, "application")
    secret = tmp_path / "private.txt"
    secret.write_bytes(b"synthetic private data")
    escaped = (target if escape_target else packages) / "application/__init__.py"
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        return secret if path == escaped else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    reason = "dependency_target_escape" if escape_target else "dependency_file_escape"
    with pytest.raises(dependencies.DependencyVendorError, match=f"^{reason}$"):
        dependencies.vendor_dependencies(target, [packages], requirements(tmp_path), [])
    assert not target.exists()


@pytest.mark.parametrize("size", [0, dependencies.MAX_METADATA_BYTES + 1], ids=["empty", "oversized"])
def test_empty_or_oversized_metadata_is_bounded_and_redacted(tmp_path, size):
    packages = tmp_path / "private-machine-folder"
    directory = distribution(packages, "application")
    (directory / "METADATA").write_bytes(b"X" * size)
    with pytest.raises(dependencies.DependencyVendorError, match="^dependency_metadata_size$") as failure:
        dependencies.vendor_dependencies(tmp_path / "bundle", [packages], requirements(tmp_path), [])
    assert "private-machine-folder" not in str(failure.value)


def test_external_requirement_include_cannot_read_machine_files(tmp_path):
    packages, config = tmp_path / "packages", tmp_path / "config"
    distribution(packages, "application")
    config.mkdir()
    req = requirements(config, "-r ../private-requirements.txt\n")
    (tmp_path / "private-requirements.txt").write_text("application==1.0\n", encoding="utf-8")
    with pytest.raises(dependencies.DependencyVendorError, match="^dependency_requirements_invalid$"):
        dependencies.vendor_dependencies(tmp_path / "bundle", [packages], req, [])
