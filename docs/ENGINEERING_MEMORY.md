# RareIQ engineering memory

## November 18, 2026 — CI fixtures must be independent of developer hardware

The Windows Release Quality run `44291995253` failed before Python tests: ten
destination and three bundled-runtime tests allocated fixtures on the developer's
F: drive, absent on the hosted runner. Use unique directories under `os.tmpdir()`
and bounded per-test cleanup. The canonical fixture-portability test reruns both
real suites with an isolated OS temp root, rejects allocations outside it and
requires no leftover profiles. Mock encoder F: strings are inert inputs, not writes.
The guard was mutation-checked against the original fixtures. Clear inherited
`NODE_TEST_CONTEXT` for nested runners and assert both suites actually execute;
Node 22 otherwise warns that recursive test files were skipped and exits zero.

The same log also exposed a separate Node 22 cancellation: the mock encoder child
has no process handle, so its deliberately unref'ed product deadline timers could
outlive the test event loop. A bounded, ref'ed test deadline now surrounds the
actual startup/stop timeout assertions and clears in finally; product lifecycle
timers remain unchanged. Local Node 24 passing was insufficient evidence for the
CI runtime. Reproduce with the exact runner Node version (22.23.4 here), use a
clean source checkout and confirm CI on the exact pushed commit. Do not infer a
current failure from an older annotation or call a local gate a remote CI pass.

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

## November 18, 2026 — Preserve setup drafts during source navigation

Native setup and the browser studio own different state. Source navigation hides
the existing settings window only after the trusted studio acknowledges that its
source panel is mounted and visible; it never destroys the draft. IPC accepts only
the exact settings main frame and evaluates one fixed navigation command. Recheck
the target/frame after awaiting and ignore stale ownership before hiding windows.
Regressions cover missing acknowledgment, duplicate clicks, replaced frames/windows
and packaged-window unsaved-field persistence. Readiness also belongs to the
selected output format: changing it must not retain a Ready label from the old one.

## November 18, 2026 — Bundled runtime isolation and launcher identity

- **Decoded UI state precedes acknowledged output readiness.** The packaged
  rehearsal initially tried Take as soon as the output's local video decoded.
  Wait for the backend's current ready groups as well; keep the real Take guard.
  Electron application evaluation also receives its Electron module as the first
  callback argument, with supplied data second. Tests must use the actual packaged
  module context and not assume a global CommonJS require. Preserve failed probes
  separately from the full passing packaged evidence.
- **A launcher PID is not always the interpreter PID.** A benign Windows probe
  confirmed that `.venv/Scripts/python.exe` is a redirector whose script runs in a
  direct child. Requiring exact PID equality in every mode would break development
  startup. Embedded Python still requires an exact spawned PID; the legacy Windows
  path may accept only a live direct child verified through OS process handles,
  parent linkage and creation ordering. Preserve both PID fields in the receipt.
  Regressions cover the real benign child, unrelated health replies and malformed
  identities; a responding server alone never establishes launch ownership.
- **Runtime resources and operator data have different lifetimes.** Set the
  desktop data root/Python environment before backend imports, generate profile
  defaults without copying machine configuration, and leave normal web/dev behavior
  unchanged. Concurrent first-use publishes only complete defaults without
  replacing an existing profile. Windows can retain an extended path prefix during
  a creation race; normalize equivalent spellings before containment comparison.
- **Lexical containment misses junction escapes.** Resolve actual resource paths
  before accepting a bundled manifest. Source packaging reads the staged Git tree
  through an allowlist, rejects traversal/link entries and records hashes. Keep
  source-staging and junction-escape regressions; do not package an entire dirty
  checkout, runtime configuration, user models or credentials. Stock wheel assets
  and license metadata are separate from operator data.
- **Feature names do not establish dependencies.** The first acceptance probe
  incorrectly assumed Python `aiortc` was required for WebRTC. This app uses browser
  peers and Python signaling. The corrected probe's dependencies are checked
  against production imports. Preserve the failed harness evidence and identify
  `backend-acceptance02` as the passing run rather than adding an unused package.
- **A packaging check must exercise the packaged controller.** Candidate 02's
  actual embedded backend proved 569 imported paths stayed under F: resources even
  with invalid Python environment paths, while profile writes stayed on F: and
  resource hashes did not change. A source test or development interpreter pass
  would not establish this. Check the exact artifact again after packaging changes.
- **Test teardown is not product quit policy.** Unknown OBS state correctly kept
  the acceptance backend running. QA terminated only its newly owned idle process
  after checking receipt, session, executable, profile/port, clients and encoding.
  The product retains its conservative guard; no reused server or port 8765 process
  was stopped. Desktop launch continues to require explicit camera choice instead
  of the older automatic boot/discovery path.

## November 18, 2026 — Recovery owns the entire start/stop attempt

Symptom: late encoder/capture callbacks or a cancelled startup could affect a new
attempt, and uncertain lease cleanup could appear idle. Root cause: asynchronous
work outlived its Start operation and public readiness did not fully represent
pending ownership. Durable guards bind callbacks to their operation/worker,
check cancellation after awaited setup, wait for unresolved reservations before
releasing ownership, and retain an ownershipPending blocker until explicit Stop
reconciles it. Unknown failure text never enters public status. Preserve safe last
metrics through Stop and reset them only on a new approved Start. A zero-origin
clock must still receive the full, resettable transient-readiness grace period.

Regression guards cover stale callbacks, late destination lookup, unresolved
reservations, worker-stop failure, backend lease-clear failure and unknown error
redaction. Actual packaged output destruction proves worker exit, lease release,
retained counts, no automatic restart, and explicit retry with a new peer. View
output must only restore/show/focus the existing trusted window: never reuse the
review action while sending or create a replacement implicitly. Its closing and
restore races are guarded. Local TLS disconnect exercises the real worker; a
generic safe encoder error is evidence of failure handling, not proof of a
specific diagnosed transport cause.

## November 18, 2026 — Destination edits need Main-level transaction guards

Symptom: renderer button locks could not prevent destination mutations racing an
awaited Start or ownership reconciliation. Root cause: the save IPC bridge had no
broadcast guard, removal only checked the currently selected active destination,
and Start did not account for an awaited destination write. Main now serializes
save/remove, rejects mutations while active/ownershipPending, and rejects Start
until persistence settles. Finally releases the mutation lock on failure. Tests
exercise both directions with deferred operations and untrusted-frame attempts.

Editing must not expose saved keys or server addresses. Omit blank fields and
verify preservation through the existing encrypted store. Changing server requires
a new key. Keep Add draft fields and its ambiguous retry receipt together when
entering/leaving editing; preserving only the fields could duplicate an earlier
uncertain Add save. Store, Settings and actual packaged DPAPI regressions cover
these contracts. Layout help text inside the form grid must span both columns.
The first native harness attempted to fill Twitch's hidden server field; the
corrected harness respects preset visibility and has an explicit action timeout.

## November 18, 2026 — Preserve aspect ratios in the final CSS owner

Symptom: header art looked stretched and camera input previews looked flattened;
tally badges collided with labels. The older header rule imposed a 208px minimum
while the later owner reduced height to 44px, distorting the 2400:680 lockup. A
legacy test incorrectly enshrined the old minimum. The final owner now clears it,
contains the art, and explicitly preserves the 32px compact mark. Input rows had
fixed 76px/40px heights independent of width; media/empty states now share 16:9
geometry with a bounded width. Labels reserve space for badges.

Guards check the final owner, removal of flattening overrides, matching empty/media
geometry and badge space. Actual isolated browser measurements cover eight skin/
viewport combinations, including short screens: correct ratios, no horizontal
overflow or nested dock scrolling, and readable label gaps. Existing API/readiness
contracts were not changed. Cache-bust only the owned stylesheet token while
preserving unrelated working-tree additions and their test-count adjustments.

## November 18, 2026 — Measure decoded audio before diagnosing a microphone

Symptom: an external physical-guest test receiver reported live audio tracks and
running WebAudio but zero PCM. The diagnostic omitted Chromium's muted autoplay
HTML audio consumer. Production already supplies this decoder consumer through
`createConferenceAudio.syncSilentConsumers`; its browser regression asserts
muted/hidden playing consumers and their cleanup. Fix the probe rather than
changing guest processing or weakening the noise gate. Preserve the early results
as inconclusive microphone evidence, not a diagnosed production failure.

The corrected actual two-PC receiver decoded moving 720p video and nonzero mic
PCM with quiet intervals. A live track, software gain or completed probe does not
prove audible output, intelligible speech, correct gate calibration, lip-sync or
echo cancellation. The low-gain monitor receiver closed after its bounded pass;
the guest's camera/mic publisher remains independent. Keep listening and two-way
return acceptance open until actually exercised and reported by the owner. Store
only numeric diagnostics; invitation material and captured media stay out of Git.

## November 18, 2026 — Startup settings and media-aware desktop readiness

Process-only guest variables disappear after restart. Persist only the explicitly
approved non-secret listener/origin pair beside the desktop profile receipt;
validate version, operator/guest ports and HTTPS origin together. Apply it only
when spawning a fresh backend, never pretend reusing an existing backend applied
new settings, and restore the controller environment even when spawning fails.
An explicit empty listener port is an atomic disable for both guest variables,
preserving the existing isolated QA launchers. Unit guards and three actual
isolated launches cover persistence without touching the active production server.

Initial loadURL completion is not desktop readiness when images or other media
resources remain open. Reload then rejects that old promise with ERR_ABORTED and
must not turn an already usable app into a startup failure. Bind initial readiness
to the exact trusted top-level document's DOM-ready event; consume late resource
rejections, but fail closed on wrong-document/frame navigation, genuine early
failure, destruction, renderer exit or a bounded timeout. Remove owned listeners
on every terminal path. Fake-event regressions and actual packaged Reload protect
both the successful media case and failure paths.

For wide rooms, give chat its own sidebar beside the entire main content rather
than spanning a guessed number of CSS rows. Keep one controller and move existing
nodes so media owners and listeners are preserved. A fixed maximum track inside
auto-fit can unexpectedly stack two tiles even when their minimum widths fit;
measure real desktop columns and retain narrower-screen overflow checks.

Use explicit UTF-8 for Windows source-edit scripts. Cached-diff review caught a
locale-decoded HTML rewrite before checkpointing; restoring exact HEAD text and
changing only the intended asset token preserved typography. The failed local
copy is retained outside Git. A screenshot test must scroll to the component
before measuring sticky sidebar positions; offscreen guest coordinates cannot
establish a bad sidebar layout. Earlier failed QA captures remain diagnostic only.

## November 18, 2026 — Account ownership and privacy stops

A delayed device approval must not overwrite a newer registered app or account.
Capture the prior vault record before the request, then recheck both configured
client ID and record freshness under the credential lock before saving. Twitch
regressions cover app and vault changes during provider validation. YouTube uses
the same ownership discipline for callback and refresh completion.

Keep one refresh owner for stored YouTube accounts. Passing a saved refresh-token
quartet to the old observer performed a second refresh and discarded rotations;
requiring scope on every refresh also rejected valid omissions. The account
service now supplies private access-token/expiry/channel/scopes through an async
observer seam on both connect and renewal. Stored mode never posts a connector
refresh, retains channel ownership checks and rejects channel changes. Explicit
legacy refresh/channel environment credentials retain their prior path; app
configuration alone must not silently select that path.

Audit storage must guard actions that enable access, but cannot prevent privacy
stops. Authenticated Stop, Disconnect and Cancel still execute when activity
history fails, and report a truthful history warning. Regressions must cover both
failed-before-action and failed-after-action logging, including OAuth cancellation
so a pending approval cannot save after the user stopped it.

Theme QA must set both data-theme and the actual operator skin. A light theme with
the dark skin falsely produced dark panels and unreadable headings in the first
fixture capture. Corrected checks use daylight/ignite and assert heading contrast,
then inspect real screenshots. Keep failed evidence as diagnostic, not acceptance.

The native Viewer chat click check caught a cross-component grid collision that
isolated panel tests missed: the older right dock spanned rows 2–3 while the newer
full-width backstage explicitly occupied row 3. Reset the right dock to row 2 only
when visible backstage takes the full bottom row. Keep hidden-room layouts intact.
A source guard, full-dashboard pointer/geometry checks and the actual EXE protect
this boundary; force clicks or keyboard workarounds cannot establish pointer QA.
The initial native audit also enumerated a closing settings window; filter out
destroyed windows and assert a surviving studio before reading preferences.

The fixed readiness badge still covered controls at 1366px after the grid fix.
Its final docked-workspace owner now keeps the existing status and Retry inline
above the dock frame, preserving feedback without overlaying controls. The full
pointer matrix passes in both skins at 960/1366/1920/3840, including Retry and
modal focus return. Known fixture-denied reads are recorded separately from
unknown page errors; never suppress arbitrary errors to pass a visual check.


## November 19, 2026 — Output lifetime and archive routing guards

- Symptom: Stop during a delayed output-profile read allowed the stale Prepare to
  create/review a window afterward. Root cause: operation ownership was registered
  after the first await. Guard: claim preparing/operation synchronously, recheck
  immediately after the read, and retain a delayed-read cancellation regression.
- Repeated startup class: output preparation awaited loadURL before its timeout,
  so a long-lived MJPEG resource could prevent the timeout from starting. Both main
  studio and public output now use exact-document DOM readiness with bounded
  navigation, trusted-frame checks and consumed late load rejections. The output
  regression leaves the resource load pending forever and still reaches readiness.
- A Twitch VOD mix must be separated before public audio is collapsed. Two paired
  480-frame stereo buses share one timestamp/credit/drop epoch, honor Program mute
  and never tap private/nested frames. Do not copy Live audio into a missing VOD bus.
  Modern OBS sends archive AAC as enhanced-FLV track 1; old PNAR/additionalMedia
  scripts describe a different legacy transport and must not be mixed into it.
  Local wire/decode proof never establishes Twitch archive acceptance.
- Twitch receiver scheduling: using the advertised keepalive deadline with zero
  grace can disconnect a healthy stream. The receive loop now has 2 seconds bounded
  scheduling grace and resets its retry budget only after validated healthy traffic.
  Safe diagnostics expose timeout/closed/transport and numeric close codes only,
  never provider reason strings, URLs, frames or tokens. A 45-second real reader probe
  remained connected and closed its owned subscription; no message was posted or
  received by that probe. The original approved test message is not a receipt proof.

- NVENC capability false negative: a hard-coded 64x64 generated probe failed even
  though normal output sizes worked. Probe the actual validated dimensions, not
  an artificially tiny frame; preserve both unsupported-size fallback and a
  dimension-sensitive regression. Two actual local HD workers now select NVIDIA
  and their files decode correctly. This does not establish platform delivery.


## November 18, 2026 — Multistream throughput evidence

A successful file encode with zero reported worker drops does not establish
real-time capacity. The previous generated-media loop slept 10 ms after doing
work, so its input could drift behind the nominal media clock. The harness now
paces against an absolute deadline and records wall time, maximum scheduling lag
and an explicit realTimeCapacityPassed flag (250ms tolerance). Eight NVIDIA HD
outputs decoded correctly but required 11.41seconds for 10 seconds of media; retain
that failing timing evidence rather than calling the capacity verified. Preserve
eighth-start cancellation and one-saturated/seven-continuing regressions when
replacing per-destination video encoders with shared encoding.


## November 18, 2026 — Shared encode and timing corrections

- A successful benchmark needs an independently checked clock. Windows short waits
  included a full timer quantum even when requested as zero. A timer-only 2.4-second
  run took 3.626 seconds. The old encoder-limit conclusion was therefore unsupported.
  Use absolute deadlines and an immediate I/O yield when already late; a simulated
  coarse-timer regression prevents cumulative delay. Rebenchmark both paths with
  the same clock and retain the old observations/correction in history.
- PyAV19 add_mux_stream silently ignores extradata/layout kwargs here. The proven
  seam is add_stream_from_template(shared_stream,opaque=True), with finalized
  shared codec metadata. Assert target codec contexts remain unopened, and create
  a fresh packet per target preserving PTS/DTS/duration/timebase/keyframe flag.
- Actual saved destinations include a bound UUID id. Strict shared-controller
  validation initially rejected that legitimate shape. Validate its binding to
  target.id, strip it before worker stdin, and test through real DestinationStore
  save/private access with a synthetic cipher rather than incomplete mock objects.
- Track shared child ownership separately from target thread ownership. Stop one
  confirms its thread; Stop all must confirm the child exit before releasing the
  native encoding reservation. Bounded target queues never block peers.
- A non-UTF8 bullet in Main survived permissive JavaScript parsing and could garble
  confirmation text. The source is now UTF8 and the packaging regression strictly
  decodes every desktop UI/launcher source before acceptance.


## November 18, 2026 — Audio gain compatibility and meter boundaries

- Adding default gain keys during normalization would invalidate v1 profile JSON
  equality and old retry fingerprints. Preserve the old two-boolean shape and
  omit explicit ±0 gains. Test a static pre-gain file/receipt, original replay and
  zero-field equivalent without rewriting, plus nonzero save/reload.
- Measure clipping before clamping PCM, and peak/RMS after clamping. Keep meter
  calculation independent of capture credits so preparing can show levels without
  starting an encoder. Hold clipping briefly so a 1-second status poll does not miss
  a 100 ms sample window. Apply the saved routing at Prepare, not only at Start.
- Main receipt freshness (750ms), finite scalar bounds, clip counter bounds and
  an explicit owned-frame check keep stale or forged diagnostics out. Invalid
  diagnostics clear meters rather than retaining a previous peak or stopping good
  media. Do not merge diagnostics into the strict source descriptor schema.
- Local activity append is separate from persisted profile mutation. Preserve the
  successful receipt and return activity_history_warning if the append fails; never
  encourage a duplicate mutation by labeling an already-saved change as failed.


## November 18, 2026 — Confirmed live mix changes

- Runtime mixing must be separate from immutable encoder/profile settings. Keep the
  existing GainNodes, borrowed tracks, capture ID, PCM credit flow and timestamps;
  smooth gains over 10 ms and confirm only after the owned renderer schedules them.
- Bind requests to output ID/revision plus internal navigation context and fresh
  attempt nonce. Reject old output controls before applying and ignore late ACKs.
  Cache bounded request receipts; identical replay must not apply twice.
- A lost ACK does not prove unchanged DSP. Preserve last confirmed routing plus an
  explicit uncertain pending payload. Retry that exact request before accepting a
  different change, including after Settings reload. Failure never stops encoding.
- Source capture cancels pending ACK on Stop/navigation; the broker keeps a
  confirmed prepared mix across Stop, but requires reconciliation of uncertain
  state before another Start. Prepare creates a new session after restoring the
  saved map; stale apply/audit completion cannot mutate it.
- Expose applying state so concurrent Start is guarded while apply/audit awaits.
  Ignore stale/lower-revision UI polls and preserve invalid drafts/focus.
- Verify the actual encoded files, not only UI values: independent Live/VOD
  amplitude changes, one capture/encoder group, monotonic A/V and unchanged preset.


## November 18, 2026 — Saved account references must not copy streaming credentials

A chat-read login does not authorize a stream-key lookup. Preserve old grants
during an explicit scope upgrade and pin an existing channel, so cancelled/stale
consent cannot replace usable authorization. Resolve the saved destination's opaque
client/channel reference against freshly validated credentials at every Start.
Backend refresh is the only token writer; the native helper reads, validates and
fetches through fixed Twitch endpoints without writing or importing the server.
The stream key crosses only a Main-owned child pipe, never HTTP or renderer IPC.
An account switch must never inherit a different channel's linked destination.

A guardian found that a safe account failure was absent from the native broadcast
reason allowlist; it became a generic start failure and hid reconnect guidance.
The explicit public reason and regression now prove failure before confirmation,
ownership reservation or encoding. Cancel may supersede a delayed Begin; stale
settings navigation cannot complete a link. Persistence retries upsert the same
reference and preserve old manual destination fingerprints. Local forget must
remain available even when history fails, with an independent warning if chat
shutdown could not be confirmed. Local forget is not provider-side revocation.

Packaged acceptance also caught a producer history allowlist that had not been
extended for begin_streaming/check/disconnect. Provider-unit and router-mock
tests passed while the actual logging owner rejected sign-in. The durable guard
exercises the mounted routes with the real Greenroom production-event allowlist
and DB; transient validation failure is not logged as successful merely because
a cached grant is still present, and local disconnect success is classified
truthfully. Native acceptance must run against original handlers, not replacements.

A second edge case appeared when Check connection refreshed a saved grant during
pending consent: its updated expiry invalidated the pending stored-record snapshot.
Owned validation/refresh now advances only the matching same-identity snapshot
under the credential lock; external writes still reject stale approval. Regressions
cover Check, refresh and a later external mutation during pending consent. Web
Manage accounts also preserves the pending scope kind so a streaming upgrade is
never described as read-only chat consent.

Native bundled helpers must set PRODUCER_DESKTOP=1 alongside their installed data
root. A data-root variable alone is deliberately ignored by the path boundary.
A native spawn-contract regression now guards the opt-in flag, cwd and data root;
local development explicitly drops a stale bundled data root.


## November 18, 2026 — Provider login and chat delivery are separate contracts

Kick sign-in was previously reported unavailable solely because chat webhook
hosting was missing. Account status now uses its own credential owner; web and
native controls keep chat delivery separate. A private Kick app secret is not a
public desktop credential: never embed it in customer builds. Main pins provider
endpoint, read scopes, callback, PKCE and state before opening a consent page;
renderers receive only public account metadata and opaque flow IDs.

All provider controls share an aggregated busy set, preventing a completed Twitch
action from unlocking destination edits while a Google/Kick action is pending.
Local disconnect must forget saved authorization even when history fails, stop
its observer separately and warn if shutdown is unconfirmed. Owned checks/refresh
advance matching pending credential snapshots; external writes remain stale.

Adding an account owner also extends lifespan cleanup. The extracted-lifespan test
namespace now supplies Kick and asserts its close is awaited in desktop/web modes.
The full gate initially exposed that missing test dependency; focused provider
tests alone did not exercise the shared shutdown contract.

Final native inspection caught a Kick setup hint using 127.0.0.1 while the registered
callback and authorization boundary require localhost. Setup copy now uses the
exact registered URL, and a regression feeds the visible callback into the native
URL validator so differing loopback spellings cannot silently break consent.


## November 19, 2026 — App configuration is private ingress, not authorization

Setup files must be selected by the native OS picker; never accept a renderer
filename or echo a parsed credential. Recheck the trusted frame after each wait.
The backend uses the provider credential lock and generation, rejects active or
pending authorization replacement, preserves other providers and detects active
environment configuration. Configuration success must not be called a connected
account. History failure after a durable save warns separately from save failure.

The generic Kick /{action} route would swallow configure-app before the setup
router could receive it. Four explicit account action routes now preserve this
extension, guarded by a real mounted-route and Greenroom audit regression. Native
checks exercise original Main import cancellation and reject untrusted imports
before any picker opens. Configured unsigned accounts retain setup-file recovery.

The first full gate hit Windows 10055 while Python created an event-loop socket
pair before a playback test body ran. The affected module then passed 75 checks.
No networking/security settings or unrelated production code were changed; the
owned native fixture was stopped before repeating the full gate. Keep resource
failures distinct from product assertions and retain the failed-run evidence.

## November 19, 2026 — Metadata drafts are not provider updates

Current saved account scopes read account/channel/stream-key information; they
must never be described as permission to edit public stream metadata. Local drafts
have their own bounded store, atomic writes, revision checks and request receipts.
Activity records contain revision/action metadata only, never titles/descriptions.
Save and Start share the existing authoritative mutation guard; unsaved renderer
drafts pause Start without disabling Stop. Exact retry cannot overwrite a newer
saved revision. Storage corruption stays visible and does not reset user data.

Private encoder destination records omit public destination UUIDs. Native Start
review therefore receives a separate ordered destination-ID list, instead of
matching names or assuming private records carry IDs. A regression uses multiple
IDs with matching destination records to guard correct stream-info association.

## November 19, 2026 — Provider metadata requires binding and reconciliation

Local drafts are inputs, never proof that a platform changed. Main resolves saved
values/revisions and destination IDs; renderers cannot supply arbitrary provider
payloads. A manually saved stream key does not prove its channel, so Apply shows
the connected channel and requires an explicit confirmation. Credential owners
hold their lock through provider operations and issue generation/token guards.

Guardian review caught two YouTube failures before activation. Selected broadcast
inspection omits the list, so rebuilding options from an absent collection erased
the selected event and disabled Apply. Preserve the confirmed ID/options and
regression-test selection through inspection to Apply. Replacing a full snippet
without a fresh ETag can overwrite an unrelated concurrent edit: reject writes
without a valid ETag and always use If-Match; read-only inspection can still work.

Never blindly repeat a timed-out metadata mutation. Reserve a fingerprinted
receipt before writing and reconcile exact retries by reading. Failed readback
remains unconfirmed. Persist a user-only fingerprint/state reservation before
writing; restored requests reconcile by reads across backend restarts, and an
invalid recovery file blocks new writes. Confirmed readback remains successful if
final recovery-state persistence fails, with a separate warning. History contains platform/outcome only.
The real Greenroom audit owner must accept begin_metadata and platform.metadata.apply.

Windows can report a child receipt as missing when its parent is a regular file.
Validate the parent directory before treating a missing recovery file as an empty
store; that failure must block Apply before credential access or HTTP mutations.

Real read-only acceptance caught an empty offline Kick channel returning exact
integer category 0 with an empty name, plus null custom_tags. Normalize only those
empty sentinels; malformed alternatives still fail closed. Credential-hook failures
must retain safe provider/setup/storage reasons so a transient check failure does
not incorrectly tell a user to replace a saved login. Keep actual provider shapes
in synthetic regressions without recording identity, text or credential payloads.

When a fixture substitutes HTTP/account owners, every newly added persistent
collaborator must also use the fixture root. Native acceptance now asserts its
recovery store is isolated and contains no provider metadata or credentials.

## November 19, 2026 — Rehearsal isolation and public audio monitoring

A UI flag cannot make a production test safe. Persist the entering latch before
awaiting idle checks, reserve publishing work through awaits, and enforce policy
at recording/OBS/replay services and the final native encoding reservation.
Recheck queued automation at execution. Stops retain their original owner and
generation and remain possible even after room state changes or becomes corrupt.
A crash/tampered store stays blocked; explicit recovery preserves evidence and
writes a sibling recovery-intent marker before moving an invalid main file.

Never implement bus monitoring by unmuting the source output window: original
media elements can then play outside their Live/VOD exclusions and double audio.
Keep it muted and send only the selected post-mix public PCM bus to an isolated
local playback renderer. Bound queues/credits, bind acknowledgements to the exact
owned frame/context/nonce, and invalidate pending selection/PCM on Off or Stop.
Private backstage audio must never become a monitoring source.

A one-second badge poll alone cannot protect the first encoded frame. Require a
visible, painted watermark bound to the durable rehearsal generation before
capture, and recheck before the first image. Capture cancellation must interrupt
that wait. Invalid or failed later badge reads retain the warning.

Canonical checks use an isolated runtime outside source. An example configuration
pointing inside the checkout is deliberately rejected by the room store's source
containment guard; configure QA storage explicitly rather than weakening it or
copying the production configuration. Component styles belong before the fixed
operator override chain to preserve its tested cascade ownership.

Guardian review found and fixed missing native HTTP Origin, stale monitor room
selection and an exit/local-claim race. Native commands now carry the exact local
Origin. Non-Off monitoring checks a fresh generation/revision; Off bypasses setup
mutations. The backend holds an atomic local encoding lease and rejects new claims
while an exit/recovery receipt is pending, including after interrupted restart.
Regression checks cover each boundary. Invalid configured storage keeps the
operator dashboard readable while publishing and unsafe recovery stay blocked.

A silent native probe found AudioWorklet unavailable on an opaque data document.
The playback renderer now loads a nonce-bound fixed document from an ephemeral
loopback listener with strict navigation/device/CSP restrictions. Exact-zero PCM
initialized, was consumed and acknowledged, then Stop removed the renderer and
listener. This proves the playback path without claiming a listening test.

## November 19, 2026 — Saved provider destinations and Kick ingest shape

One backend owns token refresh. Main checks the pinned provider/account before a
read-only child helper opens the encrypted authorization; the helper validates the
provider and rereads the stored record after network waits. Kick destinations save
only an encrypted opaque reference, never cached ingest URLs/keys. Provider identity
is part of deduplication and resolution so a hash cannot cross account families.

Real Kick retrieval exposed a valid origin-only RTMPS URL. Requiring an application
path rejected it despite valid authorization. Accept that secure form unchanged
and retain the separate provider key verbatim; do not invent /app or silently
upgrade an RTMP URL. Keep actual shape coverage synthetic without retaining a real
host, channel, key or response. Unsupported secure ingest fails before confirmation,
encoder reservation or media transport and retains an actionable safe reason.

A request conflict or retired destination receipt is definitive, unlike an unknown
response. Keeping that receipt forever traps Save in an unrecoverable retry after
a derived display name changes or the earlier destination was removed. Twitch and
Kick controllers now retire only those definitive receipts, require an operator
connection check, and use a fresh receipt on the next explicit Save. Ambiguous
failures retain their exact request. Provider/reference deduplication prevents a
second destination. Account-row navigation must open the matching provider card.

Windows Python file reads and writes must both specify UTF-8. A default-codepage
read followed by a UTF-8 write can silently transcode an otherwise valid existing
document. Rebuild the intended edit from the UTF-8 Git source, inspect its diff,
and guard the desktop setup guide against replacement/mojibake punctuation.

## November 19, 2026 — One-source-tree builds and lossless profile adoption

Bundled UI copied from the working directory can diverge from a backend captured
from the index. Pin one tree for UI, brand assets, backend, workers and recursive
requirements/constraints; receipt hashes must agree. Git archive may apply local
export attributes or CRLF conversion, so read raw Git blobs rather than relying
on an archive as byte-identical source. Keep developer quick builds separate.

A relocated runtime needs more than storage_config.json. Route session/history,
scene and OBS defaults through desktop_config_path. Route private catalog tables
and all default relative reference-image bases through the same profile root,
while preserving explicit custom roots/absolute references. Source-based unit
checks must actually execute persistence against resource decoys.

Durable card preferences and learned transition scopes are not transient scan
continuity. A safe adoption preserves those files, bounded reference libraries
and the exact catalog-reference closure; fixed corpus JSON alone omits thousands
of images. Stream large images, pin directory/corpus inventories and every hash,
rebase only reviewed known references, and keep all original files. Passive .txt
library notes are data and must remain bytes, never instructions.

Back up every old target before any replacement. Recheck fixed JSON target hashes
after temporary-file preparation, immediately before replace, as well as streaming
image targets. Guard lock files before permissions/sentinel writes: regular-file
identity alone does not reject hard links. Reject links/reparse points, multiple
links and changed opened/current identities; apply Windows ACLs through the
verified handle. Partial journal replay must retain the reviewed source/scope and
reject newly changed source or target inventories. These classes have synthetic
regressions, including changes during fsync and foreign lock descriptors.

A clean committed tree can omit active uncommitted owner frontend work. Preserve
that source in an explicitly inventoried, hashed private overlay tree, run its
checks, and package both layers from that same immutable tree. Do not commit
owner experiments, move the active checkout or copy runtime/credentials into a
source snapshot to make a release appear clean.

## November 19, 2026 — Embedded worker companion bootstrap

Actual bundled Main/Rehearsal acceptance caught an encoder startup failure before
any frame or audio: embedded Python's isolated search path omitted the immutable
resources directory containing encoder_worker, which shared_encoder_worker imports.
Developer Python implicitly found the script directory, so source tests missed it.
The package now explicitly includes only that installed directory; CWD and Python
environment overrides remain ignored. A focused synthetic archive/path regression
keeps an untrusted CWD companion out. Bundled acceptance captures authoritative
Start/failure state before cleanup; actual rebuilt acceptance remains separate.

## November 19, 2026 — One idle guard for every shutdown route

The desktop stop route guarded production, but the older system/shutdown route
used by the CLI could skip those checks. Both now share one asynchronous idle
check and atomic admission seal, including legacy web mode. Refused shutdown
returns ok:false so CLI control does not mistake a blocker for acknowledgement.
Recheck closing after the OBS wait; concurrent requests schedule only one stop.

An explicitly disabled OBS integration is outside standalone encoder ownership.
It permits idle shutdown only when its output flags are explicitly false. Enabled
but disconnected, missing or contradictory OBS state still blocks. Preserve local
client, mutation, native encoder, session and recording guards in every case.
Actual ASGI regressions cover races, failed scheduling and both entry routes.

## November 19, 2026 — Account-linked encoder boundaries and reviewed YouTube settings

Private saved-account resolution adds account references and selection metadata.
Passing that entire object into the strict encoder configuration rejects valid
linked Twitch/Kick destinations. Project only the encoder's approved transport
fields at its boundary; retain account/binding details for native confirmation
and revalidation, never renderer status or the encoder wire contract.

A YouTube account is not a stream selection. Pin the owned broadcast, dedicated
owned stream, visibility and explicit auto-start/stop settings in one fingerprint.
Read secure provider ingestion privately, recheck the vault after network waits,
and resolve/compare again after native confirmation before reserving encoding.
Never invent a secure scheme, silently create/bind a broadcast, or treat sending
media as verified platform receipt. Mutable display titles must not invalidate an
otherwise exact durable link receipt after a lost successful response.

A failed re-review invalidates the prior review before awaiting its result.
Definitive pre-save authorization, binding, visibility and ingest failures retire
the review/request and permit a fresh list. Ambiguous persistence/transport replies
retain the exact request and block choosing another broadcast until resolved.
Keep account-replacement, close, duplicate-click, own-busy lock and draft guards
covered across the pure controller and complete Settings page.

When linking a YouTube destination, propagate its public broadcast ID through the
local draft context. Lock the metadata picker to that broadcast, and validate it
again in Main before confirmation and before Apply; a channel identity alone does
not ensure the selected broadcast matches the intended streaming destination.

Official schema checks require broadcastType=all during the owned inventory so
persistent broadcasts cannot hide a shared stream. Use mine as the sole exclusive
filter, reject created streams without valid CDN settings, and keep ID bounds
consistent at 128 across backend, private/native and metadata contracts.
Canonical staged whitespace caught duplicate carriage returns after a Windows
text rewrite; normalize owned source bytes once and retain UTF-8 on both sides.
Bundled smoke probes now import both encoder companions and all account helpers
so omitted immutable search paths fail before an interactive acceptance run.

## November 19, 2026 — Verify provider metadata through the actual Main bridge

A full Settings fixture supplied safe YouTube streaming fields directly, but the
actual provider bridge still projected those fields for Kick only. Packaged Main
therefore showed a saved account while leaving YouTube selection disabled. Extend
the shared public projection to both providers, retain secret-field filtering and
unauthorized-state guards, and cover the original status/check bridge. Browser
fixtures must not replace the native boundary when claiming native acceptance.

Final native YouTube acceptance also distinguished a fixture-only control error:
its simulator's private mode endpoint was missing from that fixture's allowlist.
Allow only the exact owned test-control path, retain GET-only provider transport,
keep both failures, and rerun the original Main/Settings path. Do not weaken a
production trust boundary or treat simulated provider replies as real consent.


## November 19, 2026 — Independent native consumers and screen evidence

One physical output has one singleton IPC producer. Broadcast and recorder use
independent bounded consumer queues with per-lease Stop; normalize each new
consumer against its first paired audio timestamp. A slow recording must not
stall broadcasting. Close retires idle leases and must reject before mutation
when another consumer still runs. Aggregate backend ownership serializes purpose
claims and retains uncertain holds until an exact owner/active acknowledgement.

Repeated Stop after successful recording must preserve finalization and Reveal.
Recheck the pinned Program generation, peer, readiness and profile after encoder
startup before attaching capture. Closing the initiating panel after commitment
must not invalidate the recording's media callbacks. Cover late-start cancellation,
uncertain Stop, existing-file refusal and disk pressure without weakening guards.

UI Start uses authoritative availability, not only canStart. An ambiguous Start
keeps its exact request across read-only polls and retains Stop from last-known
idle. Missing/malformed status cannot confirm success. Keep native paths out of
renderer state and render only validated counters and basename text.

Screen QA must match the taken generation AND Program source IDs and visible
pixels: the old output can render while a newly shared source is merely preloaded.
Shared dock specificity can shrink capture controls; scope the visual owner and
verify actual 44px controls at narrow/1080p/4K in both themes.

Narrow scene header buttons need content-driven height in their existing visual
owner: wrapping a label into a fixed height clips it. Preserve 44px targets,
remove max-height clamps and verify the populated Live left dock, including the
1600x1000 trigger; a full-width scene-only view does not exercise that failure.
Private immutable source overlays must honor Git text normalization. Keep owner
working bytes intact, normalize only frozen text and retain raw source in the
private backup. An unfiltered CRLF blob otherwise fails staged whitespace checks.


## November 19, 2026 — Composition identity and bounded replay

Source membership alone cannot prove a transformed scene has rendered. Keep a
separate Preview revision and deterministic composition IDs; Preview-only edits
must not change Program generation. Both Take and its UI need a fresh matching
composition receipt containing every selected source from one complete output.
Do not combine old geometry, stale receipts or split outputs. Native capture must
match Program composition identity whenever custom geometry is active.

Hidden pictures retain existing audio routing and selected-source readiness;
locking prevents edits, not video updates. Scene save/recall roundtrips both bus
maps/layouts. Load custom scenes into Preview explicitly before Take; do not return
staged success to a rundown operation expecting a Program change. Save Preview as
scene pins its reviewed ID and opens a form without saving or changing Program.

Replay stores encoded packets with bounded time, bytes and count. Retain a
decodable keyframe plus aligned audio, rebase from one shared origin, and bound a
single asynchronous save snapshot separately. Disk/overwrite failures affect Save,
not other output consumers. Start retains no media files; every export uses native
private path inspection and exclusive creation. Stop waits for save cleanup and
releases only its own capture lease/aggregate reservation. Keep Start/Save retries
idempotent and Settings closure separate from committed work.


Quantize pointer geometry to the same six decimal places as backend normalization
before comparing Apply results. Otherwise successful fractional drags look like
conflicts. Preserve a regression using real pointer events and Apply/Take pixels.
Source-ready alone cannot enable transformed Take: expose readiness for the exact
composition from a single complete output, including visually hidden selections.

Element screenshot dimensions and interaction measurements are not visual proof
that the captured region contains the editor. The initial element captures showed
the top of Studio instead. Verify actual viewport pixels after scrolling to the
controls, canvas and actions; keep failed captures as labeled evidence.

Legacy portrait CSS hid the whole desktop command bar. Scope the correction to
the native standalone workspace and resize the real packaged window in both
themes; do not inject a test-only stylesheet or change ordinary mobile behavior.

Always specify UTF-8 for source reads and writes on Windows. A default-codepage
helper corrupted menu bullets and dialog ellipses. Restore the intended Unicode
and retain the native menu/confirmation label regression test.


## November 19, 2026 — Replay import and group interaction guards

Keep replay paths private to Main and pin the trusted Settings frame through the
confirmation, conversion, upload and Preview response. Open/read a bounded reviewed
file, retain the original MKV, write only to a unique private conversion directory
and upload a compatible copy with stable idempotency. A saved receipt identity
must distinguish two different clips with the same path/size. Preview CAS failure
keeps the imported library item but must never report a successful Take.

Groups are flat membership metadata with atomic member transforms. Preserve
keyboard focus when repainting a polled draft; replacing the focused outline
without restoring focus sends the next arrow key to the page instead. A locked
member or out-of-bounds result rejects the entire group edit. Default rotation
and empty membership must not churn legacy composition hashes.

Chat send destinations must be independent from transcript filters. All ready
chats resolves the exact displayed ready set rather than requiring an unconfigured
third platform or silently targeting blocked accounts. Persist each target's
pending claim before any provider write; merge results with transactional CAS.
Treat timeout, malformed success and restart-pending as uncertain, never eligible
for automatic retry. Retry only known unsent/retryable failures of the same payload
and binding. Recheck the private account and connected chat under the credential
owner lock. Status reads must not connect, refresh grants or post.

An additional packaged Rehearsal check under concurrent QA stopped its capture,
worker and ownership but retained rehearsal_monitor_unconfirmed after an Off
acknowledgement was cancelled or not accepted. The unchanged isolated rerun passed
on the same build; that does not prove a fixture-only cause or a fixed race. Keep
the strict acknowledgement guard, the failed evidence and the passing rerun.
Follow up with original rejection/nonce timing before claiming stress endurance.

Component-only chat measurements missed its placement below a tall preflight.
Opening the chat scrolled away the camera switcher and left a blank center.
Full-Studio QA must keep the production picture and chat header visible together
when opening sidebar chat; retain saved side/height preferences and narrow flow.

A receipt-storage error can occur after a provider accepted a message. UI wording
must not promise that nothing was sent merely because the response/receipt write
failed. Preserve uncertainty and tell the operator to check each destination
before starting a new request; durable pending receipts still prevent automatic
reposts. Keep a frontend regression for that message.
