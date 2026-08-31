# RareIQ: streaming-first product direction

Confirmed by the owner on 2026-08-31. This supersedes the card-first release
ordering in older plans. It records requirements and proposed delivery boundaries;
it does not claim the modular product, licensing or standalone broadcaster exists.

## Confirmed direction

- RareIQ's primary product is a streaming-production studio for many kinds of
  creators: gaming, conversation, music, education, selling and card streams.
- Card scanning/recognition is a secondary, optional premium add-on. A general
  streamer must not need the card workflow to use the studio.
- Specialized and advanced features may be premium add-ons. Specific bundles,
  prices, trial rules and whether the base product is free are not decided.
- Preserve landscape and portrait production, existing outputs and integrations.
  General-purpose community features must not depend on collectible-card scanning.

## Broadcasting: what exists versus what is proposed

The current production routing explicitly uses an external encoder, OBS.
RareIQ can issue guarded Start/Stop commands through OBS WebSocket and supply
browser-source video, graphics and audio. OBS must run to perform that streaming.
The FFmpeg recording hook is not a supported standalone live-publishing engine.
Platform status/route monitors are also not native publishers or audience-event
connectors.

Standalone broadcasting is a proposed additional output adapter, not a completed
feature or an approved implementation milestone from the owner's question alone.
It would consume RareIQ's composed Program video and mixed audio, encode them,
and publish to a supported destination. For example, YouTube documents encoder
ingest via [RTMPS](https://developers.google.com/youtube/v3/live/guides/rtmps-ingestion).
Each platform's authorization, ingest access and actual media receipt must be
validated independently; never promise universal publishing from one route.

Keep the existing OBS path while developing the studio. If native publishing is
selected, give it its own scoped milestone: synchronized A/V, encoding presets,
device/resource ownership, secret storage, bitrate/drop reporting, reconnects,
deliberate start/stop, destination verification and sustained off-air tests.
Do not put a standalone Go Live label on an OBS remote-control button.

## Proposed product boundaries

| Module | Purpose | Candidate features; availability must be tracked separately |
| --- | --- | --- |
| Studio core | Produce a complete ordinary stream without a card catalog | Scene/source management, landscape/portrait canvas, cameras, media and screen/window capture, essential audio mixing, basic soundboard/overlays, output setup, recording controls and diagnostics |
| Card Studio premium add-on | Collectibles/card-specific workflows | Single/multi-card recognition, reference catalog, Rare Intelligence species information, inventory, pack/break workflows, chase bars and card-driven reactions |
| Community advanced add-on | Deep viewer personalization and engagement | Personalized viewer profiles, advanced TTS/voices, cross-platform automation, rewards and advanced leaderboard/giveaway presentations |
| Production advanced add-on | Advanced show automation and postproduction | Advanced replay/automatic highlights, complex scene rules, advanced analytics and future multi-output options |

These are proposed bundles, not settled checkout tiers. Basic source controls,
mute/Stop All, diagnostics, privacy/export/delete controls and emergency recovery
must remain available independently of premium status. Basic useful streaming
must not require buying Card Studio.

Personalized **Viewer Cards** are community profiles, not scanned collectible
cards; they may be presented as Viewer Profiles in general-streaming navigation.
Basic versus advanced community features needs a separate packaging decision.

## Migration order

### First implementation slice shipped — 2026-08-31

- The production console is now **Studio**, first in navigation and the default
  start page. Card Studio remains reachable by its own navigation item, a Studio
  shortcut, `?workspace=cards` / the legacy `?workspace=live`, or the saved
  start-page preference. No card data, settings or access is removed.
- The shared header outside Card Studio uses Sounds and Output Setup instead of
  card Scan/Capture actions. Card Studio retains its recognition-mode selector
  and scanning controls. Session labels now support ordinary shows, channels
  and clients.
- Show Preflight explicitly selects General streaming or Card streaming. General
  streaming does not read or require the recognition engine, including operator
  health; Card streaming retains recognition checks and validates Camera 1 before
  its existing Main Card recovery. General startup/end keeps the prepared Program
  rather than forcing Main Card. The explicit emergency recovery remains intact.
- Show-start requests are serialized and cannot restart an active show. UI
  readiness is invalidated while checking; stale responses from another workflow
  cannot authorize Start. A slow OBS probe no longer ages an earlier camera
  snapshot into a false stale-camera failure.
- OBS remains the external encoder. No native broadcasting or pricing/entitlement
  enforcement has been added. The chosen Program camera is still required; this
  slice does **not** implement camera-free screen/media scene production.
- This is a navigation and show-policy separation, **not** complete runtime
  modularization: OCR warmup, background card services, card analytics inside
  Insights/History and the shared application initializer still need extraction.

Validation for this slice: the release gate passed 2,448 Python tests and 196
JavaScript tests. After final header CSS/cache changes, 51 focused tests passed
again. Browser checks covered Studio/Card Studio navigation, header actions,
general/card preflight, dark/light themes and 1080p/4K/narrow layout bounds.
RareIQ was restarted and the live general preflight correctly reported a fresh
Program camera while skipping card recognition. OBS was offline, so actual
streaming/recording was not started or verified; the preflight correctly remained
blocked. No saved card access or billing restrictions were changed.

### Remaining architecture migration

1. **Define module boundaries and retain current-user compatibility.** Add explicit
   installed/enabled/entitled/available states. New general-streaming profiles default
   to Studio; migrate existing card setups without deleting data or removing access.
   Do not activate a billing restriction in this development build.
2. **Make the shell studio-first.** Home becomes Studio with Preview/Program,
   sources, scenes and audio. Group common navigation around Studio, Audience,
   Sounds, Media, Outputs and Add-ons. Card controls belong inside Card Studio;
   retain old deep links and the existing card workspace during migration.
3. **Separate runtime dependencies.** Card OCR/model warmup, visual indexes,
   catalogs, card routes/workers and card-only event subscriptions load only for an
   enabled Card Studio module. Shared camera ownership, scene models, media,
   events and audio live in the core; card recognition consumes those interfaces.
   A disabled/missing card engine must not block a general show or produce startup
   errors, repeated unavailable requests or background downloads.
4. **Complete the common production workflow.** Implement the paired canvas and
   source/audio model, and verify a useful non-card stream using existing OBS output.
   Preflight evaluates required sources in the selected Program scene, not a
   mandatory card camera or recognition status. Card events become one optional
   trigger type alongside manual and authorized audience events.
5. **Validate add-on lifecycle before payment integration.** Enable/disable off-air,
   preserve saved data and disabled source placeholders, version schemas, enforce
   capabilities on the server as well as the UI, and fail clearly when a project
   refers to an unavailable add-on. Never hot-disable active Program media because
   entitlement refresh failed; establish a documented live-session policy first.
6. **Then select and deliver advanced modules/native publishing.** Maintain a
   shipped/experimental/planned matrix. Finish and verify one capability before
   advertising it or promising broad platform coverage.

## Concrete coupling found during this review

- `rareiq/web/server.py` lifespan starts OCR warmup unconditionally.
- `production_preflight()` previously let card recognition fail general shows;
  it is now workflow-aware. Both workflows still use a camera-based Program.
- General show startup/end now preserves Program. Explicit emergency recovery,
  default scene presets and the standalone session tools still need broader
  source-model/module separation.
- `BroadcastDestinationService.snapshot()` reports `external_encoder` / `OBS`;
  `ObsService.command()` sends the actual OBS Start/Stop commands.

Changing navigation labels alone would leave these dependencies in place.

## Required regression scenarios

- Fresh Studio-only profile: launch without card catalog/models/workers, create a
  non-card scene, mix audio and export it to OBS without recognition prerequisites.
- Screen/window/media-only show: no physical/card camera required by preflight.
- Existing card profile: same assigned cameras, saved scans, collections, scenes,
  overlay URLs and sound routing after migration; no forced data conversion loss.
- Card module disabled: no card UI, OCR warmup, catalog downloads or polling;
  unrelated sources and community features continue to work.
- Missing add-on in a saved project: explicit placeholder/recovery, no crash,
  deletion or unintended change to the published Program.
- Landscape/portrait and 1080p/4K UI; complete-frame defaults; A/V sync; restart
  recovery; module toggles, access checks and no accidental live publishing.
- For native publishing only if approved: test actual destination receipt and
  disconnect/reconnect, not just a successful encoder process or socket connection.
