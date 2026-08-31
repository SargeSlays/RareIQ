# Creator Studio: LIVE events and RareIQ TTS

## Status and scope

Implementation update, 2026-08-30: an isolated [LIVE Label Probe](../tools/tiktok_label_probe/README.md)
now implements opt-in, off-air rendered chat/join/follow observation, gift display
notices and unattributed Fan Club notices using structures inspected on real public
LIVE pages. Gift quantities are non-additive snapshots; gift IDs, quantity/streak
semantics and coin values remain unknown. Signed-in public profile cards expose
handles, but the inspected chat rows do not expose stable viewer/event IDs. Fan Club notices
are not paid subscriptions or Super Fan events. This prototype is not installed automatically
or connected to RareIQ production actions; the TTS/rule/ledger features below remain
planned. See the probe README for tests and explicit coverage limits.

Requested and researched on 2026-08-30. This is a delivery specification, not an
implemented production feature. The operator signed in to TikTok for public DOM
inspection; no TikTok account was connected to RareIQ, dependency installed, paid
service enabled, OBS scene changed or RareIQ server restarted for this research.

The intended operator experience is one RareIQ workspace: select the LIVE account,
assign event reactions, choose chat voices, preview everything off-air, then arm
alerts and speech for the landscape and portrait outputs. Preserve the new RareIQ
design tokens and existing camera/recognition workflow.

Scope expanded on 2026-08-30: personalized viewer trading cards, contribution history,
favorites, private notes, AI avatars and leaderboards now share this event system.
See [Viewer Cards](CREATOR_VIEWER_CARDS.md). Establish viewer identity and event-history
rules before enabling live collection; the UI is still planned, not implemented.

Further scope: [Cross-platform Events and Actions](CREATOR_EVENT_ACTIONS.md) is the
shared rule/adapter specification for TikTok, Twitch and other platforms. This file
retains the TTS and initial TikTok transport detail; do not implement a separate rule
engine for each platform or assume publishing-monitor credentials authorize chat.

## Verified feasibility and constraints

- The maintained [Python TikTokLive client](https://github.com/isaackogan/TikTokLive)
  documents comments, gifts, joins and other LIVE events through TikTok's Webcast
  connection. This is unofficial event access, not access to TikTok's source code.
  Its README cautions that the reverse-engineered client is not production-ready.
- The [Node connector](https://github.com/zerodytrash/TikTok-Live-Connector) documents
  third-party signing, free community limits and optional higher-limit API keys.
  Its authenticated mode can transmit session credentials to the signing provider.
  Never silently enable that mode, import browser cookies or promise zero dependencies.
- Both repositories currently describe modified AGPL licensing. The
  [Python license](https://github.com/isaackogan/TikTokLive/blob/master/LICENSE)
  contains integration exceptions and hosted-service restrictions. Review the exact
  pinned version and intended distribution before adoption; this research is not
  legal clearance to redistribute a connector or offer a hosted relay.
- Do not mark TikTok publishing supported merely because LIVE events connect. Stream
  eligibility, ingest and LIVE Studio picture/audio routing remain separate gates.
- Three distinct local voices were enumerated and exercised: Microsoft David,
  Microsoft Mark and Microsoft Zira. Each produced an in-memory RIFF/WAV buffer
  (183234, 150822 and 166478 bytes respectively) without speaker playback. Duplicate
  Desktop registrations are not additional unique voices. This checks synthesis only.
- Installed voice discovery uses Microsoft's
  [SpeechSynthesizer API](https://learn.microsoft.com/en-us/dotnet/api/system.speech.synthesis.speechsynthesizer.getinstalledvoices).
  Enumerate capabilities per machine instead of promising these voices everywhere.
  Use installed voices; do not redistribute Windows voice assets.
- [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) is a later local neural-voice
  candidate, with Apache-licensed model weights according to its model card. Review
  the engine, voice assets and dependencies together, and benchmark alongside all
  four cameras before deciding to ship it. It has not been installed or benchmarked.

## Delivery sequence

### 1. Local RareIQ TTS

- Own the UI, queue, moderation, pronunciation overrides and output integration;
  identify the underlying voice engine honestly. Training a proprietary speech model
  or cloning real people's voices is not required for the initial feature.
- Provide manual text preview and three installed starter voices where available,
  voice selection, speech rate, volume and optional username reading. Show unsupported
  controls as unavailable rather than pretending every engine supports pitch/styles.
- Run synthesis off the recognition/event loop with cancellation and a deadline.
  Generate audio once per utterance. Use a bounded temporary audio cache, validated
  asset identifiers and expiry; never interpret chat as SSML, code or a shell command.
- Provide a visible queue, pause, skip and immediate Stop All. Old messages expire;
  a stopped synthesis job must not reappear after it eventually returns.
- Route speech into the shared broadcast audio path with a separate TTS gain/mute.
  Each destination should hear one copy even with several browser sources open.
  Optional local monitoring and soundboard ducking must have explicit controls.

### 2. Alert rules and safe simulation

- Use the cross-platform event registry rather than limiting the UI to three hardcoded
  triggers. Support any/specific gifts, new follows, joins, new/existing fan conditions,
  shares, likes, chat/emotes and each adapter's additional verified event schemas.
- Support specific viewer IDs, specific gift IDs and eligible chat events. Display
  names are presentation, not identity keys. Gift names and amounts come from the
  event/catalog; do not hardcode a gift's cash value or assume IDs are permanent.
- Actions are operator-approved text/image/animation layers, soundboard cues and TTS
  templates. Allow per-rule duration, priority, cooldown and independent orientation
  placement. Never give arbitrary chat access to shell commands, files or OBS control.
- Track provider event IDs and room/session identity. Deduplicate messages and finish
  streakable gifts once, rather than summing cumulative updates multiple times.
- Keep an event simulator with named-viewer, gift, streak, chat and disconnect cases.
  Simulator events are visibly TEST and cannot publish to live output unless the
  operator explicitly chooses an on-air test. No real gifts or spending needed.

### 3. Opt-in TikTok LIVE adapter

- The user prefers reading page labels/HTML elements. Evaluate an opt-in local browser
  helper first and inspect actual labels for chat, joins and gifts. A conceptual DOM
  approach is not proof that TikTok exposes all required fields. Keep the adapter
  interchangeable with other reviewed transports; do not silently fall back to a
  third-party provider or authenticated session sharing.
- Report which events and identity fields the selected collector actually observes.
  Missing gift units, stable IDs or history remain unknown, not zero or fabricated.
  Track collection coverage and reconnect gaps for the viewer statistics service.
- Resolve connector/licensing/provider choices first. Start disconnected and disclose
  the provider, account, data sent and current capability state before connecting.
- Normalize only required fields into a provider-neutral schema: room/session ID,
  event ID/type/time, stable viewer ID, escaped display name, comment and gift/streak
  metadata. Do not retain raw chat history by default or log credentials.
- Handle offline rooms, unavailable joins, rate limits, removed event fields and
  disconnects honestly. Join alerts are best effort; do not claim to detect every
  silent viewer. Keep retry backoff bounded and never replay stale welcome/gift alerts.
- Automatic TTS is explicitly armed. Offer all filtered chat, allowlisted viewers or
  moderator-approved messages, with blocklists, URL/spam filtering, per-user cooldowns,
  length limits and maximum queue age. Moderation deletion cancels queued speech when
  supported; already-broadcast audio cannot be recalled.

### 4. Dual-format production integration

- Drive landscape and portrait alert layers from the same event IDs and timing, but
  preserve their independent size/position. Reuse the Scene Builder's saved model and
  draft/Program boundary rather than building a separate TikTok-only layout system.
- Keep one speech producer and deliberate output subscriptions. A video-only virtual
  camera does not carry TTS audio; validate the separate LIVE Studio audio route.
- Restore settings after restart without resuming old chat or triggering old gifts.
  Connector failure must leave card scanning, soundboard and existing outputs usable.

## Ordered acceptance checklist

1. Enumerate and synthesize with each starter voice; handle missing/disabled voices.
2. Verify manual TTS reaches the intended off-air output exactly once, with independent
   volume, monitor and mute controls. Test alongside soundboard playback.
3. Exercise queue saturation, message expiry, Unicode, URLs, repeat spam, moderation,
   provider timeout, cancellation, skip and emergency Stop All.
4. Replay simulated joins, repeat joins, gift streaks, duplicate IDs and reconnects;
   assert one intended reaction and no historical alert storm.
5. Validate the opt-in connector on the user's LIVE, without purchases or automatic
   broadcasting; compare received chat and gift events with the native client.
6. Check simultaneous OBS landscape and LIVE Studio portrait for matching reactions,
   safe text bounds, full-card visibility, audio sync and absence of doubled speech.
7. Run a sustained test with all assigned cameras, recognition, soundboard and TTS;
   measure synthesis latency and dropped frames, then test restart/reconnect recovery.

Completion requires the checklist's real application tests, not just a connected
status badge or the successful local synthesis probes recorded above.
