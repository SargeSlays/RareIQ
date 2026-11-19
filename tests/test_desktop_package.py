from tools import package_desktop_runtime as package
import hashlib
from importlib.machinery import PathFinder
import json
import subprocess
import zipfile

import pytest


def _git(project, *args, input=None):
    return subprocess.check_output(["git", *args], cwd=project, input=input).decode().strip()


@pytest.fixture
def source_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init", "-q")
    files = {name: b"# immutable backend\n" for name in package.CONTROLLERS | {
        "app.py", "rareiq/web/server.py", "rareiq/core/runtime_paths.py"}}
    files.update({"rareiq/web/static/control.html": b"immutable control",
                  "desktop/main.cjs": b"immutable UI",
                  "desktop/encoder_worker.py": b"# immutable encoder\n",
                  "desktop/shared_encoder_worker.py": b"# immutable shared encoder\n",
                  "requirements.txt": b"-c constraints.txt\n-r nested/more.txt\nsynthetic==1.0\n",
                  "constraints.txt": b"nested==2.0\n",
                  "nested/more.txt": b"nested==2.0\n",
                  "storage_config.json": b"private operator data must never stage"})
    for name, data in files.items():
        output = project / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    _git(project, "add", "--all")
    tree = package.resolve_source_tree(project=project)
    return project, files, tree


def test_runtime_source_allowlist_excludes_operator_files_and_build_artifacts():
    for path in ['app.py', 'rareiq/web/server.py', 'rareiq/core/runtime_paths.py',
                 'rareiq/web/static/control.html', 'tools/desktop_backend.py']:
        assert package.approved_source(path)
    for path in ['obs_settings.json', 'storage_config.json', 'rareiq_secrets.json',
                 'captures/person.jpg', 'rareiq/data/temporal_multi_card_history.json',
                 'rareiq/web/static/../secret.json', '../app.py', '.venv/private.py',
                 'tools/qa_native_desktop_fixture.py', 'desktop/tests/anything.cjs']:
        assert not package.approved_source(path)
    for path in [r'rareiq/web/static/..\..\..\..\outside.txt',
                 r'C:\rareiq\web\static\outside.txt', 'C:app.py',
                 'rareiq/web/static/file.txt:private', 'rareiq/web/static/line\nbreak.js']:
        assert not package.approved_source(path)


def test_embedded_runtime_is_pinned_to_a_verified_archive():
    assert package.PYTHON_URL.startswith('https://www.python.org/ftp/python/')
    assert len(package.PYTHON_SHA256) == 64


def test_isolated_embedded_bootstrap_resolves_packaged_worker_companion_without_cwd_or_environment(tmp_path, monkeypatch):
    cache = tmp_path / "verified-cache"
    cache.mkdir()
    archive = cache / f"python-{package.PYTHON_VERSION}-embed-amd64.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("python.exe", b"inert synthetic interpreter")
        output.writestr("python313.zip", b"inert synthetic standard library")
    monkeypatch.setattr(package, "PYTHON_SHA256", package.digest(archive))
    resources = tmp_path / "immutable-resources"
    interpreter = resources / "python"
    package.embedded_python(interpreter, cache)
    worker = resources / "encoder_worker.py"
    worker.write_text("# inert packaged companion\n", encoding="utf-8")
    decoy = tmp_path / "untrusted-cwd"
    decoy.mkdir()
    (decoy / "encoder_worker.py").write_text("raise AssertionError('wrong companion')", encoding="utf-8")
    (decoy / "private_cwd_module.py").write_text("# must never be on runtime path", encoding="utf-8")
    monkeypatch.chdir(decoy)
    monkeypatch.setenv("PYTHONPATH", str(decoy))
    monkeypatch.setenv("PYTHONHOME", str(decoy))
    entries = (interpreter / "python313._pth").read_text(encoding="utf-8").splitlines()
    assert entries == ["python313.zip", ".", "Lib/site-packages", "..", "../backend"]
    search = [str((interpreter / entry).resolve()) for entry in entries]
    assert all((interpreter / entry).resolve().is_relative_to(resources) for entry in entries)
    assert PathFinder.find_spec("encoder_worker", search).origin == str(worker)
    assert PathFinder.find_spec("private_cwd_module", search) is None


def test_stage_source_optional_pinned_tree_ignores_later_index_and_working_source(source_project, tmp_path):
    project, files, tree = source_project
    (project / "app.py").write_text("# newer indexed backend", encoding="utf-8")
    _git(project, "add", "app.py")
    (project / "rareiq/web/server.py").write_text("# dirty working server", encoding="utf-8")
    output = tmp_path / "pinned-backend"
    captured, inventory = package.stage_source(output, project=project, source_tree=tree)
    assert captured == tree
    assert (output / "app.py").read_bytes() == files["app.py"]
    assert (output / "rareiq/web/server.py").read_bytes() == files["rareiq/web/server.py"]
    assert not (output / "storage_config.json").exists()
    assert next(item for item in inventory if item["path"] == "app.py")["sha256"] == hashlib.sha256(files["app.py"]).hexdigest()
    current, _ = package.stage_source(tmp_path / "current-backend", project=project)
    assert current != tree


def test_backend_blob_staging_ignores_local_export_attributes_and_line_ending_filters(source_project, tmp_path):
    project, files, tree = source_project
    _git(project, "config", "core.autocrlf", "true")
    attributes = project / ".git/info/attributes"
    attributes.parent.mkdir(exist_ok=True)
    attributes.write_text("app.py export-ignore\nrareiq/web/server.py text eol=crlf\n", encoding="utf-8")
    output = tmp_path / "raw-backend"
    package.stage_source(output, project=project, source_tree=tree)
    assert (output / "app.py").read_bytes() == files["app.py"]
    assert (output / "rareiq/web/server.py").read_bytes() == files["rareiq/web/server.py"]


def test_build_workers_and_recursive_requirements_come_from_the_same_pinned_tree(source_project, tmp_path):
    project, files, tree = source_project
    for name in ("requirements.txt", "constraints.txt", "desktop/shared_encoder_worker.py"):
        (project / name).write_text("dirty or newer indexed bytes", encoding="utf-8")
    _git(project, "add", "requirements.txt", "desktop/shared_encoder_worker.py")
    output = tmp_path / "build-inputs"
    inventory = package.stage_build_inputs(output, tree, project=project)
    assert {item["path"] for item in inventory} == {"requirements.txt", "constraints.txt", "nested/more.txt", "desktop/encoder_worker.py", "desktop/shared_encoder_worker.py"}
    for item in inventory:
        assert (output / item["path"]).read_bytes() == files[item["path"]]
        assert item["sha256"] == hashlib.sha256(files[item["path"]]).hexdigest()


@pytest.mark.parametrize("value", ["HEAD", "--all", "a" * 39, "x" * 40, 42])
def test_source_tree_rejects_mutable_or_invalid_references(source_project, value):
    project, _, _ = source_project
    with pytest.raises(ValueError, match="runtime_source_tree_invalid"):
        package.resolve_source_tree(value, project=project)


def test_source_tree_rejects_a_blob_object(source_project):
    project, _, _ = source_project
    blob = _git(project, "hash-object", "-w", "--stdin", input=b"not a tree")
    with pytest.raises(ValueError, match="runtime_source_tree_invalid"):
        package.resolve_source_tree(blob, project=project)


@pytest.mark.parametrize("directive,reason", [
    ("-r ../private.txt\n", "runtime_requirements_escape"),
    ("-c requirements.txt\n", "runtime_requirements_cycle"),
])
def test_requirement_inputs_reject_escape_and_cycles(source_project, tmp_path, directive, reason):
    project, _, _ = source_project
    (project / "requirements.txt").write_text(directive, encoding="utf-8")
    _git(project, "add", "requirements.txt")
    tree = package.resolve_source_tree(project=project)
    with pytest.raises(ValueError, match=reason):
        package.stage_build_inputs(tmp_path / "unsafe-inputs", tree, project=project)


def test_build_inputs_reject_index_symlinks_without_opening_operator_data(source_project, tmp_path):
    project, _, _ = source_project
    blob = _git(project, "hash-object", "-w", "--stdin", input=b"../private-operator-data")
    _git(project, "update-index", "--add", "--cacheinfo", "120000", blob, "constraints.txt")
    with pytest.raises(ValueError, match="runtime_build_input_missing"):
        package.stage_build_inputs(tmp_path / "linked-inputs", package.resolve_source_tree(project=project), project=project)


def _receipt(resources, tree, files):
    receipt = {"sourceTree": tree, "files": [{"path": "desktop/main.cjs", "sha256": hashlib.sha256(files["desktop/main.cjs"]).hexdigest()}]}
    (resources / "desktop-source.json").write_text(json.dumps(receipt), encoding="utf-8")
    return receipt


def test_desktop_receipt_requires_matching_tree_and_source_hashes(source_project, tmp_path):
    project, files, tree = source_project
    resources = tmp_path / "receipt"
    resources.mkdir()
    value = _receipt(resources, tree, files)
    assert package.verify_desktop_source(resources, tree, project=project, required=True) == value
    value["sourceTree"] = "b" * 40
    (resources / "desktop-source.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="desktop_source_tree_mismatch"):
        package.verify_desktop_source(resources, tree, project=project, required=True)
    value["sourceTree"] = tree
    value["files"][0]["sha256"] = "b" * 64
    (resources / "desktop-source.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="desktop_source_hash_mismatch"):
        package.verify_desktop_source(resources, tree, project=project, required=True)


def test_desktop_source_provenance_requires_a_real_base_commit_not_a_tree_or_path(source_project, tmp_path):
    project, files, tree = source_project
    resources = tmp_path / "provenance"
    resources.mkdir()
    value = _receipt(resources, tree, files)
    commit = _git(project, "-c", "user.name=Synthetic fixture", "-c", "user.email=fixture@invalid", "commit-tree", tree, input=b"Synthetic base\n")
    value["baseCommit"] = commit
    (resources / "desktop-source.json").write_text(json.dumps(value), encoding="utf-8")
    assert package.verify_desktop_source(resources, tree, project=project, required=True)["baseCommit"] == commit
    for invalid in [tree, "HEAD", "F:/arbitrary"]:
        value["baseCommit"] = invalid
        (resources / "desktop-source.json").write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ValueError, match="desktop_source_commit_invalid"):
            package.verify_desktop_source(resources, tree, project=project, required=True)


def test_runtime_build_pins_backend_workers_and_dependency_input_without_downloading_or_launching(source_project, tmp_path, monkeypatch):
    project, files, tree = source_project
    resources = tmp_path / "resources"
    resources.mkdir()
    _receipt(resources, tree, files)
    (project / "requirements.txt").write_text("dirty requirement must not be used", encoding="utf-8")
    (project / "desktop/encoder_worker.py").write_text("dirty worker must not be used", encoding="utf-8")
    monkeypatch.setattr(package, "PROJECT", project)
    monkeypatch.setattr(package.shutil, "which", lambda _name: None)

    def embedded(destination, _cache):
        destination.mkdir()
        (destination / "python.exe").write_bytes(b"inert test file")
    monkeypatch.setattr(package, "embedded_python", embedded)

    def vendor(target, roots, requirements, extra):
        assert requirements == resources / "build-inputs/requirements.txt"
        assert requirements.read_bytes() == files["requirements.txt"]
        assert (requirements.parent / "constraints.txt").read_bytes() == files["constraints.txt"]
        target.mkdir(parents=True)
        return []
    monkeypatch.setattr(package, "vendor_dependencies", vendor)
    result = package.build(resources, source_tree=tree, cache=tmp_path / "no-download")
    assert result["sourceTree"] == tree
    assert (resources / "encoder_worker.py").read_bytes() == files["desktop/encoder_worker.py"]
    assert (resources / "backend/app.py").read_bytes() == files["app.py"]
    assert json.loads((resources / "runtime.json").read_text())["sourceTree"] == tree
    inventory = json.loads((resources / "runtime-inventory.json").read_text())
    assert inventory["sourceTree"] == inventory["desktopSource"]["sourceTree"] == tree
    assert inventory["operatorDataIncluded"] is False
