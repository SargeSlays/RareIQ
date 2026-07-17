# RareIQ 6.4 Update 13 — Recognition Geometry and Variant Families

Update 13 preserves rectified 1000×1400 crops, uses consistent full-card
geometry for artwork matching, normalizes Chinese language aliases, verifies a
24-card perceptual-hash shortlist, and can recover visually related variants
outside that shortlist.

## Installation

Start from a clean RareIQ v6.4.12 checkout, stop RareIQ, open PowerShell in the
project root, and run:

```powershell
python -B updates/RareIQ_6.4_Update_13.py
```

The single-file installer carries its complete compressed source and test
payload. It verifies v6.4.12 markers, creates a timestamped pre-update backup,
compile-checks every modified Python file, and runs the targeted regression
suite. Installation needs neither a network connection nor an external payload
directory.

Backups are stored under
`updates/backups/update_13_YYYYMMDD_HHMMSS/`. The manifest records whether
each allowlisted file existed and the SHA-256 of each saved pre-update file.

## Optional one-time index enrichment

The index format remains backward compatible. Version 3 records may contain:

- `artwork_fingerprint`: a normalized artwork-only perceptual fingerprint
  used to discover near-duplicate siblings after strong homography verification.
- `variant_marker_fingerprint`: a normalized lower-card marker fingerprint
  reserved for compatible variant metadata and diagnostics.

Existing indexes without these fields continue to use the current full-card
hash and verifier behavior. Recognition never silently writes or rebuilds the
live index. To enable family expansion, stop RareIQ and run this explicit
one-time command:

```powershell
python -B -m rareiq.services.artwork_index_service --enrich-index
```

The command preserves the existing records and full-card fingerprints, adds the
optional fields where reference images are readable, and atomically replaces
the index. Back up the active index before enrichment if operational rollback of
the index itself is required; the Update 13 installer deliberately never
targets runtime artwork indexes.

## Recognition behavior

The first stage remains the 64-bit full-card perceptual hash and retrieves 24
candidates. The second stage loads only those references and combines
ratio-filtered ORB matches, RANSAC homography/inliers, full-card grayscale SSIM,
and lower-card SSIM. Weak, feature-poor, or unreadable references retain their
original hash ordering.

Only a strongly verified candidate with `artwork_fingerprint` can open a
variant family. Sibling discovery scans index metadata but loads images only for
the small matching family. Each sibling must retain strong full-card geometry.
Within that family, aligned main lower-body, footer/stamp, and lower-symbol
regions use grayscale SSIM, edge overlap, template correlation, ratio-filtered
ORB, and a low-weight color-histogram signal. Weak marker evidence cannot
override full-card identity evidence. Results remain deterministically capped
at ten.

Failed direct verification is retrieval-only and capped at 0.49 before
candidate ranking. Family expansion requires strong full-card geometry, direct
live-to-artwork agreement, and pairwise seed-to-sibling artwork agreement.
Marker scoring runs only for that validated near-duplicate family.

Collector OCR must match supported number syntax; arbitrary text does not
provide identity evidence. OCR locking requires a real catalog/database match
or agreement between OCR identity and a geometrically verified visual
candidate. Studio X displays the chosen candidate's own fused score and never
labels a hash-only candidate as matched.

## Verification

```powershell
python -B updates/RareIQ_6.4_Update_13.py --verify-only
python -B -m pytest -q -p no:cacheprovider tests
```

## Automatic and manual rollback

Any installation, installed-marker, compilation, or targeted-test failure
automatically restores the timestamped pre-update backup. Rollback paths must
stay below the Update 13 backup root, match the exact allowlist, and pass stored
checksums.

Manual rollback:

```powershell
python -B updates/RareIQ_6.4_Update_13.py --rollback updates/backups/update_13_YYYYMMDD_HHMMSS
```

## Exact installed files

```text
rareiq/services/recognition_service.py
rareiq/services/candidate_ranker_service.py
rareiq/services/artwork_index_service.py
rareiq/web/static/studiox.js
tests/test_update_13_recognition_geometry.py
tests/test_update_13_artwork_verification.py
tests/test_candidate_ranking_verification.py
tests/test_studiox_live_recognition_contract.py
```

The installer never targets databases, catalog JSON, card images, runtime
artwork indexes, captures, secrets, `storage_config.json`, or external storage.
