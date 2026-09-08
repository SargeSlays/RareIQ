# Refinish implementation progress

## Local wake-command checkpoint - September 8, 2026

Voice studio now offers explicit Practice/listening controls using its existing
raw microphone owner. Only registered camera/clip actions can run. Real synthetic
speech-to-MP4 and managed-app Practice passed; no actual microphone/game session or
private spoken output is claimed. Gate: 2,506 Python and 235 JavaScript tests.
See [voice checkpoint](../VOICE_CONTROL_CHECKPOINT.md). Total ceiling35%, original
baseline0% unchanged; shared use reported30% during activation.

## Action safety follow-up - September 8, 2026

Scene takes now share camera availability checks. Rundown Stop invalidates awaited
work; scene OBS/Spotify partial outcomes pause advancement. Final gate: 2,476 Python
and 227 JavaScript tests, plus four post-restart Edge scenarios. No real broadcast,
recording or platform message started. Usage is 27% against the authorized total
30% ceiling; original baseline remains 0%.

## Motion and functional production foundation - September 8, 2026

Final gate: 2,472 Python and 218 JavaScript tests passed. Post-restart Edge checks
passed; synthetic HTTP clip save/download decoded all 40 frames with one save for
a duplicate request. No actual capture, playback or platform publication tested.

The supplied motion runtime is additive, scoped to the operator document, and
uses existing production/advisor/recognition events. No preview actions, synthetic
waveform, replacement logo, device pipeline or audience motion styles are imported.
The separately checkpointed functional foundation adds manual playable clip export
and shared clip/camera dispatch. Full hands-free/chat/multistream acceptance remains
pending. See [the phase handoff](../FUNCTIONAL_PRODUCTION_PHASE.md) for boundaries
and usage authorization (30% total ceiling, original 0% baseline unchanged).

## Portable Soundboard and Voice studio - September 8, 2026

Final gate: 2,461 Python and 208 JavaScript tests passed.
Soundboard routing collapses inside docks and restores its original standalone
layout; duplicate headings are omitted only while docked.

Session tools now offers 30 dockable panels and eight separate workspace shortcuts.
Soundboard and Voice studio retain their original nodes, listeners and media owner;
opening their standalone workspace restores those same panels to their original
location. Returning to Live Control docks them again when selected. Existing saved
workspace selections migrate into the corresponding audio docks.

Both audio tools support popouts. Voice gain edits reach the original controls;
Soundboard number shortcuts are scoped to its dock and cannot switch Program.
Dock selection itself performs no media activation or API mutation. Actual served
Edge checks passed migration, identity, drafts, navigation, popout propagation,
keyboard isolation and light/dark bounds at desktop, 4K and narrow sizes. Browser
QA blocks API writes and media starts; hardware and external delivery remain untested.

Further workspace adapters, full splitters and destination setup remain pending.

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


## Authorized usage

Original shared baseline remains 0%, reset timestamp 1789435596. On September 7,
2026 the owner authorized proceeding from 4% to a total ceiling of 6% for the
first tested implementation checkpoint. The owner subsequently approved a 7%
ceiling for the parent identity/five-skin checkpoint, then approved a 9% ceiling
for completing that checkpoint and the first customizable production-studio slice.
On September 8 the owner approved a total 10% ceiling and requested the more
expressive supplied logo for the main studio. The owner then approved a total 12% ceiling for the compact studio and session
tool-selection work. At the 12% reading the owner explicitly approved a total
20% ceiling. Original reset timestamp and 0% baseline are unchanged.
Do not reset this baseline. Check again before further substantial work.

## Plan and dependency map

### Parent identity and five-skin checkpoint

Continuing from `4000e78f`; no restart of the project or preference system.
The owner's supplied `Producer_Please_Brand_System_v2.zip` supersedes the earlier
parent reference-only kit and supplied mascot adaptations for current integration.
Its original RareIQ character and orange/lime parent assets are copied unchanged;
source paths/hashes are in `static/brand/producer-please-v2/PROVENANCE.json`.
The book, all three implementation documents and asset provenance were reviewed.

Implemented in the actual operator app: Producer, Please header/title/splash,
web icons and manifest branding, visible RareIQ entry/icon, five named choices,
immediate preview, persisted selection, keyboard radio navigation, OS following
and reset. The existing appearance controller remains the only preference owner.
All 116 supplied tokens per skin are retained; only their selectors are adapted.
Existing command-deck variables map to those tokens with legacy-page fallbacks.
Old forced logo substitutions exclude the current shell. The supplied demo and
its controller are not loaded. No output document or backend file is modified.

Actual Edge checks: all five skins on Studio and Appearance at 1920x1080; reload,
keyboard/Home/arrow selection, OS following, reset and 20 rapid changes preserving
camera/scan DOM and an edited audience-theme field. No page script errors.
Ignite/Daylight settings bounds checked at 1366x768, 2560x1440, 3840x2160 and
720x900 without page overflow. Header uses a 180px horizontal asset; the existing
mobile shell hides that header. Captures and gallery remain local under
`.tmp/refinish/`, with private camera/card images masked. The earlier state-only
checkpoint captures provide before views. No server restart was needed: the
current served files and cache parameters were exercised directly.

Remaining acceptance: complete per-workspace/dialog/menu/tooltip/status/meter
semantic audit (especially Daylight), Sarge comma/waveform and truthful service
states/commands, remaining parent copy and Windows launcher icon integration,
Windows scaling/reduced-motion checks, actual RareIQ recognition/camera/overlay
continuity and broadcast-render comparison. No hardware or platform operation is
certified by these frontend checks. The complete refinish is not finished.

Final branding gate: 2,456 Python and 200 JavaScript tests passed, including the
disabled-input specificity guard. The actual browser confirmed the winning
disabled foreground. Runtime asset bytes are protected from checkout line-ending
conversion so supplied-asset checksum guards remain valid on Windows.

Owner's next production requirement: an OBS/Streamlabs-style production workspace
in Producer, Please's own identity, full-screen mode, and tools that dock, resize,
reorder, hide/restore and pop out around the canvas. Preserve individual layouts
and working controls/state. Destination scope includes YouTube, Twitch, Facebook,
TikTok, Kick, Rumble, other supported services and custom endpoints. Inspect
existing destination and encoder support before adding connection claims; no
actual broadcast is authorized. First slice prioritizes the working production
canvas and safe layout customization; external-window lifecycle and each service
connection need their own verified contracts.

Launch/preview: open the already running `http://127.0.0.1:9040/control`; choose
Settings > Appearance. This modifies this checkout's served application; it is
not a newly packaged Windows installer. Revert this checkpoint to `4000e78f` to
restore the previous visuals while retaining the shared appearance record. Do not
reset or delete user preferences/data. Owner-authored AGENTS.md edits remain intact.

### Earlier foundation checkpoint (historical)

1. Baseline and appearance state foundation: implemented; checkpoint validation below.
2. Parent/RareIQ identity, five semantic skins and accessible Appearance selector.
3. Workspace/Sarge refinish, full visual matrix and delivery checkpoint.

The existing server serves `/control` at loopback port 9040. `control.html` owns
the shell and loads `studiox.js`; `studio_shell.js` owns Studio-first navigation.
Preserve `live`, `broadcast`, functional IDs and all API/output contracts. Existing
camera, recognition, socket and polling pathways stay in their current controller.
The appearance module makes no device, network or timer calls. All 14 legacy
fallback pages that consume `studiox.js` also load its shared bootstrap dependency.

Theme state was duplicated between an inline first-paint script and runtime code.
Both now consume `studio_appearance.js`; `applyStudioTheme` remains the existing
runtime hook. A versioned appearance record migrates legacy dark/light/system,
preserves the old key for rollback, defaults first use to Ignite, and retains
unsaved choices in memory when storage is blocked. The existing three controls
remain until the five complete token sets and selector ship together. New skin
state currently resolves to the existing light/dark presentation; this checkpoint
does not claim the five visible skins or identity migration are complete.

The final RareIQ asset library is in `output/branding/rareiq-v2/`; its mascot is a
restored adaptation, full-color SVG signatures are hybrid raster/vector assets,
and Poppins includes its OFL. The supplied parent art is a reference board with
P/play/comma variants; faithful runtime exports still need preparation. It must
not be replaced by the RareIQ mascot. Parent font fallback remains available.

`rareiq_brand_v1.css` forcibly substitutes v1 logos. `studiox_command_deck.css`
owns high-specificity dark/light tokens, header logo dimensions and Appearance
geometry. Later camera, inspector, output and `studio_shell.css` layers also need
review. Migrate these owners deliberately; keep the audience `riTheme*` designer
and browser-source presentation isolated.

Local hardware reports Ryzen 9 9900X3D and RTX 4090. The GPU had an existing
workload; frontend verification uses local CPU/browser tooling. No hardware,
broadcast, recording or external platform operation is part of this checkpoint.

## Verification

Local Edge exercised the actual served build, with a fresh appearance cache
parameter. Light/dark selection and reload restoration passed at 1920x1080 with
no page script errors. Screenshots were visually inspected and remain local in
`.tmp/refinish/appearance-light.png` and `appearance-dark.png`; existing branding
and geometry are unchanged. The initial pre-change screenshot attempt could not
launch the absent bundled headless binary, so there is no before screenshot.

A separate 1366x768 browser context blocked storage writes: the app truthfully
reported an unsaved choice and retained it through an OS color change. Twelve
rapid appearance switches preserved the current workspace and an edited audience
theme field. This is operator state evidence, not audience output render or
hardware acceptance. No app restart, broadcast or recording was initiated.

The final canonical gate result is recorded in the release checklist. Full five
skin, 4K/narrow/scaling/reduced-motion and Sarge acceptance remain pending with
their implementation. Browser verification used installed Edge; no download.

## Rollback

Revert this checkpoint's source changes to restore the old controller. The legacy
`rareiq.studiox.theme.v1` value remains unchanged. New preferences live only under
`rareiq.studiox.appearance.v2`; no production settings or saved card data migrate.
