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

## Capture safety and recovery contract

- Every automatic entry point uses the same enabled/trigger/identity/confidence
  gate. A manual-only configuration never captures from recognition updates.
- Confidence must be finite and between 0 and 1. An explicit overall score of
  zero does not fall back to a higher secondary score; missing/invalid scores
  cannot trigger automatic capture, even with a zero threshold. Manual evidence
  records unavailable confidence as `null`.
- A qualifying-hit signal must be the backend boolean `true`. Rarity-threshold
  and value-threshold capture remain unavailable in Phase 1.
- Persisted duplicate claims apply only to their original server session. History
  stays readable after restart, but reused generation numbers in a new session
  do not suppress new captures.
- Missing primary settings may load legacy settings for migration. Corrupt or
  unreadable settings disable automatic capture rather than rearming an old
  legacy configuration.
- A failed image/manifest write removes only that attempt's new bundle. A failed
  index write or sync rolls back that append before returning failure. Short
  writes are errors, not capture confirmations. Original evidence is untouched.
- Malformed history entries are logged and skipped; an interrupted index tail
  is separated from the next append so subsequent valid events remain readable.
- Corrections create linked revisions. Their failures leave the original
  manifest and image bytes unchanged and return a structured API error.

These guarantees have deterministic coverage using generated frames and injected
storage failures. Physical camera timing, device switching during capture, actual
storage disconnect/power loss, and external-drive endurance still require the
release checklist's live acceptance tests. No live hardware result is implied.
