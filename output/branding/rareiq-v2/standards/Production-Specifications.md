# Production specifications

## Master and size rules

Use the supplied files without reconstructing the lettering. Keep x = one-quarter of the visible mascot height clear around the complete signature; x excludes transparent image padding. For a wordmark alone use half the capital I height. Favicon and launcher exports are the supplied small-size exceptions with their own padding.

Digital minimum starting sizes: stacked 180 px; horizontal RareIQ 160 px; OCR horizontal 320 px; tagline signature 320 px; full mascot 48 px. Inspect at actual size. Use flat/micro exports below the full mascot limit. Print starting widths: full signature 30 mm, tagline 55 mm; proof on the intended stock. At 300 ppi a raster's usable width in mm is pixels / 300 * 25.4. Never upscale a file and claim additional detail.

## Palette and gradient construction

All color specifications are sRGB. The original rendered mascot contains additional shading colors; do not flatten it to the supporting palette. Display accent gradient: cyan 0%, purple 50%, pink 100%. Warm display gradient: purple 0%, pink 55%, orange 100%. Use gradients for large decorative accents only, never as the sole status cue.

## Typography and layout

Poppins 400 body, 500 labels, 600 headings, 700 display. Suggested digital scale: display 48-64 px, page heading 32 px, section 24 px, body 16 px/24 px, caption 12-14 px. Use 8 px layout rhythm with 4 px optical half-steps. Controls: 8 px radius; panels: 16 px. Keep actual interactive UI copy as text, rather than an image.

## Contrast and motion

The included contrast-pairs.csv calculates sRGB luminance ratios for selected foreground/background pairs. These pairs meet the stated thresholds; this is not a whole-product accessibility audit. Target 4.5:1 for normal text, 3:1 for qualifying large text and meaningful control boundaries. Test every interactive state and adjacent surface. Preserve readable labels, focus and reduced motion. Brand fades may last 160-240 ms; reduced-motion experiences should remain static. No repeated decorative movement during production.

Sources: https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html and https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html

## Formats and image safety

Keep slates and overlays inside a 5% content-safe inset as a starting rule. The transparent overlay corner marks are decorative and may sit closer to the edge; essential content must remain farther in. Platform-specific cropping still needs review before upload. Do not start a stream or recording to preview artwork. A4 artboards use the A-series ratio; a printer must set physical size, bleed, color profile and proofing. No CMYK, Pantone, embroidery or signage match is certified by this RGB package.

## Flat supporting colors

| Color | Hex | RGB |
|---|---|---|
| purple | #A855F7 | 168, 85, 247 |
| pink | #FF4EDB | 255, 78, 219 |
| orange | #FF9F43 | 255, 159, 67 |
| cyan | #00E5FF | 0, 229, 255 |
| mint | #7CFFCB | 124, 255, 203 |
| space | #080F1A | 8, 15, 26 |
| paper | #F7F8FC | 247, 248, 252 |
