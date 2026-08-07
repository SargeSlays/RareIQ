# Auto Screenshot backend Phase 1

Studio X now connects to a server-side provenance capture service. The existing
`/api/camera/capture` route still starts recognition capture and remains
separate from screenshot provenance.

Phase 1 captures the existing active camera frame and an optional validated card
crop. It never opens a second camera handle. Automatic evaluation is driven by
accepted backend recognition events and is deduplicated by server session,
recognition generation, exact identity, active slot, and active source.

Implemented capabilities:

- atomic capture of the untouched full camera frame;
- Card Focus only from validated, stable card geometry;
- truthful nulls for unsupported evidence fields;
- session, customer, vendor, workflow, pack, turn, and player-side metadata;
- server timestamps and safe filenames;
- stable event IDs and one-capture-per-card/cooldown enforcement;
- an immutable original capture and append-only corrections;
- correction revision history that never overwrites the original event;
- a capture manifest matching provenance event contract version 1;
- SHA-256 asset checksums.

Evidence-view rendering, retention management, clip association, and session
recap export remain future capabilities and are not represented as available.

The confirmation response must include the stable `eventId`, `cardContextId`,
`capturedAt`, camera source, and only paths or URLs for assets that actually
exist. Failures must return no proof record and no invented asset path.

Trigger evaluation belongs next to the authoritative recognition event, not a
frontend polling loop. Exact-match requires a verified identity; rarity and
value triggers require authoritative rarity and market-value data respectively.
The backend must reject provisional/review-needed identity for exact-match,
invalid geometry for Card Focus, duplicate event IDs, and configuration-only or
Next/Clear events.
