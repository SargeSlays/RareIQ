"""Compose the illustrated RareIQ brand book from editable content and assets."""
from pathlib import Path
import json, shutil, hashlib, csv, html, zipfile, os
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]; OUT=Path(os.environ.get('RAREIQ_BRAND_OUTPUT',ROOT/'output/branding/rareiq-v2'))
PAGES=json.loads((Path(__file__).parent/'book-content.json').read_text(encoding='utf-8'))
for weight in ('Regular','SemiBold','Bold'):
    pdfmetrics.registerFont(TTFont('Poppins'+weight,str(OUT/f'fonts/Poppins-{weight}.ttf')))
SPACE='#080F1A'; PAPER='#F7F8FC'; MUTE='#AFBDD1'; INK='#495569'
PALETTE=[('Purple','#A855F7'),('Pink','#FF4EDB'),('Orange','#FF9F43'),('Cyan','#00E5FF'),('Mint','#7CFFCB'),('Deep Space',SPACE)]
PDF=OUT/'RareIQ-Brand-Book-v2.0.pdf'
c=canvas.Canvas(str(PDF),pagesize=(960,600),pageCompression=1)
c.setTitle('RareIQ | Brand Book v2.0'); c.setAuthor('RareIQ'); c.setSubject('RareIQ and RareIQ OCR identity standards')
def rect(x,y,w,h,color,r=0):
    c.setFillColor(HexColor(color));c.setStrokeColor(HexColor(color))
    if r: c.roundRect(x,y,w,h,r,stroke=0,fill=1)
    else:c.rect(x,y,w,h,stroke=0,fill=1)
def label(txt,x,y,size=11,color=PAPER,bold=False):
    c.setFillColor(HexColor(color));c.setFont('PoppinsSemiBold' if bold else 'PoppinsRegular',size);c.drawString(x,y,txt)
def para(txt,x,top,w,size=12,color=SPACE,bold=False,leading=None):
    style=ParagraphStyle('body',fontName='PoppinsSemiBold' if bold else 'PoppinsRegular',fontSize=size,leading=leading or size*1.47,textColor=HexColor(color))
    p=Paragraph(html.escape(txt),style);_,height=p.wrap(w,600)
    p.drawOn(c,x,top-height);return top-height
def pic(rel,x,y,w,h):
    c.drawImage(str(OUT/rel),x,y,width=w,height=h,preserveAspectRatio=True,anchor='c',mask='auto')
def panel():rect(532,91,374,367,SPACE,16)
def art(n):
    panel()
    if n in (1,3):
        pic('mascot/rareiq-mascot-master.png',552,163,335,265)
        label('CURIOUS  /  CAPABLE  /  COMPOSED',558,125,10,MUTE)
    elif n==2:
        pic('logos/rareiq-horizontal-on-dark.png',552,315,326,80)
        pic('logos/rareiq-ocr-horizontal-on-dark.png',552,174,326,80)
        label('MASTER BRAND',556,410,10,MUTE)
        label('SOFTWARE DESCRIPTOR',556,274,10,MUTE)
    elif n==4:
        pic('logos/rareiq-primary-on-dark-tagline.png',562,211,308,226)
        pic('logos/rareiq-horizontal-on-dark.png',567,123,297,70)
    elif n==5:
        asset=Image.open(OUT/'logos/rareiq-horizontal-on-dark.png');bb=asset.getbbox()
        master=Image.open(OUT/'mascot/rareiq-mascot-master.png');mb=master.getbbox()
        s=280/asset.width; lx=568; ly=244; lh=asset.height*s
        x=(mb[3]-mb[1])*min(242/master.width,184/master.height)*s/4
        bx=lx+bb[0]*s-x;by=ly+lh-bb[3]*s-x
        bw=(bb[2]-bb[0])*s+2*x;bh=(bb[3]-bb[1])*s+2*x
        c.setStrokeColor(HexColor('#7CFFCB'));c.setLineWidth(.8);c.setDash(3,3)
        c.rect(bx,by,bw,bh,fill=0,stroke=1);c.setDash()
        pic('logos/rareiq-horizontal-on-dark.png',lx,ly,280,lh)
        label('x',bx+4,by+bh/2,10,'#7CFFCB');label('x',bx+bw/2,by+bh-13,10,'#7CFFCB')
        label('x = 1/4 visible mascot height',561,133,11,MUTE)
    elif n==6:
        pic('logos/rareiq-horizontal-on-dark.png',552,339,330,81)
        rect(549,221,340,88,PAPER,8);pic('logos/rareiq-horizontal-on-light.png',559,226,320,78)
        pic('logos/rareiq-horizontal-mono-white.png',552,118,330,83)
    elif n==7:
        for j,(name,color) in enumerate(PALETTE):
            xx=556+(j%3)*113; yy=299-(j//3)*139
            rect(xx,yy,93,86,color,13)
            if name=='Deep Space':
                c.setStrokeColor(HexColor(MUTE));c.roundRect(xx,yy,93,86,13,stroke=1,fill=0)
            label(name,xx,yy-22,10,PAPER,True);label(color,xx,yy-40,10,MUTE)
    elif n==8:
        label('Poppins',557,367,49,PAPER,True)
        label('Aa Bb Cc 0123',558,312,26,'#00E5FF')
        for j,(txt,sz) in enumerate([('Display / 48-64',24),('Heading / 24-32',19),('Body / 16',16),('Caption / 12-14',12)]):label(txt,558,249-j*40,sz,PAPER)
    elif n==9:
        label('Readable. Understandable.',556,402,17,PAPER,True)
        for j,(bg,fg,txt) in enumerate([('#00E5FF',SPACE,'Continue'),('#137A53','#FFFFFF','Confirmed'),('#805600','#FFFFFF','Review needed'),('#B42343','#FFFFFF','Try again')]):
            yy=325-j*58;rect(557,yy,317,43,bg,8);label(txt,574,yy+14,12,fg,True)
        label('Pair color with a meaningful label.',556,111,10,MUTE)
    elif n==10:
        label('Clear words. Useful actions.',555,405,18,PAPER,True)
        para('Check the extracted text before using it.',556,352,318,28,PAPER,True,39)
        rect(557,181,152,44,'#00E5FF',8);label('Review text',574,197,13,SPACE,True)
        label('EXAMPLE COPY / USE ONLY WHEN TRUE',556,123,9,MUTE)
    elif n==11:
        pic('templates/rareiq-social-card.png',549,257,340,179)
        pic('templates/rareiq-document-cover.png',557,112,83,118)
        para('One focus.\nA deliberate grid.\nRoom to breathe.',666,214,198,15,PAPER)
    elif n==12:
        for j,(a,b) in enumerate([('01','Ready'),('02','Reading text'),('03','Review result'),('04','Confirmed by user')]):
            yy=372-j*69;label(a,556,yy,12,'#00E5FF',True);label(b,598,yy,16,PAPER,True)
        label('STATE DESIGN / NOT A FEATURE CLAIM',556,111,9,MUTE)
    elif n==13:
        pic('icons/rareiq-app-icon.png',555,297,125,125)
        pic('icons/rareiq-ocr-app-icon.png',738,297,125,125)
        pic('templates/rareiq-starting-soon-1920x1080.png',554,112,245,138)
        pic('templates/rareiq-starting-soon-1080x1920.png',814,112,75,138)
    elif n==14:
        pic('mascot/rareiq-mascot-flat-color.png',552,268,154,154)
        pic('mascot/rareiq-mascot-mono-white.png',734,268,154,154)
        label('FLAT VECTOR',560,246,10,MUTE);label('ONE-COLOR VECTOR',733,246,10,MUTE)
        label('SVG / PNG / PDF',557,192,25,PAPER,True)
        para('Rendered masters, outlined wordmarks and editable sources. Choose by medium.',558,160,310,12,MUTE)
    elif n==15:
        label('One source of truth.',557,398,25,PAPER,True)
        for j,txt in enumerate(['01   Select the correct asset','02   Preserve proportions','03   Check final size and contrast','04   Verify the actual application']):label(txt,557,333-j*48,12,PAPER)
        label('RAREIQ / VERSION 2.0',557,126,11,'#00E5FF',True)

for n,p in enumerate(PAGES):
    dark=n in (0,3,7,10,15);bg=SPACE if dark else PAPER;fg=PAPER if dark else SPACE;muted=MUTE if dark else INK
    rect(0,0,960,600,bg)
    if n==0:
        label('RAREIQ / BRAND SYSTEM',56,537,11,MUTE,True)
        para('Intelligence\nfor creators.',56,465,450,51,PAPER,True,63)
        label('The brand book',60,232,22,PAPER)
        label('RareIQ + RareIQ OCR',60,194,13,MUTE)
        label('A premium product within Producer, Please',60,165,11,MUTE)
        pic('logos/rareiq-primary-on-dark.png',500,147,407,336)
        rect(58,122,68,4,'#A855F7')
        label('V2.0 / SEPTEMBER 2026',58,71,11,MUTE)
    else:
        label(p['kicker'].replace('·','/').upper(),56,543,10,muted,True)
        para(p['title'],56,508,850,31,fg,True,38)
        top=para(p['lead'],56,443,422,15,fg,False,22)-19
        for section in p['sections']:
            top=para(section['heading'],56,top,422,12.5,fg,True,17)-5
            top=para(section['text'],56,top,422,10.5,muted,False,15)-12
        if top<62: raise ValueError(f'Page {n+1} content reaches footer: {top}')
        art(n)
        label('RareIQ / Brand standards 2.0',56,35,9,muted)
        label(f'{n+1:02}',882,35,10,muted,True)
    c.showPage()
c.save()
shutil.copyfile(Path(__file__).parent/'book-content.json',OUT/'standards/book-content.json')
markdown='# RareIQ brand standards v2.0\n\n'
for p in PAGES:
    markdown+=f'## {p["title"]}\n\n{p["lead"]}\n\n'
    for s in p['sections']: markdown+=f'### {s["heading"]}\n\n{s["text"]}\n\n'
(OUT/'standards/Brand-Standards.md').write_text(markdown.rstrip()+'\n',encoding='utf-8')
print(f'Created {PDF.name}: {len(PAGES)} pages')
