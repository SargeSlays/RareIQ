"""Isolated visual QA: real local artwork, disposable drafts, never production state."""
from pathlib import Path
import re
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

from rareiq.services.set_chase_service import SetChaseService
from rareiq.services.global_visual_index_service import GlobalVisualIndexService
from rareiq.web.set_chase import create_set_chase_router

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "rareiq/web/static"
BASE = "http://127.0.0.1:9040"
temporary = tempfile.TemporaryDirectory(prefix="rareiq-set-chase-qa-")
service = SetChaseService(Path(temporary.name) / "state.json")
rows = httpx.get(BASE + "/api/intelligence/catalog-search", params={"q": "Pitch Black English", "limit": 100}, timeout=30).json()["results"]
rows = [{**row, "set_name": "Pitch Black · Layout Preview"} for row in rows
        if row.get("set_id") == "me5" and row.get("language") == "English" and row.get("reference_image_url")]
if len(rows) < 8:
    raise RuntimeError("Need eight local catalog cards for this visual QA fixture")
cards = [{"id": row["id"], "name": row["name"], "set_id": "me5", "language": "English", "collector_number": row.get("collector_number", ""),
          "image_url": row["reference_image_url"]} for row in rows[:8]]
service.change("draft", 0, {"set_id": "me5", "set_name": "Pitch Black · Layout Preview", "language": "English", "theme": "auto",
                          "cards_per_page": 4, "seconds_per_page": 4, "case_hits": cards[:4], "top_hits": cards[4:]})

index = object.__new__(GlobalVisualIndexService)
index._lock = threading.RLock()
index._records = rows

async def read(request: Request):
    body = await request.body()
    if len(body) > 65536:
        raise ValueError("Too large")
    return await request.json()

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(create_set_chase_router(service, index, read, STATIC))


@app.get("/qa/creator")
async def creator():
    # Actual app markup/styles and Creator controller, with no camera/OBS runtime.
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    html = html.replace('<html lang="en">', '<html lang="en" data-theme="dark">')
    html = html.replace('<title>Rare IQ Studio X</title>', '<title>Creator Studio · isolated QA</title>')
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    controller = source[source.index('const CREATOR_WORKSPACE_VIEW_KEY='):source.index('const BROADCAST_WORKSPACE_PANELS=')]
    return HTMLResponse(html.replace('</body>', '''<script>
    const $=id=>document.getElementById(id);
    document.getElementById('instantSplash').remove();
    document.getElementById('commandDeckWorkspaceTitle').textContent='Isolated Creator QA';
    function showWorkspace(view){
      document.body.dataset.ui4Workspace=view;
      document.querySelectorAll('.workspace').forEach(n=>n.classList.toggle('active',n.dataset.workspace===view));
      document.querySelectorAll('.nav-button[data-target]').forEach(n=>{
        const selected=n.dataset.target===view;n.classList.toggle('active',selected);
        if(selected)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');
      });
    }
    document.querySelectorAll('.nav-button[data-target]').forEach(n=>n.onclick=()=>showWorkspace(n.dataset.target));
    ''' + controller + '''
    initializeCreatorWorkspace();showWorkspace('creator');
    </script></body>'''))

@app.get("/api/catalog-engine/image/{folder}/{filename}")
async def image(folder: str, filename: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE}/api/catalog-engine/image/{folder}/{filename}")
    return Response(response.content, status_code=response.status_code, media_type=response.headers.get("content-type", "image/png"))


@app.get("/qa/creator-viewports")
async def creator_viewports():
    return HTMLResponse('''<!doctype html><html><head><meta charset="utf-8"><title>Creator viewport QA</title>
    <style>body{margin:0;background:#101820;color:#eff5fb;font:14px system-ui}header{display:flex;gap:12px;padding:12px;align-items:center}iframe{border:0;transform-origin:top left}#stage{margin:0 12px;overflow:hidden}output{display:block;white-space:pre-wrap;padding:12px;font:12px monospace}select,button{padding:6px}</style></head><body>
    <header><strong>Isolated Creator layout</strong><label>Viewport <select id="size"><option>1280x720</option><option>1920x1080</option><option>3840x2160</option><option>1024x768</option></select></label><button id="audit">Check fit</button></header>
    <div id="stage"><iframe id="shell" title="Creator viewport" src="/qa/creator"></iframe></div><output id="report" aria-live="polite"></output>
    <script>
    const frame=document.getElementById('shell'),size=document.getElementById('size');
    function resize(){const [w,h]=size.value.split('x').map(Number),scale=Math.min((innerWidth-24)/w,(innerHeight-200)/h);frame.style.width=w+'px';frame.style.height=h+'px';frame.style.transform=`scale(${scale})`;document.getElementById('stage').style.height=h*scale+'px';}
    size.onchange=resize;addEventListener('resize',resize);resize();
    document.getElementById('audit').onclick=()=>{
      const d=frame.contentDocument,w=d.querySelector('.workspace[data-workspace="creator"]'),c=w.querySelector('.full-shell>.content'),f=d.getElementById('creatorChaseFrame'),e=f.contentDocument;
      const r=f.getBoundingClientRect(),doc=e?.documentElement,footer=e?.querySelector('footer');
      document.getElementById('report').textContent=JSON.stringify({viewport:size.value,workspace:[w.clientHeight,w.scrollHeight],host:[c.clientHeight,c.scrollHeight],frameBottom:Math.round(r.bottom),viewportBottom:frame.clientHeight,editor:doc?{width:doc.clientWidth,scrollWidth:doc.scrollWidth,height:doc.clientHeight,scrollHeight:doc.scrollHeight,footerBottom:Math.round(footer.getBoundingClientRect().bottom)}:null},null,2);
    };
    </script></body></html>''')

@app.get("/qa")
async def qa():
    return HTMLResponse('''<!doctype html><html><head><title>Set Chase · isolated visual QA</title>
    <style>body{margin:0;background:#233142;color:#fff;font:14px Arial}p{padding:0 16px}iframe{display:block;border:0;background:repeating-conic-gradient(#101820 0 25%,#141e28 0 50%) 50%/20px 20px}</style></head>
    <body><p>VISUAL TEST ONLY · card selection is not a case-hit or top-hit ranking · 1280 × 320</p>
    <iframe title="1280 source" src="/overlay/set-chase?preview=1" width="1280" height="320"></iframe>
    <p>1080 × 320 · separate source size</p><iframe title="1080 source" src="/overlay/set-chase?preview=1" width="1080" height="320"></iframe>
    <p>1920 × 360 · full-HD source width</p><iframe title="1920 source" src="/overlay/set-chase?preview=1" width="1920" height="360"></iframe></body></html>''')

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9055, log_level="warning")
