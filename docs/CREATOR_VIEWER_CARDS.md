# Viewer Cards and Community Leaderboards

## Status

Product requirements recorded 2026-08-30. Planned, not implemented. No live viewer
data was collected, no profile was created, and no portrait or entrance audio was
generated. This extends [LIVE Events and RareIQ TTS](CREATOR_LIVE_EVENTS_TTS.md) and
the dual-format Scene Builder rather than creating a separate streaming app.

## Experience

The streamer can choose a viewer and create a personal baseball/trading-style card.
It becomes that viewer's identity in the show: artwork, title, favorite things, voice,
entrance, milestones and stats. Personalization is optional; generic viewers can
still participate without the operator designing a card for everyone.

Example only: when `sargeslay` is observed joining, display their saved card and play
the entrance clip selected by the operator. Their comments use their assigned TTS
voice if eligible and TTS is armed. Their recorded contributions update the chosen
leaderboard. The example does not assign a real sound asset or create an account.

The [giveaway system](CREATOR_GIVEAWAYS.md) can use the same approved Viewer Card
for winner reveals and link historical wins by giveaway ID. Viewer support totals,
personalization and badges must not improve giveaway odds; these are separate systems.

## Personal card and operator profile

- Public presentation: chosen display name, handle, approved avatar/portrait, custom
  title, frame/theme, earned or manually awarded badges, and selected public stats.
- Favorites: optional manually entered favorite Pokemon/cards, teams, games, sounds
  or other interests. Each field is private unless explicitly selected for display.
- Voice: installed/provider voice ID, pronunciation or spoken-name override, supported
  speech settings and fallback voice. Profile settings do not override moderation.
- Entrance: chosen licensed/user-supplied sound, animation, greeting and duration.
  Preview locally before arming. Default to once per stream, with a re-entry cooldown;
  repeated DOM rendering or a collector reconnect must not replay the entrance.
- Private notes: streamer-only notes, never included in an overlay/public-card object,
  generated-avatar prompt, TTS message or public export. Avoid collecting sensitive
  personal information; do not infer preferences or private traits from chat history.
- Controls: enable/disable personalization, preview, hide from public leaderboards,
  export, delete, and explicit identity correction with an audit record.

## AI artwork

- Start with a generic avatar or optional user-supplied image. Offer a generated
  character/mascot based on preferences the operator explicitly selects.
- Use a real person's likeness only when they have agreed and supplied an appropriate
  reference. Do not automatically scrape profile photos or infer demographic traits.
- Show the prompt and result for approval before replacing saved artwork or sending
  it on air. Keep generated-art provenance separate from the public card description.
- Reuse approved assets across entrances and rankings. No generation on every join;
  expose provider/cost before paid generation and keep private notes out of requests.
- Design card artwork for complete visibility in landscape and portrait. It must not
  resemble a fake officially issued credential or claim affiliation with a card brand.

## Identity and event history

- Key profiles by an internal viewer ID plus platform and broadcaster/community scope.
  Link a stable platform account ID when the collector provides one. Store handles
  and display-name history separately; display-name equality is not an identity match.
- If page labels expose only a handle, mark identity provisional. Renames or reused
  handles require a reviewed link; never silently merge two people's contributions.
- Keep an append-only contribution ledger with adjustments/corrections, not mutable
  totals as the only source of truth. Store the event type, source, room/stream ID,
  viewer ID, source event time when provided, receipt time, units and quality flags.
- Use stable provider event IDs for idempotency when available. A DOM collector needs
  tested occurrence tracking and streak identifiers; a hash of text alone would both
  miss real repeated messages and fail to distinguish reconstructed page history.
- Deduplicate gift streak updates by recording verified deltas or one final total,
  never summing cumulative repeat counts. Preserve source units and gift metadata at
  observation time; missing quantities/coin values are unknown, not estimated cash.
- Record tracking start and collector coverage gaps. Reconnect/backfill can repair
  history only with verifiable events, and must not replay entrance or gift effects.
- Test events use separate storage or a strictly isolated namespace and never affect
  real statistics, rewards, production overlays or the actual leaderboard rankings.
- Persist atomically with schema versions, migrations, backup/restore and indexed
  time/viewer queries. Rebuild derived period totals from the ledger after corrections.
  Live stats updates must not block camera capture, recognition or audio playback.
- Bound raw transport logs and queues; do not retain comment text just to count chat
  activity. Define retention, export and deletion for stored account IDs and events.

## Statistics and time windows

Show each metric separately, with current-stream, daily, weekly, monthly, yearly
and all-time selectors. A gift count is not interchangeable with coin units or chats.

- Gifts: quantities by gift type and source-reported coin units where available.
  Do not label coins as dollars, streamer payout or confirmed earnings.
- Session summary: distinct identified gifters, gift quantities, chats, observed
  likes/shares/follows/joins and other supported event totals. Count anonymous support
  without inventing distinct viewer identities. Keep quantities separate from the
  number of event records, including cumulative gift/like updates.
- Peak concurrent viewers requires observed room viewer-count samples, not summing
  joins. Label it as an observed peak with collection coverage; show unavailable when
  the selected collector does not expose this information.
- Community activity: observed chat messages, likes/shares when actually exposed,
  distinct streams attended and first/last observed dates. Attendance is an observation,
  not continuous watch time; one join does not establish how long a viewer stayed.
- Rewards: operator-issued badges/milestones and optional explicitly configured points,
  kept separate from monetary support. Personal recognition need not require spending.
- Periods: calendar day, week, month and year in the streamer's configured timezone;
  show exact start/end and configure week start. Store timestamps in UTC and handle
  daylight-saving transitions. Do not silently label a rolling 30 days as a month.
- All time: all retained, recorded contributions since tracking began, with that date
  visible. No promise to recover previous years of TikTok activity from page labels.
- Incomplete feeds: display observed totals and coverage status. A blank or unreported
  field is not zero; a disconnected collector is not evidence that nobody contributed.

## Branded leaderboard overlays

- Presets: current-stream supporters, daily/weekly/monthly/yearly supporters,
  all-time supporters and community activity. Allow metric and period selection.
- Options: top-N, avatars or mini trading cards, ranks, ties, movement animation,
  exact metric label, period dates and optional milestones. Deterministic ranking
  should not reshuffle ties at every refresh; use a documented stable tie-break.
- Share one statistics snapshot across landscape/portrait renderers with separate
  layout/safe-area settings. Reuse RareIQ brand tokens and the saved scene model.
- Entrance card, leaderboards and milestone celebrations reference the same viewer
  profile, but the public projection exposes only allowlisted fields. Do not send
  private notes to a browser and merely hide them with CSS.
- Provide explicit off-air preview/publish, hide/pause and privacy suppression. One
  event may animate both orientations but must not produce duplicate audio per output.
- Disconnection shows stale/paused state without losing the saved ranks or claiming
  a zero total. Avoid rapid whole-panel re-renders during bursts of activity.

## RareIQ Rewards and Recognition

Requirement added 2026-08-30: give viewers a personal sense of belonging and a way
to earn recognition. Planned, not implemented. The following are proposed defaults,
not active earning rules, awarded badges or promised prizes.

Build this into the existing Viewer Card and Creator Studio community workspace,
using the same identity, event history, rules and overlay services. Do not create a
second viewer database, independent score counter or separate streaming app.

### First release: recognition before a points shop

- Non-spendable community XP and configurable ranks, for example Rookie, Regular,
  All-Star and Legend. These are RareIQ titles, not platform roles or moderation rights.
  Spending money is not required to progress; monetary support stays a separate metric.
- Earned badges for confirmed milestones such as attendance across distinct streams.
  Helpful Viewer, Community MVP and similar qualitative awards are issued manually,
  with an optional reason; do not decide helpfulness from raw message volume.
- Unlocks: approved card frames, custom titles, entrance animations/sounds and assigned
  voices. Reuse existing approved assets. Unlocking a voice does not purchase a voice
  license, bypass TTS moderation or enable an unconfigured provider.
- An operator-controlled viewer spotlight and milestone card reveal in landscape and
  portrait. Give the same viewer one celebration, not duplicate audio from each output.
  Include preview, pause, cooldown, queue limit, reduced motion and Stop All.
- Show current rank, earned badges and the next optional milestone on the Viewer Card.
  Offer opt-out/private participation and a hidden-from-rankings setting. No public
  shaming, loss of earned ranks for taking a break or required daily streak.
- Optional shared community goals can unlock a planned show moment, such as a bonus
  card reveal. Show the actual rule/progress; no automatic prize or spending commitment.

### Earning and award integrity

- Start with operator-issued badges and manually approved recognition while the
  collector is experimental. Automatic XP requires confirmed viewer identity and an
  explicitly eligible event source. The current label probe's diagnostic observations
  cannot earn rewards: display names alone must never credit or merge viewer accounts.
- Proposed automatic attendance rule: one award per confirmed viewer per distinct
  stream, with configurable caps. Rejoins, copied rows and collector reconnects are
  not new attendance. Observed attendance is not measured watch time.
- Avoid per-message/per-like farming defaults. Any optional activity rule requires
  eligibility, cooldowns and per-viewer/per-stream caps. Unsupported metrics remain
  unavailable; missing data is not zero or evidence of misconduct.
- Persist awards in the shared append-only ledger with award ID, viewer/community,
  rule/version, qualifying event or milestone, time and manual issuer/reason where
  relevant. Enforce a unique qualifying-award key transactionally. Concurrent events,
  retries, restart and two output orientations cannot issue duplicate rewards.
- Reversals/corrections append an auditable adjustment. Recalculate affected ranks and
  entitlements without replaying celebrations. Rule changes apply prospectively;
  historical recalculation requires an explicit reviewed operation.
- Public card/overlay projections expose only approved recognition fields. Private
  notes, reward adjustment reasons and moderation history stay operator-only.

### Later: optional redeemable rewards

If wanted after the recognition release, add a separate spendable points balance;
redeeming points must not lower earned XP/rank. Begin with non-cash, non-transferable
show perks such as choosing an approved sound or requesting a bounded shout-out.
Use a transactional reservation/approval/fulfillment/refund flow with stock limits,
cooldowns and unique redemption IDs. Never charge twice after a timeout, consume
points for a rejected request or let a reward bypass moderation and emergency mute.

Keep rewards entirely separate from the free, equal-odds giveaway workflow. XP,
points, ranks, purchases and badges do not buy entries or improve giveaway odds.
Any physical-prize or cash-equivalent expansion needs separately defined rules and
fulfillment; it is not part of the initial recognition release.

### Rewards acceptance order

1. Manual award/edit/reversal; persistence, public/private projection and opt-out.
2. Eligible identity/event checks; duplicate awards, concurrent requests, caps,
   reconnect history, rule versions and isolated test data.
3. XP/rank/milestone boundaries, corrections and distinct-stream attendance; no
   accidental gift-to-XP conversion or fabricated watch time.
4. Long names, missing artwork and both output orientations; one-copy audio,
   cooldowns, stale-event suppression, restart recovery and Stop All.
5. Verify that awards never affect giveaway entry count, eligibility or draw odds.
6. Only for the later shop: insufficient balance, simultaneous redemptions, declined
   requests, crash recovery, stock reservations, fulfillment and single refunds.

## Collection and safety boundary

Page-label collection is the user's preferred route. The separate off-air
[label probe](../tools/tiktok_label_probe/README.md) maps inspected chat, join,
follow, gift-display and Fan Club notice shapes. It does not establish complete
coverage, stable viewer IDs, verified gift totals or reward eligibility. Keep the
identity, statistics, rules and TTS independent of this experimental transport.

Any browser helper needs narrow host permissions, explicit opt-in and a bounded,
authenticated local ingestion channel. An arbitrary web page must not be able to
forge gifts or trigger sounds through an unauthenticated localhost endpoint.
Treat usernames/comments as plain untrusted text, never HTML, SSML, code or file paths.

## Build and acceptance order

1. Viewer profile, public/private projections and event ledger. Test identity renames,
   provisional handles, duplicate IDs, corrections, persistence and deletion/export.
2. Period queries and stat summaries. Test local midnight, configured week start,
   month/year boundaries, daylight saving, late events and coverage gaps.
3. Manual profile editor, preview card and three-voice TTS integration. Check voice
   fallbacks, private-note isolation, missing artwork and full-card responsive layout.
4. Simulated personalized entrances, gifts and milestones. Test repeated joins,
   cumulative streaks, cooldowns, burst queues, cancellation and one-copy audio.
5. Opt-in page-label collector. Validate actual fields against the native LIVE view,
   including page rerenders and reconnect history. Unsupported metrics remain disabled.
6. Leaderboard and approved avatar assets in both orientations. Check ties, privacy,
   draft/Program publication, clipped text and OBS/LIVE Studio sound/image routing.
7. Combined soak test: assigned cameras, recognition, soundboard, TTS, entrances and
   rankings. Exercise restart/recovery without lost counts, replay storms or regressions.

Do not advertise this as complete until the real application tests pass. In-memory
voice synthesis, simulated events and a styled card preview are separate milestones.
