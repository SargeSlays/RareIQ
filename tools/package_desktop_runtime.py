"""Build a private desktop runtime from staged source and explicit dependencies.

Does not launch the application, import its services or copy operator data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.desktop_dependencies import vendor_dependencies

PROJECT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13.12"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "76f238f606250c87c6beac75dccd35ee99070a13490555936abb6cb64ecce3d0"
CONTROLLERS = {"tools/server_control.py", "tools/desktop_backend.py", "tools/desktop_twitch_account.py", "tools/desktop_kick_account.py"}
SEEDS = {"rareiq/data/cards_poc.json", "rareiq/data/set_catalog.json"}


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def approved_source(name):
    path = PurePosixPath(name)
    if ("\\" in name or PureWindowsPath(name).drive or path.is_absolute()
            or ".." in path.parts or "__pycache__" in path.parts):
        return False
    return (name in {"app.py", "storage_config.example.json"} | CONTROLLERS | SEEDS
            or (name.startswith("rareiq/") and name.endswith(".py"))
            or name.startswith("rareiq/web/static/")
            or name == "rareiq/services/windows_speech_recognizer.ps1")


def stage_source(destination, *, project=PROJECT):
    tree = subprocess.check_output(["git", "write-tree"], cwd=project).decode().strip()
    archive = subprocess.check_output(["git", "archive", "--format=tar", tree], cwd=project)
    inventory = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for item in source:
            if not approved_source(item.name) or item.isdir():
                continue
            if not item.isfile():
                raise ValueError("runtime_source_link_rejected")
            data = source.extractfile(item).read()
            output = destination / item.name
            if not output.resolve().is_relative_to(destination.resolve()):
                raise ValueError("runtime_source_escape")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            inventory.append({"path": item.name, "sha256": hashlib.sha256(data).hexdigest()})
    required = {"app.py", "rareiq/web/server.py", "rareiq/core/runtime_paths.py"} | CONTROLLERS
    if not required.issubset({item["path"] for item in inventory}):
        raise ValueError("runtime_source_incomplete")
    return tree, inventory


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


def build(resources, *, cache=Path("F:/Caches/ProducerPlease/embedded-python")):
    resources = Path(resources).resolve()
    if not resources.is_dir() or (resources / "backend").exists():
        raise ValueError("new_runtime_resources_required")
    backend = resources / "backend"
    tree, source = stage_source(backend)
    python = resources / "python"
    embedded_python(python, cache)
    packages = vendor_dependencies(python / "Lib/site-packages",
        [PROJECT / ".venv/Lib/site-packages"], PROJECT / "requirements.txt",
        [Path("F:/Caches/ProducerPlease/python-packages")])
    for worker in ("encoder_worker.py", "shared_encoder_worker.py"):
        shutil.copyfile(PROJECT / "desktop" / worker, resources / worker)
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
        "ffmpeg": "bin/ffmpeg.exe" if binaries else None, "port": 8765}
    (resources / "runtime.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    inventory = {"sourceTree": tree, "python": {"version": PYTHON_VERSION,
        "url": PYTHON_URL, "sha256": PYTHON_SHA256}, "sources": source,
        "dependencies": packages, "binaries": binaries,
        "operatorDataIncluded": False, "publicReleaseAccepted": False}
    (resources / "runtime-inventory.json").write_text(json.dumps(inventory, indent=2)+"\n", encoding="utf-8")
    (resources / "THIRD-PARTY-NOTICES.txt").write_text(
        "Private evaluation build. Original license files remain with Python, "
        "Electron/Chromium, packages and binary notices. This inventory is not a "
        "redistribution-rights determination.\n\n" + "\n".join(
            f"{item['name']} {item['version']}: {item.get('license', 'See package metadata')}"
            for item in packages) + "\n", encoding="utf-8")
    return {"buildKind": "bundled-runtime", "runtimeBundled": True,
        "sourceFiles": len(source), "dependencyCount": len(packages), "sourceTree": tree}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.resources)))
    except Exception as error:
        print("Runtime packaging failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
