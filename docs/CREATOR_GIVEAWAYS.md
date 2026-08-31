# Creator Studio: Giveaways and Winner Reveals

## Status and purpose

Requirements recorded 2026-08-30. Planned, not implemented. No real giveaway,
participant list, prize commitment or random draw has been created.

Build an entertaining, equally weighted giveaway tool inside RareIQ. The streamer
can run a wheel or random-name reveal, celebrate with the winner's optional Viewer
Card, and find the complete giveaway record later using its unique ID. It uses the
shared viewer identity, Scene Builder and broadcast audio foundations.

## Operator workflow

1. Create a giveaway: unique ID, title, prize description or optional inventory-card
   reference, stream association, entry method, eligibility rules and private notes.
2. Preview the landscape/portrait overlay, sounds and reveal style off-air.
3. Open free entries through an explicit method such as a chat keyword, or a reviewed
   manual/imported list. Show participant count, entry acknowledgments and collection
   health. Do not assume everyone watching is captured by a page-label collector.
4. Close entries and review duplicates, identity uncertainty and exclusions. Save the
   rules and eligible participant snapshot, then explicitly lock it for the draw.
5. Draw once. Save the authoritative result transactionally before starting the
   animation. All outputs reveal that same result.
6. Track winner contact/claim and fulfillment, add notes, and close the record. No
   automatic public message, shipping purchase or prize transfer is implied.

States: draft, open, entries closed, locked, drawn, completed or canceled. Winner
claim/fulfillment is tracked separately, so an unclaimed prize does not erase a draw.

## Equal-odds random selection

- Initial scope is free entry and one entry per eligible viewer account. Deduplicate
  by confirmed identity, not display name. A custom Viewer Card is not required.
  Do not claim to prove one human per account or to detect every alternate account.
- Gifting history, coin totals, subscriber status, TTS voice, badges and personal
  favorites must not add weight or choose a winner. Paid-entry/weighted raffles are
  outside this initial scope. Review applicable platform/promotion rules before use;
  the software must not advertise blanket legal compliance.
- Use an OS-backed cryptographic random source on the server, for example Python's
  [secrets.randbelow(n)](https://docs.python.org/3/library/secrets.html), to choose
  an index uniformly from the frozen eligible list. Do not use animation timing,
  wheel physics, Math.random, time-based seeds or biased random-by-sort selection.
- No configurable production seed, hidden preferred-winner option, repeated sampling
  until an operator likes the result, or predictable RNG fallback. If secure random
  selection is unavailable, stop with a visible error and leave the draw uncommitted.
- For several prizes, sample without replacement from the eligible pool. Persist
  winners and prize order together; do not accidentally let one account win twice
  when the declared rules say unique winners.
- Exactly one eligible account has probability 1; zero eligible accounts disables
  drawing. These are truthful edge cases, not animation failures.
- Cryptographic randomness and equal eligibility give the intended equal-odds draw.
  Do not call a locally editable history or a participant hash independently verified,
  tamper-proof or mathematically proven fair. Publicly verifiable draws would need
  a separately designed verification protocol and security review.

## Unique IDs and saved history

- Generate a canonical random identifier at creation, enforce a database uniqueness
  constraint and retry on collision. Keep a human-readable short giveaway code for
  search/overlay use, also checked for uniqueness. A short code is not the only key.
- Persist IDs across restarts, exports and backup/restore. Cloning a giveaway creates
  a new ID, with an optional source-record link; it never reuses the original.
- Give each draw round its own ID and idempotency key. Associate the prize and winner
  with the canonical giveaway/draw IDs, not an unstable current display name.
- Store rules/version, entrant identities and display-name snapshot, entry open/close
  times, collector coverage, exclusions and reasons, locked pool version/hash,
  participant count, draw algorithm/version, selected index/result and draw time.
  A hash detects differences against a trusted record; it does not prove RNG fairness.
- Save timestamps in UTC and display in the configured timezone. Search/filter history
  by giveaway code, title, date, stream, winner and claim/fulfillment state.
- Preserve a timestamped notes/change history. Notes can cover prize details, contact
  attempts, claim deadlines and fulfillment. Keep personal contact/shipping details
  in private fields, not public notes or raw event logs.
- Provide operator-only CSV/JSON export of records with private fields opt-in, and a
  separate public-safe draw receipt containing code, prize, draw time, entrant count
  and public winner identity. Public receipts do not expose contact details or notes.
- Define retention and deletion behavior. Private details can be removed/redacted
  without silently rewriting who originally won; preserve only necessary draw metadata.

## Draw integrity and rerolls

- Lock the participant snapshot and use a transactional draw/state transition.
  Concurrent clicks or clients cannot create two winners for the same draw request.
- Repeating a request returns the existing result. A timeout after commit, restart or
  reloaded overlay must resume/reveal that result, never silently draw again.
- Late chat, nickname changes or new gifts cannot edit a locked pool. A correction
  before any draw requires an explicit unlock/new snapshot with an audit record.
- If redraws are permitted by the saved rules, require an explicit action and reason.
  Retain the original draw and winner, mark its disposition, and create a linked new
  draw. Record the replacement pool and exclusions, including already-awarded winners.
- Never replace a random winner with an operator-selected person while labeling it a
  random draw. Manual rewards belong to a separate clearly labeled workflow.
- Disconnect gaps or uncertain identities must be visible before locking. Allow fair
  entry review before drawing, not silent pool changes after seeing the result.

## Overlay treatments

- Wheel: equal visual segments for equal entries where legible, countdown, optional
  tick sounds, deceleration and winner celebration. The server's result determines
  the landing segment; the browser does not perform another draw.
- Name picker: animated names or mini Viewer Cards followed by a winner reveal.
  Prefer this style for large pools where wheel labels become unreadable. Rendering
  a subset of names for performance must never shrink the actual eligible pool.
- Optional winner card flip, confetti, approved entrance sound and TTS announcement.
  No flashing effects required; include reduced-motion and sound-off controls.
- Landscape and portrait use one giveaway/result state, with independent layout and
  safe areas. Reveal at a shared start time and route audio once per destination.
- Show title, prize, entrant count, giveaway code and current phase. Long names,
  missing avatars and large participant counts must not break either orientation.
- Reopening an overlay shows the current result without replaying celebration audio.
  Test mode is visibly labeled and isolated from real entrants, wins and fulfillment.

## Security and privacy

Authenticated operator controls create/lock/draw/redraw/edit records. An overlay has
read-only, public-safe access; knowing a giveaway ID must not authorize a draw or
reveal notes. Do not ship private fields and merely hide them in CSS.

Treat chat keywords, names and imported notes as untrusted text. Imports validate
size, identity format and duplicates, and CSV exports guard spreadsheet formulas.
Only configured actions can run; chat cannot choose the prize, alter odds or invoke
arbitrary code. Never send private notes to TTS or image-generation services.

## Acceptance tests, in order

1. ID uniqueness, collision retry, cloning, persistence and lookup after restore.
2. Eligible entry ingestion: duplicate comments, account aliases, Unicode names,
   manual corrections, reconnect history, late entries and missing identity fields.
3. Lock/freeze behavior: exact recorded pool, rules and exclusions; no post-draw edits.
4. Selection: empty/single/many entrants; all valid indices reachable through an
   injected test RNG; production CSPRNG usage; unique multi-winner selection and failure.
   Distribution smoke tests are diagnostic, not proof of fairness or flaky CI gates.
5. Simultaneous draw requests, request replay and failure/restart around commit.
   Assert one saved result and no accidental redraw or duplicated celebration.
6. Rerolls: original winner retained, reason required, replacement pool recorded,
   rules honored and no hidden weighting from profiles or contribution totals.
7. Private/public projections, authenticated controls, safe exports, note edits,
   redaction, claim/fulfillment state and Viewer Card history links.
8. Wheel/name-picker visuals and winner identity match the saved result in both
   orientations. Check long names, missing art, large pools, reduced motion and audio.
9. Off-air OBS and LIVE Studio integration plus concurrent recognition/camera/TTS
   soak tests. No real prize giveaway or public broadcast during automated testing.

Completion requires implemented behavior and these tests, not merely a wheel demo.
