# RareIQ engineering memory

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
