"""Rebuild the identity package from the approved local mascot master."""
from pathlib import Path
import base64, json, html, shutil, os, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get('RAREIQ_BRAND_OUTPUT', ROOT / 'output/branding/rareiq-v2'))
for folder in ('logos', 'mascot', 'icons', 'templates', 'tokens', 'standards', 'source'):
    (OUT / folder).mkdir(parents=True, exist_ok=True)
FONT = TTFont(OUT / 'fonts/Poppins-Bold.ttf')
GS = FONT.getGlyphSet(); CM = FONT.getBestCmap(); UPM = FONT['head'].unitsPerEm
COLORS = dict(purple='#A855F7', pink='#FF4EDB', orange='#FF9F43', cyan='#00E5FF', mint='#7CFFCB', space='#080F1A', paper='#F7F8FC')
DEFS = '''<defs><linearGradient id="spectrum" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#00E5FF"/><stop offset=".36" stop-color="#A855F7"/><stop offset=".66" stop-color="#FF4EDB"/><stop offset="1" stop-color="#FFCF70"/></linearGradient><linearGradient id="cool" x1="0" y1="1" x2="1" y2="0"><stop stop-color="#00E5FF"/><stop offset=".5" stop-color="#009EFF"/><stop offset="1" stop-color="#B31BFF"/></linearGradient><linearGradient id="iq" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#7CFFCB"/><stop offset=".27" stop-color="#00E5FF"/><stop offset=".52" stop-color="#FFBF64"/><stop offset=".76" stop-color="#FF4EDB"/><stop offset="1" stop-color="#BF08ED"/></linearGradient></defs>'''

def textpaths(text, x, y, size, fill, spacing=0):
    scale=size/UPM; parts=[]
    for ch in text:
        glyph=CM.get(ord(ch))
        if glyph:
            pen=SVGPathPen(GS); GS[glyph].draw(pen)
            parts.append(f'<path fill="{fill}" transform="translate({x:.3f} {y}) scale({scale:.6f} {-scale:.6f})" d="{pen.getCommands()}"/>')
            x+=GS[glyph].width*scale+spacing
    return ''.join(parts), x

DEFS=DEFS.replace('</defs>','<linearGradient id="bar" x1="0%" y1="0%" x2="0%" y2="100%"><stop stop-color="#7CFFCB"/><stop offset="1" stop-color="#00B9E9"/></linearGradient></defs>')

def wordmark(x,y,size,fg,mono=False):
    rare,end=textpaths('Rare',x,y,size,fg,spacing=-size*.025)
    col=fg if mono else 'url(#bar)'; qcol=fg if mono else 'url(#spectrum)'; tail=fg if mono else '#F025E8'
    bar=f'<rect x="{end+size*.035}" y="{y-size*.71}" width="{size*.145}" height="{size*.71}" rx="{size*.072}" fill="{col}"/>'
    cx=end+size*.635;cy=y-size*.355
    q=f'<circle cx="{cx}" cy="{cy}" r="{size*.282}" fill="none" stroke="{qcol}" stroke-width="{size*.15}"/><path d="M {cx+size*.07} {cy+size*.09} L {cx+size*.335} {cy+size*.35}" stroke="{tail}" stroke-width="{size*.155}" stroke-linecap="round"/>'
    return rare+bar+q

def width(text,size,spacing=0):
    return sum(GS[CM[ord(ch)]].width for ch in text)/UPM*size+len(text)*spacing

def wmwidth(size):
    return width('Rare',size,-size*.025)+size*1.05

def svg(w,h,body,title):
    return f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(title)}"><title>{html.escape(title)}</title>{DEFS}{body}</svg>'

def save(folder,name,w,h,body):
    (OUT/folder/f'{name}.svg').write_text(svg(w,h,body,name.replace('-',' ')),encoding='utf-8')

# A purpose-drawn flat companion, not a vectorization of the rendered master.
BODY='M 146,368 C 65,351 53,292 70,242 C 73,206 91,183 119,168 C 119,121 157,94 208,101 C 260,48 353,66 377,142 C 455,153 480,213 464,277 C 452,332 386,363 266,397 C 244,404 226,410 211,416 C 201,419 199,414 200,396 C 200,376 201,369 186,362 C 158,346 136,380 137,407 C 134,430 114,414 113,396 C 109,383 112,374 116,365 Z'
GROOVE='M 204,103 C 259,79 316,108 323,166 C 305,157 302,146 295,134 C 273,104 240,93 204,103 Z M 123,165 C 95,211 129,230 167,226 C 228,221 243,264 230,293 C 282,300 295,335 282,365 C 266,389 234,405 211,416 C 230,395 245,378 241,358 C 233,333 206,333 186,331 C 204,301 204,274 184,261 C 156,244 121,257 103,225 C 92,205 98,180 123,165 Z'
SPARKS='<path d="M392 111 L407 68" stroke="CURRENT" stroke-width="19" stroke-linecap="round"/><path d="M431 139 L463 119" stroke="CURRENT" stroke-width="18" stroke-linecap="round"/><path d="M442 174 L470 175" stroke="CURRENT" stroke-width="15" stroke-linecap="round"/>'

def flat(color=None,micro=False):
    fill=color or 'url(#spectrum)'; groove='#080F1A' if color is None else '#000'
    eyes='<ellipse cx="333" cy="250" rx="24" ry="48" transform="rotate(-9 333 250)"/><ellipse cx="415" cy="230" rx="23" ry="47" transform="rotate(-9 415 230)"/>'
    if color:
        # Alpha knockouts preserve true one-ink output on any stock.
        mask=f'<defs><mask id="cut"><rect width="512" height="512" fill="white"/><g fill="black">{eyes}<path d="{GROOVE}"/></g></mask></defs>'
        return mask+f'<g fill="{color}" mask="url(#cut)"><path d="{BODY}"/>{"" if micro else SPARKS.replace("CURRENT",color)}</g>'
    return f'<path d="{BODY}" fill="{fill}"/><path d="M116 365 C57 350 50 298 71 246 C93 290 146 250 179 283 C195 301 190 325 186 331 C224 332 249 351 235 376 C220 397 176 374 161 378 C140 383 140 405 137 415 C118 426 107 387 116 365 Z" fill="url(#cool)"/><path d="{GROOVE}" fill="{groove}"/><g fill="#050712">{eyes}</g><g fill="white"><ellipse cx="329" cy="230" rx="8" ry="12"/><ellipse cx="411" cy="210" rx="8" ry="12"/></g>'+('' if micro else SPARKS.replace('CURRENT','url(#spectrum)'))

for variant,color in [('flat-color',None),('mono-black','#000000'),('mono-white','#FFFFFF')]:
    save('mascot',f'rareiq-mascot-{variant}',512,512,flat(color))
save('mascot','rareiq-mascot-micro',512,512,flat(None,True))
if '--vector-only' in sys.argv:
    raise SystemExit(0)

master=OUT/'mascot/rareiq-mascot-master.png'
if not master.exists():
    raise SystemExit('Transparent master required before building full-color lockups.')
from PIL import Image
im=Image.open(master)
assert im.mode=='RGBA' and im.getchannel('A').getextrema()==(0,255), 'Master must contain real transparency'
b64=base64.b64encode(master.read_bytes()).decode()
def mascot(x,y,w,h):
    return f'<image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{b64}"/>'

for theme,fg in [('on-dark','#FFFFFF'),('on-light','#080F1A')]:
    for product in ('rareiq','rareiq-ocr'):
        ocr=product.endswith('ocr')
        for tagline in (False,True):
            if ocr and tagline: continue
            desc='OCR' if ocr else 'INTELLIGENCE FOR CREATORS' if tagline else ''
            b=mascot(145,15,510,400)+wordmark((800-wmwidth(154))/2,523,154,fg)
            if desc:
                sz=34 if ocr else 19
                b+=textpaths(desc,(800-width(desc,sz,2.3))/2,585,sz,fg,2.3)[0]
            save('logos',f'{product}-primary-{theme}'+('-tagline' if tagline else ''),800,640 if desc else 565,b)
        b=mascot(8,8,242,184)+wordmark(267,135,117,fg)
        if ocr: b+=textpaths('OCR',276,183,30,fg,6)[0]
        save('logos',f'{product}-horizontal-{theme}',710,208,b)
        b=wordmark(30,130,145,fg)
        if ocr: b+=textpaths('OCR',38,201,36,fg,5)[0]
        save('logos',f'{product}-wordmark-{theme}',550,240 if ocr else 165,b)
        for ink,col in [('black','#000000'),('white','#FFFFFF')]:
            b=f'<g transform="translate(0 -8) scale(.43)">{flat(col)}</g>'+wordmark(243,133,117,col,True)
            if ocr: b+=textpaths('OCR',251,182,30,col,6)[0]
            save('logos',f'{product}-horizontal-mono-{ink}',690,208,b)

for product in ('rareiq','rareiq-ocr'):
    b='<rect width="1024" height="1024" rx="208" fill="#080F1A"/>'+mascot(64,95 if product=='rareiq' else 28,896,800)
    if product.endswith('ocr'): b+=textpaths('OCR',334,918,144,'#FFFFFF',6)[0]
    save('icons',f'{product}-app-icon',1024,1024,b)
    b='<rect width="512" height="512" rx="96" fill="#080F1A"/>'+f'<g transform="translate(-9 -12) scale(1.02)">{flat(None,True)}</g>'
    save('icons',f'{product}-favicon',512,512,b)

def template(name,w,h,kind='cover',light=False,ocr=False):
    bg=COLORS['paper'] if light else COLORS['space']; fg=COLORS['space'] if light else '#FFFFFF'
    b=f'<rect width="{w}" height="{h}" fill="{bg}"/>'
    if kind=='overlay':
        b=''; b+=f'<path d="M48 110 V48 H260 M{w-260} {h-48} H{w-48} V{h-110}" stroke="#00E5FF" stroke-width="3" fill="none"/>'
        b+=wordmark(w-280,h-65,58,'#FFFFFF')
    elif kind=='letterhead':
        b+=wordmark(78,115,65,fg)+textpaths('STUDIO / CORRESPONDENCE',80,154,12,fg,1)[0]
        b+=textpaths('Intelligence for creators',80,h-72,16,fg)[0]
        b+=f'<rect x="80" y="{h-44}" width="70" height="4" fill="#A855F7"/>'
    else:
        portrait=h>w
        if portrait:
            b+=mascot(w*.17,h*.09,w*.66,w*.59)+wordmark(w*.12,h*.55,w*.19,fg)
            copy='OCR' if ocr else 'INTELLIGENCE FOR CREATORS'
            b+=textpaths(copy,w*.14,h*.62,w*.032,fg,1.7)[0]
            if kind=='slate':b+=textpaths('Starting soon',w*.14,h*.77,w*.066,fg)[0]
            b+=f'<path d="M{w*.14} {h*.84} H{w*.42}" stroke="#A855F7" stroke-width="4"/>'
        else:
            b+=wordmark(w*.066,h*.23,w*.15,fg)+mascot(w*.61,h*.10,w*.33,h*.77)
            copy='OCR' if ocr else 'Intelligence for creators'
            b+=textpaths(copy,w*.07,h*.35,w*.025,fg)[0]
            headline='Starting soon' if kind=='slate' else 'Your next idea.'
            b+=textpaths(headline,w*.07,h*.67,w*.039,fg)[0]
            b+=f'<rect x="{w*.07}" y="{h*.8}" width="{w*.09}" height="4" fill="#A855F7"/>'
    save('templates',name,w,h,b)

template('rareiq-social-banner',1500,500)
template('rareiq-social-card',1200,630)
template('rareiq-ocr-social-card',1200,630,ocr=True)
template('rareiq-presentation-cover',1920,1080)
template('rareiq-document-cover',1240,1754)
template('rareiq-letterhead-a4',1240,1754,kind='letterhead',light=True)
for w,h in [(1920,1080),(3840,2160),(1080,1920),(2160,3840)]:
    template(f'rareiq-starting-soon-{w}x{h}',w,h,kind='slate')
    template(f'rareiq-overlay-{w}x{h}',w,h,kind='overlay')
shutil.copyfile(OUT/'icons/rareiq-app-icon.svg',OUT/'templates/rareiq-social-avatar.svg')

tokens={'brand':COLORS,'dark':{'background':'#080F1A','surface':'#111C2E','text':'#F7F8FC','muted':'#AFBDD1','action':'#00E5FF','actionText':'#080F1A','focus':'#7CFFCB'},'light':{'background':'#F7F8FC','surface':'#FFFFFF','text':'#080F1A','muted':'#495569','action':'#6425B5','actionText':'#FFFFFF','focus':'#6425B5'},'status':{'success':'#137A53','warning':'#805600','error':'#B42343'},'space':[4,8,12,16,24,32,48,64],'radius':{'control':8,'panel':16},'font':'Poppins, Arial, sans-serif'}
(OUT/'tokens/rareiq-tokens.json').write_text(json.dumps(tokens,indent=2)+'\n')
css='/* RareIQ v2. Opt-in tokens: integrate through the existing semantic layer. */\n'
for key in ('brand','dark','light','status'):
    selector=':root' if key in ('brand','status') else f'[data-rareiq-theme="{key}"]'
    css+=selector+' {\n'+''.join(f'  --riq-{key}-{n}: {v};\n' for n,v in tokens[key].items())+'}\n'
css+=':root { --riq-font: Poppins, Arial, sans-serif; --riq-radius-control: 8px; --riq-radius-panel: 16px; --riq-space-unit: 8px; }\n@media (prefers-reduced-motion: reduce) { .riq-brand-motion { animation: none; transition: none; } }\n'
(OUT/'tokens/rareiq-tokens.css').write_text(css)
print('Built SVG sources and brand tokens.')
