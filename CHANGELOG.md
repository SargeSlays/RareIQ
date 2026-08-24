# Changelog

## Studio X 6.4.18-dev — In development

- Added a read-only Studio X mobile-access readiness panel with safe LAN URL
  discovery and no secret exposure or in-app server-binding changes.
- Added an installable mobile Studio X shell with phone/tablet navigation,
  safe-area handling, and truthful online-only home-screen metadata.
- Added an opt-in authenticated LAN foundation for mobile Studio X access while
  preserving loopback-only operation by default.
- Added throttled device pairing plus dry-run-first token setup and private-LAN
  address discovery for safer mobile operations.

## Studio X 6.4.17 — WAR Build Foundation

### Recognition

- Consolidated high-resolution capture, continuous card-change handling, exact-crop handoff, OCR, geometric artwork verification, and variant-family ranking.
- Preserved English catalog identity for Chinese printings while resolving exact localized variants and collector numbers.
- Added verified catalog-reference fallback so strong local visual evidence can recover an exact printing without weakening shared-art safeguards.
- Corrected full collector-fraction ranking so an exact `number/set-size` match outranks numerator-only and incompatible printings.

### Studio X and capture

- Locked the Studio X camera workspace UI and integrated independent multi-camera preview sessions with one explicit active recognition source.
- Added provenance screenshot capture with immutable event manifests, checksums, active-camera attribution, and truthful handling when card geometry is unavailable.
- Kept runtime captures, artwork indexes, provenance events, diagnostics, and user configuration outside the source release.

### Runtime safety and operations

- Added single-instance server control, automatic recovery, verified recovery checkpoints, and safe scheduled recovery behavior.
- Routed runtime media through configured storage and added a verified provenance-storage migration path.
- Added truthful server, storage, camera, recognition, and recovery health reporting plus privacy-bounded diagnostic bundles.
- Moved the large local-image inventory scan off the health request path, reducing live health latency from seconds to milliseconds while retaining background inventory measurements.

### Security and release engineering

- Protected local configuration and credentials, contained replay and receipt paths, and bounded uploads and encoded capture receipts.
- Pinned the Python 3.13 dependency graph and added the Windows release-quality workflow.
- Added deterministic, manifest-backed source archives that exclude runtime data and secrets, verify every payload checksum, and fail closed on unsafe paths.
- Added disposable clean-install smoke validation covering Python and JavaScript syntax, application import, and the complete canonical test suite.
- Expanded deterministic coverage across recognition, catalog, inventory, creator, frontend, security, runtime-recovery, and release contracts.

## Studio X 6.3 — Backend Test Foundation

- Added unified runtime snapshot and normalized current-card API.
- Added backend smoke, corrected-crop recognition, recent-pulls, diagnostics, and active-session contracts.
