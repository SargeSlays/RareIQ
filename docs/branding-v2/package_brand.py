"""Validate, index and package the public brand deliverables only."""
from pathlib import Path
import os,json,html,csv,hashlib,zipfile,shutil,struct
from PIL import Image
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(os.environ.get('RAREIQ_BRAND_OUTPUT',ROOT/'output/branding/rareiq-v2'))

def lum(h):
    vals=[int(h[i:i+2],16)/255 for i in (1,3,5)]
    vals=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in vals]
    return sum(a*b for a,b in zip(vals,(.2126,.7152,.0722)))
def ratio(a,b):
    a,b=sorted((lum(a),lum(b)));return (b+.05)/(a+.05)

tokens=json.loads((OUT/'tokens/rareiq-tokens.json').read_text())
checks=[]
for mode in ('dark','light'):
    t=tokens[mode]
    for name,a,b in [('body',t['text'],t['background']),('muted',t['muted'],t['background']),('action',t['actionText'],t['action']),('focus',t['focus'],t['background'])]:
        r=ratio(a,b); threshold=3 if name=='focus' else 4.5
        assert r>=threshold,(mode,name,r)
        checks.append({'role':f'{mode}/{name}','foreground':a,'background':b,'ratio':round(r,2),'minimum':threshold,'result':'pass'})
for name,bg in tokens['status'].items():
    r=ratio('#FFFFFF',bg);assert r>=4.5
    checks.append({'role':name,'foreground':'#FFFFFF','background':bg,'ratio':round(r,2),'minimum':4.5,'result':'pass'})
with (OUT/'standards/contrast-pairs.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=checks[0]);w.writeheader();w.writerows(checks)

# ICO entries retain the precisely rendered dedicated favicon sizes.
for name in ('rareiq','rareiq-ocr'):
    blobs=[(s,(OUT/f'icons/{name}-favicon-{s}.png').read_bytes()) for s in (16,24,32,48,64)]
    offset=6+16*len(blobs);head=struct.pack('<HHH',0,1,len(blobs));body=b''
    for s,data in blobs:
        head+=struct.pack('<BBBBHHII',s,s,0,0,1,32,len(data),offset);body+=data;offset+=len(data)
    (OUT/f'icons/{name}-favicon.ico').write_bytes(head+body)

master=Image.open(OUT/'mascot/rareiq-mascot-master.png')
assert master.mode=='RGBA'
alpha=master.getchannel('A');assert alpha.getextrema()==(0,255)
assert alpha.getpixel((0,0))==0 and alpha.getpixel((master.width-1,master.height-1))==0
assert len(PdfReader(OUT/'RareIQ-Brand-Book-v2.0.pdf').pages)==16
for p in OUT.rglob('*.png'):
    if p.parent.name=='source':continue
    with Image.open(p) as im:im.verify()
for folder in ('logos','mascot','templates'):
    for p in (OUT/folder).glob('*.svg'):
        assert p.with_suffix('.png').exists(),p
        txt=p.read_text(encoding='utf-8');assert '<text' not in txt,'Unexpected font-dependent asset'

readme='''# RareIQ brand system v2.0

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
'''
(OUT/'README.md').write_text(readme,encoding='utf-8')
spec='''# Production specifications

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
'''
spec+='\n## Flat supporting colors\n\n| Color | Hex | RGB |\n|---|---|---|\n'
for name,h in tokens['brand'].items():spec+=f'| {name} | {h} | {", ".join(str(int(h[i:i+2],16)) for i in (1,3,5))} |\n'
(OUT/'standards/Production-Specifications.md').write_text(spec,encoding='utf-8')

for name in ('build_assets.py','render_assets.cjs','build_book.py','package_brand.py','book-content.json','clean_mascot.py'):
    shutil.copyfile(Path(__file__).parent/name,OUT/'source'/name)

cards=[]
for folder in ('logos','mascot','icons','templates'):
    for p in sorted((OUT/folder).glob('*.svg')):
        rel=p.relative_to(OUT).as_posix(); title=p.stem.replace('rareiq-','').replace('-',' ')
        light='on-light' in p.stem or 'mono-black' in p.stem
        cards.append(f'<article><div class="preview {"light" if light else "dark"}"><img loading="lazy" src="{rel}" alt="RareIQ {html.escape(title)}"></div><h3>{html.escape(title)}</h3><a href="{rel}" download>SVG artwork</a> <a href="{rel[:-4]}.png" download>PNG export</a></article>')
gallery='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RareIQ Brand Library</title><style>@font-face{font-family:Poppins;src:url(fonts/Poppins-Regular.ttf)}*{box-sizing:border-box}body{margin:0;background:#080F1A;color:#F7F8FC;font:16px Poppins,Arial,sans-serif}header,main{max-width:1400px;margin:auto;padding:48px}header{display:flex;align-items:center;gap:40px}header img{width:38%;max-width:380px}h1{font-size:42px;line-height:1.2}p{color:#AFBDD1;max-width:620px;line-height:1.6}a{color:#7CFFCB;margin-right:16px;text-underline-offset:4px}a:focus-visible{outline:3px solid #7CFFCB;outline-offset:6px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px}article{border:1px solid #334257;border-radius:16px;overflow:hidden;padding:0 0 22px}article h3,article a{margin-left:20px;font-size:13px}.preview{height:230px;padding:24px;display:flex;align-items:center;justify-content:center}.preview img{width:100%;height:100%;object-fit:contain}.light{background:#F7F8FC}.dark{background:#111C2E}h2{font-size:27px}@media(max-width:650px){header{display:block}header,main{padding:24px}header img{width:80%}h1{font-size:32px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}</style><header><img src="logos/rareiq-primary-on-dark.png" alt="RareIQ mascot and wordmark"><div><p>THE BRAND LIBRARY / V2.0</p><h1>Intelligence for creators.</h1><p>RareIQ and RareIQ OCR. One mascot, a complete family of signatures and practical assets.</p><a href="RareIQ-Brand-Book-v2.0.pdf">Read the brand book</a><a href="README.md">Package guide</a></div></header><main><h2>Choose your asset</h2><p>Full-color mascot SVGs contain embedded raster artwork. Wordmarks and flat or one-color mascot SVGs are vectors. Lettering is outlined; template copy can be changed in the supplied source.</p><div class="grid">'''+''.join(cards)+'</div></main></html>'
(OUT/'Asset-Gallery.html').write_text(gallery,encoding='utf-8')

shutil.copyfile(OUT/'source/original-approved-character.png',OUT/'standards/Original-Approved-Reference.png')
for p in OUT.rglob('*'):
    if p.is_file() and p.suffix in ('.md','.txt','.json','.css','.html','.svg','.py','.cjs','.csv'):
        p.write_bytes(p.read_bytes().replace(b'\r\n',b'\n'))
files=[p for p in OUT.rglob('*') if p.is_file() and 'qa' not in p.relative_to(OUT).parts and p.name not in ('asset-inventory.csv','SHA256SUMS.txt') and not(p.parent.name=='source' and p.suffix=='.png')]
rows=[]
for p in sorted(files):
    dims='';kind='document/source'
    if p.suffix=='.png':
        im=Image.open(p);dims=f'{im.width}x{im.height}';kind='raster RGBA' if im.mode=='RGBA' else 'raster RGB'
    if p.suffix=='.svg':kind='hybrid: raster mascot + vector lettering' if '<image' in p.read_text(encoding='utf-8') else 'vector'
    rows.append({'path':p.relative_to(OUT).as_posix(),'format':kind,'pixels':dims,'bytes':p.stat().st_size})
with (OUT/'asset-inventory.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=rows[0],lineterminator='\n');w.writeheader();w.writerows(rows)
files.append(OUT/'asset-inventory.csv')
(OUT/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(OUT).as_posix()+'\n' for p in sorted(files)),newline='\n')
files.append(OUT/'SHA256SUMS.txt')
archive=OUT.parent/'RareIQ-Brand-System-v2.0.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files):z.write(p,'RareIQ-Brand-System-v2.0/'+p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print(json.dumps({'assets_and_documents':len(files),'book_pages':16,'contrast_checks':checks,'zip_bytes':archive.stat().st_size},indent=2))
