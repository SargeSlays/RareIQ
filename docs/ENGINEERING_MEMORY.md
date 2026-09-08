# RareIQ engineering memory

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
