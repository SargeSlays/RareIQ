# RareIQ Release Checklist

## November 18, 2026 — Windows CI fixture portability

Authenticated logs from failed run `44291995253` identify 13 fixture-allocation
failures on an absent developer F: drive and two encoder-suite cancellations on
Node 22. The test repair uses OS temporary storage with owned cleanup, adds a
guard exercised against the original failing fixtures, and keeps a bounded test
handle alive while checking the actual encoder timeout behavior. Nested test
runners must prove both suites executed rather than accept a recursive-skip exit.

Canonical local gate passed: **3533 Python tests and 622 JavaScript tests**, using
a clean clone, Python 3.13.12 and the failed runner's exact Node 22.23.4.
Baseline encoder tests reproduce five passes/two cancellations;
the repaired focused suite passes all seven. The portability guard rejects the
original fixtures and passes the corrected suites, including cleanup checks.
The full canonical gate and the GitHub Actions run on the exact pushed commit
must both pass before reporting CI restored; a local pass alone is insufficient.

Evidence is retained under `F:/Temp/jonat/RareIQ-ci-evidence-20261118`, including
authenticated logs, baseline reproductions and `release-gate-node22-final.log`.
No application behavior or workflow configuration changed. Existing studios and
unrelated checkout changes were preserved; no hardware, real transmission,
recording, deployment or platform receipt was exercised by this repair.

## November 15, 2026 - Smart layouts and Advanced controls

Canonical gate passed: **3376 Python tests and 513 JavaScript tests**.

The idle running studio was restarted to load this build. Automatic approval
review rejected the final combined browser-regression/live-page command without
a specific reason; that final running-page inspection remains incomplete.
The isolated browser-acceptance results above passed before that rejection.

Focused backend and JavaScript checks pass; canonical results are recorded in
F:/Temp/jonat/ProducerPlease-layouts-20261115/release-gate-final.log.

The isolated Edge rehearsal selected Solo/Interview/Panel from synthetic cameras,
Presentation from a selected generated graphic, and PiP from two generated images.
Every preset and lead change kept Program generation unchanged until explicit Take.
Advanced starts collapsed; Take/Clear remain visible. Real decoded PiP output and
portrait 16:9 thumbnail proportions passed geometry checks. Both skins at
390/960/1920/3840 passed layout overflow and visual checks. Evidence is under
browser-acceptance/results.json, pip-program.png, pip-portrait.png,
focus-portrait-with-title.png and layout captures. The mixed title/focus regression
checks both portrait pictures retain full width despite the trailing text overlay.

No physical capture, real stream/recording, paid action, account or network change
was used. The backend tests also exercised PiP saved-scene persistence and Take.
The Advanced section exposes the implemented controls; it is not a free-position
layer/crop editor. Remote-login, OBS/widget acceptance and subjective audio remain
pending and are not implied by these fixture results.

## November 15, 2026 - Browser picker/Take checkpoint

Canonical gate passed: **3371 Python tests and 508 JavaScript tests**.

Focused Python source/greenroom checks and JavaScript picker/compositor checks pass.
Canonical results are recorded in release-gate-final.log under
F:/Temp/jonat/ProducerPlease-browser-take-20261115.

Intercepted Edge fixture browsers exercised the real picker/form, persistence,
Preview with no Program change, no-output Take rejection, two-output independent
reviews and Take rejection until both complete. Real iframe document nonces survived
Take and cut/fade/slide/zoom. Reloading one output revoked review and blocked Take.
An active-show preflight in browser-final kept review closed; approved review closed back to clean
output. Eight dark/light 390/960/1920/3840 picker layouts passed overflow and visual
checks. Evidence: browser-acceptance/results.json, browser-program.png, review-output.png
and picker captures. All external widget requests were locally intercepted.

No physical capture, real stream/recording or account/network change was used.
Review mode's idle-status responses were intercepted in the isolated fixture; the
running studio is checked separately. This does not verify arbitrary external sites,
OBS Browser Source interaction, platform receipt or the second-PC listening test.

## November 15, 2026 - Isolated browser adapter checks

Canonical gate passed: **3346 Python tests and 505 JavaScript tests**.

Four focused JavaScript regression tests passed. Intercepted Edge browser checks
passed opaque-origin parent isolation, denied camera/microphone/geolocation/
autoplay/display-capture/fullscreen permissions, omitted referrer, per-load visual
review, stale review rejection, cleanup and local/Studio address rejection before
navigation. An X-Frame-Options DENY fixture still fired load; the adapter correctly
remained unverified and emitted no ready status.

Evidence: F:/Temp/jonat/ProducerPlease-browser-adapter-20261115/results.json and
release-gate-final.log. The browser fixture intercepted every request; no external
network, physical capture, production connection, restart or account change was
used. This adapter is not linked into product pages or selectable in production.
The reachability gate caught an unlinked prototype in served static assets; it was
moved to tools/experiments instead of weakening the guard.
Browser-source persistence, producer/output controls and Take integration remain
unimplemented. No remote-login or physical-audio claim changes in this checkpoint.

## November 15, 2026 - Video/text source acceptance

Canonical gate passed: **3346 Python tests and 501 JavaScript tests**.

Local Edge rehearsal imported generated VP8/Opus WebM through the real picker,
created a lower-third title through the form, verified no Program mutation on save,
blocked Take without output readiness, then exercised silent Preview, output video
playback, text overlay, held end frame, replay from zero and retired-media cleanup.
Cut/fade/slide/zoom, persistent catalog reload and malformed-video Take rejection
passed. Dark/light source controls passed 390/960/1920/3840 overflow checks and
visual inspection. A bounded read-only review found the multiline clipping case;
eight-line guards and focused regressions address it.

Evidence: F:/Temp/jonat/ProducerPlease-media-20261115/browser-final/results.json,
video-text-program.png and eight layout captures; release-gate-final.log contains
the canonical gate result. The idle 8765 studio was restarted and its Add video /
Add text controls checked in a browser. Temporary guest ingress remains off.

No physical capture, real streaming, recording or remote-hosting change occurred.
WebM decoding was exercised; MP4 signature validation is covered by tests, but
an MP4 codec matrix was not exercised. Speaker/headphone perception and second-PC
echo remain untested. Browser URL sources and remote producer login remain pending.

## November 15, 2026 - Guest room gallery, moderation and images

Canonical gate passed: **3330 Python tests and 495 JavaScript tests**. Coverage
includes guest-view authentication, private-ingress boundaries, safe roster fields,
camera-only admission permissions, viewer/publisher cleanup independence, wait
retry semantics and delayed-close concurrent reconnect reservation. Terminal
removal cleanup covers active tracks, late permissions and unverified reconnects.
A camera-readiness fixture now supplies the newly required asset catalog stub;
production guards remain unchanged in that correction.

Real Edge browsers with generated cameras verified two admitted guests seeing each
other, waiting privacy, camera-only gallery streams without duplicate audio, chat,
producer source selection and Program rendering, independent viewing reconnect,
return-to-waiting clearing both buses, readmission staying off Program, confirmed
removal stopping capture, and a fresh reinvitation returning to waiting. Gallery
layouts passed dark/light at 390/960/1920/3840. The image picker exercised real local
imports, Preview without Program change, Take blocked before output readiness,
decoded same-output receipts, image-only and mixed-camera shots, all four existing
transitions, persistent reload and corrupt-image blocking. Source-library layouts
passed 960/1920/3840 dark/light checks.

Generated-audio regression also passed voice effects, sound pads/clips, gate routing,
keyboard/failure feedback and cleanup. Real local WebRTC mixed-media regression
passed mic/screen Program mute independence, unchanged backstage return, deduplicated
mix restoration, waiting exclusion and removal cleanup. No new hardware, speech,
acoustic echo, internet, OBS or platform test was performed.

Idle local studio restarted through the supported controller. Live browser verified
new image controls; current guest assets and image catalog API are served. Private
guest ingress remained off and the isolated test fixture was stopped. Evidence:
F:/Temp/jonat/ProducerPlease-room-20261115 (room-results.json, gallery/producer
screenshots, images/results.json, audio-regression, media-regression,
live-source-controls.jpg, release-gate-final.log). Physical acceptance remains in
GUEST_PRODUCTION.md; personal remote producer sign-in still requires StackThis.

## November 15, 2026 - Shared/private waiting-room chat

Canonical gate passed: **3311 Python tests and 477 JavaScript tests**. New service,
route, ingress and client tests cover recipient isolation, authorization after
removal/revocation/expiry, stale-room sends, concurrent duplicate retries, bounded
history/rates, text-only rendering, separate drafts and stale asynchronous reads.
The existing stylesheet-order guards now include the shared chat stylesheet;
those guards also passed against the staged checkpoint without unrelated edits.

Two real Edge guest browsers and the actual producer screen exercised shared
chat, separate private threads/replies, names/timestamps, keyboard send, literal
HTML-like text, uncertain delivery retry (one stored message), revocation clearing,
new-room isolation and unchanged Program generation/room revision. No device
capture was called. Dark/light guest layouts passed at 390/960/1920/3840 widths;
producer chat passed at 960/1920/3840. One unrelated control-page read rejected by
the isolated fixture was accounted for; no unexpected browser errors remained.

The idle local studio was restarted through its normal controller. The running
guest page and chat API serve this checkpoint; a live browser confirmed private
conversation guidance and invitation-required controls. No connected guests,
streams or recordings were present. The isolated fixture was stopped and private
guest ingress remains off. Physical second-PC listening/echo remains deferred.
Evidence: F:/Temp/jonat/ProducerPlease-guest-chat-20261115 (results.json, screenshots,
live-guest-chat.jpg, release-gate-final.log). No public-network verification claimed.

## November 15, 2026 - Visible guest progress states

Canonical gate: **3240 Python tests and 468 JavaScript tests passed**. Capture,
join and retry controls explain pending work with visible labels and accessible
busy state. Active capture-off remains available; completion, cancellation and
failure restore controls without erasing current errors. Generated-media browser
checks passed held camera permission, held joining, cancellation, reconnect and
revocation. Pending controls also fit at phone width; existing dark/light layouts
and failure guidance passed. Evidence: F:/Temp/jonat/ProducerPlease-guest-progress-20261115;
gate log: F:/Temp/jonat/ProducerPlease-guest-progress-gate.log. The local guest page
serves the new script. No physical device or second-PC testing was performed.

## November 15, 2026 - Guest capture cancellation and truthful status

Canonical gate: **3240 Python tests and 457 JavaScript tests passed**. Added
regressions cover active capture-off during pending permission, replacement,
enumeration and microphone setup; late cancelled streams cannot reopen or publish.
Unexpected track endings show recovery guidance and retire only their current owner.

Real Chromium checks with generated tracks and controlled permission delays passed
mic-off while camera permission waited, cancellation of microphone replacement,
private screen preview, screen-ended feedback, slow join, explicit reconnect and
revocation. Audio effect, gate, cue, clip and cleanup checks passed again. Eight
dark/light phone-to-4K layouts fit without horizontal overflow; feedback was
visually reviewed at phone and narrow desktop sizes. Paused delivery is explicitly
unconfirmed, not a promise of private capture.

The local server was found stopped, started through its supported controller and
the running guest page loaded the new script. The isolated test fixture was stopped;
private guest ingress remained closed. Evidence and gate log:
F:/Temp/jonat/ProducerPlease-guest-devices-20261115. No physical device, second-PC,
acoustic echo, live stream or recording test was performed. Owner-attended checks
remain deferred in GUEST_PRODUCTION.md.

## November 15, 2026 - Guest flow, accessibility and retry polish

Canonical gate: **3240 Python tests and 443 JavaScript tests passed**. Guest
layout, sound-pad/clip keyboard focus, readable slider units, independent error
feedback and blank audio-file type handling have focused regressions. Capture-off
remains available during slow joining/retry; stale connection callbacks cannot
restore old audio or overwrite a newer capture operation.

Real local browser checks used generated media and injected permission/transport
failures. They passed missing-invite gating, mic-off during a held handshake,
persistent permission feedback across room updates, same-session explicit retry,
and server revocation denial both immediately and after reload/rejoin. Remove,
revoke and room-close use terminal access-ended signaling; voluntary Leave stays
distinct. No new authority or invitation is created by retry.

Generated audio peers again passed voice styles, cues after a closed gate, clip
play/removal, zero sound volume, stable outgoing tracks and cleanup. Built-in and
local sound controls preserve keyboard focus; file errors survive playback updates.
Program mute, conversation mix-minus and removal regressions passed. Dark/light
390/960/1920/3840 layouts have no horizontal overflow and were visually reviewed.

The idle local studio was refreshed; private guest ingress stayed closed. Test
fixtures were stopped. Evidence: F:/Temp/jonat/ProducerPlease-guest-polish-20261115,
including release-gate-final.log, audio/layout results and recovery/transport runs.
No physical devices, second-PC session, public stream or recording were exercised
in this polish phase. Presence-dependent checks remain in GUEST_PRODUCTION.md.

## November 15, 2026 - Guest audio controls and bounded recipient recovery

Canonical gate: **3237 Python tests and 422 JavaScript tests passed**. Added guards
cover microphone owner lifecycle, quiet gating, shared voice DSP, bounded private
file decoding, stable output tracks, four-player sound limits, cancellation,
per-peer recovery, ICE ordering and stale playback callbacks.

Real Chromium peer connections using generated audio exercised all five voice
styles, four cues after a closed gate, zero-volume mute, a local WAV clip, clip
removal, stable media identity and microphone-off cleanup. Existing multi-browser
checks passed independent Program mutes, unchanged video/capture, conversation
mix-minus and guest removal. Eight dark/light layouts (390/960/1920/3840) have no
horizontal overflow; inspected controls grow naturally without nested scrolling.
The running local studio was restarted idle and refreshed with the new controls.

The second-PC physical MX Brio microphone ran the gate at -45 dB and reached
mic-only Preview readiness in the latest bounded check. This does not establish
speech quality or acoustic echo performance. The owner explicitly deferred all
presence-dependent checks; the pending checklist is in GUEST_PRODUCTION.md.
Earlier disconnects remain incompletely attributed; reproduced transport faults
were fixed independently. No public stream, recording or platform delivery tested.

Remote capture stopped, test invitation revoked, temporary private HTTPS removed,
prior mappings restored exactly and guest-only port closed. Generated test evidence
and gate logs: F:/Temp/jonat/ProducerPlease-guest-effects-20261115. Private runtime
configuration and invitation material remain untracked. Shared account sign-in,
mobile hardware and sustained internet transport remain separate acceptance steps.

## November 15, 2026 - Two-PC physical-camera rehearsal and sound recovery

Canonical gate passed: **3225 Python tests and 385 JavaScript tests**. Focused
regressions reject bare, stale, blocked, pending, wrong-generation and other-output
playback receipts; preserve sound recovery across iframe load ordering; and
re-send playback health before confirmation when signaling catches up.

An individually invited second Windows PC joined over temporary private HTTPS.
Waiting/admission, camera and tab-screen Preview/Program, combined Grid composition,
Fade/Cut, independent microphone and screen-audio mute notices, removal and invite
revocation were exercised. A physical MX Brio supplied a real picture to Program;
received video advanced with 960x540 decoded frames during the bounded check.
Microphone and screen-audio tracks were present in the earlier rehearsal; spoken
quality and mix-minus were not listened to. No public stream or recording started.

The receiving browser exposed an autoplay rejection. Enable output sound cleared
it and produced matching Program confirmation. A bounded read-only review found
two confirmation/load ordering gaps; both now have fixes and passing regressions.
Activity distinguishes producer requests from renderer confirmation and marks
invitation/local identities unverified. Personal accountability needs StackThis.

All three guests were removed, invitations revoked, and remote capture stopped.
The temporary HTTPS mapping was removed and prior network configuration matched
exactly. The idle studio restarted with the final backend and was refreshed;
it is local-only and its guest listener is closed. Redacted results and gate logs
are under `F:/Temp/jonat/ProducerPlease-two-pc-20261115`. Runtime configuration,
invitation secrets and private camera images are not committed.

Automatic rejoin after a server restart did not recover within the bounded test;
a new invitation restored access. Mobile capture, sustained internet transport,
spoken-audio/mix-minus quality, OBS encoding and platform delivery still need
acceptance. Private Tailscale testing does not establish public hosting readiness
or require future guests to install a desktop client.

## November 15, 2026 — Local guest Program audio acceptance

Canonical gate passed: **3211 Python tests and 379 JavaScript tests**. Added
backend checks cover schema defaults/migration, strict Boolean flags, producer
permission, waiting guests, conflict/retry receipts, persistence and activity.
Producer UI acceptance passes 20 interactions across eight dark/light viewport
combinations; guest notices pass eight additional layouts with real signaling and
zero device capture. Integrated studio acceptance also passes all eight baselines,
with zero page errors, horizontal overflow or nested tool scrollbars.

Real Chromium peer connections with generated audio/video confirm independent
Program microphone and screen-audio mute/unmute, preserved video and capture,
unchanged backstage audio and host mix-minus. No physical media or broadcast was
used by these tests. Mute history records producer settings; it does not claim a
separate renderer-confirmed audio receipt. A bounded read-only review found no
concrete defect in this slice.

The actual local studio was checked idle, restarted and refreshed. Its green room
connects and displays the new local invitation guidance. Cameras remain unavailable
and OBS is disconnected. Evidence and the canonical log are under
`F:\Temp\jonat\ProducerPlease-guest-audio-20261115`. Public hosting, real-device
capture, platform receipt and verified producer identity are not claimed.

## November 15, 2026 — Audience connection follow-up acceptance

Canonical gate: **3181 Python tests passed**; the updated complete JavaScript
suite passes **362 tests**. Provider traffic remains simulated. YouTube tests
cover ownership/scope, a single active chat, history suppression, pagination,
quota/retry handling and bounded cleanup. Kick tests use real RSA signatures with
generated fixture keys and cover raw-body tampering, replay, expiry, source/app/
subscription binding, rejected intake and key-refresh failure. Throwing/stalled
client cleanup is exercised across all three audience adapters.

Full-app read-only tests prove status does not load credentials, local commands
require the same origin, and the Kick event route is absent from both main app
and guest allowlist. No provider account, subscription or public host was activated.
The guest production evidence below remains applicable. Follow/subscription
events, public guest hosting, physical devices and verified producer login still
require their separate acceptance steps.

The restarted actual studio reports all three audience connections disconnected,
alerts paused and zero browser errors. A desktop readiness-notice overlap was
reproduced on the actual app and fixed with bottom scroll clearance; the final
audience disclosure is now directly reachable. Tall-tool evidence uses viewport
slices with the correct desktop/mobile scroll owner, rather than misleading
full-element captures. Final acceptance logs live under
`F:\Temp\jonat\ProducerPlease-greenroom-20261115`.
The final `ui-final-viewport` run passes all eight dark/light viewport baselines,
including 21 reachable audience controls in each, with no overlap exceptions.

## November 15, 2026 — Guest production acceptance

Verified with isolated generated media: two separate guest browser sessions,
camera + shared-screen grid, camera/mic/screen-audio receipt in a separate Program
window, waiting-guest exclusion, muted Preview, microphone deduplication,
transition generation receipts, remove/leave cleanup, and an explicit producer
microphone. Actual audio spectra verify mix-minus: other speakers are present,
the recipient's own microphone is excluded, and stopping the host removes it.

Full running studio and guest UI: dark/light at 1920x1080, 3840x2160, 960x900 and
390x844; no horizontal overflow or nested dock scrollbars. Expected blocked legacy
fixture reads are recorded separately from page failures. Component tests also
exercise microphone permission cancellation, invitation retries, conflicts,
activity-history failure/retry, and controls that remain off until clicked.

Canonical release gate passed: **3098 Python tests and 358 JavaScript tests**.
The restarted running studio passed a browser smoke check with zero page errors,
working Guests navigation and all new tools mounted. Public ingress is disabled,
voice is stopped, vision is inactive, alerts are paused and no show is active.
Checkpoint evidence and command logs are under `F:\Temp\jonat\ProducerPlease-greenroom-20261115`.
Additional audio and controls evidence is under
`F:\Temp\jonat\RareIQ-greenroom-host-audio-20261115` and
`F:\Temp\jonat\RareIQ-greenroom-controls-activity-20261115`.
Pinned vision inference/UI evidence is under
`F:\Temp\jonat\ProducerPlease-vision-20261115`.

Not exercised: physical devices, mobile-browser capture, public HTTPS/relay,
real StackThis login, real Twitch authorization/events, OBS composite receipt,
stream/recording, or destination delivery. YouTube/Kick/follow/subscription event
adapters and guest-composition replay remain unavailable. Guest session names
are unverified. No hosting, credentials, billing or real output was activated.

## November 15, 2026 - Account boundary and membership foundation

Canonical release gate passed: 2797 Python and 304 JavaScript tests. The focused
account/store/provider suite exercises 158 checks, including real application HTTP routes and
both WebSocket routes using an isolated database and fixture identities. App lifespan,
camera acquisition, streaming, recording and external authentication are not started.

Verified at this layer: viewer/uninvited denial, owner-only role changes, last-owner
protection, atomic membership history, current membership before receipt replay,
principal-scoped receipts, concurrent edit conflicts, legacy history migration,
provider failure, no loopback/cookie shortcut, and retained identity during policy change.
An integrated simulated StackThis response passes through the real adapter, middleware,
membership service, scene route and attributed history. A purchase source never upgrades
a viewer; provider revocation blocks a previously successful request before replay.
Account mode remains disabled and cannot be enabled through environment settings.

The exact deployed StackThis v249 authentication source was retrieved and inspected
with owner-approved temporary access. The local server was found stopped, then started
healthy on loopback; live scene/history reads still show revision zero, zero scenes,
zero events and no individual identity. No test identities or edits entered live storage.

Not verified or enabled: app registration, real login, member-management UI, internet
access, critical live controls or hardware. Provider verification is tested with
simulated responses only and is not connected to the running server.
Existing local studio behavior remains covered by the full gate; this checkpoint
does not add a visible login screen or claim collaborative live production is ready.

## November 15, 2026 - Scene activity and concurrent editing

Focused service/HTTP and browser-model checks pass. An isolated server with production
routes and a separate fixture database demonstrated two browser clients, propagation,
409 conflict rejection, preserved unsaved fields and three authoritative history events.
That fixture disables lifespan/hardware startup; test edits never entered live history.
The populated scene form/activity view was inspected and horizontal overflow guarded
at 1920x1080, 3840x2160 and 960x900 in Ignite and Daylight.

After checking session/recording inactive and OBS closed, the managed local server
restarted successfully. Live scene/history reads returned revision zero, zero scenes
and zero events, with individual identity explicitly unavailable. No stream, recording,
scene take, account login, real LAN client or internet teammate was exercised.

Evidence: F:/Temp/jonat/ProducerPlease-theme-20261115/scene-history-release.log,
scene-browser-results.json, scene-conflict-history.png and scene-editor-*.png.
The final canonical gate result, including the legacy-entry-point dependency guard,
is recorded in scene-history-release.log.
One earlier unrelated reference-prewarm test
failed, then passed in isolation and on the complete rerun; no recognition code changed.

## November 15, 2026 - Content-sized production console

Served-page layout checks pass in Ignite and Daylight at 1920x1080, 3840x2160 and
960x900. Checked full-height docked tools, saved short-height overrides, monitor
aspect ratio, bottom-panel spacing and horizontal overflow. Visual evidence includes
top and lower panels. Existing floating/pop-out ownership was not changed.

Evidence: F:/Temp/jonat/ProducerPlease-theme-20261115 (layout-results.json,
studio-*.png, studio-bottom-*.png and release-check.log). The QA browser blocks API
mutations and device capture/playback, which can produce connection notices.
No stream, recording, OBS playback, remote login or multiplayer session was exercised.
The canonical release gate passed, including 2,639 Python tests; details are recorded
in release-check.log. This evidence applies to the current working build, which also
contains pre-existing uncommitted RareIQ work preserved separately from this checkpoint.

## Single-source OBS handoff - September 8, 2026

Focused source/catalog/bootstrap tests pass. After confirming the show and recording
inactive and OBS closed, the managed app restarted; `/output/studio` returned 200 and
contained Program, graphics and Soundboard layers. No OBS playback, microphone capture,
stream, recording or platform receipt was exercised. Evidence:
`.tmp/refinish/obs-studio-output-release.log`.

## Second studio polish pass - September 8, 2026

Canonical gate passed: **2,604 Python and 268 JavaScript tests**. A targeted
read-only guardian review found no actionable regression in the final changes.

Served Edge checks passed at 1920x1080, 3840x2088, 1366x768 and 720x900 in Ignite,
Afterdark and Daylight. Populated readiness fixtures cover eight rows, including
blockers and recovery text. Lower actions remain reachable by scrolling; narrow
docks have no horizontal overflow. Add a tool opens the existing drawer and returns
keyboard focus on Escape; hiding every tool still collapses its empty region.
Resize, saved tool sets, node continuity, fullscreen and pop-out checks pass.
Evidence: `.tmp/refinish/studio-polish-ui.log`, `.tmp/refinish/session-tools-*.png`
and `.tmp/refinish/studio-polish-release.log`. Production writes were blocked;
no real stream, recording, playback or backend restart was needed.

## Production studio makeover - September 8, 2026

Canonical gate: **2,604 Python and 268 JavaScript tests passed**.

Served Edge checks pass for Ignite, Afterdark and Daylight at 1920x1080,
3840x2088, 1366x768 and 720x900. Source controls remain within the desktop stage;
no horizontal overflow or monitor/transition overlap. Real pointer resizing,
tool-set save/reload, hidden tools, original node/draft continuity, fullscreen,
drawer keyboard focus and pop-out/return passed. Production writes are blocked
in browser QA; no actual stream, recording or playback was started.
Focused regressions cover thumbnail failure/recovery and custom-height migration.
Evidence: `.tmp/refinish/studio-makeover-ui.log`,
`.tmp/refinish/session-tools-{ignite,afterdark,daylight}-*.png` and
`.tmp/refinish/studio-makeover-release.log`. No backend restart is needed for
these cache-busted frontend assets. Physical outputs remain an owner test.


## Sarge wake phrases and cam aliases - September 8, 2026

Canonical gate: **2,604 Python and 263 JavaScript tests passed**. Real installed
Windows recognition of five synthetic phrases covers legacy commands, bare camera,
Sarge/cam and Hey Sarge/camera variants without capture or playback. Service and
HTTP tests cover strict Open flow booleans, required prefixes in both modes,
explicit bare-command opt-in, PTT timing, stop/restart, and rejected commands causing
no production action. Read-only guardian review found no actionable regression.

Served Edge passed all four Automatic/Hold and Open flow combinations, dark/light
1920/3840/1366/720 layouts and a 354px dock. Controls retain their original nodes;
the host must confirm the requested Open flow setting before capture attaches.
After an inactive-state check, managed restart succeeded. Live status exposes
`open_flow:false`, voice stopped; served page carries the new asset version.
Post-restart Edge checks passed with inert voice endpoints and synthetic input.
The running HTTP server also passed five real recognizer/Practice cases from
memory-only synthetic speech: Sarge/cam and Hey Sarge/camera validated, bare and
legacy Producer please rejected by default, bare cam accepted only with Open flow.
Every test session explicitly stopped with Open flow false. No physical capture,
playback or production action occurred. Repeat with `tools/qa_sarge_wake_live.py`
only when the local studio is idle; evidence: `.tmp/refinish/sarge-live-practice.json`.
Artifacts: `.tmp/refinish/sarge-wake-release.log`,
`.tmp/refinish/sarge-post-restart-ui.log`, and
`.tmp/refinish/voice/qa-results-{wake,ptt}-{guarded,open}.json`.

Owner reports the preceding automatic/hotkey implementation worked in fullscreen
PUBG. Retest the new phrase rules with the owner; this checkpoint does not establish
private audio, every speaker/environment, or platform receipt.


## Optional microphone noise gate - September 8, 2026

Canonical gate passed: **2,527 Python and 259 JavaScript tests**. Twelve new tests
cover real DSP bypass/stereo/hysteresis/hold/release and module loading, cancellation,
failure recovery. Served Edge rendered actual AudioWorklet output from offline
synthetic stereo audio: quiet input muted, louder input passed, release reached
silence, disabling restored bypass. Saved controls survived reload. Dark/light
1920/3840/1100 layouts and existing microphone toggle/docking checks passed.
Artifacts: `.tmp/refinish/noise-gate-release.log` and
`.tmp/refinish/noise-gate/results.json`. No physical capture, playback, real stream
or recording was started. Owner microphone tuning remains required; this does not
verify fullscreen PUBG, external audio routing, or Sarge's separate raw input.


## Microphone toggle and fullscreen input checks - September 8, 2026

Final gate: **2,527 Python and 247 JavaScript tests passed**. New regressions cover
one-button cancellation/late permission/start/stop/failure recovery, fresh physical
chords without hotkey messages, and ordering of delayed status versus newer audio
results. Native registration/conflict and complete-utterance gates remain covered.
Read-only guardian found the delayed-result race; the correction is regression-tested.

Served Edge passed microphone toggle/docking and PTT diagnostic counters after the
managed restart, with synthetic media/host responses and actual writes/playback
blocked. First managed launch exited without a startup log; a normal managed retry
restored a healthy server. Voice remains stopped. No production stream or recording
was started. Artifacts: `.tmp/refinish/voice-game-input-final-gate.log`,
`.tmp/refinish/voice-game-ui.log`, `.tmp/refinish/voice-game-toggle.log`, and
`.tmp/refinish/voice-toggle/qa-results.json`.

**PUBG fullscreen remains an owner retest requirement.** Local/native test doubles
do not establish actual background microphone/shortcut delivery or private audio.
Use the counters and result timestamp in [the voice checkpoint](VOICE_CONTROL_CHECKPOINT.md).

## Program output correction - September 8, 2026

Canonical gate: **2,525 Python and 243 JavaScript tests passed**. Nine served Edge
cases passed using synthetic clean-camera WebSocket frames: 1920x1080, 3840x2160,
1366x768, 720x900 and 1080x1920; 34x34 bottom-right logo; contained imagery;
rapid camera switching; outgoing-view release; disconnect/reconnect; page exit.
No real subscriptions, API writes or media starts occur in that regression.
Repeat with `tools/qa_program_output.cjs`; screenshots are in
`.tmp/refinish/program-output/` and the gate log is `.tmp/refinish/program-output-gate.log`.

A separate read-only check of the already-active selected Program camera showed
the actual 1920x1080 clean frame, without the enlarged logo or detection box.
Evidence: `actual-program.json` and `actual-program-1920.png` in that same directory.
No camera settings, Program selection, recording or platform output were changed.
Updated static HTML was checked as served; no backend restart was required.

## Sarge console UI checkpoint - September 8, 2026

Canonical gate: **2,525 Python and 239 JavaScript tests passed**. Served Edge checks
passed Wake and PTT, Ignite/Daylight at 1920x1080, 3840x2160, 1366x768 and 720x900,
plus a 354px dock. Root visual review covered desktop and the light narrow dock.
Original nodes survive docking/return; one Start and one synthetic utterance were
observed per run. Actual API writes and media starts were blocked. Updated HTML,
CSS and JavaScript were served with cache busts; no Python restart was needed.
Evidence: `.tmp/refinish/sarge-ui-gate.log`, `.tmp/refinish/voice/qa-results-wake.json`
and `qa-results-ptt.json`. This does not add hardware/game/private-audio acceptance.

## Native hold-to-talk checkpoint - September 8, 2026

Final gate: 2,524 Python and 238 JavaScript tests passed. Native Ctrl+Alt+V
registration/cleanup passed without key injection or foreground changes. Entire
voiced intervals are gated, conflicts fail closed and native observer failure
revokes listening. The restarted app rejected synthetic audio outside a key hold
in Practice and was stopped. Post-restart PTT browser checks passed.
Physical keyboard/game/microphone/private-audio acceptance remains unverified;
see [voice control](VOICE_CONTROL_CHECKPOINT.md).

## Local wake-command checkpoint - September 8, 2026

Final gate: 2,506 Python and 235 JavaScript tests passed. Real synthetic speech
passed the browser worklet, Windows recognizer, isolated HTTP action/clip export,
download and full decoding. Duplicate input saved once. The restarted managed app
also recognized that audio in Practice without production changes and was stopped.
Post-restart Edge checks passed with actual voice writes and media starts blocked.
Real microphone/game-focus/PTT/private-audio acceptance remains outstanding;
see [voice control evidence and limits](VOICE_CONTROL_CHECKPOINT.md).

## Scene and rundown action safety - September 8, 2026

Final gate: 2,476 Python and 227 JavaScript tests passed. Four served Edge scenarios
passed again after managed restart: delayed scene cancellation, old/new run race,
partial OBS/Spotify pause, and waiting for requested music before advancement.
No API writes were forwarded and no media started. Saved-scene readiness HTTP tests
used isolated services. Stop cannot revoke commands already sent.
Repeat the browser check with `tools/qa_production_rundown.cjs`.

## Motion and functional production foundation - September 8, 2026

Final gate: 2,472 Python and 218 JavaScript tests passed. Managed restart and
post-restart capability/Edge checks passed; no actual stream or recording started.

Motion is checked in actual Edge with writes/media starts blocked. Clips are
checked through actual HTTP routes with synthetic frames, then downloaded and
decoded. Neither establishes live hardware/game/audio/platform acceptance.
See [the capability matrix and repeatable checks](FUNCTIONAL_PRODUCTION_PHASE.md).

## Portable audio panel acceptance - September 8, 2026

Final gate: 2,461 Python and 208 JavaScript tests passed.
Soundboard routing collapses inside docks and restores its original standalone
layout; duplicate headings are omitted only while docked.

Actual served Edge QA passed old-selection migration, original-node identity,
retained edits, standalone/docked navigation, local Soundboard shortcuts and Voice
popout gain propagation. Ignite/Daylight were checked at 1920x1080, 3840x2160,
1366x768 and 720x900 without horizontal overflow. Session selection and existing
window fixtures are regression checks for the shared infrastructure.

`tools/qa_studio_audio_docks.cjs` blocks every API mutation and browser media start.
Existing startup camera restoration, recognition context and soundboard output
registration requests remain blocked during QA. No microphone, playback, OBS or
platform delivery is established by these checks.

## Session tool selection and compact studio - September 8, 2026

Final gate: 2,461 Python and 207 JavaScript tests passed. Actual served Edge
regressions passed after the fullscreen and popout focus fixes.

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

Final gate: 2,461 Python and 205 JavaScript tests passed.

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
Final gate: 2,461 Python and 203 JavaScript tests passed. Hidden-workspace
resize, drag/drop, floating drag and blocked-storage feedback passed in Edge.
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


## Parent identity and five operator skins - September 7, 2026

- [x] Supplied parent header/splash/web assets, original RareIQ icons and manifest
  branding integrated into the existing app; payload provenance/hashes recorded.
- [x] All five 116-token skins, selection, reload, keyboard, reset and OS following
  checked against the actual served app. No second preference controller loaded.
- [x] Original 1,338 IDs retained; only three appearance IDs added. Twenty rapid
  switches preserved camera/scan nodes and an edited audience-theme field.
- [x] Main Studio/Appearance captured in all five skins at 1080p; Ignite/Daylight
  settings checked at 1366, 2560, 3840 and 720px widths without page overflow.
- [x] Final canonical gate passed 2,456 Python and 200 JavaScript tests. One earlier
  reference-learning persistence failure passed its focused suite and full rerun;
  recorded in engineering memory, with no backend changes.
- [ ] Complete component/state/Daylight contrast audit across every workspace.
- [ ] Sarge visual/service-state integration and remaining parent/Windows branding.
- [ ] Full scaling, reduced-motion, device/recognition and audience-output acceptance.

This is an installed local source checkpoint, not a finished Windows installer or
completed refinish. See `branding-v2/REFINISH_PROGRESS.md` for preview and rollback.

## Refinish appearance state foundation - September 7, 2026

- [x] One shared bootstrap/runtime state; legacy preferences preserved for rollback.
- [x] First-use default, five valid stored skin values, migration/reload, OS following,
  corrupt data and blocked storage covered by behavior tests.
- [x] All 15 current/fallback Studio X entry points load the shared dependency first.
- [x] Final canonical gate passed: 2,453 Python and 200 JavaScript tests.
- [x] Actual served build checked in Edge: dark/light reload at 1080p; blocked-save
  feedback, OS change and rapid switching with an audience field preserved at 1366x768.
- [ ] Supplied identity migration, five visible semantic skins and selector.
- [ ] Full visual/workflow/output-isolation and Sarge acceptance from the handoff.

Details and rollback: `branding-v2/REFINISH_PROGRESS.md`. This is a state
foundation checkpoint; the visual refinish remains pending.

## RareIQ brand package v2 - September 7, 2026

- [x] Original approved reference recovered and preserved unchanged.
- [x] Transparent mascot and RareIQ/OCR logo families exported; vector and hybrid
  formats identified; fonts, licenses, tokens and editable sources included.
- [x] All 16 book pages visually inspected; final clear-space diagram and custom
  IQ treatment rechecked after refinement.
- [x] Local asset gallery renders at 1920x1080, 3840x2160 and narrow 720px width;
  all 84 download/navigation links resolve and preview images decode.
- [x] Favicon exports inspected at actual 16/24/32/48/64px sizes; matte reviewed
  against dark and light backgrounds; 11 selected contrast pairs pass.
- [x] Package validation checks PNG integrity, asset pairs, PDF page count and ZIP.
- [x] Canonical repository gate passed 2,452 Python and 196 JavaScript tests.
- [ ] Separate parent-platform UI migration and runtime visual acceptance.
- [ ] Physical print proof and destination/platform crop acceptance where required.

Latest audit: [2026-08-30 readiness findings and next test order](READINESS_AUDIT_2026-08-30.md).
Local automated checks are green; hardware/account/streaming acceptance is not yet signed off.

Run the release gate from the repository root with the Python 3.13 environment active:

```powershell
.venv\Scripts\python.exe -B tools\release_check.py --require-node
```

If Node.js is not on `PATH`, provide its executable explicitly with `--node`.

The gate verifies:

- repository credential hygiene and untracked-source whitespace before staging
- installed dependency integrity
- Python syntax without writing bytecode
- JavaScript syntax, including inline scripts in shipped HTML
- duplicate HTML IDs and missing local static assets in every shipped HTML document
- isolated JavaScript behavior tests for browser-source/replay recovery, soundboard playback, recording controls, and microphone lifecycle
- working-tree and staged whitespace
- the complete canonical `tests/` suite

Repository work must also follow the owner-aligned operating baseline in
[`AGENTS.md`](../AGENTS.md), including product boundaries, live-production safety,
visual QA, regression memory, checkpoints, and backups.

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

## Studio-to-OBS handoff focused follow-up - September 16, 2026

Local recovery fixes passed these focused checks:

- `node --test tests/browser/program_output.test.cjs tests/browser/soundboard_output.test.cjs tests/browser/studio_audio_transport.test.cjs tests/browser/overlay_runtime.test.cjs`: 35 passed.
- `.venv\Scripts\python.exe -B -m pytest tests/test_studio_output_contract.py tests/test_broadcast_outputs.py -q`: 26 passed.

This is deterministic behavior/backend evidence, not live browser or OBS acceptance.
The full release gate was not run for this bounded follow-up; no checkpoint was committed.
After authorization, confirm current-build Program switching, transparent graphics and
clear/expiry, one routed Soundboard playback, and disconnect/reconnect in an OBS Browser
Source using `/output/studio`. Check OBS audio routing and avoid capturing the same sound
through both the combined source and a separate Soundboard or desktop-audio path. Do not
start real playback, recording or streaming without the owner's explicit authorization.

## Authorized local OBS handoff acceptance - September 17, 2026

The owner authorized configuration and local playback with streaming/recording off.
The existing RareIQ Program Browser was migrated from /program to /output/studio,
1920x1080, Control audio via OBS enabled, shutdown/activation refresh disabled.
Its transform fits the 3840x2160 canvas without cropping. The separate Soundboard
scene item in RareIQ Program was disabled, retained for recovery, not deleted.
The source remains unmuted at unity with monitoring off to avoid speaker feedback.

- Actual OBS source audit: Studio Program configured, no reported issues.
- Slot 1 now uses the discovered Insta360 Link through RareIQ's existing capture
  owner. Fresh physical-camera frames reached Program and were visually inspected
  in an OBS scene screenshot after a Browser Source cache refresh.
- A temporary lower-third was visually present over Program, then absent after its
  duration. Previous hidden graphic content was restored; no test graphic remains.
- Two brief low-volume Soundboard tests produced OBS Program meter events before
  and after refresh. The separate disabled Soundboard layer produced no meter events
  during the final test. Audio transport was empty and Program meters idle afterward.
- Final state: Program camera 1, physical camera connected, graphics hidden,
  OBS streaming false and recording false. No stream or recording was started.

This verifies local OBS video composition and audio-meter receipt, not listener
quality, microphone mixing, encoded recording, delivery to a platform or a network
outage recovery. Refresh recovery was exercised; transport-failure handling remains
covered by the September 16 deterministic tests. The full release gate was not rerun.
Local recovery settings and redacted numeric evidence are under
.tmp/obs-handoff-20260917; camera captures there remain private and untracked.

## Camera reassignment acceptance - September 17, 2026

Canonical gate passed 2,612 Python tests and 275 JavaScript tests. Focused camera
checks passed 57 tests. After managed restart, two physical Insta360 unassign/restore
cycles and one reconnect resumed fresh frames. OBS input settings and scene visibility
were preserved; Program slot 1, streaming off, recording off. See
CAMERA_REASSIGNMENT_CHECKPOINT.md. Logs and numeric evidence remain local in .tmp.

## 2026-09-19 bounded launch-hardening pass

- [x] Reject stale, missing, malformed, non-finite and future frame timestamps
  before Preview/Take/scene actions mutate production state or reach OBS.
- [x] Recover readiness when fresh frames arrive; explain disabled switcher actions.
- [x] Keep browser-route availability distinct from verified OBS source/playback setup.
- [x] Canonical release gate: 2,639 Python tests plus JavaScript behavior, syntax,
  assets, dependency integrity, whitespace and credential-hygiene checks passed.
- [x] Safely reload the managed local server with OBS closed, session inactive and
  recording inactive; confirm the live API exposes per-slot readiness and the
  browser-output warning. No stream or recording was started.
- [ ] Full launch sign-off: current Program slot 1 is disconnected; slot 2 has a
  fresh frame. Assignments were preserved. Resolve and recheck the intended camera.
- [ ] OBS stability after the earlier Windows handle-exhaustion incident, the final
  audio mix, authorized recording/listener acceptance and destination receipt remain
  separate hardware/platform acceptance tasks. This pass does not verify them.
- [ ] Narrow-screen full-shell visual acceptance remains incomplete; isolated
  component captures are not proof of the complete running Studio layout.

## November 18, 2026 — Desktop native-output acceptance

- [x] Native Windows shell and isolated renderer bridge; real DPAPI round trip and
  synthetic destination persistence without plaintext credentials in public status
  or on-disk JSON. No real account connection or key was used.
- [x] Output capture/audio isolation at 1280×720, 1920×1080 and 720×1280: public
  media only, mute/volume/pause/seek/loop behavior, monotonic timestamps, review guard.
- [x] Full production-component chain with isolated generated media: asset import,
  Preview/Take, exact peer/generation preflight, native ownership, compositor/audio
  capture and PyAV local FLV. Decoded H.264 720p, AAC 48 kHz stereo, 6.153 seconds,
  184 frames / 29.9041 fps, detected 440 Hz tone, zero reported dropped frames or
  audio packets. Image/title Take appears in the file while the window was minimized.
- [x] Native stop released backend encoding ownership while its Main PID was still
  alive, then closed owned test processes. Unit coverage also exercises stale,
  replaced, unknown and reused backend/owner identities and active-client guards.
- [x] Local RTMPS receiver: successful decoded H.264/AAC delivery with trusted
  certificate; wrong hostname and wrong CA rejected with zero received media bytes;
  successful repeated valid-certificate run. This is transport fixture evidence.
- [x] Document local-development-runtime dependency, F: build/data/cache/evidence
  locations, the C: checkout/Python requirement and Windows Start Menu exception.
- [ ] Real platform dashboard receipt and listener-quality A/V sync.
- [ ] Current native path with real cameras, microphones and explicit screen capture;
  driver/device recovery and sustained production at each offered encoding format.
- [ ] NVENC initialization/performance acceptance; current successful runs use
  software H.264. No cause or successful GPU encode is asserted.
- [ ] Self-contained, signed install/update/uninstall and clean-machine acceptance.
- [x] Canonical gate passed on the isolated checkpoint source: **3474 Python
  tests and 575 JavaScript tests**. The source excludes unrelated local edits;
  evidence is `ProducerPlease-desktop-20261118/release-gate-isolated-final.log`.
- [x] Rehearsal 05 excluded an injected opaque preparation notice from the encoded
  picture and restored preparation controls after Stop. Decoded video was visually
  inspected. Earlier rehearsal 04's notice contamination is preserved as a defect
  in its visual audit, not accepted as clean output.
- [x] Latest local app launched against the actual managed studio; native setup
  opens with output preparation enabled and no destination saved. Windows Start
  Menu shortcut points to the validated F: executable. No broadcast was started.

Release decision: available for local operator evaluation on this development PC.
This is not clean-machine or platform-live acceptance; the unchecked items above
remain open. A portable/signed installer is not part of this checkpoint.

Evidence and reproduction paths: [DESKTOP_APP.md](DESKTOP_APP.md). Use
`ProducerPlease-native-full-20261118-05`, the RTMPS `serialized-20261118` run and its
`repeat-20261118` result. The earlier RTMPS directory containing `final-20261118`
failed during handshake and is diagnostic history, not passing acceptance.
No physical capture, external broadcast, public deployment or real account change
was performed by these native rehearsals.

## November 18, 2026 — Guided desktop setup acceptance

Packaged native-window rehearsal passed source-library navigation, unchanged
Program generation, hidden/reopened settings with both unsaved fields retained,
DPAPI round trip, synthetic secure-key save, disabled transmission in the fixture,
and six dark/light 960/1920/3840 layout captures. Focused IPC/navigation/UI guards
pass. Evidence: `F:/Temp/jonat/ProducerPlease-desktop-onboarding-20261118/native-02`.
This pass does not capture devices, connect accounts or start a real broadcast.
The current production app remains open; the newer package takes effect on reopen.

Canonical gate passed on the isolated checkpoint source: **3474 Python tests and
586 JavaScript tests**. Log: `ProducerPlease-desktop-onboarding-20261118/release-gate.log`.

## November 18, 2026 — Private bundled-runtime candidate acceptance

- [x] Separate private candidate packages official embedded CPython 3.13.12 amd64
  with pinned archive SHA-256, 48 dependency distributions, approved backend/static
  source, default seeds and FFmpeg. Inventory and Python/package/binary notices
  retained; operator configuration, keys, catalogs and user models are not copied.
- [x] Source allowlist and resource containment guards, including junction escape;
  default-profile and legacy redirector-child/foreign-PID regression coverage.
- [x] Candidate 02 actual controller/backend on isolated 8767: executable identity
  verified, 569 probed import paths inside resources despite invalid environment
  Python paths, F: profile writes and zero resource hash changes. Native encoding
  stayed inactive; readiness truthfully blocked empty Program and missing output.
- [x] Normal stop preserved unknown OBS state. QA then stopped only its exact newly
  owned idle test process after identity/profile/port/client/encoding checks.
- [x] Candidate 02 native EXE/setup on 8770 with bundled backend, source navigation
  without Take, protected storage available and owned test-process cleanup.
- [x] Bundled software encoder produced a local synthetic FLV with 90 video frames
  and 144,000 audio samples; zero reported video/audio drops.
- [x] Primary development build, shortcut, data and port 8765 studio preserved.
- [x] Candidate 04 full packaged Program: actual app/backend/resources, local
  H.264 720p/AAC 48 kHz stereo, 170 frames / 5.685 seconds / 29.9033 fps, generated
  tone, minimized image/title Take, zero reported dropped queues, preparation UI
  excluded/restored and native ownership released. `native-program-acceptance04`.
- [x] Canonical isolated-source gate: **3533 Python and 592 JavaScript tests**.
  Evidence: `ProducerPlease-bundled-20261118/release-gate.log`.
- [x] Separate Standalone Preview shortcut installed and actual app opened and
  visually inspected. Its banner and F: ProducerPleasePreview profile/port 8767
  distinguish it; primary app/shortcut/data are preserved. No keys or data migrated.
- [x] Candidate copied to another folder and real isolated backend acceptance
  passed on port 8771 with no resource changes. `relocated-acceptance/results.json`.
- [x] Local preview ZIP created and integrity-checked; operator configuration
  filenames excluded. Archive path is recorded in [DESKTOP_APP.md](DESKTOP_APP.md).
- [ ] Runtime patch/update strategy, signing, installation/update/uninstall,
  migration/recovery and clean-machine acceptance.
- [ ] Public redistribution/license review. Preserved metadata/notices alone are
  not a legal assessment or public-release approval.
- [ ] Real platform receipt, physical capture, listener A/V sync, endurance and
  hardware encoding remain separate authorized acceptance work.

Passing evidence under `F:/Temp/jonat/ProducerPlease-bundled-20261118`:
`backend-acceptance02/results.json`, `native-acceptance/results.json` and
`encoder-acceptance/results.json`. The earlier `backend-acceptance` failure was an
incorrect harness dependency assumption, not evidence of a passing candidate.
Final candidate evidence/counts are deliberately not inferred from these checks.
See [DESKTOP_APP.md](DESKTOP_APP.md) for the two build types and interpreter pin.

## November 18, 2026 — Desktop explicit-recovery acceptance

- [x] 62 focused broker, encoder, output, bridge and Settings regressions pass.
- [x] Canonical isolated staged-source gate: **3533 Python + 612 JavaScript tests**.
- [x] Actual recovery EXE: `0.1.0-20261118105522739`, own profile/backend on 8770.
- [x] Real Settings View output bridge restores the same minimized output without
  review, Take, capture start or transmission. Dark/light recovery layout inspected
  at 960×900 using explicitly simulated public statuses; no horizontal overflow.
- [x] Real packaged Program/peer/preflight/capture/encoder path, generated PNG and
  local FLVs only: output destruction stops worker, clears backend ownership,
  preserves 37 frames and does not automatically restart. A second explicit
  confirmation prepares a new window/peer and encodes 44 frames; normal Stop clears
  ownership. Both files decode as 720p H.264 and 48 kHz stereo AAC; workers exit.
- [x] Actual current bundled encoder, local trusted TLS receiver: deliberate
  disconnect reports safe `encoder_failed`, worker closes 47 ms after failure,
  no automatic retry; explicit new local-file attempt encodes/decodes 90 frames
  and generated audio. Owned child processes and listener close. This generic
  failure does not prove a specialized transport diagnosis.
- [x] One-pass read-only recovery review found no concrete blocker.
- [x] Existing primary and preview studios were not restarted or changed by QA.
- [ ] Real destination receipt, physical devices/listener/echo, endurance, clean
  machine, signing/installer/update and public redistribution acceptance remain.

Evidence under `F:/Temp/jonat/ProducerPlease-recovery-20261118`:
`native-ui01/results.json`, `native-recovery01/recovery/recovery-results.json`,
`encoder03/results.json`, and `release-gate.log`. Earlier `encoder02` proof remains
preserved for the prior build; the final repeat uses the recovery candidate.
No real platform stream, user recording, credentials or physical capture were used.

## November 18, 2026 — Desktop destination-edit acceptance

- [x] 32 focused store/Settings/mutation-guard tests, including retained retry IDs.
- [x] Canonical final isolated-source gate: **3533 Python + 621 JavaScript tests**.
- [x] Actual bundled EXE `0.1.0-20261118110448557`, fresh QA profile/backend 8770:
  Settings creates synthetic destinations using real Windows encryption; same-ID
  rename preserves key/server, Cancel restores Add draft, server-only change is
  blocked and explicit replacement updates key/server. Public status stays redacted.
- [x] Dark/light 800×900, 1920×1080 and 3840×2160 inspected without horizontal overflow.
- [x] Main guards save/remove vs Start/Stop/ownership, including reverse pending-save
  race; one read-only integration review found no concrete blocker.
- [x] No Program change, encoding, actual credentials or physical capture; owned QA
  processes closed and existing 8765/8767 studios were preserved.
- [ ] OAuth/platform sign-in, destination receipt, hardware/listener/endurance and
  installer/update/public-release gates remain separate.

Evidence: `F:/Temp/jonat/ProducerPlease-destination-edit-20261118/native02/results.json`,
the six layout captures and `release-gate-final.log`. `native01` is a preserved
failed harness probe, not passing acceptance evidence.

## November 18, 2026 — Studio asset-sizing checkpoint

- [x] Canonical isolated staged-source gate: **3535 Python + 621 JavaScript tests**.
- [x] Proportional header lockup and 32px compact mark; matching 16:9 camera/empty
  thumbnails capped at 320px; PGM/PVW badges do not overlap camera labels.
- [x] Eight isolated dark/light layouts at 1920×1080, 3840×2160, 960×900 and
  1366×768: ratio 1.7778, no horizontal overflow, clipped buttons or nested dock
  scrolling. Final evidence is `visual03`; `visual02` is a preserved failed probe.
- [x] Actual primary development desktop inspected after stylesheet cache bust.
- [x] Bundled candidate `0.1.0-20261119013309197` passed isolated native startup,
  protected storage readiness and source navigation without Take or capture.
- [x] Current private guest-only HTTPS boundary: 21/21 checks pass. Second PC
  actually displayed the secure guest page; no operator routes exposed there.
- [ ] Owner joins/enables physical camera and mic; verify admission, waiting,
  readmission, received picture, noise gate, speech, conversation and echo.
- [ ] Restore the temporary private mapping and revoke the test invitation after
  the two-PC test. Do not call this network cleanup complete before observing it.

Sizing evidence: `F:/Temp/jonat/ProducerPlease-makeover-sizing-20261118/visual03/`.
Gate/native evidence: `F:/Temp/jonat/ProducerPlease-makeover-room-20261118/`.
Private configuration, invitation material and physical images are excluded from
source/backups. No public stream, recording, platform receipt or producer login
acceptance is claimed. This is a first sizing pass, not the full visual refinish.
