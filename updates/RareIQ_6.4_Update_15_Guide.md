# RareIQ 6.4 Update 15 — Studio X Compact UI

Update 15 replaces the oversized Studio X workflow blocks with a compact five-step operator rail: Detect, Stabilize, Capture, Recognize, and Match. Phase 1 establishes the scoped UI 4.0 design-token and semantic-region foundation. Phase 2 applies the desktop information hierarchy for 1920x1080 and 2560x1440: one restrained app bar, one compact control row, a camera-first workspace, a compact current-card inspector, and a shallow diagnostics rail. It is a frontend-only update and does not alter camera, recognition, orchestration, scoring, API, database, artwork-index, or storage behavior.

## Install

Start from a clean `v6.4.14` checkout. Copy this installer and `updates/update_15_payload/` into the project, then run from the RareIQ root:

```powershell
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_15.py --verify-only
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_15.py
```

The installer verifies the project and pre-update markers, validates the seven-file allowlist, creates a timestamped backup, installs the complete payload, compile-checks Python tests, and runs the focused Studio X suite.

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

The updater never targets recognition or camera services, APIs, databases, catalogs, card images, artwork indexes, captures, secrets, or storage configuration.

## UI behavior

The rail supports waiting, active, complete, warning, failed, and skipped states using visible text and symbols. Backend stage names are normalized in the browser only. EMPTY and server-session changes reset the rail while preserving the existing generation/revision guards and inspector clearing.

The UI 4.0 token stylesheet loads after the legacy Studio X cascade and the scoped Update 15 component stylesheet loads last. Semantic regions cover the app bar, controls, camera, inspector, pipeline, diagnostics, product navigation, and future mobile actions without cloning functional elements. Phase 2 keeps health signals in the app bar and moves operator actions into the single control row. At 1920x1080 the camera receives all remaining workspace width after a 380px inspector; at 2560x1440 the inspector expands to 440px. The diagnostics dock remains shallow, all five pipeline steps remain visible, and the existing 1366x768 compact fallback is retained. Mobile restructuring belongs to a later phase.
