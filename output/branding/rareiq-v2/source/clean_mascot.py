"""Owner-authorized local matte cleanup, preserving enclosed white eye highlights."""
from pathlib import Path
import sys,json
import numpy as np
from PIL import Image,ImageDraw,ImageFilter

src=Path(sys.argv[1]); dst=Path(sys.argv[2]); dst.parent.mkdir(parents=True,exist_ok=True)
im=Image.open(src).convert('RGB'); a=np.asarray(im)
# Only pale neutral pixels connected to the canvas boundary are background.
# White eye highlights are enclosed by dark eyes and cannot enter that component.
neutral=(a.max(axis=2).astype(int)-a.min(axis=2).astype(int)<=8)&(a.min(axis=2)>=180)
flood=Image.fromarray(np.uint8(neutral)*255).copy()
ImageDraw.floodfill(flood,(0,0),128,thresh=0)
mask=Image.fromarray(np.where(np.asarray(flood)==128,0,255).astype('uint8'))
# Remove a one-pixel pale fringe, then antialias the matte at subpixel scale.
mask=mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(.45))
out=im.convert('RGBA');out.putalpha(mask)
assert mask.getextrema()==(0,255)
for pt in ((0,0),(im.width-1,0),(0,im.height-1),(im.width-1,im.height-1)):
    assert mask.getpixel(pt)==0
box=mask.getbbox();pad=32
out=out.crop((box[0]-pad,box[1]-pad,box[2]+pad,box[3]+pad));out.save(dst)
qa=dst.parents[1]/'qa';qa.mkdir(exist_ok=True)
for name,color in [('dark','#080F1A'),('light','#F7F8FC')]:
    bg=Image.new('RGBA',out.size,color);bg.alpha_composite(out)
    bg.convert('RGB').save(qa/f'mascot-on-{name}.png')
print(json.dumps({'mode':out.mode,'size':out.size,'alpha_range':mask.getextrema(),'visible_bbox':mask.getbbox()}))
