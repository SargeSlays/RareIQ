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
PAYLOAD_ROOT = PROJECT / "updates" / "update_14_payload"
BACKUP_ROOT = PROJECT / "updates" / "backups"
MANIFEST = "update_14_manifest.json"

TARGETS = tuple(Path(value) for value in (
    "rareiq/services/vision_service.py",
    "rareiq/services/camera_manager_service.py",
    "rareiq/core/orchestrator.py",
    "rareiq/services/recognition_service.py",
    "rareiq/services/trigger_manager_service.py",
    "rareiq/core/recognition_state.py",
    "rareiq/web/server.py",
    "rareiq/web/static/studiox.js",
    "tests/test_continuous_recognition_state_machine.py",
    "tests/test_automatic_recognition_trigger.py",
    "tests/test_vision_trigger_handoff.py",
    "tests/test_trigger_manager_service.py",
    "tests/test_vision_confidence_engine.py",
    "tests/test_update_12_high_resolution_roi.py",
    "tests/test_update_13_artwork_verification.py",
    "tests/test_camera_manager_service.py",
    "tests/test_studiox_live_recognition_contract.py",
))
PYTHON_TARGETS = tuple(path for path in TARGETS if path.suffix == ".py")
TARGETED_TESTS = (
    "tests/test_continuous_recognition_state_machine.py",
    "tests/test_camera_manager_service.py",
    "tests/test_automatic_recognition_trigger.py",
    "tests/test_multiframe_acquisition.py",
    "tests/test_vision_confidence_engine.py",
    "tests/test_vision_trigger_handoff.py",
    "tests/test_trigger_manager_service.py",
    "tests/test_studiox_live_recognition_contract.py",
    "tests/test_update_12_high_resolution_roi.py",
    "tests/test_update_13_recognition_geometry.py",
    "tests/test_update_13_artwork_verification.py",
)
PRE_MARKERS = {
    Path("rareiq/services/recognition_service.py"): "def submit_frame(self, frame: np.ndarray | None) -> None:",
    Path("rareiq/services/trigger_manager_service.py"): "self.recognition.submit_frame(crop)",
    Path("rareiq/web/server.py"): 'path = orchestrator.vision.save_latest_crop(source="manual")',
}
POST_MARKERS = {
    Path("rareiq/services/vision_service.py"): "ARTWORK_STRONG_STRUCTURAL_SIMILARITY_THRESHOLD = 0.60",
    Path("rareiq/services/camera_manager_service.py"): '"device_sequence_id": self._last_device_sequence_id',
    Path("rareiq/core/orchestrator.py"): "artwork_identity_change",
    Path("rareiq/services/recognition_service.py"): "def invalidate_before(self, generation: int)",
    Path("rareiq/services/trigger_manager_service.py"): "orchestrator owns submission",
    Path("rareiq/core/recognition_state.py"): "continuous_state: str = \"EMPTY\"",
    Path("rareiq/web/server.py"): "SERVER_SESSION_ID = uuid.uuid4().hex",
    Path("rareiq/web/static/studiox.js"): "resetRecognitionPresentation",
    Path("tests/test_continuous_recognition_state_machine.py"): "test_out_of_order_result_is_ignored",
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
        raise RuntimeError(f"Update 14 payload allowlist mismatch: {sorted(actual ^ expected)}")
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
        raise RuntimeError("Expected clean v6.4.13 pre-update markers were not found.")
    return "pre-update"


def backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = inside(BACKUP_ROOT / f"update_14_{stamp}")
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
    if {item["path"] for item in data["files"]} != {p.as_posix() for p in TARGETS}:
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
    parser = argparse.ArgumentParser(description="Install RareIQ 6.4 Update 14.")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--simulate-test-failure", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    verify_root()
    verify_payload()
    if args.rollback:
        restore(args.rollback)
        print(f"RareIQ Update 14 rollback complete: {args.rollback.resolve()}")
        return 0
    state = marker_state()
    if args.verify_only:
        print(f"RareIQ Update 14 verification passed ({state}; {len(TARGETS)} allowlisted files).")
        return 0
    if state != "pre-update":
        raise RuntimeError("Update 14 is already installed; installation requires clean v6.4.13.")
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
    print(f"RareIQ Update 14 installed successfully. Backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
