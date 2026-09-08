# Refinish implementation progress

## Authorized usage

Original shared baseline remains 0%, reset timestamp 1789435596. On September 7,
2026 the owner authorized proceeding from 4% to a total ceiling of 6% for the
first tested implementation checkpoint. Latest reading before implementation: 5%.
Do not reset this baseline. Check again before further substantial work.

## Plan and dependency map

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
