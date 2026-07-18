# RareIQ 6.4 Update 15 — Studio X Compact UI

Update 15 introduces the true Studio X UI 4.0 desktop shell: a vertical product-navigation rail, a camera-first center workspace, a single command bar, and a dedicated result inspector. The five-step Detect, Stabilize, Capture, Recognize, and Match rail now lives inside the camera workspace. Diagnostics move into a closed-by-default overlay drawer, while Market, Copilot, Signals, and Session move into keyboard-accessible inspector tabs. The inspector also provides a read-only Recent Scans view using the existing `/api/recent-pulls` data. It is a frontend-only update and does not alter camera, recognition, orchestration, scoring, API, database, artwork-index, or storage behavior.

## Install

Start from a clean `v6.4.14` checkout. Copy this installer and `updates/update_15_payload/` into the project, then run from the RareIQ root:

```powershell
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_15.py --verify-only
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_15.py
```

The installer verifies the project and pre-update markers, validates the eight-file allowlist, creates a timestamped backup, installs the complete payload, compile-checks Python tests, and runs the focused Studio X suite.

## Rollback

Copy, checksum, compilation, or test failure automatically restores the pre-update files. Manual rollback uses the backup path printed during installation:

```powershell
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_15.py --rollback updates\backups\update_15_YYYYMMDD_HHMMSS_microseconds
```

Rollback paths and manifest entries are constrained to the RareIQ project and validated before restoration.

## Files installed

- `rareiq/web/static/control.html`
- `rareiq/web/static/studiox.js`
- `rareiq/web/static/studiox_ui4_tokens.css`
- `rareiq/web/static/studiox_update15.css`
- `tests/test_studiox_live_recognition_contract.py`
- `tests/test_update_15_studiox_compact_ui.py`
- `tests/test_update_15_studiox_responsive_ui.py`
- `tests/test_update_15_camera_preview_history.py`

The updater never targets recognition or camera services, APIs, databases, catalogs, card images, artwork indexes, captures, secrets, or storage configuration.

## UI behavior

The rail supports waiting, active, complete, warning, failed, and skipped states using visible text and symbols. Backend stage names are normalized in the browser only. EMPTY and server-session changes reset the rail while preserving the existing generation/revision guards and inspector clearing.

The UI 4.0 token stylesheet loads after the legacy cascade and the scoped Update 15 component stylesheet loads last. At 1920x1080 the application uses an 84px navigation rail, 400px inspector, 68px command bar, and 52px camera pipeline. At 2560x1440 the rail expands to 188px and the inspector to 460px. The camera image again occupies the full containment viewport, retaining the checkpoint `object-fit: contain` framing and normalized scan-zone alignment while the pipeline overlays its lower edge. The Status popover contains lower-frequency camera controls and health telemetry. The Diagnostics drawer overlays the camera without resizing it and closes with Escape.

Current Card remains the default inspector view. Recent Scans requests the newest 20 completed pulls from the existing endpoint only when selected, sorts them newest-first, and offers read-only details plus a Return to Live Card action. It creates no second recognition polling loop and does not touch recognition generation or revision guards. Live EMPTY clearing still clears the current card underneath history; a server-session change returns the inspector to Current Card. Presentation state never initiates recognition or changes camera APIs, generations, revisions, or server-session behavior.
