# RareIQ Release Checklist

Latest audit: [2026-08-30 readiness findings and next test order](READINESS_AUDIT_2026-08-30.md).
Local automated checks are green; hardware/account/streaming acceptance is not yet signed off.

Run the release gate from the repository root with the Python 3.13 environment active:

```powershell
.venv\Scripts\python.exe -B tools\release_check.py --require-node
```

If Node.js is not on `PATH`, provide its executable explicitly with `--node`.

The gate verifies:

- installed dependency integrity
- Python syntax without writing bytecode
- JavaScript syntax, including inline scripts in shipped HTML
- duplicate HTML IDs and missing local static assets in every shipped HTML document
- isolated JavaScript behavior tests for browser-source/replay recovery, soundboard playback, recording controls, and microphone lifecycle
- working-tree and staged whitespace
- the complete canonical `tests/` suite

The gate does not require cameras, API credentials, an artwork index, captures, catalog caches, or other runtime data. GitHub Actions runs the same command on Windows for pull requests and protected development/release branches.

Before creating a release tag:

1. Confirm the branch and worktree are clean.
2. Confirm `rareiq/version.py` contains the intended release version and no development suffix.
3. Run the release gate successfully.
4. Review the exact commit and tag targets.
5. Push without force and verify the remote workflow passes.

## Product validation order

Use this sequence after the desktop feature set is locked. A later test should not begin while an earlier dependency is failing. Record the build, machine, operator, result, and evidence path for every physical or third-party test.

### 1. Installation and process lifecycle

- [ ] Install or update from a clean supported release.
- [ ] Verify backup, compile checks, targeted tests, and automatic rollback.
- [ ] Start RareIQ once; confirm one server, one Vision worker, and one camera owner.
- [ ] Stop and restart cleanly without visible console windows or orphaned processes.
- [ ] Confirm server-session IDs change only after a backend restart.

### 2. Camera discovery and workspace

- [ ] Start with the camera unplugged, reconnect it, refresh devices, and select it.
- [ ] Confirm active-source persistence and truthful disconnected/recovery states.
- [ ] Validate 1080p request, supported-resolution fallback, FPS, frame age, and device sequence.
- [ ] Validate Camera 1 recognition, staging cameras, 1–4 camera layouts, and source isolation.
- [ ] Validate PTZ, focus, exposure, white balance, presets, and unsupported-control states.
- [ ] Run a 60-minute camera endurance and reconnect test.

### 3. Single-card recognition

- [ ] Detect near, far, angled, foil, low-contrast, and partially occluded cards.
- [ ] Verify the full-card polygon, 1000×1400 crop, reference image, and crop comparison.
- [ ] Verify exact match, provisional, review-needed, reference-missing, and unknown states.
- [ ] Verify OCR name, collector number, language, set, HP, and truthful missing evidence.
- [ ] Verify variant-family resolution for near-duplicate, stamped, holo, and symbol variants.
- [ ] Verify Approve, Reject, Review Match, Search Catalog, and Next/Clear.

### 4. Continuous live operation

- [ ] Hold one card through glare, autofocus, and small movement without retriggering.
- [ ] Swap A-to-B directly and confirm one new generation and one recognition job.
- [ ] Remove A, reach EMPTY, present B, and confirm the old result clears.
- [ ] Confirm stale recognition jobs cannot overwrite the newest card.
- [ ] Confirm Manual Capture always produces a fresh validated crop.
- [ ] Scan at least 50 cards continuously and record latency, errors, and duplicate events.

### 5. Multi-card mode

Automated baseline (2026-08-30): analyzed counts are separate from verified counts;
saved results are labeled, missing confidence is not fabricated as 0%, and canonical
names/reference paths are shared by the operator and browser source. Only verified,
resolved identities can be newly selected. Invalid/rejected selections preserve the
existing output. Tests cover stale tiles, image failures, double-clicks, status-request
failures, capture/selection exclusion, delegated-worker failure, and overlay filtering.
Multi-card tests now use temporary history/presentation files: they must never replace
the operator's saved scan. The live-camera acceptance items below remain unverified.

Multi-card detection/recovery baseline (2026-08-30): the contour detector accepts
normal three-card layouts above the former 8.5%-of-frame cutoff, preserves perspective
corners, and suppresses nested artwork/text proposals. A camera-only replay of the
supplied Slowpoke/Armarouge/Tropius screenshot finds three full-card regions in physical
left-to-right order. This verifies geometry, **not** exact catalog identification.
Synthetic tests cover large tilted cards, blank-region rejection, and nested proposals.
Interim references now use the recognizer's explicit eligible candidate, not the first
raw retrieval hit. Geometry confidence is separate from identity confidence.
Index/submission/result failures fail closed, stalled analysis expires after 120 seconds,
and late worker events cannot replace a newer scan. Worker startup/final-validation
failures release ownership; a still-running native OCR call is not forcibly terminated.
Empty/in-progress rescans invalidate old saved output before it can be restored.
These backend changes need a controlled restart before live acceptance.

Multi-card crop/OCR follow-up (2026-08-30): bright external silhouettes now complement
edge contours, break thin bridges, and retain structured foreshortened cards. Tests
cover the three-card textured-table case at 0.5x/1x/2x resolution and reject blank
foreshortened rectangles. Final worker/reconciliation output cannot promote a rejected
retrieval-only hit to a card identity. Grid OCR keeps its cheap first pass, then allows
one offset-footer retry and a title read only when identifiers are missing. General
OCR explicitly restores detection/classification: RapidOCR persists the fast-line
mode flags between calls, which previously disabled subsequent fallback detection.
A stateful-engine regression test covers repeated fast/fallback/title transitions.

Offline replay of one saved live-preview JPEG now returns all three complete cards
in order. Armarouge 12/84 and Tropius 1/84 verify against local references. Slowpoke's
title is read correctly but its footer remains unresolved; it stays Review needed,
without an unrelated reference or invented confidence. This preview contains the
single-card outline and is **not raw-camera acceptance**. The replay uses local
indexes and temporary scan/history/output storage; the live scan and output are
untouched. These follow-up changes still require a controlled backend restart and
a fresh three-card scan before claiming the live issue is resolved.

Live follow-up (2026-08-30, 15:09 PDT): controlled restart completed (PID 58552,
session `0dea73b70e504a1f87cd1abaf8fce587`); the Insta360 Link recovered at 3840x2160
with a fresh stream and one loopback listener. Fresh multi-card job 1 detected and
verified all three physical cards independently: Slowpoke 029/084, Armarouge 012/084,
and Tropius 001/084. Slowpoke used the bounded footer retry; the other two used the
fast footer pass. Selected output stayed empty. This passes one real three-card
recognition case, not the broader 2–12-card, movement, glare, or on-air acceptance matrix.

Repeatability follow-up (2026-08-30, 15:32 PDT): the subsequent user scan exposed
another Slowpoke failure: a high-confidence but incorrect `029/064` footer skipped
both recovery and title OCR. Grid OCR now retries a syntactically valid identifier
unless independently verified artwork supports that complete fraction. The retry
remains bounded; full-card and catalog-image OCR are still skipped. If necessary,
the observed title filters local retrieval (8 hits, at most 4 directly verified
references). Conflicting OCR alternatives, or a standalone three-digit footer with
a slash read as `1`/`7`, can be recovered only when the observed digits match a
directly verified reference. Original OCR text is retained; catalog digits are not
substituted into observations. Ambiguous alternatives remain unresolved.

Live validation on the final running build: controlled restart to PID 37488,
session `36d339df28a84836874b3593e145c4ad`; fresh 3840x2160 Insta360 Link stream,
one loopback listener, no camera error. Five consecutive fresh jobs (1–5) each
detected and verified Slowpoke 029/084, Armarouge 012/084, and Tropius 001/084 in
left-to-right order. Job 1 corrected an initial `025/084` read using the independent
`029/084` retry. All three catalog PNG endpoints returned HTTP 200; selected output
stayed empty throughout. An earlier five-job run of the recovery patch also passed
3/3 each time. No cards were sent on air.

Timing is not signed off: the final cold scan took 19.5 seconds; subsequent scans
took 8.6, 7.8, 8.0, and 9.9 seconds. A verified catalog record using `name` instead
of `canonical_name` no longer triggers a redundant family search. Status snapshot
waiting is off the async event loop. Necessary reconciliation still dominates some
scans and needs a separate performance pass. The full release gate passed 2,285
Python tests and 68 JavaScript behavior tests, including unsupported-footer,
separator-recovery, ambiguity, exact-name filtering, and status-thread regressions.
This is repeated acceptance of this three-card setup, not a claim that every card,
lighting condition, 2–12-card layout, or broadcast integration is validated.

Status/performance follow-up (2026-08-30, 16:02 PDT): restarted to PID 40152,
session `aa0dec5f0b7c4ddf8ec814ef632c9d73`. The camera's top shield and bottom HUD
now share the active workflow's presentation. Background single-card updates and
handoff events cannot replace multi-card progress; camera-offline state takes
precedence, and switching back restores the latest single-card state. Browser QA
covered idle, recognizing, complete, partial review, restored, empty, transport
failure, disconnection/recovery, and mode switching. The actual live UI displayed
Saved Scan on both badges, matching its restored three-card results.

Exact-footer lookup now runs before unnecessary grid OCR recovery and is reused
within that same crop's worker. Independently verified artwork plus the observed
complete fraction avoids redundant family retrieval, without promoting candidates
or bypassing temporal/output safety. Full gate: 2,303 Python + 70 JavaScript tests.
An old source-string assertion was replaced with a behavioral exact-lookup test.

Live timing acceptance remains pending: selected output was discovered as slots
1/2/3 after restart and was preserved, so automated fresh captures were stopped.
Five isolated replays of fresh 1920x1080 preview frames used temporary state only:
2.438s (3/3), 1.304s (3/3), 1.712s (3/3), 9.174s (2/3), 1.382s (3/3).
The fourth replay withheld the unresolved first card and spent 5.624s on family
recovery; do not describe this as five clean passes. A subsequent diagnostic replay
returned 3/3 in 1.318s. These preview replays are not raw 4K live-capture acceptance.
Obtain permission to clear selected output before repeating live timing tests;
retain the slow/review case in the performance and recovery acceptance matrix.

Visible match-speed follow-up (2026-08-30): the consolidated Recognition Workspace
header now shows `Matched in`, `Candidate in`, or `Analyzed in` with measured elapsed
time. It prefers camera-to-result timing (including queueing), falls back to worker
processing time with an explicit tooltip, and never sums overlapping stage timers.
Missing timing, card handoff/stale generations, idle, and disconnect cannot retain an
old match time. This measures the latest scan, not the entire multi-scan verification
cycle. The detailed timing trace remains separate from the compact result badge.
Seven new JavaScript regressions pass; full gate: 2,303 Python + 77 JavaScript tests.
Browser QA checked the actual live candidate (756 ms), plus verified/candidate/review,
missing/stale/idle/disconnected states with production CSS in dark/light and wide/narrow
headers using `/qa/speed` on `tools/preview_multi_card.py`. Asset versions prevent
cached old styling from breaking the badge. No production restart or new capture;
multi-card job 8 and selected slots 1/2/3 were preserved. The overlay rebrand and fresh
raw-camera timing acceptance remain pending.

Camera-outline baseline (2026-08-30): the production renderer now recalculates
scan-region coordinates after image load, preview/inspector resizing, and fit changes.
It uses the loaded image's dimensions and actual letterboxing, never a guessed aspect
ratio. Resize work is coalesced to one animation frame; cleared regions stay cleared
and teardown releases observers. Six regression tests cover those cases, cover/fill
fitting, and invalid coordinates. Camera-free browser QA reproduced the old resize
drift and verified all three outlines against known card corners after resizing and
frame reload. These are scan-time regions, not continuous tracking of moving cards.

Saved-frame geometry replay (read-only, no camera):
`.venv\Scripts\python.exe -B tools\check_multi_card_frame.py <image> --region <left> <top> <right> <bottom> --max-cards 12`.
Use a camera-only region; browser decorations/detection boxes are not raw camera input.

For a diagnostic snapshot of the existing preview (does not acquire a camera):
`.venv\Scripts\python.exe -B tools\check_multi_card_frame.py --current-preview --preview-dir .tmp\multi-card-diagnostic`.
Replay that saved file with `--recognize` to exercise local recognition using temporary
state. Do not treat preview annotations as card pixels or a replay as live acceptance.

Camera-free visual preview: run `.venv\Scripts\python.exe -B tools\preview_multi_card.py`
and open its loopback URL. It exercises production markup, styles, rendering, and the
selection service with synthetic artwork and temporary data, without starting RareIQ
or acquiring a camera. Check 1/6/12 results, narrow/4K layouts, saved/review/error states,
missing images, and Show/Hide in the selected-card browser source.
Open `/qa/geometry` on the same preview server to check production camera outlines
against a synthetic three-card frame using Resize camera area and Reload frame.

- [ ] Switch between Single Card and Multi-Card Grid without losing camera selection.
- [ ] Validate 2–12 cards, complete-card containment, ordering, and unique-variant mode.
- [x] Rescan Slowpoke, Armarouge, and Tropius together; require three full-card regions and independently correct catalog identities (five consecutive final-build scans; broader conditions remain pending).
- [ ] Resize the inspector and switch camera fit with scan results visible; require numbered outlines to stay aligned with the captured card regions.
- [ ] Verify incomplete, overlapping, duplicate, and low-quality cards fail truthfully.
- [ ] Confirm one unverified card shows one result, Review needed, no invented score, and disabled Show.
- [ ] Verify real reference-image loading and verified Show/Hide in the OBS browser source.
- [ ] At 4K, confirm all 12 result cards fit; at narrower sizes, confirm usable scrolling and no horizontal clipping.
- [ ] Restart with saved results; confirm Saved scan until a fresh Scan Cards capture.
- [ ] Verify error/timeout → retry, and confirm late results or restarting during a rescan never restore an older card on air.
- [ ] Verify selecting a result does not mutate recognition generation guards.

### 6. Pack workflow

- [ ] Enter Pack Scan intentionally; verify Card Identify remains the safe default.
- [ ] Scan a learned wrapper and lock the correct set and language.
- [ ] Learn a new wrapper only after a set is explicitly selected.
- [ ] Verify expected-card count, current-card progress, rare-slot marker, and hit evidence.
- [ ] Complete a pack and verify automatic or manual next-pack handoff occurs once.
- [ ] Verify pack removal recovery, no stale-sample retries, and no duplicate submissions.
- [ ] Validate Pack Speed history, tuning recommendations, export, and reset.

### 7. Catalog, collection, and business data

- [ ] Search, filter, inspect, add, edit, and remove collection records.
- [ ] Validate catalog downloads, reference coverage, artwork sync, and missing-reference states.
- [ ] Validate price availability, stale pricing, unavailable pricing, currency, and cost basis.
- [ ] Confirm unpriced cards never produce invented values or margins.
- [ ] Validate import/export round trips without modifying the source file.

### 8. Provenance and capture

Automated baseline (2026-08-29): deterministic coverage now exercises manual API
capture/read/asset/correction round trips, PNG checksums and native dimensions,
workflow metadata, strict trigger/confidence safety, same-session duplicate
suppression and new-session capture, malformed settings/history recovery, short
writes and disk-sync failures, retry recovery, and byte-preserving corrections.
These checks do **not** sign off the live acceptance items below. Backend changes
require a controlled restart before testing the running app; no live restart was
performed during this unattended pass.

- [ ] Manual Screenshot creates a confirmed event, manifest, image, and matching checksum.
- [ ] Auto Screenshot remains off by default and deduplicates one event per card context.
- [ ] Repeat the same card after a server restart; confirm a new event and accessible prior evidence.
- [ ] Validate full-frame, card-focus, and evidence-view availability rules.
- [ ] Verify provisional identity, missing rarity, or missing value cannot satisfy unsafe triggers.
- [ ] Validate customer, vendor, session, pack, turn, and player-side metadata.
- [ ] Verify corrections preserve the original event and add revision history.
- [ ] Switch/disconnect the active camera during capture; verify no source/identity mix-up.
- [ ] Interrupt external storage during capture and correction; verify truthful errors, retry, and prior evidence integrity.

### 9. Broadcast production tools

Automated baseline (2026-08-30): isolated OBS clients verify connection cleanup
on success/failure, stream-route invalidation/reconnect, detached settings, and
configuration rollback after a failed save. Overlay tests execute the production
JavaScript with a simulated DOM, clock, and network: same-generation visibility,
expired graphics, same-card profile updates, On Air changes, disconnect recovery,
bounded single-flight polling, and teardown. API tests cover slow species lookups
across card changes, verification withdrawal, and multi-card selection changes.
Reset hides all overlay surfaces; saved Rare Intelligence themes survive restart.
The release gate runs these checks without opening a camera, connecting to OBS,
or publishing a stream. They do **not** replace the live acceptance tests below.
These backend changes require a controlled restart before live validation.

Audio baseline (2026-08-30): simulated media tests cover queue/layer transitions,
duplicate error callbacks, Stop All, one shared playback animation loop, pad-image
preservation/filtering, and recovery from malformed local presets. Microphone
tests cover clean processing, zero output, cancellation during permission/device
startup, disconnect cleanup, slow shutdown, and remembered input selection.
Storage tests cover missing assets, duplicate pad IDs, malformed saved data, and
failed saves preserving both active configuration and prior disk state. No real
speakers, microphone, or Spotify connection are used by these tests.

Recording/replay baseline (2026-08-30): fake encoders verify Windows argument
quoting, paths containing spaces, unique output names, start/stop ownership,
cancelled tests, forced-stop failures, persistent finalization status, and atomic
settings rollback. Replay tests cover stale buffers, provider recovery, partial
frame/index writes, retention while on air, missing frames, malformed history,
and playback expiry. Browser-source tests cover current-time resume, disconnect
recovery, late image callbacks, and teardown. No physical camera, microphone,
encoder process, or live server was started by this test pass. "Verified" recording
status means a clean encoder exit and a non-empty output, not a full media-decode
or audiovisual-quality check; those checks remain below.

Auto Clip baseline (2026-08-30): **implemented; live-device acceptance remains pending**.
In Broadcast → Instant Replay & Auto Clip, save settings and explicitly arm.
Only new, current, conflict-free VERIFIED cards with reference evidence qualify;
the default threshold is a big hit or better (the existing reveal hit classifier).
The current verified card is not captured retroactively when arming.

- Default window: 5 seconds before verification + 3 seconds after; configurable
  pre-roll 1–10 seconds and post-roll 1–6 seconds.
- Reuses the existing Program-camera JPEG buffer; no second camera owner, microphone,
  OBS capture, or automatic On Air action. Output is a **silent 5fps MPEG-4 MP4,
  up to 1280px**, preserving the entire frame with letterboxing where necessary.
  It does not include browser graphics or mixed show audio; full A/V recording is separate.
- Three pending/saving clips maximum; one attempt per recognition generation.
  A cold/incomplete buffer, stale camera frame, source change, or full queue skips
  that pull with a visible reason. No endless retry or duplicate-clip storm.
- Auto and manual highlights share the existing newest-25 retention policy;
  an active replay is protected. Download important clips before they age out.
- Disarming cancels queued/in-progress capture; encoding checks cancellation before
  publishing. A save already committed may finish. Settings persist, but arming does not.
- Encoding is off the event loop. Saved MP4s are decoded before success is reported;
  failed/cancelled writes clean up partial files and preserve prior history.
- Automated tests cover gates, deduplication, boundaries, source freshness, cancellation,
  disk/codec failures, actual synthetic MP4 encoding/decoding, APIs, and UI request races.
  Browser skill QA in an isolated preview exercised save/arm/disarm, synthetic pulls,
  MP4 download, interruption, and manual replay. Mobile and 4K component widths were
  checked for overflow. No live RareIQ server, camera, microphone, or account was used.

Repeat the isolated browser check with
`.venv\Scripts\python.exe -B tools\preview_auto_clip.py` (loopback-only URL printed
at startup; synthetic frames and temporary storage). This preview never boots RareIQ.

- [ ] Validate Broadcast workspace layout, session controls, history, and economics.
- [ ] Validate browser-source overlays, On Air state, Rare Intelligence, card reveal, and clear.
- [ ] Disconnect/reconnect OBS and verify status, scene mappings, authentication errors, and no orphaned request connections.
- [ ] Disable On Air during a slow lookup, swap cards, and select a different multi-card result; verify no old profile reappears.
- [ ] Reload browser sources during/after a timed graphic; confirm expired graphics do not replay.
- [ ] Interrupt the browser-source network and restore it; verify stale identity hides and current state recovers.
- [ ] Validate Soundboard, Voice, FX, Instant Replay, recording, and truthful unavailable states.
- [ ] Recording: run the generated encoder test, play the output, verify duration/audio/video, then test device-based recording and graceful/forced shutdown.
- [ ] Recording: validate paths with spaces, storage disconnect/full, start/test conflicts, clean server shutdown, and report persistence.
- [ ] Instant Replay: mark a highlight, switch Program cameras, take it at each speed, reload the browser source mid-clip, and Return To Live.
- [ ] Auto Clip: arm with a warm Program buffer; scan qualifying/nonqualifying cards, swap cameras, disconnect/reconnect, disarm during post-roll, download and play the MP4 in the intended editor/player; verify silent output and restart-disarmed behavior.
- [ ] Soundboard: test queue/layer switching, Stop All during loading, corrupt/missing audio, volume, images, and preset persistence.
- [ ] Voice: use headphones to test each effect, monitoring, device unplug/reconnect, permission cancellation, and stream handoff to production.
- [ ] Confirm overlays never expose provisional identity as an exact match.
- [ ] Run a full mock stream with camera switching, card swaps, captures, and recovery.

### 10. Streaming-platform integrations

Inventory each connector before testing; do not treat a UI placeholder as working support.

- [ ] Twitch: authentication, scopes, destination selection, reconnect, and revocation.
- [ ] YouTube: authentication, channel selection, stream lifecycle, and quota errors.
- [ ] TikTok: supported publishing path, authentication, eligibility, and truthful unsupported state.
- [ ] Kick: authentication, channel configuration, reconnect, and revocation.
- [ ] Rumble: supported publishing path, configuration, reconnect, and error handling.
- [ ] X: authentication, broadcast destination, permissions, and revocation.
- [ ] Facebook: page/profile selection, permissions, token expiry, and revocation.
- [ ] Instagram: supported live path, account eligibility, permissions, and truthful unsupported state.
- [ ] Confirm no secrets enter Git, logs, exports, screenshots, or diagnostics.

### 11. Desktop UX and accessibility

- [ ] Validate dark and light themes at 3840×2160, 1920×1080, 1366×768, and 1024×768.
- [ ] Verify no overlap, clipping, duplicate IDs, horizontal overflow, or inaccessible controls.
- [ ] Complete all workflows with keyboard-only navigation and visible focus.
- [ ] Verify status, warning, error, empty, and disconnected states with readable contrast.
- [ ] Validate all left-rail workspaces against the shared RareIQ shell and brand system.

### 12. Mobile and remote access

- [ ] Validate install, launch, safe-area layout, orientation changes, and reconnect.
- [ ] Validate camera permission, source selection, operator controls, and card review on mobile.
- [ ] Validate local-network and approved remote-access paths without weakening security.
- [ ] Repeat core recognition, pack, provenance, and recovery flows on target mobile devices.

### 13. Help and operating guides

- [ ] Freeze feature names and workflows before authoring final documentation.
- [ ] Write operator, vendor, pack-ripping, broadcast, recovery, and troubleshooting guides.
- [ ] Populate Ask Sarge from approved RareIQ guides; answers must cite the relevant guide section.
- [ ] Verify suggestions never claim unsupported features or fabricate runtime state.

### 14. Final endurance, security, and release evidence

- [ ] Run an 8-hour mixed-workflow endurance test and inspect memory, CPU, GPU, handles, and disk growth.
- [ ] Validate camera/server crash recovery, network loss, storage-full behavior, and corrupt settings.
- [ ] Review permissions, secrets, local data retention, diagnostics, and exported customer data.
- [ ] Run the automated release gate again and archive the full validation evidence bundle.
- [ ] Create the release commit and annotated tag only after every required gate is signed off.
