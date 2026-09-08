# RareIQ brand system v2.0

Start with **RareIQ-Brand-Book-v2.0.pdf**, then open **Asset-Gallery.html**.
This package covers RareIQ and RareIQ OCR using the same selected mascot.
RareIQ is the premium collectible/card recognition and intelligence product within Producer, Please, the parent live-production environment. This brand architecture does not activate pricing or entitlements.

## Choose the right file

- `logos/*primary*`: stacked hero signatures; tagline variants are for larger use.
- `logos/*horizontal*`: shallow headers and compact brand placements.
- `logos/*wordmark*`: outlined, scalable lettering, without a mascot.
- `on-dark`: white lettering for dark fields. `on-light`: dark lettering for light fields.
- `mascot/rareiq-mascot-master.png`: restored full-color RGBA master.
- `mascot/*flat*`, `*mono*`, `*micro*`: purpose-drawn vector adaptations for constrained reproduction. These are simplified companions, not exact vector copies of the rendered mascot.
- `icons/`: app icons, small favicons, ICO files and size-specific PNGs. OCR app icons include a descriptor; tiny favicons share the family symbol.
- `templates/`: social, presentation, A4 document/letterhead, slates and transparent overlays. Landscape and portrait include HD and 4K exports.
- `tokens/`: opt-in design values. Integrate through the product's existing semantic layer.
- `standards/`: editable text, measured contrast pairs, production specifications and source notes.

## Formats and editing

Full-color mascot signatures contain embedded raster artwork inside SVG with outlined vector lettering. They are self-contained hybrid SVG files, not infinitely scalable mascot vectors. Wordmark-only and flat/mono mascot SVGs are vectors. PNG dimensions are recorded in the inventory. Transparent space inside an export does not replace external clear space.

The SVG artwork is editable in a vector editor, with outlined lettering. To change template copy, edit the included `source/build_assets.py` template parameters and rerun; these are not live text fields or PowerPoint/Word files. PDFs are digital RGB reference output, not press-certified files.

## Sources and rebuilding

The owner selected the large top-left mascot concept supplied September 7, 2026. The restored artwork and Poppins-derived outlined lettering with custom IQ geometry are production adaptations of that concept. The original approved character/signature was recovered from the downloaded Producer, Please handoff and is included unchanged in standards/Original-Approved-Reference.png. Unselected concepts and draft extractions are excluded from this distribution.

Fonts: unmodified Poppins Regular, Medium, SemiBold and Bold; copyright and SIL Open Font License are included in `fonts/OFL.txt`. Sources: https://github.com/google/fonts/tree/main/ofl/poppins

Rebuilding requires Python with reportlab, fonttools, Pillow and pypdf, and Node.js with sharp. Set RAREIQ_BRAND_OUTPUT to this package's absolute directory, then run source/build_assets.py, source/render_assets.cjs, source/build_book.py and source/package_brand.py in that order. The transparent master must already exist. The book text is source/book-content.json; editable standards are also supplied as Markdown.

## Delivery boundaries

Brand assets and specimen layouts are supplied. Application integration, OCR capability claims, external streaming, print proofs and platform crop acceptance require separate verification. No product pricing or availability has been invented. The existing running app has not been rebranded by this package.
