# RareIQ engineering memory

## November 15, 2026 - Layout suggestions must remain Preview-only

- Compute suggestions from current selected visual IDs at click time. Never add or
  drop guests, text or microphones to achieve a preset; reorder existing pictures
  only. Updating a suggestion during polling must not send a mutation.
- A microphone-only source should not occupy a picture cell alongside cameras or
  graphics. Keep its tile/audio readiness internally, hide only its visual avatar,
  and preserve the prior audio-only shot behavior when there are no pictures.
- Hidden audio and text overlays are trailing DOM children, not pictures. Portrait
  two-picture Focus must target the second visual tile rather than :last-child;
  the real mixed-image/title portrait check guards this shared selector.
- PiP thumbnails need a width-driven aspect ratio. A percentage of portrait output
  height creates a tall empty inset; real browser geometry now guards 16:9 insets.
- Preset cards must fit the dock width, not only the browser viewport. Auto-fitting
  minimum card widths keep narrow desktop docks readable alongside mobile layouts.
- Browser QA must wait for the producer's source selection to synchronize before
  clicking a suggestion; matching recommendation text alone can still represent a
  previous camera. Wait for the selected IDs and the in-flight operation to finish.

## November 15, 2026 - Preserve reviewed browser documents through Take

- Conventional DOM append/reparent reloads descendant iframes. Connect the incoming
  layer first, then move the reviewed figure with Element.moveBefore; transfer its
  ownership out of the outgoing layer before disposal. Feature-check and fail closed
  without append fallback. A browser fixture nonce guards actual context continuity.
- Do not append the already-connected destination layer again after preserving its
  children: moving that ancestor conventionally also destroys the iframe context.
- Browser approval belongs to one output's loaded frame. Every connected output
  must report each selected browser ready; other source kinds retain the existing
  same-output complete-composition rule. Reload/reconnect never inherits approval.
- Review temporarily changes output layout. Require explicit idle status, warn the
  operator, withhold readiness while reviewing, and hide all review controls after
  closing an approved review. Controls are restricted to an explicit preparation
  URL, whose flag is cleared on close. An unreviewed Preview must never paint
  controls on normal Studio Output. Preserve outgoing browser tiles into Preview
  before disposing a zero-duration Cut layer.

## November 15, 2026 - Iframe loading is not content verification

A browser fires iframe load even when embedding fails, and generally suppresses
iframe error events. The experimental adapter therefore never turns load into a
ready receipt. Review tokens are single-use and tied to one frame/load; reload,
error and disposal invalidate them. All restrictions precede navigation/insertion.
No iframe message is accepted as operator confirmation.

Sandboxing does not block all outbound requests or make requests credential-free.
Cross-origin navigation starts and script-driven content changes are not reliably
observable by the parent, so visual review must not promise continuous assurance.
See https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#error_and_load_event_behavior
and https://html.spec.whatwg.org/multipage/iframe-embed-object.html#attr-iframe-sandbox.
The asset-reachability gate caught the initially unlinked static file. Keep this
prototype outside served assets in tools/experiments until integration is ready.
Unit checks plus intercepted-browser QA guard the experimental contract. Production
pages do not load this adapter and composition still rejects browser identifiers.

## November 15, 2026 - File playback and bounded text layers

- Video preload readiness means a decoded frame, not upload success. Keep Preview
  paused/muted, reset playback at Take, stop retired video sound immediately even
  while the old picture transitions, and dispose its media source on removal.
  Generated-media browser QA guards output receipts, replay and corrupt files.
- Text character count alone cannot bound preserved multiline height. Review caught
  a valid 100-line payload clipping while marked ready. The store and renderer now
  reject more than eight lines; UI explains the limit and regressions cover it.
- Source creation uses stable request receipts; immutable definitions prevent an
  edit to a saved title from silently changing an already-on-air composition.
- Studio Output embeds Program in iframe.program. Browser assertions must inspect
  that frame, not assume composition nodes live in the wrapper document.

## November 15, 2026 - Independent room viewing and terminal cleanup

- A gallery viewer is not a publishing guest. Authenticate its invitation separately,
  expose only a safe roster, and permit admitted-other-guest cameras only. Never
  forward operator snapshots, private chat, screen/audio or return mixes to this
  view. Closing a viewer must not change publishing presence; losing the publisher
  must invalidate source availability even while the viewer socket remains open.
- Reserve the newest role/session peer before awaiting closure of an old socket.
  Otherwise two reconnects can both register after a delayed close, exceeding the
  bounded recipient count and interrupting healthy publishers. Recheck reservation
  ownership before Hello. Delayed-close tests cover publisher and viewer roles.
- Returning to waiting is reversible; removal is terminal. Keep capture/session for
  wait, remove guest sources from both buses, and never automatically take a
  readmitted source. A stale retry receipt for a prior wait must not remove a newly
  readmitted shot. Ended sessions require fresh invitations.
- Browser rehearsal exposed that access-denied UI previously left local capture on.
  Terminal access end must retire the publisher and all capture/audio owners,
  invalidate pending permissions/replacements, clear credentials and borrowed
  streams, and prevent late callbacks from re-enabling controls. Ordinary network
  interruption and return-to-waiting retain capture. Unit and actual browser
  generated-track regressions verify this distinction.
- Image import success is not decode/readiness proof. Validate local image IDs,
  preload/decode in Studio Output and require one output to report the entire
  intended mix ready. Broken images cannot be taken; import and Preview leave
  Program unchanged. Keep uploads in the isolated fixture's asset store for QA.

## November 15, 2026 - Backstage conversation isolation

- Derive a guest's private recipient from its authenticated invitation session,
  never from the request body. Revalidate invitation/room/expiry inside the same
  SQLite transaction as each read or write; retry receipts cannot bypass removal.
- Require room identity for sends, isolate chat from production revisions, and
  keep bodies/credentials out of general activity and signaling. Keep sender keys
  and immutable message receipts in the dedicated local table for accountability.
- Client requests belong to a session plus conversation generation. Abort and
  ignore obsolete reads when changing token, room, guest or channel; an initial
  response must not establish a new session's room. Clear drafts/history on access
  end. Keep channel/guest drafts separate, and reuse the exact request ID and body
  after uncertain delivery so a lost HTTP response cannot duplicate a message.
- Render content as text, announce only new arrivals, preserve keyboard focus, and
  leave the surrounding tool panel at natural height. Only the message transcript
  has a bounded scrolling region. Verify theme attributes on the document root
  using actual skin values (ignite/daylight), not dark/light labels on the body.
- Guards: chat service/routes and ingress tests; mocked client lifecycle tests;
  tools/qa_guest_chat.cjs with two guest browsers and the actual producer screen.

## November 15, 2026 - Capture-off must not wait for permissions

- A global capture-busy flag blocked Off while another device permission was
  pending. Keep active source shutdown synchronous and available independently.
- Invalidate pending capture/replacement and enumeration callbacks per source,
  while preserving the shared request lock until the outstanding operation settles.
  Late streams must be stopped; they must not reopen a source the guest stopped.
- Distinguish private prejoin screen preview from connected availability and
  unconfirmed delivery during connection failures. Signaling state is not media
  receipt. Unexpected track-ended callbacks must belong to the current source.
- Pending operations need visible progress and matching accessible busy state.
  Keep progress owned by the current operation; cancellation/error must restore
  controls without overwriting newer feedback or blocking active capture-off.

## November 15, 2026 - Separate guest operation and feedback ownership

- Periodic room/audio snapshots must not erase device or file-operation errors.
  Give actionable feedback independent live regions, cleared by a subsequent
  relevant action. Keep local sound rows keyed; rebuilding or disabling a focused
  control during an asynchronous action must not lose keyboard position.
- A successful capture followed by failed enumeration is still successful capture.
  Preserve the track and show its actual device selection, with a refresh warning.
  Empty browser MIME metadata is not proof of an invalid audio file: allow only
  recognized picker extensions, then enforce actual decoding and all bounds.
- Joining and retrying have independent connection state; awaiting signaling must
  not trap already-running capture behind disabled Off controls. Expose Leave as
  soon as a session exists and reject stale connection/permission completions.
- Voluntary Leave and producer removal/revocation need distinct socket close
  semantics. Sending normal-close for both made a revoked session display Retry,
  although backend access was correctly blocked. Use terminal access-ended close
  for remove/revoke/room-close; regress both UI feedback and server denial.
- Terminal retry reuses the authenticated session and must not renew revoked
  access. Ignore callbacks from the retired publisher and retire return audio
  before a new connection. Exercise failures with generated tracks and an isolated
  server; never equate injected browser recovery with internet or acoustic proof.

## November 15, 2026 - Isolate guest audio processing and recipient failures

- A Voice Mod gate does not filter a separate guest capture pipeline. Reuse shared
  DSP at the guest microphone owner. Gate the raw mic before voice effects; mix
  sound pads afterward so silence detection does not cut them off. A stable output
  track preserves negotiated media while changing styles, gate and sounds.
- Mic-off, Leave, device replacement and late initialization must release raw and
  processed tracks, oscillators, sound players and contexts. Decode only bounded
  local files, hold a bounded number of decoded buffers, and never expose producer
  soundboard/catalog APIs to invitations. No automatic local monitoring.
- Preserve supported raw mono/stereo channel count and prepare enabled processing
  before initial publication. These are compatibility guards, not a proven cause
  of the earlier physical guest interruption. Processing fallback is explicit:
  a resolved configuration promise can still report unavailable/unfiltered.
- Per-recipient ICE/negotiation failure must not tear down healthy media or the
  shared signaling session. Bound recovery (1/2/4 seconds), cancel old timers and
  callbacks, scope warnings per peer, and clear them on normal unsubscribe too.
- Buffer new-credential ICE until its matching remote description; discard stale
  candidates. A rejoined publisher replaces obsolete records for that participant
  so track selection cannot keep finding the old connection. Regressions cover
  early ICE, partial failure, recipient removal and changed signaling identity.
- Gate delayed playback success/rejection by the current stream and session. An
  old play rejection must not restore Enable room audio after Leave. Show only
  known diagnostic enums, never SDP, tokens or arbitrary error payloads.

## November 15, 2026 - A visible guest picture does not prove output sound

- A real second-PC rehearsal displayed camera/screen frames while audio.play()
  was rejected by browser autoplay policy. The clean composite's noninteractive
  iframe prevented the child recovery gesture, and the operator only saw a
  pending receipt. Preserve the truthful audio gate and expose a sound-enable
  control only while blocked. Invoke the embedded compositor synchronously from
  the real click; postMessage does not reliably carry transient user activation.
- Treat renderer receipts as historical evidence. Track fresh playback health per
  output and generation; a blocked, pending or stale output cannot borrow another
  output's receipt. Playback reports expire after six seconds. Unit and route
  regressions cover stale generations, blocked playback, distinct outputs and
  recovery. The actual browser click cleared audioBlocked and confirmed Program.
- Gate confirmed activity history with the same fresh, matching playback evidence
  used by operator status. Bare receipts must not create a confirmed audit event.
  Re-send health before the receipt when HTTP rendering precedes signaling.
- Iframe load can follow a blocked-audio status message. Re-read the child state on
  load rather than hiding recovery unconditionally; regressions cover that order.
- Driver standby video and silent audio tracks verify transport only. The later
  MX Brio check established physical camera video on Program; spoken audio and
  mix-minus listening still require separate acceptance.

## November 15, 2026 — Program audio ownership and local invitation scope

- Program mute policy belongs to the producer and must not toggle or stop a
  guest-owned track: that same track also feeds backstage conversation and video
  readiness. Mute removes only the selected Program playback consumer. Invalidate
  queued/late play callbacks so a retired consumer cannot resume after mute.
  Unit regressions and real generated-tone browser checks cover independent
  microphone/screen mutes, unmute, deduplication and unchanged mix-minus returns.
- A displayed mute button must follow authoritative room state, including
  conflicts from another producer tab. Waiting/offline-media guests can be
  pre-muted; toggling one flag preserves the latest value of the other.
- Localhost invitation URLs belong to the production computer. Explain that at
  creation, keep one invitation per person, validate the guest URL before linking,
  open without opener/referrer, and clear both the input and href on dismissal.
  Guest mute notices clear on leave/disconnect and never change capture.

## November 15, 2026 — Audience adapter verification and cleanup

- Fixed desktop readiness notices can cover a tall tool's final control. Reserve
  bottom scroll clearance while the notice is visible. UI acceptance scrolls to
  every visible control and checks its hit target, including the last summary.
  Capture tall tools in actual viewport slices: full-element screenshots inside
  a clipped workspace can misleadingly show unrelated panels and blank space.
- A failed public-key refresh must not advance successful verification time.
  Kick advances its cache timestamp only after a valid key is parsed; failed
  expired-key refresh disables receiving. A valid old signature cannot bypass
  the failure on the next request. Signed delivery and accepted audience intake
  are distinct: a rejected event must not increment successful intake counters.
- Provider cleanup can throw or stall. All three audience adapters bound client
  close operations, drop credential/client references and expose incomplete
  cleanup. Regression fixtures cover exceptions and never-finishing close calls.
- YouTube liveBroadcasts.list permits exactly one of broadcastStatus, id or mine.
  Channel ownership uses a separate channels.list(mine=true) call; provider mocks
  now reject incompatible filters, including across broadcast pagination.
- On Windows, Python text edits must specify UTF-8 explicitly. Default encoding
  can create mixed-encoding JavaScript when adding non-ASCII interface copy.
  Audience source decoding is checked strictly in the browser regression suite.

## November 15, 2026 — Guest media, lifecycle and output evidence

- A pending device permission promise can resolve after Leave/pagehide. Capture
  uses a lifecycle generation and stops every track returned to a stale request.
  Six browser regressions cover late camera, mic and screen results.
- Chromium exposed live received audio tracks/RTP while a Web Audio-only return
  graph stayed silent. Always-muted media consumers, created only after explicit
  conversation start, activate decoding. Real frequency tests prove host/other
  guest return and self exclusion. Consumers release borrowed tracks without
  stopping their owner and never enable audible monitoring themselves.
- HTTP switcher polling can beat the signaling generation. Do not permanently
  mark a render receipt sent when the receiver rejects that newer generation;
  retry on refresh. A regression covers the poll/signaling race.
- Require one output to receive the whole guest mix. A union of two partial output
  readiness sets is insufficient. Readiness expires, and source availability,
  browser rendering and platform receipt remain distinct layers.
- Sequential socket sends let one slow recipient trip every healthy client's
  watchdog. Isolate sends concurrently; bound send-lock and close waits, revoke
  failed peers before cleanup, and recheck access on pushes and late messages.
- Disconnect and room closure clear guest IDs from both composition buses,
  including stale IDs absent from the current socket/history snapshot. Rejoining
  cannot silently resume a prior Program selection.
- SAFE revokes pending vision authorization inside the Program mutation lock.
  A gesture's short-lived request authorization is rechecked inside that same
  lock. Dispatch waits never hold the vision controller lock.
- Scene automation reads the authoritative SQLite store even before a scene-list
  request after restart. Browser audio follow-ups use the returned scene, not an
  obsolete local draft. Hands-free scenes containing browser-only audio actions
  reject before changing Program.
- Integrated visual QA caught a mount API returning `{element, stop}` where the
  studio expected an element; isolated component checks missed this boot failure.
  Keep a full-page mount/interaction check alongside component baselines.
- Tests observing global cv2 must count their fixture path, not concurrent catalog
  reads. Main-app switcher tests stub activity writes or use a temporary database;
  synthetic actions must not become real operator history.

Guest public ingress must share the existing app/hub in one process and permit
only exact guest routes. A second app process splits signaling; a generic proxy
to loopback promotes public requests into operator trust. Strip cookies, forwarded
identity and inherited request state at the dedicated boundary. Its optional
listener has a separate bounded lifecycle and never implies public reachability.

## November 15, 2026 - Shared identities must not inherit legacy control access

A role check on scene handlers alone leaves older control endpoints, static entry
points and camera WebSockets accessible through legacy loopback/shared-cookie rules.
Put a deny-by-default ASGI boundary ahead of those paths. The disabled account pilot
allows only scene APIs; no cookie, forwarded header, localhost or first-visitor shortcut
substitutes for verified identity and persisted production membership.

Check membership inside BEGIN IMMEDIATE before idempotency lookup. Otherwise a revoked
editor can replay a successful receipt. Scope receipts to provider/app/subject within
the production store. Membership mutations and their activity must roll back together;
protect the last owner and preserve legacy history as unverified. Member-role events
use membership revisions; scene events use scene revisions.

Review found a request race when the global account-mode flag changed after verification:
dropping the captured principal would enter permission-free legacy behavior. Preserve
the typed request principal regardless of later global mode changes. Regression tests
exercise that race, real HTTP/socket routes, provider failures, denied viewers, revocation,
principal collisions, concurrent edits and migration without application lifespan or
hardware. The fake verifier proves the boundary, not real StackThis authentication.

Do not infer app-login registration from marketplace catalog entries. In deployed
StackThis v249 (`7de1788d08547876e7717d320df30d743b05abbb`), Producer, Please is listed
but omitted from all callback/login policy registries. Session verification is
server-only GET `/api/apps/session/check?appId=producer-please`, using a 64-lowercase-hex
Bearer token. Require allowed=true, exact appId, nonempty subject and fresh checkedAt;
recheck every request and deny unavailable/redirect/malformed responses. The provider's
source/access classification is neither a studio role nor RareIQ entitlement.

## November 15, 2026 - Shared scene writes and honest attribution

The previous scene path changed the in-memory list before JSON persistence and allowed
stale clients to overwrite each other. Use one SQLite transaction for scene state,
revision, activity and a minimal idempotency receipt; history failure rolls back the edit.
Retain the legacy JSON without rewriting it. Never archive all scene free text in each
retry receipt. Record allowlisted value changes and only changed flags for free text.

Keep a draft's starting revision independent of polling. A delayed/replayed mutation
receipt must not replace a newer visible snapshot. Refresh current state after success.
HTTP LAN clients may lack crypto.randomUUID; use crypto.getRandomValues as its fallback.
Shared pairing cookies and loopback access identify neither a person nor a unique device;
label the coarse access origin unverified until the sign-in adapter provides a subject.

Guards: test_production_scene_store.py, production_scene_edits.test.cjs and
qa_studio_scene_activity.cjs cover transactions, concurrent writers, retries, pagination,
unpaired reads, forged actors, browser propagation and preserved conflict drafts.
Populated scene forms require the narrow dock grid rules; empty-state screenshots miss
their overflow. Visual checks include the open editor and populated activity disclosure.
Shared controller dependencies must also load in the served fallback HTML pages;
the browser test checks script ordering in every Studio entry point.

## November 15, 2026 - Natural-height production tools

Viewport-sized dock frames, fixed bottom rows and independently scrolling tool wrappers
clipped populated Session Control and Production Health cards. Saved inline tool heights
could reintroduce the problem. Docked regions and tools now size to their content; saved
dimensions remain available for floating windows. Keep the right checklist spanning the
main and bottom rows, with the flexible track last, so it does not create a large gap
above the bottom tools. When removing fixed monitor parents, explicitly preserve image
aspect ratio: the previous flex/zero-height image rule otherwise collapses the preview.

Guard: tools/qa_studio_flow.cjs runs against the served page, blocks API mutations and
device capture/playback, checks six theme/viewport combinations and saved short heights,
and asserts no clipped/scrolling tools, horizontal overflow, collapsed preview or excess
gap above the bottom dock. API blocking can show connection notices in QA screenshots;
these checks do not verify hardware, live output or successful production mutations.

## Keep one primary OBS composition - September 8, 2026

Mirroring every operator panel as a separate OBS input duplicates rendering and setup.
Bootstrap one Studio Program Browser Source containing camera, graphics and routed web
audio, while retaining individual sources for advanced layouts. Mark the composed
source as audio-capable so OBS enables browser-audio routing. Do not claim a complete
mix while the microphone is still captured once in OBS.

## Test populated docks, not just their loading shells - September 8, 2026

Early visual QA could capture an empty Preflight while its read request was pending;
an every-element font check then passed vacuously. The served layout test now uses
eight explicit readiness fixture rows with failure, warning, pass and skip states,
waits for them, and verifies readable detail text plus reachable lower controls.
This fixture verifies layout only, never hardware or platform readiness. Use actual
DOM selectors for incident forms, event logs and health journals; historical class
names silently missed these interiors. A dock's Add a tool affordance must not count
as a selected tool or keep an otherwise empty region open.

## Docking must retain its interior styling - September 8, 2026

Moving panels into docks invalidated Broadcast direct-child selectors, restoring
legacy navy gradients and 6–8px labels. Scope the visual owner to nested dock panels
and explicitly replace fixed legacy typography. Hide only repeated interior titles;
retain actions, statuses and the dock's accessible label. Consolidating switcher
layout must retain zero margin and bounded height: losing the old margin reset
placed source controls below the stage at short desktop heights. Served QA now
asserts source-strip containment as well as monitor/transition non-overlap.

Content-sized default side docks need an explicit custom-height flag before native
resize starts; otherwise an important auto-height rule suppresses the resize.
Preserve old nondefault heights, save resized heights, and verify a real pointer
resize plus tool-set reload. Do not wait for a page load event on endless camera
streams; wait for DOM readiness and initialized controls.


## Recognition vocabulary and execution authorization must agree - September 8, 2026

Owner testing found “cam two” rejected despite “camera two” working. The installed
finite speech grammar and server parser both need the alias; a parser-only fix
cannot recover words the recognizer cannot produce. Guard both with synthetic
speech through the installed engine and parser/service regression tests.

PTT previously enabled bare commands implicitly. The owner now requires a wake
phrase in either mode. Keep input mode separate from a strict `open_flow` boolean:
only an explicitly enabled session may omit the prefix. Capture that configuration
with the owned recognition job; Stop/default restart clears it. Validate booleans
without coercion, preserve PTT whole-utterance checks, and require the host to echo
the requested setting before attaching capture. An older host must not silently
accept controls whose semantics it does not understand.


## Optional audio filters must preserve input ownership - September 8, 2026

The noise gate connects after input gain and before both dry and effect branches.
Gating only the wet branch leaks quiet input through the dry mix; averaging stereo
samples before measuring power can wrongly mute opposite-phase channels. Measure
per-channel power with one shared envelope/gain, preserving each output channel.
Bypass remains exact, defaults off, and module/processor failure restores unfiltered
audio with an explicit status. A pending module must not reconnect after microphone
stop. Synthetic DSP, loading/cancellation/failure tests and served offline browser
rendering guard these contracts without acquiring or playing a physical microphone.


## Fullscreen voice test needs input evidence - September 8, 2026

Owner reports hold-to-talk ineffective in fullscreen PUBG. The earlier gate required
both a queued WM_HOTKEY and physically held Ctrl+Alt+V; missing message delivery
therefore rejected a real held chord. After successful registration, a fresh
physical chord now also opens the bounded hold interval. Initial held state without
a message requires release/repress. Conflicts still block arming; zero key state,
observer failure and emergency stop cannot authorize commands. Only the fixed
chord is polled; no input injection, hooks, privilege or game changes are used.
Microsoft documents the high-order bit as current key state, with zero possible
on access failure: [GetAsyncKeyState](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate).

A generic Practice message can remain visible across attempts. Expose per-session
shortcut/audio counters and the result timestamp; duplicate requests must not make
old feedback look new. Diagnostic counts and one timestamp stay in memory, without
transcripts or stored audio. Test actual gameplay separately; mocked native state cannot establish
that PUBG permits observation or that the browser delivers audio while backgrounded.

## Program logo and audience-source isolation - September 8, 2026

An image selector (`.program img`) assigned full-frame dimensions to the corner
logo and outweighed `.program-bug`. Restrict frame layout and transitions to a
dedicated frame class; explicitly bound the decorative image to 34x34px with its
own positioning. Check computed browser geometry, not only source declarations.
The adjacent audience outputs were audited; no matching active logo collision was
found.

Program also used the annotated operator preview feed. It now embeds the existing
clean camera output, retaining that view's reconnect and stale-frame protection.
A direct swap to clean MJPEG is insufficient: its lease ends after source or scan
camera reassignment. Program must preserve the clean view's reconnection behavior.
Rapid takes now update the active view synchronously and cancel old release timers;
closing Program removes both views and prevents late fetches from reopening them.
Regressions exercise selection, rapid takes, invalid state and close-during-fetch.

## Sarge console layout must retain input ownership - September 8, 2026

The voice controls were buried inside the microphone card, making status and the
latest command result difficult to find. Move the existing console into the same
Voice studio grid above that card; do not clone controls or build a second media
owner for docking. A served Edge regression retains exact node identities through
dock/return, checks one Start request and blocks actual media and API writes.
Readiness badges derive from the existing session and input, never decorative
activity. Container rules cover the 354px dock independently of viewport width.

## Voice ownership, delayed completion and safe synthesis - September 8, 2026

Speech borrows the raw Voice Mod node; it must never own a second microphone or
close the source context/tracks. Invalidate asynchronous attachment and recognition
on Stop/device changes. Emergency and lease checks must cover errored sessions,
not just healthy listening. A pending action needs observation of its existing
Future; acknowledging dispatch or retrying the adapter cannot establish completion.
Regression tests cover all three classes, plus actual synthetic speech/clip output.

A synthesis diagnostic used a nonexistent output-binding overload without stopping
on errors; the following Speak call may have used the default speaker. This was
disclosed to the owner. All synthesis tests now set ErrorActionPreference=Stop and
select null output before binding explicit memory output; a failed binding aborts
before Speak. Never assume a failed output-selection call preserved privacy.

PTT must validate first and last voiced timestamps within one held-key interval;
checking only the last word permits speech from before the press. Reserve the
shortcut on its native worker, fail closed on conflict, and unregister on that
same worker. A dead native observer must revoke Wake mode too, because its emergency
stop is otherwise lost even when the audio/heartbeat path remains healthy.

## Saved scenes must share camera availability checks - September 8, 2026

The switcher rejected unavailable cameras, but saved scenes bypassed that guard.
Saved-scene takes now reject unassigned/disconnected/missing targets while holding
the production lock, before any Program, screen or OBS effect. HTTP regressions
assert every downstream effect remains untouched on rejection. This checks
availability; frame freshness remains a separate preflight concern.

Clearing a rundown timer did not invalidate an action already awaiting a reply.
Use a run generation across awaits, settle cancelled waits, and check the generation
before follow-up actions, advancement or feedback. An old finally block must not
unlock a newer run. Regressions cover Stop/restart races, replay lookup and delayed
scene/Spotify completion; partial scene outcomes pause rather than auto-follow.

## Motion and functional production foundation - September 8, 2026

Manual replay previously indexed JPEG highlights while only card-triggered auto
clips encoded MP4. The manual save endpoint now requests the same verified export,
and UI success requires playable-video evidence. Request IDs must bind expiry as
well as action/parameters; retain records for the full allowed retry window so a
changed deadline cannot escape deduplication. Tests cover concurrent retries,
expiry extension, capacity, untrusted inputs, low disk and failed encoding.

## Portable controls need their original state and styling context - September 8, 2026

Moving an audio shell outside its standalone workspace preserved listeners but
lost workspace-scoped control styling. Extend the existing style selectors to the
dock's tool identity, and preserve that identity in popout wrappers. The dock owns
width/padding while original tokens and control rules remain shared. Verify actual
rendering; node identity checks alone do not catch missing ancestor styles.

Use anchors to restore the original shell when leaving Live Control. Never clone
controllers or replay input/change events while docking. Local audio keys must not
bubble into Program switching. Saved launcher-to-dock migrations must preserve
explicit new choices and migrate both the current selection and named sets.
Guards: model migration test plus `tools/qa_studio_audio_docks.cjs`; all API mutations
and media starts are blocked in the browser test.

## Tool sets, modal focus and full-screen navigation - September 8, 2026

Automatically overwriting the active saved set while preparing Save as new loses
the original project selection. Keep the working draft in existing local layout
storage and update named sets only with explicit Save changes. Independent opaque
IDs, duplicate labels, switching and reload are covered by regression checks.

A full-screen workspace cannot display a sibling workspace. Exit full screen
before session-launcher/drawer navigation. A popout returning to the main studio
must close the modal tool drawer and restore the intended tool's focus, rather
than its stale trigger. Real browser regressions cover both transitions.
Measure available frame height from its rendered top position rather than a fixed
header subtraction. Hidden workspaces must not reset geometry; narrow viewports
retain vertical document flow. Camera and production DOM owners are unchanged.


## Tool-window presentation contracts - September 8, 2026

A cloned select loses its machine values if the general attribute filter drops
OPTION.value. An initial fixture used labels equal to values and missed this;
review caught it. Preserve OPTION/BUTTON values, synchronize editable properties
separately, and test labels like General streaming with a value of studio.
The canonical unit guard and real Edge fixture cover this distinction.

Mirrored tools must keep original DOM ownership, guard disconnected/disabled
sources at interaction time, retain focused drafts through background updates,
and flush them before submission. Reconcile stable nodes rather than rebuilding
while typing. Exclude executable/media/credential elements before insertion;
re-evaluate restrictions after type/identity changes. Never start another control
app or camera/audio owner in a popup. Explicit popup width/display ownership is
required to override the old workspace's 12-column grid.


## Docked tools and legacy grid placement - September 8, 2026

A retained tool may still inherit wide-screen grid-column/grid-row placement.
Moving the switcher into a dock initially let monitors overlap transitions at
1920px despite no page overflow. The scoped dock owner resets both column and row
placement on every direct switcher child; source and real-browser overlap checks
now cover it. Existing Broadcast visibility also must delegate to the dock owner,
otherwise tab selection hides pinned tools. Preserve actual nodes and document
ownership: external adoption breaks the app's document-based lookups.
Do not clamp floating coordinates while their workspace is unrendered: zero
bounds erase positions. A visibility guard and browser resize regression cover
this case. Give the parent lockup an explicit 36px height: Edge collapsed its
auto height to zero on the CSS Daylight image swap despite a valid SVG ratio.

Generated branding CSS/provenance was normalized to LF after byte-preservation
attributes exposed CRLF as whitespace errors. Check Git command exit codes before
continuing to commit; do not treat the final command's success as proof that an
earlier check passed. Imported payload hashes remain unchanged.


## V2 operator token and asset adoption - September 7, 2026

Late command-deck rules owned the winning colors while v1 CSS forcibly substituted
logos. The current shell now excludes those v1 substitutions; existing semantic
variables resolve the supplied v2 tokens with legacy-page fallbacks. Tests retain
ordering, local asset hashes, technical routing and contrast checks across all five
palettes. Read/write text explicitly as UTF-8: a migration helper briefly decoded
a test's Unicode expectations using the Windows default; restoring the original
test with explicit UTF-8 corrected it without changing product copy.

During the v2 gate, `test_pack_transition_learning_survives_restart` failed once
with an empty restored prediction rather than `[18]`; all 27 reference-prewarm
tests passed immediately afterward. Root cause is unconfirmed. No recognition
backend or test was changed to bypass this result; retain it as an intermittent
test investigation if it recurs. This rebrand does not authorize backend changes.

## Shared appearance persistence - September 7, 2026

The old first-paint and runtime theme resolvers duplicated state; a blocked save
still displayed success and a later OS event reread stale storage. The shared
`studio_appearance.js` record now owns both paths, preserves legacy preferences
and unsaved in-memory selections, and reports persistence failure. All HTML entry
points consuming `studiox.js`, including fallback pages, load this dependency
first. Behavior tests cover migration, reload, corrupt/blocked storage and OS
following; an entry-point guard prevents missing bootstrap dependencies.

This is the state foundation only. Five skin palettes and identity migration
remain pending; existing light/dark controls and presentation are retained.

## Branding provenance and false transparency - September 7, 2026

Symptom: two image-generation extractions displayed checkerboards but were RGB
files, and an early brand-book draft treated RareIQ as the parent studio.

Root causes: a transparency-looking image is not evidence of an alpha channel;
repository historical positioning did not include the user's Producer, Please
brand decision. The original approved character was found in the downloaded
implementation handoff referenced by the earlier branding task.

Guards: retain the unmodified original reference; label restored/flat adaptations
and hybrid SVGs accurately. `docs/branding-v2/package_brand.py` requires a real RGBA
master with transparent corners, validates PNGs, book page count, asset pairs,
contrast ratios and ZIP integrity. Local matte cleanup was explicitly authorized.
Pale highlights must survive matte extraction, and dark/light compositing must be
visually inspected. A writable image copy is required before Pillow flood-fill.

Record brand architecture independently from runtime implementation. RareIQ/OCR
is the premium recognition/intelligence product within Producer, Please; this
package does not prove that the application has been rebranded or newly integrated.

This file turns regressions into permanent operating knowledge. It is not a bug
backlog. Add an entry when a defect repeats, escapes visual review, or exposes a
class of failure that can be prevented automatically.

## The rule

Every qualifying regression records:

1. visible symptom and affected workflow;
2. root cause rather than only the edited selector/function;
3. smallest durable guard: unit/contract/browser test, release check, or explicit
   operator preflight;
4. environments verified (dark/light, 1080p/4K/narrow, hardware/offline service);
5. any limitation that still needs real-device or live-platform testing.

Do not keep duplicate production implementations “just in case.” Git preserves
deleted and replaced code. Keep the current tree understandable and use commits,
tags, and archives to recover older behavior.

## Learned patterns

### Cascade and legacy-style regressions

- Symptom: old colors, spacing, or card-only controls return after a new shell is
  added.
- Root cause: late or more-specific legacy selectors override the new semantic
  layer; visual inspection covered only one workspace or resolution.
- Permanent guard: keep the final shell stylesheet last, assert the asset order,
  test header controls per workspace, and inspect dark/light plus 1080p/4K/narrow.

### Async readiness and race regressions

- Symptom: stale results authorize a button, a second click starts twice, or a
  slow OBS probe makes a fresh camera appear stale.
- Root cause: state was sampled before a slow await or responses were accepted
  after the selected workflow changed.
- Permanent guard: generation tokens, server-side locks, current-workflow checks,
  no retries for mutating operations, and concurrency/stale-response tests.

### Test-pass versus running-runtime regressions

- Symptom: source code is fixed but the open browser still serves old behavior.
- Root cause: the server or cached static asset was not restarted/version-busted.
- Permanent guard: cache-bust changed assets, restart only after checking that no
  show/recording/stream is active, and verify the live API/UI after restart.

### Hardware ownership and external integrations

- Symptom: OBS cannot use a camera already owned by RareIQ, or an offline external
  service is mistaken for a working broadcast.
- Root cause: physical-device ownership and external encoder/platform receipt are
  different readiness layers.
- Permanent guard: RareIQ browser outputs for owned cameras/audio, explicit local
  versus destination readiness, and no claim of live verification without actual
  destination receipt.

### Credentials and local evidence

- Symptom: OBS passwords or diagnostic camera frames appear as untracked source.
- Root cause: machine-local files were created before ignore and release rules.
- Permanent guard: ignore `obs_settings.json` and `.tmp/`, preserve them locally,
  and make the release gate reject tracked local configuration/private keys.

## Checkpoint procedure

Before a checkpoint or push:

1. confirm the active show, recording, and OBS stream are off before restarts;
2. review untracked files, deletions, and large files, then stage the intended
   checkpoint so staged whitespace is visible to the gate;
3. run `python -B tools/release_check.py --require-node` in the pinned environment;
4. scan staged paths for credentials and generated runtime state;
5. commit a coherent checkpoint with tests/docs, push it, then verify the remote
   commit ID;
6. create and verify a dated source archive outside the repository when the phase
   is large or risky.

The code guardian should report findings and add guards; it must not silently
rewrite user work, remove evidence, expose credentials, or claim untested live
integrations are working.

## Studio output reconnect guards - September 16, 2026

Program previously swallowed switcher failures, leaving the previous camera selected,
and an indefinitely stalled request prevented further polling. It also compared only
process-local generation values, missing a changed slot when a restart reused a value.
Program now uses the existing overlay transport's single-flight requests, four-second
deadline, abort and teardown guards. Failure or invalid state clears both camera
frames; recovery restores current state, comparing generation and slot together.

Soundboard callbacks from a disposed player could mark a reconnected playback ID
complete and stop its replacement. Completion/error handlers now check player ownership;
pagehide also blocks queued transport events from recreating audio. The combined Studio
source explicitly permits autoplay on its audio iframe; this is permission delegation,
not evidence of OBS playback. The soundboard script URL was versioned for cache refresh.

Regression evidence: 35 JavaScript behavior tests and 26 focused Python tests passed.
New cases cover stalled/failed switcher recovery, reused generation values, stale audio
callbacks, heartbeat loss, malformed snapshots and post-close events. Existing graphics
checks cover hiding, expiration and same-generation reconnect. Tests use fake media,
transports and isolated backend fixtures; no OBS control, real playback, capture, stream,
recording or running-app restart occurred. Actual OBS acceptance remains pending.

## Existing OBS scene migration and physical-camera acceptance - September 17, 2026

The existing OBS Program source still pointed to the older camera-only /program URL
with audio rerouting off, and the scene separately included Soundboard. Updating the
bootstrap plan alone does not migrate preserved scenes. An explicitly authorized
migration changed the existing source to /output/studio and disabled the redundant
Soundboard scene item. Keep one audio route in the combined Program scene. Actual
OBS meters received the two short tests; the redundant route was inactive.

An available virtual-camera endpoint returned fresh placeholder artwork. Connected
status and fresh frames alone do not prove a physical camera picture: inspect actual
OBS output. Program now selects the physical Insta360 in slot 1, with a picture
visually confirmed after source refresh. The Mevo placeholder assignment in slot 2
was retained rather than described as a verified physical feed.

During configuration, slot 1 was assigned to Insta360 but had no fresh staging frames
before an output subscriber was attached. Attempting to restore its prior assignment
returned HTTP 500 and left Insta360 assigned. Opening the existing camera-output
WebSocket produced fresh frames, permitting a guarded Program take; OBS then held the
output subscription. The reassignment error's root cause was not established or fixed.
Follow-up: reproduce staging-source reassignment/stop failure in isolation, ensure API
failures are recoverable and truthfully reported, and add a focused regression guard.
Do not mistake the successful handoff acceptance for a fix to that separate error.

## Camera read/release race resolved - September 17, 2026

The prior reassignment HTTP 500 was traced to OpenCV capture.release in stop,
called from the request thread while the capture worker could still be reading.
The worker now owns release; slow cleanup retains the session and prevents
replacement handles. API cleanup failures return a sanitized 503. Seven isolated
regression cases were added, and actual Insta360 reassignment twice plus reconnect
passed after a managed restart with OBS configuration preserved and outputs off.
See CAMERA_REASSIGNMENT_CHECKPOINT.md for evidence and driver-failure limitations.

## 2026-09-19: Connected cameras are not necessarily safe to take

- Symptom: Preview, manual/voice Take and saved-scene Take accepted a connected
  camera without a recent frame. Non-finite or future frame timestamps could also
  make preflight readiness misleading or non-JSON-safe.
- Root cause: action validation checked connection state separately from the
  existing Program frame-freshness contract; timestamp arithmetic did not reject
  non-finite values or future times.
- Durable guard: all camera take paths share the two-second freshness check.
  Timestamps must be finite, positive and not in the future. The switcher API
  returns per-slot readiness, and Preview/Cut/Auto explain unavailable inputs.
- Regression evidence: 27 new Python cases failed before the fix; focused Python
  and browser-renderer checks then passed, including recovery on a fresh frame.
  The canonical gate passed with 2,639 Python tests and its JavaScript suite.
- Route registration is not OBS acceptance: browser-output preflight now warns
  that source setup, picture and audio still require OBS verification.

## November 18, 2026 — Desktop ownership and native-output evidence

- **Preparation UI is not Program.** Decoded rehearsal 04 exposed a retained
  review warning in the encoded picture even though frame/audio counters passed.
  Native capture now hides only preparation controls, waits for a clean painted
  compositor, and seeds a fresh frame. Actual review remains a blocker. Ownership
  tokens restore UI safely after stop/cancellation without affecting a newer run.
  Rehearsal 05 injects an opaque preparation notice and verifies it is excluded
  from capture, then restored after stop; decoded pictures are inspected as well.
- **Refresh must not erase an action failure.** The browser-review renderer's
  periodic status message cleared a native-broadcast refusal within 200 ms. Keep
  the warning until the next explicit review attempt or successful preparation;
  regression checks exercise both refresh and recovery. Native setup likewise
  prioritizes failed encoder state over a retained readiness receipt, and leaves
  startup cancellable while ignoring late Start/poll replies after Stop.
- **Process identity is not an idle verdict.** Reusing a healthy managed backend
  must not inherit shutdown authority. A private one-use receipt binds the desktop
  launch to its exact backend PID/session; stop checks that identity under the
  managed-server lock, then the server checks active production/recording/encoding
  and clients. Unknown state preserves the backend. Keep asynchronous window close
  under one quit owner until encoder and backend cleanup settle.
- **No heartbeat is not proof of an exited encoder owner.** Native encoding state
  remains active while Main is alive or cannot be inspected. Clear it only after
  confirmed owner exit or the matching owner's explicit post-stop update. Expose
  that state to browser-source review so an active output cannot enter review.
- **Aggregate output readiness can combine incompatible evidence.** Native
  preflight requires source availability and a fresh rendered receipt from the
  exact captured peer at the same Program generation. Another window, old receipt,
  pending browser review or stale generation cannot supply readiness. Camera-only
  programs also need the captured output's rendered receipt.
- **A muted window can still require a public audio tap.** Capture only approved
  Program and direct public Soundboard media; exclude nested/private/backstage
  frames. Preserve borrowed tracks. Native tests check volume, mute, pause, seek,
  loop, private-frame exclusion, monotonic timestamps and review rejection.
- **Codec enumeration is not a working encoder.** Probe a generated frame before
  selecting NVENC; report the selected software fallback truthfully. NVENC did not
  initialize successfully in this runtime. The verified full-chain file uses
  `libx264`, not a claimed GPU path.
- **TLS flags and a handshake alone are insufficient.** Explicit CA behavior in
  the Windows native transport required a verified stdlib TLS relay. One owner
  pumps each SSL connection; bounded serialized I/O avoids the handshake failures
  seen in intermediate attempts. The permanent checks require decoded media for a
  valid certificate and zero media for wrong-host and wrong-CA cases. Neither a
  local TLS pass nor an encoder's sending state means a platform is live.
- **Rehearsal isolation must precede application import.** The native fixture
  redirects storage/cwd first, substitutes an empty credential provider, suppresses
  constructor workers, blocks external sockets/DNS and skips hardware lifespan.
  Its allowlist adds only native preflight/status and encoding ownership, never
  shutdown. Browser isolation must allow the fixture's exact WebSocket origin as
  well as HTTP; blocking signaling created a false readiness timeout in the first
  harness run. Production readiness was not mocked to resolve it.
- **Inspect the decoded artifact, not just counters or a restored window.** The
  full-chain check takes an image/title while minimized, then verifies that the
  encoded frames changed and the generated 440 Hz tone survived AAC encoding.
  It records zero dropped queues and confirms ownership clears while Main remains
  alive. Passing evidence is `ProducerPlease-native-full-20261118-05`; failed runs
  remain preserved. A directory named `final` is not proof of success: cite the
  passing RTMPS serialized/repeat results listed in [DESKTOP_APP.md](DESKTOP_APP.md).
