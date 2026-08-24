from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
BACKUP_ROOT = PROJECT / "updates" / "backups"
MANIFEST_NAME = "update_12_manifest.json"
PATCH_NAME = "update_12_payload.patch"

TARGETS = (
    Path("rareiq/services/vision_service.py"),
    Path("rareiq/web/static/control.html"),
    Path("rareiq/web/static/studiox.js"),
    Path("rareiq/web/static/studiox.css"),
    Path("tests/test_vision_confidence_engine.py"),
    Path("tests/test_studiox_live_recognition_contract.py"),
    Path("tests/test_update_12_high_resolution_roi.py"),
)

PYTHON_TARGETS = (
    Path("rareiq/services/vision_service.py"),
    Path("tests/test_vision_confidence_engine.py"),
    Path("tests/test_studiox_live_recognition_contract.py"),
    Path("tests/test_update_12_high_resolution_roi.py"),
)

TARGETED_TESTS = (
    "tests/test_vision_confidence_engine.py",
    "tests/test_update_12_high_resolution_roi.py",
    "tests/test_multiframe_acquisition.py",
    "tests/test_vision_trigger_handoff.py",
    "tests/test_automatic_recognition_trigger.py",
    "tests/test_trigger_manager_service.py",
    "tests/test_camera_frame_bridge.py",
    "tests/test_studiox_live_recognition_contract.py",
)

PRE_UPDATE_MARKERS = {
    Path("rareiq/services/vision_service.py"): (
        "cv2.CAP_PROP_FRAME_WIDTH,\n            1280,",
        "cv2.CAP_PROP_FRAME_HEIGHT,\n            720,",
        "[499, 699]",
        "(500, 700)",
    ),
    Path("rareiq/web/static/control.html"): (
        '/static/studiox.js?v=6.3.2',
        '<link rel="stylesheet" href="/static/studiox.css">',
    ),
    Path("rareiq/web/static/studiox.js"): (
        "function updateResolutionBadge(){",
        "snapshot?.primary_candidate",
        "snapshot?.provisional_candidate",
    ),
    Path("rareiq/web/static/studiox.css"): (
        "position:absolute;inset:7% 20%;border-radius:20px;",
    ),
    Path("tests/test_vision_confidence_engine.py"): (
        "assert result.crop.shape == (700, 500, 3)",
    ),
    Path("tests/test_studiox_live_recognition_contract.py"): (
        'assert "/static/studiox.js?v=6.3.2" in html',
    ),
}

POST_UPDATE_MARKERS = {
    Path("rareiq/services/vision_service.py"): (
        "REQUESTED_FRAME_WIDTH = 1920",
        "DETECTION_MAX_WIDTH = 960",
        "OUTPUT_CROP_HEIGHT = 1400",
        '"requested_resolution"',
        '"resolution_fallback"',
    ),
    Path("rareiq/web/static/control.html"): (
        "/static/studiox.js?v=6.4.12",
        "/static/studiox.css?v=6.4.12",
    ),
    Path("rareiq/web/static/studiox.js"): (
        "function alignScanZone(vision={})",
        "vision.actual_resolution",
        "snapshot.primary_candidate",
        "snapshot.provisional_candidate",
    ),
    Path("rareiq/web/static/studiox.css"): (
        ".riq-pill.fallback",
    ),
    Path("tests/test_update_12_high_resolution_roi.py"): (
        "test_resolution_fallback_and_scan_zone_telemetry",
    ),
}

# Required post-tag baseline fixes between tag v6.4.11 and the branch on which
# Update 12 was built. Keeping this layer separate makes the tag provenance
# explicit while allowing the Update 12 layer below to remain narrowly scoped.
BASELINE_GZIP_BASE64 = """
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
""".strip()

# Complete Update 12 source/UI/test payload. This is a gzip-compressed UTF-8
# unified patch against the branch baseline produced by BASELINE_GZIP_BASE64.
PAYLOAD_GZIP_BASE64 = """
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
""".strip()

CONTRACT_CLEANUP_PATCH = (
    b"diff --git a/tests/test_studiox_live_recognition_contract.py "
    b"b/tests/test_studiox_live_recognition_contract.py\n"
    b"--- a/tests/test_studiox_live_recognition_contract.py\n"
    b"+++ b/tests/test_studiox_live_recognition_contract.py\n"
    b"@@ -15,7 +15,7 @@ "
    b"def test_studiox_uses_recognition_state_contract() -> None:\n"
    b" \n"
    b"     assert \"result?.recognition_state\" in script\n"
    b"     assert \"/api/recognition-state?t=${Date.now()}\" in script\n"
    b"-    assert \"snapshot?.primary_candidate\" in script\n"
    b"+    assert \"snapshot.primary_candidate\" in script\n"
    b"     assert \"snapshot?.pipeline_stages\" in script\n"
    b"     assert \"window.__rareiqRecognitionPoll\" in script\n"
    b" \n"
)


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def target_path(relative: Path) -> Path:
    if relative not in TARGETS:
        raise RuntimeError(f"Refusing non-target path: {relative}")
    resolved = (PROJECT / relative).resolve()
    if not inside(resolved, PROJECT):
        raise RuntimeError(f"Target escapes project root: {relative}")
    return resolved


def require_project_root() -> None:
    if Path.cwd().resolve() != PROJECT.resolve():
        raise RuntimeError(f"Run this installer from the RareIQ root: {PROJECT}")
    required = (PROJECT / "app.py", PROJECT / "rareiq/version.py", PROJECT / ".git")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Not a RareIQ Git checkout: " + ", ".join(missing))


def verify_pre_update() -> None:
    if target_path(TARGETS[-1]).exists():
        raise RuntimeError("Update 12 test already exists; refusing a non-v6.4.11 tree.")
    for relative, markers in PRE_UPDATE_MARKERS.items():
        path = target_path(relative)
        if not path.is_file():
            raise RuntimeError(f"Missing pre-update target: {relative}")
        content = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in content]
        if missing:
            raise RuntimeError(f"Unexpected pre-update contents in {relative}: {missing}")


def verify_post_update() -> None:
    for relative, markers in POST_UPDATE_MARKERS.items():
        content = target_path(relative).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in content]
        if missing:
            raise RuntimeError(f"Installed contract missing in {relative}: {missing}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_backup() -> Path:
    destination = BACKUP_ROOT / datetime.now().strftime("update_12_%Y%m%d_%H%M%S")
    if not inside(destination, PROJECT):
        raise RuntimeError("Backup directory escapes the RareIQ project.")
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for relative in TARGETS:
        source = target_path(relative)
        record = {"path": relative.as_posix(), "existed": source.exists()}
        if source.exists():
            saved = destination / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, saved)
            record["sha256"] = sha256(saved)
        records.append(record)
    (destination / MANIFEST_NAME).write_text(
        json.dumps({"project": str(PROJECT.resolve()), "files": records}, indent=2),
        encoding="utf-8",
    )
    return destination


def validated_backup(path: Path) -> tuple[Path, list[dict[str, object]]]:
    backup = path.resolve()
    if not inside(backup, BACKUP_ROOT) or backup == BACKUP_ROOT.resolve():
        raise RuntimeError("Rollback path must be a timestamped Update 12 backup.")
    manifest_path = backup / MANIFEST_NAME
    if not manifest_path.is_file():
        raise RuntimeError(f"Rollback manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = payload.get("files")
    if not isinstance(records, list):
        raise RuntimeError("Invalid rollback manifest.")
    expected = {item.as_posix() for item in TARGETS}
    actual = {str(item.get("path")) for item in records if isinstance(item, dict)}
    if actual != expected:
        raise RuntimeError("Rollback manifest target list is not the Update 12 allowlist.")
    return backup, records


def restore_backup(path: Path) -> None:
    backup, records = validated_backup(path)
    for record in records:
        relative = Path(str(record["path"]))
        destination = target_path(relative)
        if bool(record.get("existed")):
            source = (backup / relative).resolve()
            if not inside(source, backup) or not source.is_file():
                raise RuntimeError(f"Invalid rollback source: {source}")
            expected_hash = str(record.get("sha256") or "")
            if not expected_hash or sha256(source) != expected_hash:
                raise RuntimeError(f"Rollback checksum failed: {relative}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif destination.exists():
            destination.unlink()


def install_payload(backup: Path) -> None:
    layers = (
        ("v6.4.11-baseline.patch", BASELINE_GZIP_BASE64),
        (PATCH_NAME, PAYLOAD_GZIP_BASE64),
    )
    for filename, encoded in layers:
        patch_path = backup / filename
        patch_path.write_bytes(gzip.decompress(base64.b64decode(encoded)))
        subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            cwd=PROJECT,
            check=True,
        )
        subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_path)],
            cwd=PROJECT,
            check=True,
        )
    cleanup_path = backup / "update_12_contract_cleanup.patch"
    cleanup_path.write_bytes(CONTRACT_CLEANUP_PATCH)
    subprocess.run(
        ["git", "apply", "--check", str(cleanup_path)],
        cwd=PROJECT,
        check=True,
    )
    subprocess.run(
        ["git", "apply", "--whitespace=nowarn", str(cleanup_path)],
        cwd=PROJECT,
        check=True,
    )


def compile_python(backup: Path) -> None:
    compile_dir = backup / "compile"
    compile_dir.mkdir(parents=True, exist_ok=True)
    for index, relative in enumerate(PYTHON_TARGETS):
        py_compile.compile(
            str(target_path(relative)),
            cfile=str(compile_dir / f"{index}.pyc"),
            doraise=True,
        )


def run_targeted_tests() -> None:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *TARGETED_TESTS,
        ],
        cwd=PROJECT,
        env=environment,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Install RareIQ 6.4 Update 12.")
    parser.add_argument(
        "--rollback",
        type=Path,
        help="Manually restore a timestamped Update 12 backup.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify the installed Update 12 contracts without writing files.",
    )
    parser.add_argument(
        "--simulate-test-failure",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    backup: Path | None = None
    try:
        require_project_root()
        if args.rollback:
            restore_backup(args.rollback)
            print(f"RareIQ Update 12 rollback complete: {args.rollback.resolve()}")
            return 0
        if args.verify_only:
            verify_post_update()
            print("RareIQ 6.4 Update 12 contracts verified.")
            return 0

        verify_pre_update()
        backup = create_backup()
        install_payload(backup)
        verify_post_update()
        compile_python(backup)
        run_targeted_tests()
        if args.simulate_test_failure:
            raise RuntimeError("Simulated post-test failure for rollback validation.")
    except Exception as exc:
        if backup is not None:
            try:
                restore_backup(backup)
                print(f"Automatic rollback restored: {backup}", file=sys.stderr)
            except Exception as rollback_error:
                print(f"AUTOMATIC ROLLBACK FAILED: {rollback_error}", file=sys.stderr)
        print(f"RareIQ Update 12 failed: {exc}", file=sys.stderr)
        return 1

    print("RareIQ 6.4 Update 12 installed successfully.")
    print(f"Pre-update backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
