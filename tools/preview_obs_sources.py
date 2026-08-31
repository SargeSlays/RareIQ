"""Isolated OBS audit visual fixtures. No OBS connection or production API calls."""
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from rareiq.services.broadcast_source_catalog import broadcast_sources
from rareiq.services.obs_source_audit import new_result, issue, summarize

STATIC = Path(__file__).resolve().parents[1] / "rareiq/web/static"
app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def preview():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    styles = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', html))
    section = html.split('<section class="obs-source-audit"', 1)[1].split('</section>', 1)[0]
    script = (STATIC / "studiox.js").read_text(encoding="utf-8")
    formatter = script[script.index('function broadcastSourceFormat('):script.index('async function bootstrapObs(')]
    return HTMLResponse('''<!doctype html><html lang="en" data-theme="dark"><head>
    <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>OBS configuration · isolated visual QA</title>''' + styles + '''
    <style>body.studiox-command-deck{display:block!important;overflow:auto!important;height:auto!important;min-height:100vh;padding:16px}
    .qa-controls{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:0 16px 16px}.qa-controls select{padding:8px}
    .obs-source-audit{margin:0 16px 16px}</style></head>
    <body class="studiox-ui4 studiox-premium studiox-command-deck" data-studiox-visual-system="unified">
    <header class="qa-controls"><strong>ISOLATED QA · simulated OBS · no production access</strong>
    <label>Fixture <select id="fixture"><option value="configured">All configured</option><option value="attention">Setup issues</option><option value="offline">Disconnected</option><option value="failure">Request failure</option></select></label>
    <label>Theme <select id="theme"><option>dark</option><option>light</option></select></label></header>
    <section class="obs-source-audit"''' + section + '''</section>
    <script src="/static/obs_source_audit.js"></script><script>''' + formatter + '''
    const audit=RareIQObsSourceAudit.init({format:broadcastSourceFormat,request:async(path,options)=>{
      const response=await fetch(path+'?fixture='+document.getElementById('fixture').value,options);
      if(!response.ok)throw new Error('Simulated request failure');return response.json();
    }});
    document.getElementById('fixture').onchange=()=>audit.invalidate('Fixture changed. Run Check sources.');
    document.getElementById('theme').onchange=event=>document.documentElement.dataset.theme=event.target.value;
    </script></body></html>''')


@app.post("/api/production/obs/sources/check")
async def check(request: Request, fixture: str = "configured"):
    if fixture == "failure":
        return JSONResponse(status_code=503, content={"ok": False})
    rows = [new_result({**item, "url": str(request.base_url).rstrip('/') + item["path"]}) for item in broadcast_sources()]
    for row in rows:
        row["state"] = "configured"
    if fixture == "offline":
        for row in rows:
            issue(row, "not_checked", "Not checked. Connect OBS and run Check sources again.", state="unavailable")
    elif fixture == "attention":
        issue(rows[0], "scene_missing", "Scene missing. Preview Plan can add it without replacing existing scenes.", state="missing")
        chase = next(row for row in rows if row["key"] == "set_chase")
        issue(chase, "size_mismatch", "Set Browser Source dimensions to 1280 × 320. Canvas transforms are left unchanged.")
        issue(chase, "source_cropped", "This source is cropped in OBS. Review the transform if you need the complete output.")
        issue(rows[-1], "audio_routing", "Enable Control audio via OBS for the soundboard.")
    return {"ok": True, "audit": {"connected": fixture != "offline", "read_only": True, "checked_at": time.time(),
            "diagnostic": {"message": "Simulated configuration snapshot only; no real OBS sources were inspected."}, **summarize(rows)}}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9056, log_level="warning")
