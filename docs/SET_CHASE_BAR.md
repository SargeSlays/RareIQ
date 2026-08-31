# Set Chase browser source

Set Chase is a silent, transparent-background browser source for a curated set's
case hits and top hits. It is independent of live card recognition and does not
change sets when another card passes under a camera.

## Operator workflow

1. Open **Creator Studio → Set Chase Bar**, or `/creator/set-chase`.
2. Select the exact catalog set and language, then **Use selected set**.
3. Search the local catalog and add cards to **Case hits** or **Top hits**.
   **Rarity levels** start with the highest available tier selected. Check one or
   more levels to see only those cards, optionally combined with a name or number.
   **All rarities** is explicit; **Clear selection** shows no cards. **Reset filters**
   clears the name/number and returns to the highest tier, without editing the rotation.
   Reorder or remove cards with the controls in **Your rotation**.
   **To top hits / To case hits** moves a card between groups without duplicating
   it. The same action is available on an already-added catalog result.
4. Choose three or four cards per page, a 4–30 second page duration, and a theme.
5. **Save & preview** changes only the saved draft. Inspect its preview.
6. **Publish saved draft** copies the draft to the live browser source.
7. **Hide live strip** hides the output without deleting either list.

Source URL on the standard local setup:
`http://127.0.0.1:9040/overlay/set-chase`

Recommended browser-source dimensions: **1280 × 320** for four cards or
**1080 × 320** for three. **1920 × 360** is also supported. Scale and position the
source in OBS or another browser-source-capable compositor. The page makes no
audio and does not claim a physical camera. Adding it does not start a stream.
Use the program URL above, not the editor's `?preview=1` URL, for broadcasts.

## Rotation and presentation

- All case-hit pages play first, followed by all top-hit pages; the loop repeats.
- Empty groups are skipped; short final pages are centered, without duplicate
  cards inserted to fill space. Each group supports up to 32 cards.
- Full card artwork is contained, never cropped. Missing artwork has an explicit
  placeholder rather than silently substituting a different card.
- Set name, language, group, card names/numbers, page count and progress remain
  visible. Card entrances are staggered, with a subtle moving foil highlight.
- Six set-inspired artistic palettes are available. Auto uses set-name keywords,
  not official set branding. Two custom accents allow manual color matching.
- Reduced-motion preferences disable entrance/foil motion and the progress bar.

## Data and on-air safety

Case-hit and top-hit membership is operator-curated. There is no automatic price
ranking, pull-rate guarantee, or claim that the catalog's rarity field proves a
card is a case hit. Only existing local catalog artwork is accepted. Import any
missing set or artwork through Library before curating it here.

Rarity options use the selected set/language's exact local catalog labels, with
counts across the whole set—not just the first 100 search results. Options and
results sort highest-first before the result limit. **Unlisted**
means no rarity was supplied by the catalog. Search shows the matching count and
reports when only the first 100 results are displayed; narrow the filters to find
the remaining cards. Changing search filters never edits the saved or live lists.

The display hierarchy classifies explicit rarity labels only. Unknown labels
remain available below known tiers, with unlisted last. English Ultra Rare and
Japanese UR have different positions. This is a browsing order, not a guarantee
of pack odds or value. Existing generic labels such as `R` are not subdivided by
guessing from artwork or card number. Rarity categories follow the published
[Pokémon card checklist](https://www.pokemon.com/static-assets/content-assets/cms2-en-uk/pdf/trading-card-game/checklist/svi_web_cardlist_en.pdf);
legacy/localized aliases are supported without rewriting catalog labels.

One draft and one published snapshot are stored atomically in
`<configured config_path>/set_chase.json`. Restarting RareIQ restores the lists
but leaves the strip **off air** until explicitly published again. Concurrent
editors use revision checks; stale saves require **Reload saved** and cannot
silently overwrite another editor. Draft edits never reset the live rotation.
The saved set is restored in the picker. Selecting that same set cannot clear
its card list. Changing sets or reloading over unsaved changes requires a
confirmation; **Keep editing** or Escape leaves the current draft intact. Browser
navigation also warns when the editor has unsaved changes. Failed or missing
artwork keeps a labeled placeholder instead of removing the card's image slot.

The editor refreshes the confirmed browser-source status every three seconds,
with one bounded request at a time. It shows the published set independently of
the working draft. Changes in another editor require an explicit reload before
saving or publishing; local fields and card selections are never replaced by polling.
**Hide live strip** remains available using the latest confirmed output revision,
without adopting or overwriting another window's saved draft.
Unsaved changes are also labeled above the saved-draft preview.

Connection loss is **unknown output**, not a claim that the strip is off air.
Saving and publishing pause until connectivity is confirmed. A timed-out write
is never retried automatically; if it reached the server, the new revision
requires a reload. The preview shows a reconnect message, while the broadcast
source stays transparent on failure and resumes the shared rotation on recovery.

## Inside Creator Studio

**Creator → Set Chase Bar** uses the remaining workspace height, with one editor
scrolling region instead of a fixed-height frame inside another scrolling panel.
The shell supplies the heading; the embedded editor keeps its output-health row
without repeating the standalone hero. **Open in own window** remains available.

The editor loads on the first visit and stays mounted while switching Creator
tabs or other workspace tools. Unsaved fields, the card rotation, and search
filters remain in that document. This is session continuity, not autosave:
use **Save & preview** before closing or reloading the whole app. Saving still
does not publish anything, and another window's edits still require a reload.

## Broadcast handoff

Open **Broadcast → Setup** for the shared browser-source library and OBS plan.
Set Chase is listed alongside the camera, soundboard and existing production
outputs, with a clean `/overlay/set-chase` URL and **1280 × 320** dimensions.
**Configure Set Chase** opens the existing editor; it does not publish a draft.

New OBS setups place the strip bottom-center with a safe margin. Its native
size is capped, and it scales down to fit smaller or portrait canvases without
cropping. Existing nonempty OBS scenes keep their operator-defined content and
transforms. **Preview Plan** is read-only; **Create in OBS** stays disabled when
OBS cannot be authenticated. A disconnected plan says **Connect to inspect**,
not that existing scenes have been verified.

## Verification (2026-08-31)

- Python tests cover validation, local-only artwork, duplicate/cross-set
  rejection, filtered catalog search, searchable-set discovery, atomic persistence, corrupt settings,
  concurrent saves, restart/off-air behavior and HTTP routes.
  Rarity checks cover full-set facets, exact matching, unlisted rarity, query
  intersections, pagination limits, language boundaries and read-only searches.
  Multi-level tests check union filtering, tier sorting before the result limit,
  highest-tier defaults independent of the query, and unchanged recognition ranking.
- JavaScript behavior tests cover ordered rotation, three/four-card pages,
  deterministic shared timing, centered short pages, empty/offline output,
  safe artwork and unchanged-state rendering without redundant DOM rebuilds.
  Editor checks cover automatic rarity filtering, empty results, reset without
  changing the rotation, set switches and stale-response protection.
  Clearing every tier never falls back to all cards, and unchanged facets retain
  their checkbox DOM nodes so keyboard focus survives a search.
  Draft workflow checks cover set-picker load order, same-set preservation,
  cancel/confirm behavior, unsaved navigation guards, cross-group moves, capacity
  limits and missing-artwork placeholders.
  Output-status tests cover two-editor conflicts, unsaved-field preservation,
  disconnect/recovery, uncertain writes, stale in-flight reads and timer cleanup.
  Overlay checks distinguish empty previews from network failures and verify
  reconnects resume the broadcast's shared page without showing error text on air.
- Isolated browser testing exercised catalog selection, reorder, save, preview,
  publish and hide. Real local artwork was visually checked at 1280 × 320,
  1080 × 320 and 1920 × 360. Test selections were explicitly marked as layout
  fixtures and were not published to the production app or OBS.
- Rarity filtering and the compact search/preview layout were also checked in
  the browser at a 1280 × 720 viewport with real local artwork.
  Editor and overlay HTML are served without caching; the embedded preview is
  versioned so older preview styling is replaced after an update.
- Draft guards and cross-group moves were exercised in the browser, including
  keeping edits, discarding back to the saved list, and saving a moved card.
  The editor was checked at 1280 × 720 and 390 × 844 without horizontal overflow.
- Two isolated editor windows verified publish/hide status synchronization,
  conflict warnings, and hiding a newer broadcast while retaining unsaved fields.
  Stopping and restarting only the QA server verified reconnect messaging,
  transparent broadcast failure, automatic preview recovery and no auto-publish.
- Creator integration was checked at 1280 × 720, 1920 × 1080, 3840 × 2160 and
  1024 × 768. The frame stays within its host at all four sizes, without host
  scrolling or horizontal editor overflow. The eight-card fixture fits without
  editor scrolling at 4K; smaller screens scroll only inside the editor.
  Browser tests covered unsaved theme/search retention across Creator tabs and
  workspace navigation, a visible discard confirmation, cancellation and saving.
  Behavior tests cover lazy initialization, preserving the same editor document,
  saved-view restoration, keyboard navigation and explicitly embedded styling.
- Broadcast catalog tests verify unique clean URLs, unchanged existing scene
  names, common API/OBS metadata, isolated soundboard audio, and strip placement
  on 1080p, 4K, portrait and small canvases. Setup retries remain idempotent and
  preserve operator layouts. UI tests cover clean URL copying, unavailable
  clipboard feedback, source dimensions, and disconnected-plan labeling.
- Browser review checked the 14-source library in dark and light modes. It has
  no horizontal overflow at 1920 × 1080, 3840 × 2160 and 390 × 844. Camera/audio
  guidance appears only on Setup; copy notifications now use the current shell's
  styling instead of depending on the retired stylesheet.
- The local server was restarted and the production strip remained off-air.
  The real OBS WebSocket was offline during this handoff check: its read-only
  plan and disabled creation controls were verified, but no real scene creation,
  repositioning, audio routing, stream or recording was performed.
- Broadcast Setup now provides **Check sources**, a read-only configuration
  snapshot including Set Chase's clean URL, native strip size and crop checks.
  It does not publish, reposition or refresh the strip. Offline and incomplete
  checks never retain a green configuration result. Dark/light and responsive
  UI checks use isolated fixtures; live OBS inspection is still pending while
  OBS is closed. See `OBS_CAMERA_AUDIO_OUTPUTS.md` for scope and limitations.
- Full release gate: 2,434 Python tests and 189 JavaScript behavior tests passed.

`tools/preview_set_chase.py` starts a disposable visual QA server on port 9055.
It requires a running local server on 9040 with the English Pitch Black catalog;
it proxies local artwork but keeps all QA draft/program writes in a temporary
directory, never in production configuration.
`/qa/creator` serves the production Creator markup, styles and navigation logic
without camera or OBS handlers. `/qa/creator-viewports` adds screen-size controls
and read-only layout measurements for repeatable responsive checks.
