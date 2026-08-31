# Creator Studio: Cross-platform Events and Actions

## Status

Implementation update: the separate [LIVE Label Probe](../tools/tiktok_label_probe/README.md)
now observes inspected TikTok chat/join/follow DOM shapes, gift display notices and
unattributed Fan Club notices off-air. Gift quantity/streak semantics, stable account
IDs and Super Fan coverage remain unverified. Signed-in viewer profile cards expose
handles, but the inspected chat rows do not. This is not yet the
shared event/actions service or a trusted viewer ledger. No production alerts are
wired, and the other platform adapters remain planned.

Requirements and primary-source coverage reviewed 2026-08-30. The shared actions
service remains planned. The operator signed in to TikTok for public DOM inspection;
no account was connected to RareIQ, OAuth integration enabled or alert triggered.
Existing RareIQ broadcast connectors monitor identity/status/encoder routes;
they do not currently implement this audience-interaction service.

The requirement is one configurable system for every supported public stream event.
Platforms supply events; the same rules, viewer profiles, soundboard, TTS, overlays,
leaderboards and giveaway entry logic consume them. New event types should not require
a separate UI or a duplicate action engine.

## User-provided tracker reference

The screenshot supplied on 2026-08-30 shows a session summary with coins, gifters,
gifts, likes, peak viewers, chats, joins, shares, follows and battles. It also shows
a timestamped activity list, user/event filtering and CSV/JSON export controls.
These are visible UI observations, not verification of the tracker or its totals.

Use this as a reference for RareIQ's session activity inspector: filter by viewer,
event type and time, inspect the source/coverage, and export selected public-safe
fields. Keep aggregate totals distinct from the count of individual event records.
An unavailable metric must not silently become zero. Imports, if added later, require
schema/identity validation and must never replay the imported records as live alerts.

The accompanying claims about following arbitrary creators, complete activity capture,
gifting trends and viewer groups are unverified third-party claims, not additional
RareIQ requirements. The image contains no collector code, DOM selectors or network
trace, so it does not establish whether the tracker reads labels or an event feed.
A redacted event export could establish its data shape; collector code or a page
inspection example would be needed to establish the transport.

## Reviewed event targets

The following are documented upstream targets, not claims of tested RareIQ coverage.
Available fields, authorization and eligibility must be checked for the actual account.

| Platform | Initial event targets | Source and qualification |
| --- | --- | --- |
| TikTok | Any/specific gifts, gift streaks; follows; joins; new Super Fans; existing Super Fan joins; shares; likes; chat and custom emotes; subscription notices | [TikTokLive event catalog](https://github.com/isaackogan/TikTokLive#events), unofficial. Its schema coverage does not establish which events page labels expose. |
| Twitch | Follows; subscriptions, resub messages and gift subs; Bits/Cheers; raids; channel-point redemptions; chat/emotes | [Official EventSub catalog](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/). Each subscription has its own authorization requirements. |
| YouTube | Chat; new-member announcements, member milestone chats and gifted memberships; Super Chats, Super Stickers and gifts/Jewels where available | [Official liveChatMessages resource](https://developers.google.com/youtube/v3/live/docs/liveChatMessages). Event types/fields vary; not a universal viewer-join or subscriber feed. |
| Kick | Chat, follows, new/renewed subscriptions, gifted subscriptions, reward redemptions and KICKs gifts | [Official webhook payloads](https://github.com/KickEngineering/KickDevDocs/blob/main/events/event-types.md). Requires a separately configured event transport and authorization. |
| Rumble, Facebook, Instagram, X and later platforms | Capability review before enumerating supported audience triggers | Already relevant to RareIQ's broadcast destinations, but no audience-event coverage established by this research. Never inherit a green status from an encoder-route monitor. |

Extended catalogs can include documented TikTok battles/polls/goals and Twitch Hype
Trains, polls, predictions, goals and shoutouts. Keep beta or changing schemas distinct
from stable event types and only offer them when an adapter can validate them.

Twitch chat includes typed message fragments for emotes according to its
[chat documentation](https://dev.twitch.tv/docs/chat/send-receive-messages/).
Parse platform tokens/IDs rather than assuming an emote is any matching substring.
Kick documents webhook signatures and message IDs in its
[security reference](https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md).

## Capability truth and transport choices

- Track source documentation, adapter implementation, account authorization and
  actual event verification independently. A listed upstream type is not a working
  RareIQ trigger. Show unconfigured, authorization-needed, unverified, available,
  degraded or unsupported with a useful reason.
- The user's preferred TikTok route is a local page-label/DOM helper. Validate it
  against real representative events. Do not silently substitute a third-party
  signing service, forward cookies or claim DOM coverage for the entire Webcast schema.
- Prefer official event transports for other platforms where supported. Existing
  read-only channel-monitor tokens may not include chat, subscription or reward scopes.
  Request only the permissions needed by enabled features, with explicit consent.
- Receiving events does not require permission to post messages, ban users or change
  stream settings. Do not request those write scopes merely to play local alerts.
- Any public webhook relay, tunnel, paid provider or new hosting requirement is a
  separate deployment decision. Do not expose RareIQ's local server automatically.
- Do not treat first observed chat as proof of room entry. Expose distinct First chat
  this stream and Viewer joined triggers according to each source's actual evidence.
- A new membership and an existing member appearing are different events. Badges are
  conditions on a chat/join, not an event to replay every time the page renders them.
- Anonymous gifts remain anonymous. Missing membership status, identities, quantities
  or money fields are unknown, not invented false/zero values or inferred accounts.
- Private messages/whispers and sensitive moderation content are not broadcast alerts.
  Moderation events may cancel queued speech or suppress actions without being exposed.

## Rule editor

Each saved rule has a stable ID, name, enabled state, schema version and description:

1. Source: any connected platform or selected platform/account/stream.
2. Trigger: a registered supported event type, including provider-specific types.
3. Conditions: everyone, selected viewer(s), available member/fan role or tier, exact
   gift/emote ID, amount/count threshold, text keyword or first occurrence this stream.
4. Actions: play a sound or a bounded sound sequence; show an animation/Viewer Card;
   speak a configured TTS template; update a goal; grant a configured cosmetic badge.
5. Timing: duration, once-per-stream option, cooldown, maximum rate, action priority,
   queue/drop/coalesce behavior, and whether this rule replaces or adds to a default.
6. Outputs: off-air preview, landscape, portrait or both, with one audio emission per
   intended destination. Explicitly arm production use after preview.

Show a human-readable rule sentence and a test-event button. Explain which condition
matched or prevented an alert. Avoid arbitrary JavaScript, shell commands or chat
controlled file/URL access in rule templates.

Examples, not active rules:

- TikTok / existing Super Fan joins / selected viewer -> personal entrance clip and card.
- TikTok / gift / selected gift ID / completed streak -> gift animation and thank-you TTS.
- TikTok / likes / each 100 observed likes -> one brief community celebration.
- Twitch / emote / exact native emote ID -> assigned sound, subject to cooldown.
- Twitch / raid / minimum reported size -> welcome animation and a bounded sound cue.
- Any supported platform / first chat this stream / known viewer -> personal greeting.

## Gifts, emotes and high-volume events

- Offer Any gift and a searchable current gift catalog with platform IDs. Cache and
  refresh safely; preserve unknown/retired gift IDs in existing rules with a warning.
- Separate units (gift quantity, coin units, Bits, Jewels, native currency). Threshold
  fields only compare compatible values. Never add unrelated platform units together
  or relabel amounts as streamer earnings.
- Distinguish Unicode emoji from native custom emotes, membership emotes and optional
  third-party emote catalogs. Catalog access and asset licensing need their own review;
  a visible token name is not proof that its image or animation can be redistributed.
- Define occurrence behavior: once per message, per counted emote, or threshold in a
  bounded window. Count Unicode emoji as sequences, not isolated code units.
- Likes, repeated emotes and rapid joins need aggregation/cooldowns by default. A burst
  must not create minutes of obsolete speech or overload capture/recognition threads.
- Gift streak totals, subscription gift bundles and related chat notifications can
  describe the same action. Deduplicate transport retries and semantic duplicates;
  do not count a bundle plus each recipient notice as additional gifted support.
- Some event IDs can be updated with cumulative counts (YouTube documents this for
  gift combos). Idempotency must distinguish a duplicate from a legitimate update,
  rather than dropping every later message with the same ID.

## Shared processing and persistence

- Normalize into versioned events with platform/account/room/session, provider type,
  event ID, correlation ID when supplied, event/receipt times, actor identity, role
  evidence, emote tokens, units/amounts and collector quality/coverage.
- Each adapter supplies a typed capability schema, catalog lookup and fixture tests.
  Unknown events are diagnostic-only until mapped; never automatically attach them
  to production actions. Bounded/redacted raw payload capture is opt-in for debugging.
- Store accepted contributions once in the viewer event ledger independently of alert
  playback. Muting a sound or hitting its cooldown must not erase a valid contribution.
- Avoid silently merging matching handles across platforms. Profile links require
  reviewed identity mapping. Keep platform-specific support metrics distinguishable.
- Dispatch actions through bounded queues with per-rule/per-viewer/global limits.
  Set a maximum event age and cancel stale actions after disconnect, Stop All or
  moderation. One slow connector/voice provider must not block other platforms.
- Keep durable event/draw/award IDs separate from transient playback instances.
  Restarts restore configuration without replaying old sound alerts automatically.
- Keep giveaway entry rules independent of gifting. Gift/member alerts must not add
  entries or change equal-odds draws unless a separately reviewed future mode says so;
  the initial [giveaway specification](CREATOR_GIVEAWAYS.md) remains free/equal entry.
- Role/fan status must not bypass TTS filters, emergency mute, privacy or user opt-out.
  No raw private notes enter template variables or public leaderboard payloads.

## Delivery and acceptance order

1. Implement the shared registry, normalized events and deterministic rule evaluator,
   with synthetic fixtures for every advertised event and a human-readable test log.
2. Connect soundboard, TTS, Viewer Cards, goals and leaderboard consumers. Test rule
   precedence, cancellation, cooldowns, burst coalescing and one-copy dual-output audio.
3. Validate the opt-in TikTok label collector and official Twitch event transport.
   Expose only their verified capabilities; leave unavailable fields visibly disabled.
4. Add YouTube and Kick adapters using the same fixtures/contract. Verify permission
   expiry, webhook authenticity where applicable, quotas, retries and provider changes.
5. Review other platform event access individually; broad product scope does not imply
   every platform exposes every trigger. Never ship nonfunctional "connected" controls.
6. Cross-platform replay tests: renamed users, same handle on two platforms, anonymous
   gifts, emote tokens, repeated likes, fan arrivals, gift bundle/combo duplicates,
   late events, failed actions and restoration after restart.
7. Off-air OBS/LIVE Studio tests at 1080p/4K with both orientations, assigned cameras,
   recognition and sustained alert bursts; verify no missing/doubled stats or audio.

Platform availability changes over time. Record adapter/schema versions and actual
verification dates in the product rather than promising permanent universal coverage.
