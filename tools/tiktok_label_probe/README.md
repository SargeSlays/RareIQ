# RareIQ LIVE Label Probe (experimental, off-air)

This is a working inspection prototype, **not the production LIVE connector**.
It is independent of the camera/OBS server. It sends no network requests, reads no
cookies/session stores, and does not start alerts, TTS, viewer contributions or
giveaway entries. No extension was installed automatically.

## What was actually inspected

On 2026-08-30, public TikTok LIVE pages were inspected before and after the operator
signed in through the normal browser UI. Their rendered chat exposed:

| Rendered marker | Observed use |
| --- | --- |
| `data-e2e="live-chat-container"` | Chat container |
| `data-e2e="chat-message"` | Comment row |
| `data-e2e="message-owner-name"` | Display name inside the row |
| `data-e2e="enter-message"` | Changing viewer `joined` notice |
| `data-e2e="social-message"` | `followed the host` notice, with owner and notice span |
| Unlabelled row inside a `data-index` list wrapper | Fan Club announcement, direct text after an icon |
| Unlabelled row with owner wrapper, `sent`, gift-name span, image span, `×`, quantity | Gift notice; full structure inspected for Heart Me ×1, Treasure Clover ×2 and GOAT ×1 |

The tested row structure has an avatar and a content column containing an owner
header and a message body. The parser validates this structure rather than using
generated CSS hashes or concatenating badges into chat. It fails closed if the
structure or notice wording changes. Version 0.3.0 adds the inspected English gift
notice to the existing follow and Fan Club mappings. Ordinary comments containing
gift/follow/member wording remain comments, not events of those types.

The Fan Club notice did not expose a separate owner element. Its actor remains
**unattributed**, with no name/handle/ID extracted from prose. Its complete text is
only included when the operator opts into personal-text export. It is **not** a
paid subscription or Super Fan event. A `data-index` value is a transient list
position, never a provider event ID or authoritative membership total.

Chat and join rows changed during inspection. Their rendered attributes contained
no stable account ID, event ID or provider timestamp, and names were not profile
links. Therefore display names **cannot safely identify a particular viewer** for
personal sound rules. No identity is inferred from avatars, hidden React state or
network/session data. Fixtures use synthetic names and text, not real chat logs.

Gift rows now parse as **`gift.notice.observed`**, not confirmed transactions. Only
the separate owner, gift-name text and displayed positive integer quantity are
retained. Optional level/fan/rank badges are excluded. Unknown layouts, nested gift
labels and unsupported quantity formats fail closed; quantities are bounded to
1–999,999,999 and labels to 160 characters, not silently truncated or coerced.
Gift image URLs are not stored or used to invent gift IDs.

Each gift record has `gift.name`, `gift.displayed_quantity` and
`gift.quantity_semantics: "unknown"`. Gift ID, streak ID/completion and coin value
remain `null`. **Whether the displayed count is incremental or cumulative has not
been verified.** A count changing from 1 to 2 can produce two display observations;
it must never be summed into three gifts. The Observed counter counts retained
observations before buffer eviction, not gifts, gift units or verified transactions.
Same-node redraws and ambiguous cloned repeats use the existing conservative
deduplication rules. No contribution or alert eligibility is enabled.

Individual likes, shares, Super Fans and paid memberships remain unverified.
The public page also showed rounded counters; those are not authoritative
per-viewer contributions.

After normal sign-in, explicitly clicking a viewer's display name opened a public
profile card with an `/@handle` link. That handle was **not present in the inspected
chat row**, and no immutable account ID was exposed. The probe does not open profile
cards automatically or associate display-name matches with previously seen handles.
Handles are not stable account IDs. No login wall, hidden state, cookies or session
data were bypassed. Signing in to the browser does not install the extension or
connect TikTok to RareIQ; actual Chrome extension testing is still outstanding.

## Try in Chrome or Edge when ready

1. Open the browser's Extensions page and enable Developer mode.
2. Choose **Load unpacked** and select this `tools/tiktok_label_probe` directory.
3. Open the specific TikTok `/@username/live` page you want to inspect.
4. Open **RareIQ LIVE Label Probe** and choose **Start inspection**.
5. Read the off-air counters, then **Stop**. **Export JSON** redacts names, chat and notices
   unless you explicitly check the personal-text option. **Clear observations**
   stops collection and empties the buffer.

The helper requests only `activeTab` and `scripting`, not permanent all-site access.
It starts only after a click, stays confined to that LIVE room, and stops on room
navigation or reload. Closing the popup does not stop an active inspection.
Observations are memory-only, retaining at most the latest 500. No background
collector follows other creators, and no import/bridge into RareIQ is enabled.

After updating this unpacked extension, reload both the extension and the LIVE tab.
Version mismatches block collection rather than silently running an older parser;
Stop/Clear remain available. The popup stays targeted at its original tab/room.
Stop can interrupt refresh/startup, and late replies cannot overwrite it. Failed
requests show **Connection unconfirmed**, not a false stopped/connected badge.
If Stop cannot be acknowledged, reload the LIVE tab to stop collection. Opening
`popup.html` as an ordinary webpage is a disabled visual preview, not a connection.

## Accuracy and lifecycle boundaries

- Existing rows are baselined on start/reconnection; they are not replayed.
- Same-node repaints are ignored. Identical new rows inside five seconds are
  conservatively suppressed and counted as ambiguous: genuine repeats can be lost.
  Without provider IDs, exact deduplication is impossible from these labels alone.
- Tab reload/new-room collection starts a separate session. Observation IDs are
  local IDs, not TikTok event IDs. Provider event time and stable viewer ID remain
  `null`; `observed_at` is the local receipt time.
- Chat replacement/disappearance increments a coverage-gap counter and rebaselines.
  Labels arriving and disappearing inside the 150 ms batch interval can be missed.
  Initial history that arrives after baseline cannot be distinguished from new chat.
- Recycled rows and changed message bodies can yield new observations. There is no
  claim of complete joins, watch time, hidden/filtered chat or historical coverage.
- Gift quantities are display snapshots, never additive. Identical gift notices can
  be suppressed as ambiguous, and updated counters can yield another observation.
  Neither case establishes an event ID, gift streak boundary or authoritative total.
- Parsing is scoped to the chat container, with a 250-row safety limit, bounded
  dedup memory and record buffer. Unexpected layouts are skipped visibly.
- Exported observations are untrusted diagnostics, never verified ledger entries,
  giveaway tickets or executable commands. Raw markup/asset URLs are not retained.

## Tests

Run `node --test tests/browser/tiktok_label_probe.test.cjs` from the repository root.
The existing release gate discovers this suite automatically. Tests cover mapping,
schema drift, URL scope, history suppression, repeat ambiguity, recycling, bounded
memory, redaction, stop/clear, room navigation and chat remounts. Gift tests cover
badge isolation, malformed quantities, native SVG, quantity mutations, non-additive
semantics, redaction and export-copy isolation. The Chrome API
boundary is mocked for injection, Stop during startup/polling, late replies,
timeouts, permission errors, room pinning, version mismatch and popup closure.

Verified 2026-08-30: the full RareIQ release gate passed 2,350 Python tests and
144 JavaScript tests, including all 43 probe tests. A real-browser synthetic
DOM/MutationObserver run passed for all five mapped types plus a gift quantity
mutation, including the actual virtual-row selector and native SVG namespace.
The 380-pixel-wide popup was visually reviewed; its normal preview height measured
576.4 pixels, with the last control ending at 560.4 pixels. Long diagnostics
scroll within their text area so the controls remain reachable.

Extension installation and collection through actual
Chrome extension permissions still require a separate live test; they were not claimed
by the unit tests or the ordinary-browser preview. RareIQ and OBS were not restarted.

For native browser DOM/MutationObserver testing, serve **only this directory** on a
temporary loopback port and open `self_test.html`. It uses synthetic rows and has no
platform connection. This does not test extension installation/permissions in Chrome.

Before production: validate installation against the user's chosen LIVE, capture
gift ID/quantity/streak semantics and Super Fan contracts, resolve stable identity and authenticated
event transport, and add an explicitly paired local bridge. Do not enable broad
CORS or let arbitrary websites invoke RareIQ's soundboard/OBS endpoints.

The browser mechanisms are documented by
[MDN (MutationObserver)](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver)
and [Chrome (activeTab)](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab).
These explain the implementation mechanism, not TikTok's completeness or stability.
