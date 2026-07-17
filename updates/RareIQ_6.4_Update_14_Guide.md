# RareIQ 6.4 Update 14 — Continuous Live Recognition

Update 14 adds continuous, generation-ordered recognition for handheld cards. The orchestrator is the sole recognition coordinator; direct card swaps invalidate old results, confirmed removal clears Studio X, and Manual Capture always processes the newest camera frame.

The detector accepts valid card contours down to 1.5% of the resized scan-zone area so cards held farther from the camera can enter acquisition. Aspect ratio, rectangularity, solidity, corner, edge-support, ROI, and overall-confidence safeguards remain unchanged.

When a normal accepted rectangle is contained inside a much larger fragmented card-shaped contour, the detector may recover the larger minimum-area envelope as a fallback. The envelope must have a card-aspect score of at least 0.70, remain inside the ROI within four detection pixels, be at least four times the inner area, contain the inner rectangle, and have local edge density of at least 0.16 on three of four sides. It must also meet the normal detection-confidence threshold. Normal contour scoring always runs first; these rules do not relax its geometry checks.

Replacement detection uses an eight-frame rolling window and requires six frames with simultaneous full-card dHash distance of at least 16/64, artwork-region dHash distance of at least 14/64, structural similarity below 0.72, polygon IoU of at least 0.75, and normalized corner movement no greater than 0.025. Several stable captured samples form the reference consensus. Successful capture rebases the acquisition history so glare, autofocus, or an older high-quality frame cannot repeatedly become the card identity.

A second conservative qualification branch handles full-card layout-hash collisions: artwork dHash distance of at least 14/64 plus structural similarity below 0.60 may qualify without full-card dHash 16, but only when the same geometry, detection-confidence, and crop-quality safeguards pass. Confirmation remains six qualifying observations in the most recent eight. Nonqualifying observations stay in that bounded window; one or two glare, autofocus, or near-identity frames therefore cannot erase sustained evidence or independently confirm a change. The full window resets only after three consecutive invalid-geometry observations or six identity-collapse observations in eight, plus the existing removal, replacement, acquisition-epoch, and successful-capture resets.

Identity and geometry are intentionally routed to different references. Full-card dHash, artwork dHash, and structural similarity compare a proposed replacement against the captured Card A consensus. Polygon IoU and corner movement compare Card B only against the rolling median of recent proposed-B polygons. Consequently, a shifted Card B can confirm when it is internally stable, while an unstable moving proposal resets its geometry window. The proposed window is bounded to eight frames and resets when identity collapses, geometry becomes invalid, removal is confirmed, replacement is confirmed, or capture rebases identity.

A confirmed replacement is latched so Vision emits exactly one `card_changed` event. The acquisition epoch advances once, the orchestrator clears Card A and enters `CHANGING`, and one validated Card B crop is accepted for that generation. Duplicate change events from the same epoch and duplicate automatic captures for the same generation are ignored.

Vision and the orchestrator retain bounded 64-entry diagnostic journals. They record replacement-window decisions, capture validation, state transitions, generation changes, recognition submission, completion, and obsolete-result discard. The read-only continuous journal is exposed alongside `/api/trigger/status`; Vision replacement decisions are included in acquisition telemetry.

Automatic capture now selects from eligible recent consensus samples instead of a global quality winner. A candidate must belong to the current acquisition epoch, have a valid frame ID, be no more than 400 ms old, agree with the current lock polygon at IoU 0.80 or higher, and be newer than any frame quarantined during the current lock revision. Only after this filter does the existing quality and multiframe-consensus score determine ordering.

Samples rejected for stale frame, polygon mismatch, invalid epoch, or invalid frame ID are quarantined for that lock revision. Vision immediately tries the next eligible newer sample in the same capture cycle. If none exists, capture remains armed and waits for newer frames without emitting a capture or changing recognition generation. Quarantine resets on a new lock revision, replacement, removal, acquisition-epoch change, or successful capture. Capture thresholds remain unchanged.

Capture-selection telemetry is cumulative and independent of the bounded journal: total attempts, total rejections, rejection counts by reason, current quarantine size, last rejected and accepted frame IDs, consecutive retries, eligible-sample count, and lock revision.

While recognition is running, ambiguous change evidence is deferred and cannot invalidate the active generation. A direct replacement may invalidate immediately only when the complete rolling-window evidence is decisive. Ambiguous deferred evidence is discarded after the active result publishes; a persistent replacement will produce a fresh decisive event.

Before any automatic or manual recognition handoff, the exact 1000x1400 crop must pass capture validation. The initial gate requires Laplacian sharpness of at least 5.0, grayscale standard deviation of at least 28.0, edge density of at least 0.008, edge support of at least 0.012 on three of four crop sides, polygon IoU of at least 0.80, a frame no more than 400 ms old, and the current acquisition epoch. Rejected crops remain armed for retry and expose their metrics and reason in Vision telemetry.

The `card_captured` event carries a read-only copy of the exact accepted crop together with its path, frame ID, polygon, timestamp, acquisition epoch, source, and validation metrics. The orchestrator submits that event crop directly; it never re-fetches `latest_crop()`. Stale epoch or frame events are rejected without advancing the recognition generation.

Automatic capture selects its consensus sample before attempting the save. A missing, invalid, or recoverably failed sample remains armed for retry and is reported through capture-validation telemetry without terminating the Vision worker. Camera/device open and frame-read failures still terminate the worker through the outer fatal handler.

Camera health is based on authoritative device-sequence progression, not retained JPEG bytes or an application frame counter alone. Every successful device read carries a stream-session ID, device sequence, device timestamp, application frame ID, normalized 64-bit content fingerprint, camera index, and backend. The stream-session ID changes only after a genuine camera open or recovery. Telemetry includes repeated-content count, the last genuinely changed-frame timestamp, and the last duplicate-content application frame ID.

Acquisition samples retain that provenance. Every accepted capture must belong to the current stream session and acquisition epoch, have a device sequence newer than the epoch baseline, and have been observed after EMPTY or replacement acquisition began. A pre-removal duplicate requires all three conservative signals: full-card dHash distance at most 2/64, artwork dHash distance at most 3/64, and structural similarity of at least 0.94. Such a sample is quarantined, automatic capture remains armed, and Vision tries the next eligible sample without advancing recognition generation. A legitimate return of the same card is allowed after genuinely changed empty-scene content and fresh device progression establish a new acquisition.

The orchestrator rejects mismatched stream-session or acquisition-epoch capture events and journals the complete accepted provenance. Submission and completion records retain crop path, capture source, generation, frame ID, stream session, device sequence, acquisition epoch, content fingerprint, and published candidate ID/name so completed A/B cycles remain attributable after recognition finishes.

Each RareIQ server process creates one random `server_session_id`. Recognition, trigger, and mission-control state responses expose it. Studio X tracks the ID independently of recognition generation: a changed server session clears card artwork and inspector fields, resets generation/revision guards and pipeline presentation, then accepts the new process baseline. Older generations and revisions remain rejected within the same server session, and an `EMPTY` state always removes prior artwork and confidence.

A stream is healthy only while Vision reports running, its worker thread is alive, authoritative device progression is newer than the two-second stall timeout, and no camera error is active. A frozen stream becomes `stalled`; a dead worker becomes `error`. Start, stop, and recovery operations are serialized, and starting the same already-healthy camera returns `already_running` without stopping or reopening it. Studio X uses these authoritative fields to display ONLINE, STALLED, or OFFLINE; card visibility is not a camera-health signal.

## Install

Start from a clean `v6.4.13` checkout, copy this updater and the committed `updates/update_14_payload/` directory into the project, then run from the RareIQ root:

```powershell
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_14.py --verify-only
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_14.py
```

The installer verifies project and v6.4.13 markers, validates the payload allowlist, creates a timestamped pre-update backup, installs the payload, compile-checks every Python target, and runs the targeted Update 14 regressions.

## Automatic rollback

Any copy, checksum, compilation, or test failure automatically restores every pre-update file from the timestamped backup. Backup paths and manifest entries are resolved beneath the project directory before use, preventing rollback path escape.

## Manual rollback

Use the backup path printed by the installer:

```powershell
.venv\Scripts\python.exe -B updates\RareIQ_6.4_Update_14.py --rollback updates\backups\update_14_YYYYMMDD_HHMMSS_microseconds
```

The manifest checksum is validated before each original file is restored. Files that did not exist before installation are removed.

## Files installed

- `rareiq/services/vision_service.py`
- `rareiq/services/camera_manager_service.py`
- `rareiq/core/orchestrator.py`
- `rareiq/services/recognition_service.py`
- `rareiq/services/trigger_manager_service.py`
- `rareiq/core/recognition_state.py`
- `rareiq/web/server.py`
- `rareiq/web/static/studiox.js`
- `tests/test_continuous_recognition_state_machine.py`
- `tests/test_automatic_recognition_trigger.py`
- `tests/test_vision_trigger_handoff.py`
- `tests/test_trigger_manager_service.py`
- `tests/test_vision_confidence_engine.py`
- `tests/test_update_12_high_resolution_roi.py`
- `tests/test_update_13_artwork_verification.py`
- `tests/test_camera_manager_service.py`
- `tests/test_studiox_live_recognition_contract.py`

The updater never targets databases, catalogs, card images, captures, artwork indexes, secrets, or storage configuration.

## Runtime behavior

The server publishes `EMPTY`, `ACQUIRING`, `STABLE`, `RECOGNIZING`, `IDENTIFIED`, `CHANGING`, and `LOST`. Each physical-card generation invalidates older work. Recognition can finish obsolete computation internally, but obsolete results are discarded. If the worker is busy, only the newest current-generation crop is retained.
