# RareIQ: streaming-first product direction

## November 15, 2026 - Simple presets with Advanced controls

The room now offers explicit Smart suggestions, Equal grid, Focus/Presentation and
Picture-in-picture. Smart recommends Solo, Interview, Panel or Presentation using
only the selected visual sources. Recommendations update as selections change;
applying one is a deliberate Preview-only click, never an automatic Program change.
Text and mic-only sources remain selected without consuming picture slots when
pictures are present. PiP's shortcut requires exactly two pictures; the renderer
also keeps all stored multi-picture sources visible. Saved scenes support PiP.

Manual layout, lead picture, transition and duration controls are grouped in a
collapsed Advanced section. Clear Preview and Take stay visible. This establishes
the simple/default and advanced split; a free-position layer editor, cropping,
per-source transforms and broader reusable scene templates remain planned.

## November 15, 2026 - Browser picker and guarded Take

Browser sources are now immutable saved definitions with a public-looking HTTPS
address, source name, request receipt and operator kind. The picker selects them
for Preview without changing Program. Each connected Studio Output must review its
own loaded page before Take; frame load alone never grants readiness. Review is a
pre-show preparation view that temporarily changes that output's layout, then
returns to clean output, clearing the preparation flag. Ordinary output never
automatically displays review controls. Opening review fails closed unless show/stream/recording are
explicitly idle. A reviewed browser document is preserved through Take using
state-preserving DOM moves; unsupported browsers keep the source unavailable.

Pages run with restricted sandbox/permissions, without interaction or browser audio.
Some sites refuse embedding or need unsupported cookies/permissions; replace blank
or blocked pages rather than approving them. Review records the operator's past
visual check, not continuing content assurance or DNS/redirect network isolation.
Reload/new output requires its own review. Local Edge fixture testing is complete;
external widget compatibility and OBS interaction/receipt are not yet verified.

## November 15, 2026 - Browser source experiment (not enabled)

An isolated browser-source adapter under tools/experiments now validates initial HTTPS addresses, restricts
iframe capabilities and interaction, and keeps frame load separate from visual
review. It is not included by product pages, persisted in the source catalog or
accepted by Preview/Program. End-user browser sources remain planned.

The policy checks the initial URL only: it does not provide DNS/redirect network
isolation or credential-free loading. Review records a past appearance, not a
continuing content guarantee. The complete producer/output review workflow and
its connection to guarded Take must be designed and tested before activation.

## November 15, 2026 - Video files and text sources

The production room now imports local MP4/WebM video files up to 64 MiB and saves
immutable text sources (1,000 characters, eight lines; lower third, center or top).
Both use the existing Preview selection, same-output readiness and guarded Take.
Text overlays the selected pictures without consuming a picture grid cell. Video
Preview stays paused and silent; Take starts playback from the beginning, holds
the final frame, and owns audio only in Studio Output. Removal stops playback.
Autoplay restrictions retain the existing Enable output sound recovery control.
Saving a source never changes Program. Browser codec support is still required.

This is locally browser-tested with generated WebM video/audio; no physical guest
listening or external encoder/platform receipt is claimed. Browser URL sources,
producer screen/window capture and free-position layer editing remain planned.
Remote producer login remains disabled pending the StackThis identity registration
and callback agreement; this checkpoint makes no account or networking change.

## November 15, 2026 - Visible guest room and production images

Admitted guests now see one another's camera pictures in a responsive room gallery,
with their own local preview, names, microphone/screen status and a separate waiting
roster. Invitation-authenticated camera-only viewing is independent of the guest's
publisher connection. Gallery video is muted; existing producer conversation audio
remains the sole return path. Waiting guests can chat, but receive no admitted-room
pictures or conversation audio. A picture retry does not restart local capture.

The producer can Return to waiting room and admit the same session again. Waiting
removes that guest's sources from Preview and Program; readmission never takes them
back on air automatically. Remove & end access requires confirmation, revokes the
session and stops capture. Invite again creates a fresh invitation; it does not
restore the ended session. Terminal cleanup also rejects late permission results.

Image sources reuse the local asset library (configured F:/RareIQ/creator_assets).
PNG/JPEG/WebP/GIF imports up to 8 MB can be selected in Build Preview alongside
cameras and guest sources. Imports and Preview do not change Program. Take requires
a current decoded-image receipt from the same Studio Output receiving the entire
composition; cut/fade/slide/zoom, image-only shots and saved scene source IDs use
the existing composition path. These are image tiles, not a full movable overlay
layer editor. Local video files, arbitrary browser URLs, text layers and dedicated
producer screen/window capture remain follow-up source types. Guests currently
publish camera/microphone/screen, not image uploads.

Real local browser connections used generated cameras/audio; no new physical,
internet, OBS or platform acceptance is claimed. Named remote producer sign-in is
still disabled pending StackThis identity-only registration, approved callbacks and
production membership/control integration. A guest invitation is not producer login.

## November 15, 2026 - Shared and private backstage chat

Waiting and admitted guests can chat with everyone in the room or privately with
the production team. Private means that guest plus all authorized producers, not
a guest-to-guest direct message. The producer selects the guest conversation.
Messages show sender labels and local timestamps, remain off Program, and do not
change production state. Guest display names are not verified identities; producer
messages use the Production team label and only show verified identity when a
trusted account principal is present.

The local database retains append-only history and sender keys. The UI reads the
latest 100 messages in the current conversation; a new room starts empty. Removal,
revocation, expiry and closing the room end guest access. Old records are retained,
not silently deleted. Retention/export policy and named producer profiles remain
separate follow-up work. Local browser and access-boundary checks do not establish
public hosting, internet connectivity or physical second-PC audio acceptance.

## November 15, 2026 - Guest flow and recovery polish

Guest preview and joining now share a compact first row, with a full-width voice
and soundboard area that stacks on phones. Expanded content uses page scrolling.
Device/connection/file feedback has independent ownership so room updates cannot
hide actionable errors. Keyboard focus survives pad/clip playback. Recoverable
terminal connection failures offer an explicit authenticated retry; revoked access
still requires a new invitation. Media-off and Leave remain available during
connection setup. These are local browser improvements; physical speech/echo,
mobile hardware and internet acceptance remain deferred.

Active capture can be stopped while another device permission is pending. Stopping
a source cancels its pending replacement; late permission results cannot reopen it.
Private-preview, paused-delivery and unexpected capture endings have distinct
feedback. These guards are tested with generated tracks, not physical devices.
Pending device requests, joining and reconnecting now have explicit progress
feedback, without disabling active capture-off controls.

## November 15, 2026 - Guest voice, soundboard and noise gate

Guests have Natural, Warm & deep, Radio, Robot and Megaphone voice styles, four
original synthesized sound pads, and up to six local audio clips. Shared native
Web Audio processing serves both producer Voice Mod and guests; these are tone
effects, not pitch shifting or voice cloning. Clips decode on the guest device,
are not uploaded or saved, and clear with microphone-off or Leave. Voice and
sounds share the outgoing microphone and its producer Program mute. Screen audio
and conversation returns are not fed through this processing.

The optional microphone gate defaults off at -45 dB, adjusts from -70 to -10 dB,
and stores its preference in that browser. It filters the mic before voice effects;
sound pads mix after the gate. Gate status distinguishes passing, closed and
unavailable/unfiltered. Echo cancellation/noise suppression remain requested.
Generated-media browser checks establish routing, cleanup and responsive controls;
physical speech, acoustic echo and perceived effect quality are deferred by owner.

## November 15, 2026 - Two-PC guest rehearsal and output sound recovery

An individually invited guest on a second Windows PC reached the private guest
studio and supplied camera video, microphone and tab-sharing tracks. An MX Brio
physical camera was subsequently selected and its picture reached local Program.
Camera, screen and combined compositions reached the production PC's local
Program output. This is private two-device transport acceptance, not public
hosting, sustained camera/voice quality, OBS encoding or platform delivery.

When a browser blocks Program sound, Studio Output now offers an explicit Enable
output sound action and the producer sees the reason. A historical picture receipt
alone cannot establish current audio playback readiness. Confirmation requires
fresh playback state and a matching receipt from the same output and generation.

## November 15, 2026 — Local guest audio polish

Producer, Please now has separate producer-owned microphone and screen-audio
mute settings for each guest's Program output. They can be prepared while a guest
waits or changed mid-shot, without changing guest capture, video or backstage
conversation. Guests see the policy and settings changes enter activity history;
these are recorded settings, not separate renderer-confirmed mute receipts.

Each guest still needs an individual invitation. The owner chose localhost for
now: the new Open guest tab action supports testing on the production PC. Public
hosting/domain work remains deferred; other devices cannot use a localhost link.
Real generated-media browser tests pass; physical devices, OBS receipt and internet
participation remain separate acceptance steps.

## November 15, 2026 — Audience connection follow-up

Twitch and YouTube chat observers now have explicit host-only Connect/Disconnect
controls. YouTube reuses existing host authorization, verifies channel ownership,
requires one active chat and discards initial/recovery history. Both support only
first-chat and featured-participant chat observations, with no silent-viewer joins.
Kick has a signed-event adapter and local status, but no mounted public receiver,
approved callback registration or credential-owner integration. Its setup control
remains disabled. All provider acceptance is simulated; none was activated.
Follow/subscription adapters remain pending. The guest/voice/vision checkpoint
below and its hardware, hosting and verified-account limitations still apply.

## November 15, 2026 — Guest productions and hands-free studio checkpoint

Owner direction: Producer, Please is a general live-production studio for PCs and
mobile browsers. Invite guests backstage, choose their camera/mic/screen/game
sources, compose them with local cameras, and take Preview to Program with a
transition. RareIQ remains a separate premium card add-on. Guest participation,
producer account access and paid entitlement are distinct boundaries.

Implemented and exercised locally: six-slot invitation room, producer admission,
six-source compositions, explicit host microphone, conversation mix-minus,
separate clean output, activity history, custom voice phrases, opt-in local
gesture/head-direction practice and audience animation rules. Actual Chromium
WebRTC tests use generated media; responsive checks cover 390/960/1920/3840 widths
in dark/light. OBS remains the external encoder; no real broadcast was started.

The optional Twitch first-chat/featured-chat observer is wired behind explicit
local Connect and tested with simulated provider traffic. YouTube/Kick and
follow/subscription adapters are still pending. A silent viewer arrival is not
an observable welcome event. The prepared guest-only HTTPS ingress and short-lived
TURN configuration are inactive. Public hosting, relay and real two-network/device
acceptance remain required. Head direction is experimental, not eye tracking.

Invitations identify guest sessions, not verified people. Program history labels
operator/device/voice/gesture/renderer origins honestly; multi-producer personal
login still requires the StackThis registration described below. No billing or
premium enforcement was activated. See [Guest production guide](GUEST_PRODUCTION.md).

## November 15, 2026 - Account permission foundation (disabled)

The scene service now supports server-verified subjects with owner/editor/viewer
membership for this one production instance. Owner-only membership changes, scene
edits and their attributed history are transactional. Revocation/downgrade is checked
before returning a previous edit receipt. Host bootstrap is explicit and never grants
ownership to a first visitor or localhost request. Historical device events remain
unverified; host bootstrap is labeled separately from authenticated account actions.

An API-only account boundary defaults off and has no deployment/environment switch.
A StackThis verification adapter is tested with simulated responses and remains unused.
When the boundary is enabled in isolated tests it allows only
scene read/save/delete/history routes, requires a server-verified bearer session,
checks current membership and rejects every legacy control route and WebSocket.
The regular studio remains in its existing local/LAN mode. There is no account login,
member-management UI, internet transport or verified multi-person live production yet.

With the owner's approved temporary repository access, the exact deployed StackThis
version 249 source was retrieved read-only: commit
`7de1788d08547876e7717d320df30d743b05abbb`. Its server-only session-check contract is
verified in source, including active Clerk/account checks. Producer, Please has a
development catalog listing but no login registration in the free-tool, membership
or paid-app policies. Registration, callback and access-policy approval remain required;
a listing does not authorize login and does not decide base-studio pricing. No StackThis
settings, deployments, billing or public access changed. No real user session was tested.

Stackthis Dev recommends a dedicated identity-only registration because its current
app-session endpoint couples identity to product access policy. Do not add Producer to
the free-tools or subscription policies merely to pass those checks. Exact permitted
origins/callbacks and the identity-only contract/registration/deployment need approval
before real login. Studio membership and RareIQ entitlement remain separate decisions.

## November 15, 2026 - Scene collaboration foundation

Scene saves and deletions now use durable SQLite transactions containing the scene
collection, its revision, a minimal retry receipt and a server-recorded activity event.
The existing JSON scene file is imported once and preserved. Conflicting edits return
409; the browser preserves the draft and asks the operator to review the latest scene.
Visible Studio clients refresh scene snapshots every five seconds without rebasing an
open draft. The Scene activity disclosure shows paginated changes and rejected conflicts.
It covers saves/deletes only, not scene takes, live output, audio or all other controls.

Current attribution is explicitly unverified: local operator or paired LAN operator.
The browser cannot submit an actor name. Named-user login, production membership,
roles, remote internet transport and critical live-action ownership remain unimplemented.
Append-only database triggers prevent ordinary history edits; this is not proof against
an administrator replacing the database. Retention/export policy is still pending.

Coordination with the owner's Stackthis Dev chat found Clerk-backed identity and
app-session verification in its October 23 security-candidate checkout. The inspected
`lib/clerk-auth.ts`, `lib/app-sessions.ts`, `app/api/licenses/check/route.ts` and
`app/api/apps/session/check/route.ts` provide candidate integration contracts. They do
not supply production membership/roles. Producer, Please was absent from that checkout's
app registries; current deployed registration and the latest canonical source still
need verification. No StackThis deployment, credentials, billing or access rules changed.

## November 15, 2026 - Studio presentation and shared production

The owner requests content-sized production tools: docked panels grow downward and
use the workspace scroll surface, including panels with previously saved heights.
Floating windows retain independent sizing. The production console now uses more
consistent spacing, compact headings and controls, and grouped health cards in the
existing semantic themes. This is a presentation change, not a broadcasting upgrade.

The owner also requests several people collaborating on one live production, with
both local and remote internet access explicitly confirmed on November 15, 2026.
Plan browser clients joining an authenticated shared production workspace, with
one authoritative host for production state and device/output ownership. Define
member permissions, presence, reconnect recovery, revision/conflict handling and
exclusive ownership of critical live actions before enabling shared control.
An installed companion is optional for device capabilities requiring native access;
it is not a prerequisite for the shared control interface. Existing local/LAN
pairing and WebSocket updates do not establish individual customer accounts or
safe concurrent editing. Shared login/collaboration is not implemented by this pass.
Use the existing identity integration direction once its actual contract is available.
Local and remote members must use the same authenticated membership and permission
model. Remote access must use an authenticated encrypted connection, not public
exposure of the current local control, camera or OBS endpoints. Keep one production
host responsible for physical devices and output; an operator disconnect must not
stop the production. Remote camera contribution is a separate media capability
from collaborative control and must be designed and verified separately.

Accountability is an explicit owner requirement for shared productions. Keep a
server-recorded activity history for each production: authenticated actor identity,
server timestamp, action and target, safe before/after details, and success/failure
outcome. Cover scene/source edits, transitions, audio adjustments, session/show
controls, membership and permission changes. Attribute automatic actions to the
service, retaining the initiating member when applicable. Derive actor identity
from the authenticated session, never a client-supplied name. Correlate requests
and outcomes so retries do not create duplicate successful actions or hide failures.
For live output commands, distinguish a request from a confirmed external result.
Restrict history access to authorized members; ordinary users cannot edit or delete
events. Exclude credentials, tokens and unnecessary private content. Define retention,
export permissions and tamper protection before calling this a complete audit trail.
This activity history is a planned requirement, not an implemented capability.

For this requested studio direction, Producer, Please is the separate production
brand and RareIQ is an optional paid card add-on. This does not invent prices,
activate billing, or retire existing standalone card workflows.

## Single-source OBS handoff - September 8, 2026

New OBS setups use `/output/studio` as the primary 1920x1080 Browser Source. It
composes the switched Program camera, graphics overlay and routed Soundboard audio;
OBS performs final microphone capture, monitoring, encoding, recording and delivery.
Individual camera, overlay and audio sources remain available for advanced layouts.
This foundation is locally tested but has not been played in OBS or sent to a platform.

## Studio console polish - September 8, 2026

Production uses narrower side docks, a compact readiness checklist and a readable
session console. Add a tool opens the existing session tool chooser from beneath
Scenes. Saved positions, custom sizes and pop-out ownership stay unchanged. Every
readiness detail, recovery instruction and guarded start action remains available.

## Production studio visual refinish - September 8, 2026

The main production page now gives Preview/Program, source selection and Cut/Auto
clear visual priority. Nested docks use Producer, Please semantic surfaces and
readable text instead of legacy panel styling. Empty scene docks fit their content;
custom heights, docking, pop-outs and tool sets remain user-controlled. Camera
thumbnails distinguish unavailable, unassigned and loading states without broken
browser images. This phase changes presentation, not broadcasting capability.


## Sarge wake phrases and camera aliases - September 8, 2026

The owner reports both automatic and hotkey voice commands succeeded in the
fullscreen PUBG test. The next correction accepts “cam” and “camera” interchangeably
for slots one through four. Every command starts with “Sarge” or “Hey Sarge” in
both listening modes. Legacy “Producer please” commands require Open flow.
Explicit Open flow removes that prefix requirement for one listening session,
resets on Stop, and never bypasses PTT timing or Practice/action authorization.
This is one complete spoken phrase per command, not a conversational wake session.


## Optional microphone noise gate - September 8, 2026

Voice Mod has an off-by-default noise gate, adjustable from -70 to -10 dB with
a -45 dB starting threshold. Its switch and threshold persist in local microphone
preferences. The gate filters the processed voice and monitor branches before
effects; Sarge retains its existing raw microphone input. This mutes quiet passages,
not background noise while speaking, and does not replace Windows microphone routing.


## Microphone toggle and voice test feedback - September 8, 2026

One microphone button changes between Start, Cancel and Stop using the existing
input owner. Voice-command readiness now includes observed shortcut presses, audio
received and the latest result time. This supports the owner's fullscreen PUBG
acceptance test; the reported background failure remains open until a real retest.
Fixed-chord fallback preserves registration and complete-utterance authorization.

## Program camera output correction - September 8, 2026

Open Program Output follows the selected Program camera through the existing clean
camera output. Detection annotations stay in operator previews. A small corner
mark remains separate from camera sizing and transitions; the page title/favicon
identify Producer, Please. Program is still a camera-only browser source, without
a mixed-audio track or complete studio composition. This correction does not add
broadcasting or change OBS state.

## Sarge console presentation - September 8, 2026

Voice studio places the existing Sarge controls in a full-width console above the
audio tools. Microphone readiness, Practice/action mode, command mode and the latest
outcome stay visible together; examples are passive guidance. Detailed instructions
collapse while the Program-routing caution remains visible. Docking retains the
same controls and microphone owner. This presentation change adds no new commands,
private audio, chat connection or publishing capability.

## Local voice command checkpoint - September 8, 2026

Explicit local wake-command control now borrows the existing Voice Mod input for
Windows speech recognition. Practice defaults on; only camera selection and
silent camera-buffer clip saving can execute through the shared action registry.
Native Hold Ctrl+Alt+V is an alternative with whole-utterance gating and explicit
shortcut conflicts. Synthetic worklet/recognizer/HTTP/MP4 checks pass. Real microphone/game-focus
and physical-key acceptance, private spoken feedback, multichat and multistream remain
pending. See [voice control boundaries and operation](VOICE_CONTROL_CHECKPOINT.md).

## Motion and functional production foundation - September 8, 2026

Voice-controlled production, playable local clips, routed effects/private confirmations,
unified multichat and independent multistream delivery are now core requirements.
The current checkpoint supplies a narrow action foundation and manual silent
Program-camera clip export; background voice/chat/multistream remain unimplemented.
See [the capability matrix](FUNCTIONAL_PRODUCTION_PHASE.md) for verified layers.

## Audio tools in the production studio - September 8, 2026

Soundboard and Voice studio now use the same original controls in either a
production dock or their standalone workspace. Both support the existing popout
window. Session tools contains 30 docks and eight workspace shortcuts; existing
saved audio selections migrate without changing explicit dock choices.

Layout selection does not start playback, microphones or broadcasting. Voice
processing and digital output retain their existing availability and limitations.
Camera effects, Spotify and Creator still use separate workspaces.

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


## Parent application refinish in progress - September 7, 2026

The actual operator header, title, splash and web manifest now display Producer,
Please using the supplied v2 package. RareIQ retains its independent original
character and existing Card Studio access. Five operator skins are selectable
through the existing preference controller. Full workspace/Sarge/Windows branding
and hardware acceptance remain in progress; see `branding-v2/REFINISH_PROGRESS.md`.

## Brand architecture correction - September 7, 2026

The owner's branding request and recovered approved handoff establish **Producer,
Please** (including the comma) as the parent live-production environment. **RareIQ**
and **RareIQ OCR** identify its premium collectible/card recognition and intelligence
product, using the selected colorful mascot. The v2 brand book and asset library are
under `output/branding/rareiq-v2/`; see `docs/branding-v2/WORK_PLAN.md` for evidence.

This supersedes the older customer-facing master-brand assumption in the title and
historical sections below. It does not rename the Python package, repository, routes,
stored data or the currently running application. The existing Studio-first workflow
and separation of general production from card recognition remain engineering
requirements. Product integration of the parent identity is a separate phase; the
brand package activates no prices, billing restrictions or new OCR capabilities.

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

## Local OBS Studio handoff acceptance - September 17, 2026

The existing OBS Program scene now uses the combined /output/studio source with
OBS audio routing and without a second active Soundboard scene layer. Physical
Insta360 Program video, temporary graphics/expiry, and Soundboard meter receipt were
checked in actual OBS with streaming and recording off. Camera output and audio receipt
survived source refresh. This is local OBS acceptance, not platform delivery,
listener-quality validation, microphone-mix acceptance or standalone broadcasting.

## 2026-09-19 production-readiness evidence

Implemented and locally tested: shared fresh-frame guards across production camera
actions, per-slot readiness explanations and truthful browser-output preflight.
A connected device or registered output route is not proof of fresh video, a usable
OBS source, audible audio or successful broadcasting. Hardware and platform launch
acceptance remain explicitly separate from the passing local release gate.
## 2026-10-01 owner direction: Studio launch, accounts and monthly subscriptions

The owner requests an end-of-week product target: sharpen Studio, prepare for real
streaming/testing, and add customer login plus a monthly platform subscription tied
to the owner's StackThis.AI platform. This is a new product requirement, not a claim
that authentication, checkout or the integration is implemented or launch-ready.

- Studio remains the primary product; Card Studio stays optional. Protect the
  setup -> Preview -> Program -> OBS workflow before adding adjacent features.
- Customer identity must be separate from local/LAN device pairing. Confirm whether
  StackThis.AI owns accounts, billing or both, and its supported integration contract,
  before choosing an identity provider or implementing provider-specific endpoints.
- Monthly pricing, currency, trials and access rules are not yet approved. Do not
  invent amounts, activate live billing, create duplicate billing identities or
  impose a new restriction on the development installation.
- Subscription changes require authenticated server-side evidence. Test duplicate,
  delayed and out-of-order events and reconcile missed events; a checkout redirect
  or a browser-supplied paid flag must not grant access by itself.
- Keep local OBS outputs separate from interactive account login. Define and approve
  offline/grace behavior; a routine login or billing refresh failure must not
  unexpectedly interrupt an active show.
- Streaming-ready and commercially ready need separate acceptance evidence. Existing
  local checks do not replace OBS/audio, encoded-output or destination verification.
- Exact StackThis.AI URL/docs and account/billing ownership are awaiting confirmation.
  No real charge, stream, recording, deployment or public release is authorized by
  this product-direction update alone.

## November 18, 2026 — Producer, Please desktop checkpoint

The current owner-requested slice resumes Producer, Please as a Windows desktop
production application with a native encoding path independent of OBS. This
supersedes the earlier desktop deferral for this bounded Producer checkpoint; it
does not change RareIQ's separate identity or invent hosting, billing or account
contracts. Existing OBS workflows remain available.

Implemented and locally exercised: Electron shell, manual Twitch/YouTube/Kick/custom
RTMPS destination setup, Windows account-encrypted secrets, exact-output native
readiness, compositor/public-audio capture, software H.264/AAC encoding and guarded
stop/quit. Saving a destination is not OAuth/account connection; sending media is
not verified platform receipt. The complete generated-media chain produced a
decoded 720p local file, and a separate local RTMPS fixture verified certificate
acceptance/rejection. Neither constitutes a real platform broadcast.

The app remains a local development build dependent on the C: checkout/Python
environment. F: contains app builds, desktop data, caches and evidence; the Windows
Start Menu shortcut retains its supported C: location. Real platform/hardware
acceptance, reliable NVENC, portable packaging and public release remain open.
See [Desktop checkpoint and evidence](DESKTOP_APP.md).

## November 18, 2026 — Guided desktop broadcast setup

Desktop setup now guides Program composition, clean-output preparation and secure
destination configuration separately. Choose sources navigates to the existing
production library while retaining the unsaved destination draft. It does not add
or select sources, Take, start capture or transmit. This is usability polish on the
local desktop checkpoint; account sign-in and platform acceptance remain separate.

## November 18, 2026 — Private bundled desktop preview

Producer, Please now has a separate private bundled-runtime candidate. The existing
thin development app and primary shortcut remain unchanged. The candidate packages
CPython 3.13.12, 48 dependency distributions, approved source/static assets and
FFmpeg; it uses resource-relative code paths and writable F: profile data. This
advances the standalone desktop direction without claiming a public installer or
clean-machine release.

`--preview` selects the separate ProducerPleasePreview profile on F: and port 8767.
No existing scenes, keys, accounts or data are migrated; port 8765 remains intact.
Camera choice is explicit rather than automatic discovery on desktop launch.
Candidate 02 passed isolated actual-backend, native-EXE and local-encoder checks.
Candidate 04 passed final packaged Program acceptance; the separate Standalone
Preview shortcut was installed and opened. The primary entry is preserved. Runtime updates, signing, license/redistribution review, migration,
clean-machine and real platform/hardware acceptance remain open. See
[Desktop build types and evidence](DESKTOP_APP.md).

## November 18, 2026 — Guarded desktop recovery

Desktop transmission failures now retain safe last-attempt metrics and show an
explicit recovery path. View output restores the existing clean output without
changing Program or opening review. Unconfirmed worker shutdown or backend
ownership keeps Stop available and blocks retry/close. A new transmission always
requires an explicit Start and destination confirmation; automatic reconnect is
not implemented. Actual bundled output-loss/explicit-retry and local TLS-failure
checks passed with synthetic media. Real platform/hardware acceptance remains
separate; see [desktop recovery evidence](DESKTOP_APP.md).

## November 18, 2026 — Protected destination editing

The desktop setup now supports editing saved destination names, keys and servers
without displaying saved credentials. Blank edits preserve values; changing server
requires a replacement key. Cancel restores the Add draft. Destination mutations
and transmission startup are mutually guarded in Main, including pending ownership.
Actual packaged Settings/DPAPI acceptance passed with synthetic profiles; real
platform identity, OAuth and delivery remain separate. See [desktop evidence](DESKTOP_APP.md).

## November 18, 2026 — Asset sizing makeover, first pass

Studio header art now keeps its natural proportions and compact square mark.
Camera input thumbnails and empty states share a responsive 16:9 picture area,
capped at 320px wide. Short screens retain that aspect instead of flattening it.
PGM/PVW badges reserve room beside camera names. Existing themes, controls, source
selection, dock choices and production behavior remain intact. Eight isolated
dark/light viewport checks and the actual running desktop inspection passed.
This corrects concrete scaling defects; it is the first pass of the requested
broader makeover, not a claim that the whole interface has been redesigned.

After the owner granted browser device permissions, the second PC joined and
was admitted over invitation-only private HTTPS. Its selected C922 webcam and
Yeti GX microphone reached a real producer receiver: 1280x720 moving video,
nonzero microphone PCM and quiet intervals. Returning this guest to waiting and
readmitting the same session preserved Program. The guest gate was enabled at
-45 dB and displayed open/closed states. The owner confirmed hearing the return
audio test beeps clearly through headphones on the second PC. A bounded processed-
mic listening check also passed: clear voice and quiet speech came through. The
owner confirmed the delayed self-voice stopped after that test ended. Host-mic
conversation and multi-guest acoustic echo remain untested.

At the owner's explicit request, the tested private guest route remains available
for the running studio. Guests still need individual invitations; producer
controls stay local. Restart/startup provisioning for this private route is not
yet implemented in the desktop app. No public stream or recording was started,
and guest access remains distinct from producer sign-in.
