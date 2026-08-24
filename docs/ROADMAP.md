# RareIQ Roadmap

## Active
- X.4 Fast Pipeline stabilization
- X.5 WAR BUILD Foundation

## Next
- X.5.1 Recognition Engine 2.0 integration
- X.5.2 Collection Intelligence
- X.5.3 Creator Studio
- X.5.4 Pack Battle Mode
- X.5.5 Marketplace Intelligence
- X.5.6 In-app Help Chat Agent and versioned operations manual

### X.5.3 Creator Studio Overlay Requirement

- Pack-reveal suspense overlay:
  - Track the presenter's card-by-card progression through a pack and build tension as the expected rare slot approaches.
  - Hold the payoff until the rare card is actually revealed and recognition confidence is stable.
  - Drive the reaction from a configurable hit tier rather than card rarity alone; market value, scarcity, chase status, and operator overrides may contribute.
  - Miss / low hit: brief deflation or "aww" reaction, then reset cleanly.
  - Medium hit: energetic "YES!" celebration.
  - Grail hit: maximum-event treatment with the requested "OH MY FUCKING GOD!! IT'S JOHN CENA"-style reveal and a "bop badada" wrestling-style sting.
  - Make reaction copy, audio, intensity, duration, and streamer-safe language configurable. Use licensed or user-supplied audio rather than bundling protected broadcast music.
  - Include cooldowns, spoiler prevention, false-positive cancellation, manual trigger/override, and an instant disable control for live production safety.

## Parked
- Hybrid card-library storage and retrieval
  - Never require the complete global image library to remain on the user's machine.
  - Let users download selected games, languages, sets, or an offline event pack.
  - Retrieve missing reference images and metadata from the configured catalog/database on demand.
  - Cache fetched assets locally with a configurable storage budget, visible usage, expiry policy, pin/offline controls, and safe least-recently-used eviction.
  - Keep compact identity and visual-search indexes locally where practical so recognition can locate a candidate before downloading its full-resolution reference image.
  - Provide explicit offline, metered-network, image-quality, and "download while idle" preferences.
  - Verify checksums and catalog versions; never silently replace user-corrected identities or locally pinned assets.
- Cloud sync
- Tournament brackets
- Enterprise dealer workflows
- Universal collectibles beyond cards
