# RareIQ readiness audit — August 30, 2026

## Decision

**Ready for structured local acceptance testing; not signed off for a production stream or release tag.**

The local server, camera, recognition engine, replay buffer, and saved multi-card output
recovered after a controlled restart. Broadcast preflight reports `local_ready: true`,
but `broadcast_ready: false` and `on_air_verified: false`. No stream was started and
no production on-air selections were changed during this audit.

## Repaired in this pass

- Scoped custom inspector width to Live. A late CSS rule had reserved the hidden
  right column on every other app, squeezing tool pages into part of the screen.
- Made the header brand size intrinsic, with a container-width breakpoint for
  narrow Live layouts; the logo and Studio X caption no longer compete for a fixed box.
- Fixed Broadcast's tab-row height budget: its 38px buttons plus padding were
  overflowing a 46px row. The row now measures 53px inside with no vertical overflow.
- Removed undefined presentation-token references; added dark/light primary-action
  text colors with a 4.5:1 contrast regression check. Light buttons were dark-on-dark.
- Replaced remaining audited legacy Broadcast/feature-label colors with semantic
  theme tokens. Warning, error, and intentionally selected custom accents remain distinct.
- Consolidated browser-source styling into `overlay_theme.css`; refreshed selected-card,
  landscape, portrait, current-card, graphics, countdown, replay, and Rare Intelligence
  defaults. Selected/reference card imagery uses contain sizing, not cropping.
- Added selected-card density handling for 1–12 results. Untouched old brand and Rare
  Intelligence palettes migrate without resetting deliberate custom colors or layout.
- Saved multi-card results retain their tiles/output, but their old polygons are no
  longer drawn over a different current camera frame.
- Fixed Spotify's active-device selection precedence, connected-but-idle messaging,
  stale cover art, and volume rendering while the operator is adjusting the slider.
  Status polling is single-flight and no longer refetches playlists every five seconds.
- Preserved zero corner radius in the Rare Intelligence theme editor.
- Extended the release gate to inspect all shipped HTML for duplicate IDs and missing
  local assets, and syntax-check inline JavaScript as well as standalone files.
- Added regression tests for layout ownership, token definitions, button contrast,
  overlay artwork sizing, brand migration, Spotify races, and stale scan geometry.

## Verification evidence

Canonical command:

```powershell
.venv\Scripts\python.exe -B tools\release_check.py --require-node --node C:/Users/jonat/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe
```

- Full gate: **2,316 Python tests and 82 JavaScript behavior tests** (final rerun).
- Dependency integrity, Python syntax, 37 HTML documents/local references, 32
  standalone/inline JavaScript sources, and working-tree whitespace checks.
- Browser review of the primary view in all 11 left-rail apps: Live, Collection,
  Broadcast, Creator, Soundboard, Voice Mod, Camera Effects, Spotify DJ, AI Lab,
  Library, and Settings. This is not a claim that every nested workflow was exercised.
- Dark/light header and Broadcast checks; main apps use the available canvas.
- Keyboard inspector resize changed width from 564px to 548px and back.
- Camera-free selection tests used the actual Show buttons and temporary storage.
  Three and twelve selected cards rendered complete images with no tile overflow at
  1280×720. Six-card output was visually checked in a 3840×2160 iframe viewport;
  twelve-card output was checked in a 1080×1920 portrait iframe viewport.
- Landscape, Rare Intelligence, graphics, and countdown browser-source visual checks
  used synthetic fixture data. Transparent canvas behavior was confirmed separately
  from the browser's white page background. OBS compositing is still pending.
- Backend restart at **17:31 PDT**, PID 63468, session
  `46ff0040568441d6b620c3b76f7dfa82`. Camera frames recovered. Multi-card job 8 still
  had three verified results and selected slots `[1, 2, 3]` after restart.
- Brand API after restart returned mint `#8be8ca`, slate panel `#18222e`, and chrome
  `#0b1016`. Startup log contained no traceback at the health check.

Repeat isolated visual QA with `tools/preview_multi_card.py`. The printed loopback
server has `/`, `/qa/speed`, `/qa/geometry`, and `/qa/overlay` test pages; all selection
state is temporary. The overlay viewport page supports 720p, 1080p, 4K, and portrait.

## Still incomplete or unverified

| Area | Current evidence | Requirement before sign-off |
| --- | --- | --- |
| Evidence-view screenshot | Explicitly unimplemented in `provenance_capture_service.py`; UI choice disabled | Implement and test it, or exclude it from the release scope and documentation |
| OBS / destinations | OBS connected and six browser-source scenes created; Program and selected cards checked in OBS Preview (see follow-up below); destinations still unverified | Configure only the intended destination; validate routing, start/stop and reconnect with explicit operator approval |
| Streaming support | App distinguishes supported monitors from conditional/external encoder paths | Do not advertise every listed platform as a native publisher; validate each promised integration |
| Full A/V recording | FFmpeg available; encoder hook not configured | Configure output, record, play back, verify audio/video/duration and failure recovery |
| Auto Clip | Implemented and automated tests pass; silent 5fps, up to 1280px | Confirm intended quality and retention; it is not full-resolution show recording |
| Spotify | Not connected | Authorize account, confirm Premium/device requirements, test playback/device transfer and token expiry |
| Voice / sound / PTZ / FX | UI and automated behavior checked; device interactions not exercised this pass | Headphone-monitored effect/level test, device release/reconnect, supported PTZ control test |
| Recognition | Saved three-card result and live health observed; automated race/gating suite passes | Fresh 50-card run and 4–12 physical-card layouts, including foil, unknown and near-duplicate printings |
| Collection / pricing / exports | App surface reviewed; automated suite passes | Real test dataset, quote freshness, cost basis, listings, imports/exports and backup restore |
| Backup | Existing manifests observed; same-volume backups are not disaster recovery | Copy to a separate device/location and test restoration |
| Desktop/mobile/accessibility | 1280px app review and overlay viewport checks | Physical 4K app, 1080p, smaller laptop, mobile, zoom and full keyboard-only acceptance |
| Endurance/security/release | Server remains loopback-only; version is `6.4.18-dev`; dirty worktree preserved | Mixed-workflow soak, permissions/export review, intentional commit review, release version/tag |

Large legacy `studiox.js` and layered stylesheets remain architectural debt. This pass
removed/replaced specific conflicting rules and palette definitions; it did not delete
active feature code simply because it is old. Extract workspace controllers/styles
incrementally behind the regression gate rather than doing an unverified bulk rewrite.

## Next test session — order

1. Camera start/reconnect, single owner, PTZ, and panel/header layout at the actual 4K desktop.
2. Single-card identity/reference review, match speed, swap/remove, approve/reject, and unknown cards.
3. Multi-card 3/6/12 detection, stable slot ordering, Show/Hide, rescan and restart persistence.
4. Browser sources in OBS: transparency, complete cards, Rare Intelligence sync, timed graphics and disconnect recovery.
5. Soundboard/Voice/FX with headphones; stop/release/reconnect and output routing.
6. Recording/replay/Auto Clip: record and play the actual files, verify limitations and storage failures.
7. Collection, pack tracking, provenance, imports/exports, and a separate-location backup restore.
8. Spotify, OBS and the selected platform account; private/unlisted test stream only after explicit operator approval.
9. Full mock show, then endurance testing and final release gate.

Detailed per-feature checkboxes remain in [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

## OBS setup follow-up — 2026-08-30

- Connected to local OBS 32.2.2 using authenticated WebSocket. Credentials were not
  included in source code, screenshots of the setup verification, or this report.
- Created Program, Graphics, Production Screen, Replay, Intelligence, and Multi Card
  scenes with distinct browser-source names. Existing operator scene `Scene` was preserved.
- Real OBS testing exposed a shared-name collision between scenes and inputs. Fixed
  bootstrap naming, completion of empty scenes left by failed attempts, preservation of
  existing nonempty scenes, and false success reporting. Added namespace-aware regression tests.
- All six 1920×1080 browser sources returned HTTP 200 and were fitted proportionally
  to the existing 3840×2160 canvas. OBS output resolution remains 1920×1080.
- Temporarily used Studio Preview to inspect Program and Multi Card, then restored
  Studio Mode and the selected Program scene. Multi Card rendered all three selected
  reference images completely with the current slate/mint styling. Program rendered
  the camera feed and its currently configured effect layer; effect styling is not
  claimed to be validated by this setup check.
- Verification screenshots: `artifacts/obs-setup/program-scene.png` and
  `artifacts/obs-setup/multi-card-scene.png` (local ignored QA output).
- No stream or recording was started. Live camera health recovered after the RareIQ
  restart and saved multi-card job 8 retained selected slots `[1, 2, 3]`.
- Automated gate: **2,321 Python tests + 85 JavaScript behavior tests passed**.
  Audio routing, timed overlays, full recording and destination end-to-end tests remain.

## Camera workspace follow-up — 2026-08-30

- Fixed the primary camera header spanning adjacent tiles and obscuring cameras 2–4.
  The dedicated camera stylesheet now owns all four header/media bounds, with matching
  source and player-side controls, full-frame previews, and slate/mint presentation.
- Manage Cameras opens the four-camera layout and focuses the first unassigned slot.
  Each empty secondary tile also has a Choose camera action. Source clearing and
  failed assignments restore the correct saved preferences without changing Camera 1.
- Removed the separate destructive Camera 2 dropdown renderer. Shared option updates
  are signature-cached and deferred while a native picker is focused; new stream frames
  no longer rebuild presentation. Hidden staging tiles release their preview streams.
- Prevented legacy recovery/status copy from leaking over the camera header. The scan
  workflow prompt stays inside Camera 1 and uses two full-width action buttons when
  the multi-camera workspace is narrow.
- Isolated browser tests used production controls, markup and styles with synthetic
  cameras: assignments for slots 2–4, clearing, failure recovery, player-side changes,
  and Manage Cameras. Sixteen viewport/layout cases passed at 1280×720, 1920×1080,
  3840×1980 and 3840×2160, covering single, two-, three- and four-camera layouts.
  Header bounds, overlap, selector hit targets and scan-prompt bounds were checked.
- Live browser review confirmed all eight source/side selectors were unobscured.
  Camera 1 remained connected to Insta360 Link; slots 2–4 were left unassigned.
  Additional physical camera streams and hardware promotion still need operator testing.
- Final release gate: **2,325 Python tests + 93 JavaScript behavior tests passed**,
  plus dependency integrity, Python/JavaScript syntax, HTML/local asset and whitespace
  checks. No production restart or OBS changes were needed for this camera follow-up.
- Repeat camera-free visual/interaction QA with `tools/preview_camera_workspace.py`;
  use its Test all sizes and layouts action for the viewport matrix.

## 1080p and OBS feed follow-up — 2026-08-30

- Inspector sizing now responds to the panel's width. Auto Next and action buttons
  no longer collide; Rare Intelligence facts wrap inside narrow panels.
- Live 1920×1080 checks passed for the normal single-card workspace and a three-card
  result grid (two columns, no right-rail overflow). Native 3840×2160 was rechecked.
  Shorter 1920×900 browser windows and the expanded Tools stack intentionally keep
  vertical scrolling; content is not clipped to manufacture a fit. Extra review
  evidence or long content may also require scrolling at smaller viewport heights.
- Added clean scan, individual Camera 1–4, and four-up OBS sources, plus an isolated
  soundboard audio source. Camera output uses WebSockets to avoid HTTP connection
  starvation when all feeds are active. Existing camera capture owners are reused.
- New regression tests cover clean-frame caching/staleness, original-session lease
  cleanup after source reassignment, four-slot WebSocket multiplexing, remote pairing,
  audio ordering/expiry/validation, and receiver layering/volume/stop behavior.
- Created all seven additional OBS sources and linked shared soundboard audio into
  RareIQ Program and its camera scenes. Verified clean scan image in real OBS and
  a nonzero meter on the dedicated soundboard input; Program selection was preserved.
- See `docs/OBS_CAMERA_AUDIO_OUTPUTS.md` for URLs, audio toggles, resolution limits,
  the repeatable OBS test command, and remaining physical-camera tests.
- Closing or cancelling a soundboard controller request no longer raises a server
  error or publishes partial audio state. Declared the existing Starlette version
  explicitly now that its disconnect exception is imported directly.
- Final release gate: **2,344 Python tests + 98 JavaScript behavior tests passed**,
  including dependency integrity, syntax, HTML/local assets and whitespace checks.
  RareIQ was restarted; real OBS scan/quad output and the dedicated audio meter
  passed again afterward. No stream or recording was started.

## Automatic OBS setup follow-up — 2026-08-30

- Enabled the soundboard's dedicated OBS output and disabled local monitoring.
  Routing now persists in RareIQ configuration, so browser profiles share the
  selected settings. Save failures roll back controls; revision checks reject stale
  settings responses. Existing pages need one reload to load this controller.
- Linked the one shared soundboard source into all 12 managed visual scenes,
  including Multi Card. OBS monitoring remains off; the dedicated source is
  unmuted. Desktop Audio, microphone and unrelated operator scenes were preserved.
- Restarted RareIQ, confirmed saved controls in a fresh browser page, and repeated
  the real OBS image/audio-meter check successfully with no stream or recording.
- Final gate: **2,350 Python tests + 101 JavaScript behavior tests passed**.
- Camera 1 remains Insta360 Link. Slots 2–4 await operator device selection; Mevo
  Wireless Camera and LSVCam are listed alongside virtual sources, but were not
  assigned speculatively or claimed to be verified physical feeds.
