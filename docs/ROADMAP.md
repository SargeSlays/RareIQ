# RareIQ Roadmap

## Program output repair - September 8, 2026

Fix the full-screen logo regression, reuse the clean reconnecting camera view, and
verify normal/rapid camera switches before the next checkpoint. Full Program/audio
composition remains a separate functional stage; the camera-only output must stay
truthfully labeled. Owner authorized a total 50% ceiling; original usage baseline
0% and reset1789435596 remain unchanged (41% at resumption).

## Sarge UI checkpoint - September 8, 2026

The owner's next priority is a clearer Sarge experience. Elevate existing voice
controls, verify state feedback and responsive layouts, then checkpoint the tested
change. Keep private monitor feedback, real microphone/game-focus acceptance and
full Program/audio capture as the next functional work, within separately checked
remaining usage headroom.

## Local voice command checkpoint - September 8, 2026

Implemented the first local wake-command path with the existing input owner,
practice, strict camera/clip commands, stop/expiry guards and real synthetic
speech-to-clip evidence. Native hold-to-talk now gates whole utterances, with tested
registration/cleanup. Next: configured private monitor feedback, physical-key and
real microphone/background-game acceptance, then full Program/audio
capture. Chat and independent publishing remain separate unimplemented stages.
See [the checkpoint](VOICE_CONTROL_CHECKPOINT.md).

## Motion and functional production foundation - September 8, 2026

Continue the existing branding with the supplied operator-only motion layer.
Stage A starts with shared clip/camera dispatch and real manual clip export. Next
complete safe scene/sound/preset adapters and cancellation; host speech and full
Program/audio capture follow. Authorized chat connectors and two independent
nonpublic publishing outputs remain later acceptance stages. Full game-focus
acceptance is pending; see [the phase handoff](FUNCTIONAL_PRODUCTION_PHASE.md).

Scene camera guards, partial-result feedback and rundown cancellation are now in
the operator path. Next adapters must reuse these protections; already-dispatched
effects remain outside Stop cancellation.

## Audio docking checkpoint - September 8, 2026

Implemented portable Soundboard and Voice studio panels, saved-selection migration,
original-node restoration on navigation, scoped audio shortcuts and popout controls.
The remaining customizable-studio scope includes additional specialty workspace
adapters, full dock splitters, expanded/custom destination setup and per-tool
hardware/platform acceptance. Preserve original controllers in those adapters.

## Session tool selection and compact studio - September 8, 2026

Dock headers now contain only the title/drag handle and an options button. The
Session tools drawer owns placement, popout, visibility, layout reset and saved
tool sets. A compact Studio view selector replaces the horizontal seven-tab row;
the original navigation and production controls remain intact.

The picker includes 28 Broadcast docks and 10 separate workspace shortcuts, with
search, select all and clear all. Workspace selection adds launcher choices; it
does not start tools or change their availability. Separate workspaces remain
explicitly distinct from dockable panels. Named tool sets save locally in this
browser. Save as new preserves previous sets; Save changes updates the selected
set. Current unsaved selections survive reload separately from saved sets. No
production-session metadata or device settings are written by these controls.

On desktop, the frame uses actual available viewport height; a single side panel
fills its dock. The native drawer overlays the studio and traps keyboard focus.
Returning from a popout closes the drawer and restores tool focus. Opening another
workspace through the session launcher/drawer exits full screen before navigating.
Narrow screens retain vertical flow for readable controls.

Actual Edge checks cover bulk selection, search/empty state, two saved sets,
explicit update, reload, original nodes/unsaved fields, popout return, full screen,
blocked storage, and dark/light at 1920x1080, 3840x2088, 1366x768 and 720px. Desktop
frame bounds fit without outer vertical overflow or monitor/transition overlap.
Production writes are blocked in the repeatable browser QA script:
`tools/qa_studio_session_tools.cjs`. No broadcasting or recording was initiated.

Destination setup, separate audio docking and the broader per-tool acceptance
remain outstanding. This is the owner's requested layout/selection checkpoint.


## 3D identity and separate tool windows - September 8, 2026

The owner requested a more expressive parent logo. The main header now uses the
exact supplied approved 3D orange/lime lockup at 208x59px, with dark/light variants;
the existing micro mark still serves constrained spaces. No logo art was generated
or recolored, and RareIQ retains its own identity.

Broadcast tool headers now offer Pop out. Each separate browser window presents
the existing tool and forwards supported form/control interactions to its original
nodes. The main studio remains the controller. Protected fields, file inputs,
iframes, images, canvas and audio/video are replaced by main-studio guidance.
Global production keyboard shortcuts stay in the main window. Notifications point
back to the main studio for details/confirmation. Closing a tool window does not
stop a show; reloading/closing the parent disables the old window's controls.

Real Edge fixture regressions cover native validation/Enter, distinct select labels
and values, checkbox state, editing during background updates, dynamic and stale
controls, disabled guards, one activation, theme, window reuse/block/close, parent
reload and no copied credentials/media/API owner. Actual served Scenes and Show
Details windows plus unsaved text propagation were checked without saving or
starting any production action. Five header skins and narrow/1080p/4K bounds passed.

Still pending: docking the separate audio workspaces, complete splitters, custom
and expanded destination connection flows, full per-tool visual/interaction audit,
and actual hardware/platform acceptance. Popout support does not establish OBS
or destination delivery. Local evidence is under `.tmp/refinish/`; the repeatable
browser regression is `tools/qa_studio_tool_windows.cjs` (Playwright + installed Edge).


## Customizable studio checkpoint - September 8, 2026

The main Studio now centers the existing Preview/Program switcher, transitions
and source inputs. The existing Broadcast tools can be shown from Tools, placed
at any edge, hidden/restored, or floated inside the studio. Layout saves locally;
reset restores defaults. Side/floating panels have vertical resize handles.
Native full screen and the seven existing Broadcast views remain available.
Original controls and DOM nodes are retained; no second controller is started.

External browser-window tool popouts, audio-workspace docking, full dock-width/
height splitters, custom destinations and additional platform connection flows
are still pending. Floating panels are explicitly labeled as staying in Studio.
Existing platform evidence remains truthful; no live broadcast was initiated.

Actual served Edge checks passed: placement, float, hide/restore, reload, reset,
all seven views, native full screen, and original nodes/unsaved input continuity.
Ignite/Daylight at 1080p, 4K, 1366x768 and 720px have no page overflow or overlapping
monitor/transition regions. Camera imagery is masked in local QA captures. These
checks do not verify encoder/platform delivery or hardware continuity.


## Refinish in progress - September 7, 2026

Parent header/title/splash/web icons and five supplied operator skins are now
integrated, retaining RareIQ access and the one preference controller. Next within
this same phase: complete component/state audit, remaining parent copy, Sarge
visual integration, launcher assets and the handoff's full acceptance matrix.
The state-foundation note below describes the previous checkpoint.

Shared first-paint/runtime appearance state is implemented with versioned legacy
preference migration and blocked-storage handling. The current light/dark/system
controls remain. Next: supplied parent/RareIQ assets, five semantic skin palettes
and selector, workspace/Sarge styling, then full runtime acceptance. See
`branding-v2/REFINISH_PROGRESS.md`; the visual refinish is not yet complete.

## Brand package checkpoint - September 7, 2026

The v2 RareIQ/RareIQ OCR brand book and reusable asset library are delivered under
`output/branding/rareiq-v2/`. The owner-selected mascot represents the premium
recognition/intelligence product inside Producer, Please. Original artwork,
transparent production adaptations, vector companions and their distinctions are
documented. See `docs/branding-v2/WORK_PLAN.md` for scope and validation.

The next separate implementation phase is the Producer, Please customer-facing
rebrand of the existing application, retaining RareIQ recognition labels and all
compatibility-sensitive internals. This branding task did not perform that migration.
The historical Studio-first functional requirements below still apply.

## Streaming-first product direction — 2026-08-31

The owner's current direction supersedes the card-first ordering below: RareIQ
is a general streaming-production studio; Card Studio is an optional premium
add-on, with other advanced capabilities packaged separately. Core streaming
must not require card recognition, catalogs or a card-specific layout.

Next priority: define module boundaries, move to a studio-first shell, decouple
card startup/preflight dependencies, and complete the shared landscape/portrait
production workflow. Preserve all existing card data and working OBS outputs.
No prices, paywalls or automatic removal of existing access are approved here.

Current broadcasting still uses OBS as the external encoder. Standalone native
publishing is a separate proposed milestone, not an existing capability.

See [product boundaries, migration order and acceptance tests](PRODUCT_DIRECTION.md).
The following X-series items remain feature backlog, not the current release order.

## Active
- X.4 Fast Pipeline stabilization
- X.5 WAR BUILD Foundation

## Next
- X.5.1 Recognition Engine 2.0 integration
- X.5.2 Collection Intelligence
- X.5.3 Creator Studio
- X.5.4 Pack Battle Mode
- X.5.5 Marketplace Intelligence
- X.5.6 In-app Help Chat Agent and versioned operations manual

### X.5.3 Creator Studio Overlay Requirement

- Pack-reveal suspense overlay:
  - Track the presenter's card-by-card progression through a pack and build tension as the expected rare slot approaches.
  - Hold the payoff until the rare card is actually revealed and recognition confidence is stable.
  - Drive the reaction from a configurable hit tier rather than card rarity alone; market value, scarcity, chase status, and operator overrides may contribute.
  - Miss / low hit: brief deflation or "aww" reaction, then reset cleanly.
  - Medium hit: energetic "YES!" celebration.
  - Grail hit: maximum-event treatment with the requested "OH MY FUCKING GOD!! IT'S JOHN CENA"-style reveal and a "bop badada" wrestling-style sting.
  - Make reaction copy, audio, intensity, duration, and streamer-safe language configurable. Use licensed or user-supplied audio rather than bundling protected broadcast music.
  - Include cooldowns, spoiler prevention, false-positive cancellation, manual trigger/override, and an instant disable control for live production safety.

### X.5.3 Unified Scene Builder — Landscape and Portrait

User requirement confirmed 2026-08-30: build the complete show in RareIQ and send
finished output to OBS and TikTok LIVE Studio, without rebuilding each scene there.
This is planned work, not a claim that the visual editor or TikTok output exists.

- Maintain two first-class canvases: landscape 16:9 (1920×1080, optional 3840×2160)
  and portrait 9:16 (1080×1920). Support concurrent landscape and portrait outputs.
- Share source identities, camera capture owners, current-card data, recognition
  events and soundboard state. Store position, size, crop, layer order and visibility
  independently for each orientation. Do not create duplicate camera captures.
- Offer Landscape, Portrait and Both editor previews, with linked scene selection,
  independent layout edits, snapping, alignment and adjustable platform-safe guides.
  Keep complete card artwork visible by default; never turn a landscape crop into
  the portrait layout automatically without operator review.
- Build on the existing Production workspace. Keep draft changes separate from
  published Program state; Take Live publishes the paired scene deliberately.
- Render both formats from the same saved scene model used by the editor. Preserve
  the existing independent camera/overlay outputs as optional advanced sources.
- OBS receives the composed Program browser source. Validate TikTok LIVE Studio's
  actual supported ingest in the installed version; use a tested browser/capture or
  virtual-camera bridge as appropriate. Existing OBS Browser Sources do not imply
  that a Windows virtual-camera device or TikTok-compatible output is installed.
- Treat TikTok audio as a separate required route when using a video-only bridge.
  Provide explicit output/mute/monitor controls and prevent doubled sound. Do not
  declare TikTok ready until both picture and sound pass an off-air application test.
- Acceptance tests: simultaneous OBS landscape and LIVE Studio portrait; all four
  camera feeds with single capture ownership; full-card visibility; shared identity
  updates; safe draft/publish; saved-layout restoration; disconnect/reconnect; audio
  start/stop and sync; 1080p/4K operator UI; sustained dual-output performance.

Compatibility references (reviewed 2026-08-30):
[TikTok scene layouts](https://www.tiktok.com/live/studio/help/article/Get-started-with-your-first-LIVE/Whats-a-scene?lang=en),
[TikTok virtual-camera guidance](https://www.tiktok.com/live/studio/help/article/Gaming-Co-host/Gaming-Co-host),
[OBS virtual-camera output selection](https://obsproject.com/kb/virtual-camera-guide).

### X.5.3 LIVE Events and RareIQ TTS

User requirement confirmed 2026-08-30: TikTok LIVE chat, named-viewer arrival and
gift events should trigger custom overlays, sounds and spoken chat inside RareIQ.
Integrate these with both Scene Builder orientations and the shared audio output.
Status: researched and specified; the connector and TTS product are not implemented.

- Add configurable event-to-action rules: a selected viewer joins, a particular gift
  arrives, a gift streak completes, or an eligible chat message is received.
- Use one normalized event service and bounded queues, with cooldowns, deduplication,
  reconnect handling and a test-event simulator. Never let connector failures block
  recognition or camera capture. Join alerts are best effort, not a complete viewer list.
- Build RareIQ's own TTS controls, moderation and routing over a replaceable speech
  engine. Start with the installed David, Mark and Zira Windows voices; all three
  generated in-memory WAV test audio on this PC on 2026-08-30. This verifies synthesis,
  not chat integration or OBS/TikTok playback. Evaluate higher-quality licensed local
  voice packs later without requiring a cloud subscription for the initial version.
- Include voice previews, rate/volume, optional username reading, per-viewer voice
  assignments, filtered automatic chat reading, queue limits, skip, pause and Stop All.
  Keep chat-controlled actions restricted to operator-configured templates.
- Produce speech once and route it to the shared broadcast audio path; do not run a
  speech engine independently in every overlay or duplicate audio in OBS scenes.
- Treat TikTok events as a separate capability from TikTok publishing. The reviewed
  unofficial clients use Webcast events and third-party signing, not TikTok source code.
  Verify current connector licensing, provider requirements and platform terms before
  adoption; do not advertise permanent API-free or guaranteed event access.
- The user prefers a page-label/DOM collector. Prototype and validate the actual
  labels and event fields before selecting a transport. This route is not yet verified
  on the user's LIVE; incomplete labels must not become invented IDs or gift totals.
- Ship in this order: viewer identity/event-history foundation; local TTS controls and
  simulated personalized rules; opt-in LIVE collection; paired landscape/portrait
  cards, alerts and leaderboards; real application and recovery tests.

See [LIVE events and TTS delivery plan](CREATOR_LIVE_EVENTS_TTS.md) for compatibility
findings, implementation boundaries and the ordered acceptance checklist.

### X.5.3 Cross-platform Events and Actions

Scope expanded 2026-08-30: sound alerts and personalized actions must cover all
available interaction types on TikTok, Twitch and other connected platforms, not
just a fixed gift list. Status: specified/researched; event adapters are not built.

- One rule builder: platform/account, event, optional viewer/gift/emote/threshold
  conditions, then one or more sounds, animations, Viewer Cards or TTS actions.
- TikTok targets: any/specific gifts and streaks, follows, room joins, new Super Fans,
  existing Super Fan arrivals, shares, likes, chat, emoji/custom emotes, subscriptions
  and additional provider-exposed interaction types. Verify page-label coverage;
  the unofficial event library's catalog does not prove DOM support for every event.
- Twitch targets: follows, subscriptions, resub messages, gifted subs, Bits/Cheers,
  raids, channel-point redemptions, chat/emotes and additional authorized EventSub
  interactions. Use official event access where supported, with explicit authorization.
- Extend the same system to YouTube and Kick using their documented events. Keep
  Rumble, Facebook, Instagram and X in a capability-review queue; existing broadcast
  route/status connectors are not proof of chat, gifts or alert-event support.
- New fan/subscriber status and an existing fan/subscriber arriving are different
  triggers. First observed chat can be its own trigger; never call it a guaranteed join.
- Every rule gets a preview/test, cooldown, rate limit, queue/priority policy, output
  selection and master-disable support. Deduplicate related provider notifications.
- Fetch supported gift/emote catalogs, retain platform IDs and expose unknown values
  honestly. Register new event schemas without redesigning the whole rule editor.
- Keep the shared viewer ledger accurate independently of whether an alert is muted
  or rate-limited. Do not combine coins, Bits, Jewels and currencies as raw money.
- Explicitly label adapter/event states: documented, implemented, authorized, verified,
  degraded or unsupported. Do not enable a trigger solely because it appears in docs.

See [event coverage, rule behavior and adapter tests](CREATOR_EVENT_ACTIONS.md).

### X.5.3 Viewer Cards and Community Leaderboards

User requirement confirmed 2026-08-30: optionally create a personal baseball/trading
card for a viewer, with a portrait/avatar, favorites, assigned TTS voice, private
streamer notes, custom entrance sound/animation and contribution history.
Status: specified, not implemented; no real viewer profile has been created.

- One viewer profile drives personal rewards, entrances, speech preferences and
  leaderboard presentation. Keep personalization optional; not every viewer needs
  a custom card. Use platform identity when available, not a changeable display name.
- Track received gift quantities and reported coin units, chat activity and observed
  stream attendance separately. Support current stream, calendar day/week/month/year
  and all time in the streamer's configured timezone, with clear coverage dates.
  All time means since collection began, not an assumed backfill of TikTok history.
- Keep an auditable event history so retries, gift streak updates, reconnects and
  corrected identities cannot silently inflate totals. Never infer cash earnings or
  continuous watch time from page labels, gift counts or join notifications.
- Make branded leaderboard overlays for both orientations: selectable metric/period,
  top-N, rank, avatar/card treatment, ties and optional personal milestone highlights.
  Keep support and community activity separate instead of inventing a monetary score.
- Offer an operator-approved generated character/avatar or viewer-supplied portrait
  for each personal card. Likeness generation is opt-in; preview before publishing.
  Preserve the chosen art rather than regenerating it on every join.
- Private notes and hidden preferences never enter overlay payloads, TTS templates,
  public exports or image-generation prompts. Include hide, export and delete controls.
- Validate through simulated events first, including time boundaries, aliases,
  duplicate arrivals, gift streaks, disconnect gaps, privacy and dual-output audio.

See [viewer-card product and testing specification](CREATOR_VIEWER_CARDS.md).

### X.5.3 Viewer Rewards and Recognition

User requirement added 2026-08-30: recognize viewers and reward community
participation through their existing Viewer Cards. Status: planned, not implemented.

- Start with manually awarded badges, community spotlights and approved card/entrance
  personalization. Add non-spendable XP, configurable ranks and milestone unlocks once
  identity/event quality is verified. Spending is not required to earn recognition.
- Reuse the shared viewer ledger, rules and both overlay orientations. Award once per
  qualifying event/milestone; add caps, corrections, privacy controls and off-air tests.
  Do not turn repeated chat, reconnects or unverified gift counters into points.
- The current experimental label probe cannot automatically earn rewards. Unsupported
  watch-time/identity measurements remain unavailable rather than guessed.
- Keep equal-odds giveaways independent: rewards, ranks and support cannot change
  entries or winning chances. A future optional points shop is a separate phase, with
  transactional redemptions, operator approval, refunds and no loss of lifetime rank.

See [rewards design and acceptance order](CREATOR_VIEWER_CARDS.md#rareiq-rewards-and-recognition).

### X.5.3 Giveaways and Winner Reveals

User requirement confirmed 2026-08-30: fun wheel or random-name-picker overlays,
unbiased random selection, a persistent unique ID for every giveaway, and searchable
history with operator notes. Status: specified, not implemented; no draw was run.

- Offer a branded spinning wheel and name-shuffle reveal, countdown, sound and winner
  celebration using the winner's optional Viewer Card. Support landscape and portrait.
- Default to free entry, one entry per eligible viewer account and equal odds. Gifts,
  supporter rank, custom avatars and favorites must not influence selection.
- Freeze and record the eligible entry list and rules before drawing. Select on the
  server with the operating system's cryptographic randomness using an unbiased
  bounded draw. The visual animation reveals the saved result; it never chooses it.
- Generate a collision-checked canonical giveaway ID plus a short display code.
  Preserve it across restarts; assign separate IDs to draw rounds and prizes.
- Record title, prize, stream, rules, entry window, participant snapshot, winner(s),
  timestamps, notes and claim/fulfillment status. Search/export by ID, date or winner.
- Make draws atomic and idempotent. Repeated clicks, another overlay or a reconnect
  must return the same saved result. Record rerolls as additional draws with a reason;
  do not erase the original winner or silently edit a completed entrant snapshot.
- Keep private notes and fulfillment information out of public overlay payloads.
  IDs identify records; they are not authorization tokens.
- Test duplicate entries, zero/one/many entrants, multiple winners without replacement,
  RNG failure, click races, restart recovery, reroll history, privacy and both outputs.

See [giveaway specification and acceptance checklist](CREATOR_GIVEAWAYS.md).

## Parked
- Hybrid card-library storage and retrieval
  - Never require the complete global image library to remain on the user's machine.
  - Let users download selected games, languages, sets, or an offline event pack.
  - Retrieve missing reference images and metadata from the configured catalog/database on demand.
  - Cache fetched assets locally with a configurable storage budget, visible usage, expiry policy, pin/offline controls, and safe least-recently-used eviction.
  - Keep compact identity and visual-search indexes locally where practical so recognition can locate a candidate before downloading its full-resolution reference image.
  - Provide explicit offline, metered-network, image-quality, and "download while idle" preferences.
  - Verify checksums and catalog versions; never silently replace user-corrected identities or locally pinned assets.
- Cloud sync
- Tournament brackets
- Enterprise dealer workflows
- Universal collectibles beyond cards
