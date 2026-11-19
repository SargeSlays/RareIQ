"""Build a private desktop runtime from staged source and explicit dependencies.

Does not launch the application, import its services or copy operator data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.desktop_dependencies import vendor_dependencies

PROJECT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.12"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0"
CONTROLLERS = {"tools/server_control.py", "tools/desktop_backend.py", "tools/desktop_twitch_account.py", "tools/desktop_kick_account.py", "tools/desktop_profile_adoption.py"}
SEEDS = {"rareiq/data/cards_poc.json", "rareiq/data/set_catalog.json"}


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def approved_source(name):
    path = PurePosixPath(name)
    if ("\\" in name or ":" in name or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or PureWindowsPath(name).drive or path.is_absolute()
            or ".." in path.parts or "__pycache__" in path.parts):
        return False
    return (name in {"app.py", "storage_config.example.json"} | CONTROLLERS | SEEDS
            or (name.startswith("rareiq/") and name.endswith(".py"))
            or name.startswith("rareiq/web/static/")
            or name == "rareiq/services/windows_speech_recognizer.ps1")


def resolve_source_tree(value=None, *, project=PROJECT):
    tree = (subprocess.check_output(["git", "write-tree"], cwd=project).decode().strip()
            if value is None else value)
    if not isinstance(tree, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", tree):
        raise ValueError("runtime_source_tree_invalid")
    if subprocess.check_output(["git", "cat-file", "-t", tree], cwd=project).strip() != b"tree":
        raise ValueError("runtime_source_tree_invalid")
    return tree


def stage_source(destination, *, project=PROJECT, source_tree=None):
    tree = resolve_source_tree(source_tree, project=project)
    entries = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--full-tree", tree], cwd=project)
    selected = []
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        header, separator, raw_name = entry.partition(b"\t")
        if not separator:
            raise ValueError("runtime_source_inventory_invalid")
        name = raw_name.decode("utf-8")
        if not approved_source(name):
            continue
        fields = header.split()
        if len(fields) != 3 or fields[0] not in {b"100644", b"100755"} or fields[1] != b"blob":
            raise ValueError("runtime_source_link_rejected")
        selected.append((name, fields[2]))
    # Raw blobs bypass checkout filters, export attributes and core.autocrlf.
    raw = subprocess.check_output(["git", "cat-file", "--batch"], cwd=project,
        input=b"".join(oid + b"\n" for _, oid in selected))
    inventory = []
    offset = 0
    for name, oid in selected:
        end = raw.find(b"\n", offset)
        header = raw[offset:end].split()
        if end < offset or len(header) != 3 or header[:2] != [oid, b"blob"] or not header[2].isdigit():
            raise ValueError("runtime_source_blob_invalid")
        size = int(header[2])
        offset = end + 1
        data = raw[offset:offset + size]
        if len(data) != size or raw[offset + size:offset + size + 1] != b"\n":
            raise ValueError("runtime_source_blob_invalid")
        offset += size + 1
        output = destination / name
        if not output.resolve().is_relative_to(destination.resolve()):
            raise ValueError("runtime_source_escape")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        inventory.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    if offset != len(raw):
        raise ValueError("runtime_source_blob_invalid")
    required = {"app.py", "rareiq/web/server.py", "rareiq/core/runtime_paths.py"} | CONTROLLERS
    if not required.issubset({item["path"] for item in inventory}):
        raise ValueError("runtime_source_incomplete")
    return tree, inventory


def _tree_file(tree, name, *, project=PROJECT):
    relative = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or PureWindowsPath(name).drive or relative.is_absolute()
            or ".." in relative.parts or any(part in {"", "."} for part in relative.parts)):
        raise ValueError("runtime_build_input_invalid")
    entry = subprocess.check_output(["git", "ls-tree", "-z", tree, "--", name], cwd=project)
    header, separator, stored = entry.rstrip(b"\0").partition(b"\t")
    if (not separator or stored.decode("utf-8") != name
            or header.split()[0] not in {b"100644", b"100755"}
            or header.split()[1] != b"blob"):
        raise ValueError("runtime_build_input_missing")
    return subprocess.check_output(["git", "show", tree + ":" + name], cwd=project)


def stage_build_inputs(destination, tree, *, project=PROJECT):
    """Pin worker bytes and the complete requirements/constraints input closure."""
    destination = Path(destination)
    inventory, visited, visiting = [], set(), set()

    def stage(name, requirements=False):
        if name in visiting:
            raise ValueError("runtime_requirements_cycle")
        if name in visited:
            return
        data = _tree_file(tree, name, project=project)
        if requirements and len(data) > 1024 * 1024:
            raise ValueError("runtime_requirements_size")
        output = destination / name
        if not output.resolve().is_relative_to(destination.resolve()):
            raise ValueError("runtime_build_input_escape")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(data)
        inventory.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
        visiting.add(name)
        if requirements:
            for raw in data.decode("utf-8-sig").splitlines():
                line = raw.split(" #", 1)[0].strip()
                directive = re.fullmatch(r"(?:-r|--requirement|-c|--constraint)\s+(.+)", line)
                if directive:
                    relative = PurePosixPath(directive[1].replace("\\", "/"))
                    if (relative.is_absolute() or PureWindowsPath(directive[1]).drive
                            or ".." in relative.parts):
                        raise ValueError("runtime_requirements_escape")
                    stage((PurePosixPath(name).parent / relative).as_posix(), True)
        visiting.remove(name)
        visited.add(name)

    stage("requirements.txt", True)
    for worker in ("encoder_worker.py", "shared_encoder_worker.py"):
        stage("desktop/" + worker)
    return inventory


def verify_desktop_source(resources, tree, *, project=PROJECT, required=False):
    receipt = Path(resources) / "desktop-source.json"
    if not receipt.exists() and not required:
        return None
    if not receipt.is_file() or receipt.stat().st_size > 1024 * 1024:
        raise ValueError("desktop_source_receipt_invalid")
    value = json.loads(receipt.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) not in ({"sourceTree", "files"}, {"sourceTree", "baseCommit", "files"})
            or value["sourceTree"] != tree or not isinstance(value["files"], list)
            or not value["files"] or len(value["files"]) > 1024):
        raise ValueError("desktop_source_tree_mismatch")
    if "baseCommit" in value:
        commit = value["baseCommit"]
        if (not isinstance(commit, str) or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", commit)
                or subprocess.check_output(["git", "cat-file", "-t", commit], cwd=project).strip() != b"commit"):
            raise ValueError("desktop_source_commit_invalid")
    seen = set()
    for item in value["files"]:
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or not isinstance(item["path"], str) or item["path"] in seen
                or not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
            raise ValueError("desktop_source_receipt_invalid")
        data = _tree_file(tree, item["path"], project=project)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("desktop_source_hash_mismatch")
        seen.add(item["path"])
    return value


def embedded_python(destination, cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if not archive.is_file():
        partial = archive.with_suffix(".download")
        with urllib.request.urlopen(PYTHON_URL, timeout=45) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(partial) != PYTHON_SHA256:
            raise ValueError("embedded_python_checksum_mismatch")
        partial.replace(archive)
    if digest(archive) != PYTHON_SHA256:
        raise ValueError("embedded_python_checksum_mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            name = PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename:
                raise ValueError("embedded_python_archive_escape")
        source.extractall(destination)
    # Isolated embedded Python ignores PYTHONPATH. These are the only app roots.
    (destination / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\n../backend\n", encoding="utf-8")


def build(resources, *, cache=Path("F:/Caches/ProducerPlease/embedded-python"), source_tree=None):
    resources = Path(resources).resolve()
    if not resources.is_dir() or (resources / "backend").exists():
        raise ValueError("new_runtime_resources_required")
    tree = resolve_source_tree(source_tree, project=PROJECT)
    desktop_source = verify_desktop_source(resources, tree, project=PROJECT, required=source_tree is not None)
    backend = resources / "backend"
    _, source = stage_source(backend, project=PROJECT, source_tree=tree)
    build_inputs = resources / "build-inputs"
    inputs = stage_build_inputs(build_inputs, tree, project=PROJECT)
    python = resources / "python"
    embedded_python(python, cache)
    packages = vendor_dependencies(python / "Lib/site-packages",
        [PROJECT / ".venv/Lib/site-packages"], build_inputs / "requirements.txt",
        [Path("F:/Caches/ProducerPlease/python-packages")])
    for worker in ("encoder_worker.py", "shared_encoder_worker.py"):
        shutil.copyfile(build_inputs / "desktop" / worker, resources / worker)
    ffmpeg = shutil.which("ffmpeg")
    binaries = []
    if ffmpeg:
        parent = Path(ffmpeg).resolve().parent
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            file = parent / name
            if file.is_file():
                output = resources / "bin" / name
                output.parent.mkdir(exist_ok=True)
                shutil.copyfile(file, output)
                binaries.append({"path": "bin/" + name, "sha256": digest(output)})
        notices = resources / "notices/ffmpeg"
        notices.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE", "README.txt"):
            file = parent.parent / name
            if file.is_file():
                shutil.copyfile(file, notices / name)
    manifest = {"buildKind": "bundled-runtime", "projectRoot": "backend",
        "python": "python/python.exe", "encoderWorker": "encoder_worker.py",
        "sharedEncoderWorker": "shared_encoder_worker.py",
        "pythonPackages": "python/Lib/site-packages",
        "ffmpeg": "bin/ffmpeg.exe" if binaries else None, "port": 8765,
        "sourceTree": tree, "baseCommit": desktop_source.get("baseCommit") if desktop_source else None}
    (resources / "runtime.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    inventory = {"sourceTree": tree, "python": {"version": PYTHON_VERSION,
        "url": PYTHON_URL, "sha256": PYTHON_SHA256}, "sources": source,
        "dependencies": packages, "binaries": binaries, "buildInputs": inputs,
        "desktopSource": desktop_source,
        "baseCommit": manifest["baseCommit"],
        "operatorDataIncluded": False, "publicReleaseAccepted": False}
    (resources / "runtime-inventory.json").write_text(json.dumps(inventory, indent=2)+"\n", encoding="utf-8")
    (resources / "THIRD-PARTY-NOTICES.txt").write_text(
        "Private evaluation build. Original license files remain with Python, "
        "Electron/Chromium, packages and binary notices. This inventory is not a "
        "redistribution-rights determination.\n\n" + "\n".join(
            f"{item['name']} {item['version']}: {item.get('license', 'See package metadata')}"
            for item in packages) + "\n", encoding="utf-8")
    return {"buildKind": "bundled-runtime", "runtimeBundled": True,
        "sourceFiles": len(source), "dependencyCount": len(packages), "sourceTree": tree,
        "baseCommit": manifest["baseCommit"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    parser.add_argument("--source-tree")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.resources, source_tree=args.source_tree)))
    except Exception as error:
        print("Runtime packaging failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
