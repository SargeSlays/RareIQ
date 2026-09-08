# Provenance and verification

The owner chose the large top-left mascot and RareIQ wordmark on September 7,
2026, then confirmed the same mascot for RareIQ OCR. The earlier task titled
Rebrand Rare IQ Logo pointed to a downloaded Producer, Please implementation
handoff. Its visual-references/RareIQ_Original_Character.png is included unchanged
as Original-Approved-Reference.png. It is an RGB reference, not a transparent logo.

The transparent rendered master is a restored production adaptation generated
with the built-in image tool and cleaned locally with the owner's explicit
permission. It preserves the chosen visual direction; it is not a pixel-exact
extraction of the recovered original. Two generator attempts returned a painted
checkerboard. The local matte removes only connected pale neutral background,
preserves enclosed white eye highlights, and was refined to retain the crown.

The outlined wordmark uses Poppins-derived Rare lettering and custom rounded IQ
geometry. The flat/mono/micro mascot drawings are purpose-drawn vector companion
adaptations. Their proportions and details differ from the rendered master; use
them for small-size or restricted-color reproduction, not as a full-color master.
Full-color mascot SVGs embed the rendered PNG and are explicitly marked hybrid.

## Image prompt record

Built-in extraction: isolate the large top-left mascot; preserve silhouette,
eyes, folds, color placement, three sparks and polished material; remove lettering,
the board, background and surrounding shadow. Output one mascot with real alpha,
no new features or alternate concepts.

Built-in correction: remove the baked checkerboard without changing the mascot;
retain white eye highlights and transparent gaps between the three sparks.
Local cleanup, after permission: connected-background matte, preserved highlights,
one-pixel fringe control and subpixel edge antialiasing. Native final raster size
is 1171x867; 4K application artboards do not imply a native 4K mascot master.

## Verification record

All 16 book pages were rendered and visually reviewed. The transparency was
inspected against dark and light fields. Dedicated favicon exports were viewed
at actual size. The local gallery was checked at 1080p, 4K and narrow desktop,
with decoded preview images, no horizontal overflow and 84 valid local links.
Package validation verifies the master alpha, PNG integrity, vector/export pairs,
16 PDF pages, 11 selected color-contrast pairs and archive integrity.

The repository gate passed 2,452 Python tests and 196 JavaScript tests. This is
artifact delivery: runtime application migration, hardware/encoder operation,
external publishing and physical print proofs were not exercised.
