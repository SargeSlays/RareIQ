"""Isolated camera-control QA: production markup, CSS and JS; synthetic sources only."""
from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[1] / "rareiq/web/static"


def camera_page():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', html))
    start = html.index('      <article id="cameraWorkspace"')
    markup = html[start:html.index('</article>', start) + len('</article>')]
    prompt = next(line.strip() for line in html.splitlines() if 'id="recognitionWorkflowPrompt"' in line)
    markup = markup.replace('</article>', prompt.replace(' hidden>', '>') + '</article>')
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    functions = source[source.index('function normalizeCameraWorkspacePreferences('):source.index('function normalizeSecondaryBayPreferences(')]
    codecs = source[source.index('function decodeCameraValue('):source.index('function sortCameraDevices(')]
    bindings = source[source.index('  $("cameraSlot1Source")?.addEventListener'):source.index('  $("cameraPtzButton")?.addEventListener')]
    bindings += source[source.index('  $("cameraSlot1Side")?.addEventListener'):source.index('  if(secondaryBayPreferences.activeSource&&$("cameraSelect"))')]
    return f'''<!doctype html><html data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Camera workspace isolated QA</title>{css}
    <style>html[data-theme] body.studiox-command-deck{{display:block!important;margin:0!important;overflow:hidden!important}}
    .qa-controls{{height:70px;box-sizing:border-box;display:flex;gap:12px;align-items:center;padding:12px;background:var(--sx-chrome)}}
    .qa-camera-area{{position:relative;width:70vw;height:calc(100dvh - 70px);float:left}}
    .qa-notes{{margin-left:70vw;padding:16px;font:14px system-ui;color:var(--sx-text-soft)}}
    #qaReport{{display:block;white-space:pre-wrap;font:12px monospace;max-height:70vh;overflow:auto}}
    #cameraWorkspace{{height:100%!important;min-height:0!important}}
    #cameraWorkspace .camera-top-hud,#cameraWorkspace .camera-bottom-hud,#cameraWorkspace .pipeline-rail,#cameraWorkspace .ui4-diagnostics-drawer{{display:none!important}}
    </style></head><body class="studiox-ui4 studiox-premium studiox-command-deck" data-operator-layout="v2" data-studiox-visual-system="unified" data-ui4-workspace="live">
    <div class="qa-controls"><strong>Camera-free QA</strong><button id="qaRefresh">Refresh telemetry</button><button id="qaTheme">Toggle theme</button><label><input id="qaFailure" type="checkbox">Fail next assignment</label><button id="qaAudit">Check layout</button></div>
    <div class="qa-camera-area">{markup}</div><aside class="qa-notes"><p>Production camera controls. Synthetic devices; no hardware or live-server access.</p><p id="qaNotice" role="status"></p><output id="qaReport"></output></aside>
    <select id="cameraSelect" hidden></select><script>
    const $=id=>document.getElementById(id),CAMERA_WORKSPACE_LAYOUTS=['single','dual-side','triple','quad'],CAMERA_WORKSPACE_KEY='qa-camera-workspace';
    let cameraWorkspacePreferences,cameraWorkspaceStateSignature='',cameraWorkspaceSlotStates={{}},cameraWorkspaceSlotActions=new Set(),secondaryBayPreferences={{}},selectedCamera=null,cameraStreamStarted=true;
    {codecs}
    {functions}
    const cameras=Array.from({{length:4}},(_,i)=>({{source_id:'qa-'+(i+1),device_key:'qa-'+(i+1),index:i,backend:700,name:'Test camera '+(i+1)}}));
    let slots=cameras.map((camera,i)=>({{slot_id:i+1,source:i===0?camera:null,source_id:i===0?camera.source_id:null,role:i===0?'active':'staging',side:'unassigned',connection_state:i===0?'connected':'unassigned',connected:i===0,frame_id:1}}));
    function saveSecondaryBayPreferences(){{}}
    function alignScanZone(){{}}
    function startCameraStream(){{}}
    function promoteSecondaryStagingSource(){{return promoteCameraWorkspaceSlot(2);}}
    function notify(title,message){{$('qaNotice').textContent=title+': '+message;}}
    function renderSecondaryWorkspaceBay(){{const image=$('secondaryBayImage'),assigned=Boolean(cameraWorkspacePreferences.sources['2']),visible=cameraWorkspaceVisibleSlots().includes(2);$('secondaryWorkspaceBay').hidden=!visible;$('secondaryBayUnavailable').hidden=assigned;image.hidden=!assigned||!visible;if(assigned&&visible)image.src='/api/camera-slots/2/stream';else image.removeAttribute('src');}}
    async function api(path,options={{}}){{
      if(path==='/api/camera-slots')return {{slots}};
      const match=path.match(/camera-slots\\/(\\d+)\\/(source|activate)/);if(!match)throw Error('Unexpected fixture request');
      if($('qaFailure').checked){{$('qaFailure').checked=false;throw Error('Simulated unavailable source');}}
      const id=Number(match[1]),body=JSON.parse(options.body||'{{}}'),row=slots[id-1];
      if(match[2]==='activate'){{slots.forEach(s=>s.role=s.slot_id===id?'active':'staging');return {{slots}};}}
      const camera=cameras.find(c=>c.source_id===body.source_id)||null;
      Object.assign(row,{{source:camera,source_id:camera?.source_id||null,side:body.side,connection_state:camera?'connected':'unassigned',connected:Boolean(camera)}});
      return {{slot:row}};
    }}
    function cameraAudit(testId=null){{
      const issues=[],headers=[...document.querySelectorAll('.camera-tile-header')].filter(e=>e.getBoundingClientRect().width>0),workspace=$('cameraWorkspace').getBoundingClientRect();
      const rect=e=>{{const r=e.getBoundingClientRect();return {{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}};}};
      const controls=headers.flatMap(h=>[...h.querySelectorAll('select')].map(e=>{{const r=rect(e),p=rect(h),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(r.x<p.x-1||r.right>p.right+1||r.y<p.y-1||r.bottom>p.bottom+1)issues.push(e.id+' outside header');if(hit!==e)issues.push(e.id+' obscured');if(r.height<29)issues.push(e.id+' too short');return {{id:e.id,...r}};}}));
      headers.forEach((h,i)=>{{const r=rect(h);if(r.bottom>workspace.bottom+1)issues.push('header outside workspace');headers.slice(i+1).forEach(other=>{{const s=rect(other);if(Math.min(r.right,s.right)>Math.max(r.x,s.x)+1&&Math.min(r.bottom,s.bottom)>Math.max(r.y,s.y)+1)issues.push('headers overlap');}});}});
      const prompt=$('recognitionWorkflowPrompt'),promptRect=rect(prompt),mediaRect=rect(document.querySelector('.camera-stage-inner'));
      if(promptRect.x<mediaRect.x-1||promptRect.right>mediaRect.right+1||promptRect.y<mediaRect.y-1||promptRect.bottom>mediaRect.bottom+1)issues.push('scan prompt outside primary media');
      prompt.querySelectorAll('button').forEach(button=>{{const r=rect(button);if(r.x<promptRect.x||r.right>promptRect.right||r.y<promptRect.y||r.bottom>promptRect.bottom)issues.push('scan mode button outside prompt');if(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)!==button)issues.push('scan mode button obscured');}});
      const report={{testId:typeof testId==='string'?testId:null,viewport:[innerWidth,innerHeight],layout:cameraWorkspacePreferences.layout,headers:headers.length,controls,issues}};
      $('qaReport').textContent=JSON.stringify(report,null,2);parent.postMessage({{cameraReport:report}},location.origin);return report;
    }}
    cameras.forEach(camera=>{{const option=document.createElement('option');option.value=cameraOptionValue(camera,camera.index);option.textContent=camera.name;$('cameraSelect').append(option);}});
    cameraWorkspacePreferences=normalizeCameraWorkspacePreferences({{layout:'quad'}});syncCameraWorkspaceSlotStates(slots,{{force:true}});renderSecondaryWorkspaceBay();
    $('cameraFeed').src='/api/camera-slots/1/stream';$('cameraWorkspace').classList.add('viewer-live');$('cameraPlaceholder').classList.add('hidden');$('cameraRecovery').classList.add('suppressed');
    {bindings}
    $('qaRefresh').onclick=()=>{{slots.forEach(s=>s.frame_id++);syncCameraWorkspaceSlotStates(slots);}};
    $('qaTheme').onclick=()=>document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';
    $('qaAudit').onclick=cameraAudit;
    addEventListener('message',event=>{{if(event.origin!==location.origin)return;if(event.data.layout)document.querySelector(`[data-camera-layout-option="${{event.data.layout}}"]`)?.click();if(event.data.audit)requestAnimationFrame(()=>requestAnimationFrame(()=>cameraAudit(event.data.testId)));}});
    addEventListener('resize',()=>requestAnimationFrame(cameraAudit));setTimeout(cameraAudit,200);
    </script></body></html>'''


def viewport_page():
    return '''<!doctype html><html><head><meta charset="utf-8"><title>Camera viewport QA</title><style>body{margin:0;background:#0b1016;color:#f4f7fa;font:14px system-ui}header{display:flex;gap:16px;padding:12px}iframe{border:0;transform-origin:top left}#frame{margin:12px;overflow:hidden}#report{white-space:pre-wrap;margin:12px}</style></head><body>
    <header><label>Viewport <select id="size"><option>1280x720</option><option>1920x1080</option><option>3840x1980</option><option>3840x2160</option></select></label><label>Layout <select id="layout"><option value="quad">Four cameras</option><option value="triple">Three cameras</option><option value="dual-side">Two cameras</option><option value="single">Single camera</option></select></label><button id="check">Check layout</button><button id="matrix">Test all sizes and layouts</button></header>
    <div id="frame"><iframe title="Camera workspace under test" src="/camera"></iframe></div><output id="report"></output><script>
    const frame=document.querySelector('iframe'),size=document.getElementById('size'),layout=document.getElementById('layout');
    function resize(){const [w,h]=size.value.split('x').map(Number),scale=Math.min((innerWidth-24)/w,(innerHeight-160)/h);frame.style.width=w+'px';frame.style.height=h+'px';frame.style.transform=`scale(${scale})`;document.getElementById('frame').style.height=h*scale+'px';frame.contentWindow.postMessage({audit:true},location.origin);}
    size.onchange=resize;layout.onchange=()=>frame.contentWindow.postMessage({layout:layout.value,audit:true},location.origin);document.getElementById('check').onclick=()=>frame.contentWindow.postMessage({audit:true},location.origin);frame.onload=resize;
    let pending=null,running=false;
    addEventListener('message',e=>{if(e.origin!==location.origin||!e.data.cameraReport)return;const r=e.data.cameraReport,result={viewport:r.viewport,layout:r.layout,headers:r.headers,controls:r.controls.length,issues:r.issues};if(pending&&r.testId===pending.id){pending.resolve(result);pending=null;}if(!running)document.getElementById('report').textContent=JSON.stringify(result);});addEventListener('resize',resize);
    document.getElementById('matrix').onclick=async()=>{running=true;document.getElementById('matrix').disabled=true;const results=[];for(const viewport of [...size.options].map(o=>o.value)){size.value=viewport;resize();for(const mode of ['single','dual-side','triple','quad']){layout.value=mode;const id=viewport+mode;const response=new Promise((resolve,reject)=>{pending={id,resolve};setTimeout(()=>{if(pending?.id===id){pending=null;reject(Error('QA report timed out'));}},5000);});frame.contentWindow.postMessage({layout:mode,audit:true,testId:id},location.origin);results.push(await response);document.getElementById('report').textContent=JSON.stringify(results);}}running=false;document.getElementById('matrix').disabled=false;document.getElementById('report').textContent=JSON.stringify(results);};
    </script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in {'/', '/camera'}:
            content = viewport_page() if path == '/' else camera_page()
            body, mime = content.encode(), 'text/html; charset=utf-8'
        elif re.fullmatch(r'/api/camera-slots/[1-4]/stream', path):
            slot = path.split('/')[-2]
            body = f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#18222e"/><rect x="20" y="20" width="1560" height="860" stroke="#8be8ca" fill="none" stroke-width="12"/><text x="800" y="450" text-anchor="middle" fill="#f4f7fa" font-size="80">TEST CAMERA {slot}</text><text x="800" y="830" text-anchor="middle" fill="#8be8ca" font-size="36">Full frame · bottom edge</text></svg>'.encode()
            mime = 'image/svg+xml'
        elif path.startswith('/static/'):
            target = (STATIC / path.removeprefix('/static/')).resolve()
            if not target.is_relative_to(STATIC) or not target.is_file():
                self.send_error(404)
                return
            body, mime = target.read_bytes(), mimetypes.guess_type(target)[0] or 'application/octet-stream'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(f'Camera-free workspace QA: http://127.0.0.1:{server.server_port}', flush=True)
    server.serve_forever()
