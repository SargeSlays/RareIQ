from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PAYLOAD_ROOT = PROJECT / "updates" / "update_15_payload"
BACKUP_ROOT = PROJECT / "updates" / "backups"
MANIFEST = "update_15_manifest.json"
TARGETS = tuple(Path(value) for value in (
    "rareiq/web/static/control.html",
    "rareiq/web/static/studiox.js",
    "rareiq/web/static/studiox_ui4_tokens.css",
    "rareiq/web/static/studiox_update15.css",
    "tests/test_studiox_live_recognition_contract.py",
    "tests/test_update_15_studiox_compact_ui.py",
    "tests/test_update_15_studiox_responsive_ui.py",
))
PYTHON_TARGETS = tuple(path for path in TARGETS if path.suffix == ".py")
TARGETED_TESTS = (
    "tests/test_update_15_studiox_compact_ui.py",
    "tests/test_update_15_studiox_responsive_ui.py",
    "tests/test_studiox_live_recognition_contract.py",
)
PRE_MARKERS = {
    Path("rareiq/web/static/control.html"): "/static/studiox.js?v=6.4.12",
    Path("rareiq/web/static/studiox.js"): "function renderPipeline(stages,hasCard)",
}
POST_MARKERS = {
    Path("rareiq/web/static/control.html"): "ui4-program-actions",
    Path("rareiq/web/static/studiox.js"): "const PIPELINE_STAGE_DEFINITIONS=",
    Path("rareiq/web/static/studiox_ui4_tokens.css"): "--ui4-touch-target:44px",
    Path("rareiq/web/static/studiox_update15.css"): "@media(min-width:2200px) and (min-height:1200px)",
    Path("tests/test_update_15_studiox_compact_ui.py"): "test_compact_pipeline_has_exact_order",
    Path("tests/test_update_15_studiox_responsive_ui.py"): "test_all_91_existing_ids_remain_unique",
}


def inside(path: Path, root: Path = PROJECT) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Path escapes RareIQ project: {path}") from exc
    return resolved


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_root() -> None:
    if Path.cwd().resolve() != PROJECT.resolve():
        raise RuntimeError("Run this installer from the RareIQ project root.")
    if not (PROJECT / "app.py").is_file() or not (PROJECT / "rareiq").is_dir():
        raise RuntimeError("Expected RareIQ project markers were not found.")


def verify_payload() -> None:
    expected = {path.as_posix() for path in TARGETS}
    actual = {
        path.relative_to(PAYLOAD_ROOT).as_posix()
        for path in PAYLOAD_ROOT.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise RuntimeError(f"Update 15 payload allowlist mismatch: {sorted(actual ^ expected)}")
    for relative in TARGETS:
        inside(PROJECT / relative)
        if not (PAYLOAD_ROOT / relative).is_file():
            raise RuntimeError(f"Missing payload file: {relative}")


def marker_state() -> str:
    post = all(
        (PROJECT / path).is_file()
        and marker in (PROJECT / path).read_text(encoding="utf-8")
        for path, marker in POST_MARKERS.items()
    )
    if post:
        return "post-update"
    pre = all(
        (PROJECT / path).is_file()
        and marker in (PROJECT / path).read_text(encoding="utf-8")
        for path, marker in PRE_MARKERS.items()
    )
    if not pre:
        raise RuntimeError("Expected clean v6.4.14 pre-update markers were not found.")
    return "pre-update"


def backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = inside(BACKUP_ROOT / f"update_15_{stamp}")
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for relative in TARGETS:
        source = inside(PROJECT / relative)
        target = inside(destination / relative, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = source.exists()
        if existed:
            shutil.copy2(source, target)
        records.append({
            "path": relative.as_posix(),
            "existed": existed,
            "sha256": digest(source) if existed else None,
        })
    (destination / MANIFEST).write_text(
        json.dumps({"created_at": stamp, "files": records}, indent=2),
        encoding="utf-8",
    )
    return destination


def restore(destination: Path) -> None:
    destination = inside(destination)
    manifest_path = inside(destination / MANIFEST, destination)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if {item["path"] for item in data["files"]} != {path.as_posix() for path in TARGETS}:
        raise RuntimeError("Rollback manifest allowlist mismatch.")
    for item in data["files"]:
        relative = Path(item["path"])
        target = inside(PROJECT / relative)
        source = inside(destination / relative, destination)
        if item["existed"]:
            if digest(source) != item["sha256"]:
                raise RuntimeError(f"Backup checksum mismatch: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        elif target.exists():
            target.unlink()


def install_payload() -> None:
    for relative in TARGETS:
        source = PAYLOAD_ROOT / relative
        target = inside(PROJECT / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(source) != digest(target):
            raise RuntimeError(f"Installed checksum mismatch: {relative}")


def compile_check(backup_dir: Path) -> None:
    compile_dir = inside(backup_dir / "compile", backup_dir)
    compile_dir.mkdir(parents=True, exist_ok=True)
    for index, relative in enumerate(PYTHON_TARGETS):
        py_compile.compile(
            str(PROJECT / relative),
            cfile=str(compile_dir / f"{index}.pyc"),
            doraise=True,
        )


def run_tests() -> None:
    subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TARGETED_TESTS],
        cwd=PROJECT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Install RareIQ 6.4 Update 15.")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--simulate-test-failure", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    verify_root()
    verify_payload()
    if args.rollback:
        restore(args.rollback)
        print(f"RareIQ Update 15 rollback complete: {args.rollback.resolve()}")
        return 0
    state = marker_state()
    if args.verify_only:
        print(f"RareIQ Update 15 verification passed ({state}; {len(TARGETS)} allowlisted files).")
        return 0
    if state != "pre-update":
        raise RuntimeError("Update 15 is already installed; installation requires clean v6.4.14.")
    backup_dir = backup()
    try:
        install_payload()
        compile_check(backup_dir)
        run_tests()
        if args.simulate_test_failure:
            raise RuntimeError("Simulated post-test failure")
    except BaseException:
        restore(backup_dir)
        print(f"Automatic rollback restored pre-update files: {backup_dir}", file=sys.stderr)
        raise
    print(f"RareIQ Update 15 installed successfully. Backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
