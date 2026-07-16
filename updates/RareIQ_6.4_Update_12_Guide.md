# RareIQ 6.4 Update 12 — High-Resolution ROI

Update 12 requests 1920×1080 camera input, accepts a supported fallback,
detects only inside the fixed normalized scan zone, and creates a 1000×1400
portrait crop from the original full-resolution frame.

## Installation

Start from a clean RareIQ v6.4.11 checkout. Place
`RareIQ_6.4_Update_12.py` in `updates/`, open PowerShell at the RareIQ project
root, stop RareIQ, and run:

```powershell
python -B updates/RareIQ_6.4_Update_12.py
```

The installer verifies the project root and expected v6.4.11 source markers
before writing anything. Its complete Update 12 payload is embedded as a
compressed unified patch, so no network access or external payload is needed.

Before applying the patch, it copies every original target into:

```text
updates/backups/update_12_YYYYMMDD_HHMMSS/
```

The manifest records checksums and whether each file existed before installation.
The new Update 12 test is recorded as absent and is therefore removed by rollback.

## Verification

Installation automatically:

1. Verifies installed Update 12 markers.
2. Compile-checks every modified Python file into the backup directory, avoiding
   source-tree bytecode changes.
3. Runs the targeted vision, camera, trigger, handoff, acquisition, and Studio X
   tests with bytecode and pytest cache writing disabled.

After installation, the complete canonical suite can be run separately with:

```powershell
python -B -m pytest -q -p no:cacheprovider tests
```

## Automatic rollback

If patching, installed-contract verification, Python compilation, or targeted
tests fail, the installer automatically restores all original files from the
pre-update backup. Files that did not exist before installation are removed.
Every rollback path is restricted to the RareIQ project and the exact Update 12
target allowlist, and every saved file is checksum-verified before restoration.

## Manual rollback

Stop RareIQ and run from the project root:

```powershell
python -B updates/RareIQ_6.4_Update_12.py --rollback updates/backups/update_12_YYYYMMDD_HHMMSS
```

## Exact files installed

The installer modifies only:

```text
rareiq/services/vision_service.py
rareiq/web/static/control.html
rareiq/web/static/studiox.js
rareiq/web/static/studiox.css
tests/test_vision_confidence_engine.py
tests/test_studiox_live_recognition_contract.py
tests/test_update_12_high_resolution_roi.py
```

It does not target or inspect databases, artwork indexes, catalog data, captures,
secrets, `storage_config.json`, or any runtime storage directory.
