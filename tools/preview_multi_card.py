"""Camera-free multi-card QA using production markup, renderers, CSS and selection gate.

Run .venv\\Scripts\\python.exe -B tools\\preview_multi_card.py; loopback + temporary storage only.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rareiq.services.multi_card_recognition_service import MultiCardRecognitionService

STATIC = ROOT / "rareiq/web/static"


def scenario(key):
    def card(slot, verified=True):
        return {"slot": slot, "status": "verified" if verified else "review-needed", "verified": verified,
                "confidence": .94 if verified else .42, "card": {"canonical_name": f"Sample card {slot}",
                "set_name": "Synthetic reference set", "collector_number": f"{slot:03}/084", "language": "English",
                "reference_image_url": "/qa/reference.svg"}, "polygon": []}
    if key == "review":
        slots = [{"slot": 1, "status": "review-needed", "card": {"canonical_name": "Armarouge"}}]
    elif key == "saved":
        slots = [{"slot": 1, "status": "review-needed", "card": {"canonical_name": "Crocalor"}}]
    elif key == "twelve":
        slots = [card(slot, slot % 4 != 0) for slot in range(1, 13)]
    elif key in {"three-verified", "six-verified", "twelve-verified"}:
        count = {"three-verified": 3, "six-verified": 6, "twelve-verified": 12}[key]
        slots = [card(slot) for slot in range(1, count + 1)]
    elif key == "six":
        slots = [card(slot, slot != 3) for slot in range(1, 7)]
    elif key == "broken-image":
        slots = [card(1)]
        slots[0]["card"]["reference_image_url"] = "/qa/missing.svg"
    elif key == "recognizing":
        slots = [card(1), {"slot": 2, "status": "recognizing", "card": None}]
    elif key in {"idle", "no-cards-detected", "error"}:
        slots = []
    else:
        slots = [card(1)]
    return {"status": key if key in {"idle", "recognizing", "no-cards-detected", "error"} else "complete",
            "ok": key not in {"error", "no-cards-detected"}, "restored": key == "saved", "slots": slots, "max_cards": 12,
            "detected_count": len(slots), "completed_count": sum(s["status"] != "recognizing" for s in slots)}


def page():
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', html))
    start = html.index('        <section class="multi-card-panel"')
    end = html.index('        <div class="recognition-state"', start)
    markup = html[start:end]
    # Fixture-only density scenarios; production controls still enforce verification.
    tabs_start = html.index('        <div class="ui4-inspector-primary-tabs"')
    tabs_end = html.index('        <div class="single-card-control"', tabs_start)
    tabs = html[tabs_start:tabs_end]
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    js = source[source.index("function multiCardName("):source.index("const VIRTUAL_CAMERA_TERMS=")]
    mode = source[source.index("function syncRecognitionModeWorkspace()"):source.index("function setRecognitionMode(")]
    presentation_js = source[source.index("function applyRecognitionPresentation("):source.index("function renderRecognitionLatencyTrace(")]
    shield = re.search(r'<div class="camera-feed-state-shield".*?</div>', html, re.S).group(0)
    hud = html[html.index('        <div class="camera-bottom-hud'):html.index('      </article>', html.index('        <div class="camera-bottom-hud'))]
    return f'''<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Multi-card isolated QA</title>{css}
    <style>body.studiox-command-deck{{display:block!important;margin:0!important;overflow:auto!important}}.qa-head{{padding:16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}.qa-shell{{display:grid;grid-template-columns:minmax(0,7fr) minmax(350px,3fr);align-items:start}}.qa-camera{{padding:32px;color:var(--sx-text-soft)}}.qa-results{{min-width:0;container-type:inline-size;container-name:result-panel}}.qa-results>header{{padding:22px;background:var(--sx-chrome)}}body .ui4-current-card-view{{height:auto!important;max-height:none!important;padding:0!important;overflow:visible!important}}#qaNotice{{padding:12px}}@media(max-width:900px){{.qa-shell{{display:block}}.qa-camera{{display:none}}}}</style></head>
    <body class="studiox-ui4 studiox-premium studiox-command-deck" data-studiox-visual-system="unified" data-operator-layout="v2" data-recognition-mode="six-card-grid" data-ui4-workspace="live">
    <header class="qa-head"><strong>Multi-card regression preview</strong><label>Test scenario <select id="qaScenario"><option value="review">Unverified / no artwork</option><option value="saved">Saved incomplete result</option><option value="verified">One verified card</option><option value="three-verified">Three verified cards</option><option value="six-verified">Six verified cards</option><option value="twelve-verified">Twelve verified cards</option><option value="six">Six mixed results</option><option value="twelve">Twelve mixed results</option><option value="recognizing">Recognition in progress</option><option value="broken-image">Broken reference image</option><option value="no-cards-detected">No cards detected</option><option value="error">Scan failure</option><option value="idle">Idle</option></select></label></header>
    <main class="qa-shell"><section class="qa-camera"><h1>Camera-free QA</h1><p>Production component and selection service. Synthetic catalog artwork. Temporary storage only.</p><p>No camera, microphone, OBS or live server access.</p><button id="qaFocus">Focus inspector</button><p id="qaNotice" role="status"></p></section><div class="qa-results ui4-inspector-column"><aside class="riq-surface inspector ui4-inspector-region" data-operator-section="card" data-ui4-region="current-card">{tabs}<div class="ui4-current-card-view">{markup}<nav id="inspectorSectionNav" class="inspector-section-nav"><button>Recognition</button><button>Tools</button></nav></div></aside></div></main>
    <style>.qa-head{{height:72px;box-sizing:border-box}}.qa-shell{{height:calc(100dvh - 72px);grid-template-columns:minmax(0,7fr) 12px minmax(350px,3fr)}}html[data-theme] body.studiox-ui4.studiox-premium.studiox-command-deck[data-operator-layout="v2"] .qa-results.ui4-inspector-column{{width:100%!important;height:100%!important}}body .qa-results .ui4-inspector-region{{height:100%!important;max-height:100%!important}}body .qa-results .ui4-current-card-view{{flex:1;min-height:0;height:auto!important;overflow:auto!important}}body.qa-focus .qa-shell{{display:block;max-width:1142px;margin:auto}}body.qa-focus .qa-camera{{display:none}}.qa-hud #cameraFeedStateShield,.qa-hud #recognitionStatePanel{{position:static!important;display:flex!important;transform:none!important;margin:20px 0!important;max-width:600px}}</style>
    <script src="/static/multi_card_state.js"></script><script>
    const $=id=>document.getElementById(id);let studioXRecognitionMode='six-card-grid',multiCardPollTimer=null,captureBusy=false;
    let latestSingleCameraPresentation=null,cameraConnectionAvailable=true,cameraConnectionFailure=null,cardPlaceholderResetTimer=null;
    const normalize=value=>value;function updateConfidenceRing(){{}}function setStateChip(){{}}function updateAiPulse(){{}}function setCoreState(){{}}
    const qaHud=document.createElement('div');qaHud.className='qa-hud';qaHud.innerHTML={json.dumps(shield + hud)};
    document.querySelector('.qa-camera').appendChild(qaHud);
    for(const [id,label,action] of [
      ['qaStale','Background single-card event',()=>applyRecognitionPresentation({{key:'candidate-found',title:'CANDIDATE FOUND',detail:'Single-card candidate'}})],
      ['qaOffline','Toggle camera connection',()=>{{cameraConnectionAvailable=!cameraConnectionAvailable;renderCameraRecognitionPresentation();}}],
      ['qaMode','Toggle recognition mode',()=>{{studioXRecognitionMode=studioXRecognitionMode==='single'?'six-card-grid':'single';renderCameraRecognitionPresentation();}}]
    ]){{const button=document.createElement('button');button.id=id;button.textContent=label;button.onclick=action;qaHud.appendChild(button);}}
    function setCardText(id,text){{if($(id))$(id).textContent=text;}}
    function recognitionMutationInFlight(){{return captureBusy;}}
    function setRecognitionCaptureBusy(busy){{captureBusy=busy;$('multiCardCaptureButton').disabled=busy;}}
    function notify(title,text){{setCardText('qaNotice',title+': '+text);}}
    async function api(path,options={{}}){{const response=await fetch(path,{{headers:{{'Content-Type':'application/json'}},...options}});const data=await response.json();if(!response.ok)throw new Error(data.reason||'Request failed');return data;}}
    {js}
    {presentation_js}
    {mode}
    $('qaScenario').addEventListener('change',async()=>{{await api('/qa/scenario',{{method:'POST',body:JSON.stringify({{scenario:$('qaScenario').value}})}});await loadMultiCardStatus();}});
    $('multiCardResults').addEventListener('click',event=>{{const button=event.target.closest('.multi-card-show-toggle');if(button)toggleMultiCardOutput(button.dataset.slot).catch(()=>{{}});}});
    $('multiCardCaptureButton').addEventListener('click',()=>captureMultiCardGrid().catch(()=>{{}}));
    $('qaFocus').addEventListener('click',()=>document.body.classList.add('qa-focus'));
    syncRecognitionModeWorkspace();loadMultiCardStatus();
    </script></body></html>'''


def speed_page():
    """Camera-free result-speed states using the production header and renderer."""
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', html))
    start = html.index('<header class="studiox-recognition-workspace-head">')
    header = html[start:html.index('</header>', start) + len('</header>')]
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    renderer = source[source.index("function deriveRecognitionSpeed("):source.index("function renderRecognitionLatencyTrace(")]
    return f'''<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Match speed QA</title>{css}
    <style>body.studiox-command-deck{{display:block!important;padding:24px!important;overflow:auto!important}}.qa-speed-controls{{display:flex;gap:12px;margin-bottom:20px}}#qaSpeedHeader{{max-width:100%;width:1142px}}#qaSpeedHeader.narrow{{width:330px}}</style></head>
    <body class="studiox-ui4 studiox-premium studiox-command-deck" data-studiox-visual-system="unified" data-operator-layout="v2">
    <div class="qa-speed-controls"><label>Timing state <select id="qaSpeedState"><option value="exact-match">Verified</option><option value="candidate-found">Candidate</option><option value="review-needed">Review needed</option><option value="ready">Idle</option><option value="error">Disconnected</option><option value="stale">Previous card timing</option><option value="missing">Missing timing</option></select></label><button id="qaSpeedWidth">Toggle narrow panel</button><button id="qaSpeedTheme">Toggle theme</button></div>
    <section id="qaSpeedHeader">{header}</section>
    <script>const $=id=>document.getElementById(id);{renderer}
    function renderSample(){{const selected=$('qaSpeedState').value,context={{presentation:{{key:selected}},verified:selected==='exact-match',card:{{id:'sample'}},snapshot:{{generation:3,result_current:true,stage_timings:{{capture_to_result_ms:756,total_ms:720}}}}}};
      if(selected==='candidate-found')context.snapshot.stage_timings.capture_to_result_ms=1324;
      if(selected==='stale'){{context.presentation.key='exact-match';context.snapshot.raw_recognition={{generation:2}};}}
      if(selected==='missing'){{context.presentation.key='exact-match';context.snapshot.stage_timings={{}};}}
      renderRecognitionSpeed(context);
    }}
    $('qaSpeedState').onchange=renderSample;
    $('qaSpeedWidth').onclick=()=>$('qaSpeedHeader').classList.toggle('narrow');
    $('qaSpeedTheme').onclick=()=>{{document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';}};
    renderSample();</script></body></html>'''


class FakeWorker:
    def shutdown(self):
        pass


def geometry_page():
    """Exercise the production box renderer against known full-frame coordinates."""
    html = (STATIC / "control.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', html))
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    renderer = source[source.index("const multiCardOverlayBindings="):source.index("let singleCardPickerActive=")]
    return f'''<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Camera box geometry QA</title>{css}
    <style>html[data-theme] body.studiox-command-deck{{display:block!important;margin:0!important;padding:20px!important;overflow:auto!important}}
    .qa-bar{{display:flex;gap:20px;padding:12px}}
    #qaGeometryStage{{position:relative;width:calc(100vw - 40px);height:calc(100dvh - 120px);background:#000;overflow:hidden}}
    #qaGeometryStage.narrow{{width:55vw;height:calc(100dvh - 120px)}}
    #qaGeometryStage #cameraFeed{{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;object-fit:contain!important}}</style></head>
    <body class="studiox-ui4 studiox-premium studiox-command-deck" data-studiox-visual-system="unified" data-operator-layout="v2">
    <div class="qa-bar"><strong>Camera-free geometry check</strong><button id="qaResize">Resize camera area</button><button id="qaReload">Reload frame</button><span>Numbered outlines should match all four card corners.</span></div>
    <div id="qaGeometryStage"><img id="cameraFeed" alt="Synthetic three-card frame"><svg id="multiCardCameraOverlay" class="multi-card-camera-overlay" hidden aria-label="Detected card outlines"></svg></div>
    <script>const $=id=>document.getElementById(id);let studioXRecognitionMode='six-card-grid';
    {renderer}
    const slots=[180,650,1120].map((left,index)=>({{slot:index+1,status:'verified',polygon:[[left/1600,.3],[(left+280)/1600,.3],[(left+280)/1600,.76],[left/1600,.76]]}}));
    const art='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#222a35"/>'+[180,650,1120].map((left,i)=>`<rect x="${{left}}" y="270" width="280" height="414" fill="${{['#805464','#815a36','#52764c'][i]}}"/><text x="${{left+140}}" y="400" fill="white" font-size="36" text-anchor="middle">Card ${{i+1}}</text>`).join('')+'</svg>';
    $('qaResize').onclick=()=>$('qaGeometryStage').classList.toggle('narrow');
    $('qaReload').onclick=()=>{{$('cameraFeed').src='';renderMultiCardCameraOverlay(slots);requestAnimationFrame(()=>{{$('cameraFeed').src='data:image/svg+xml,'+encodeURIComponent(art)}})}};
    $('cameraFeed').addEventListener('load',()=>{{if(!$('multiCardCameraOverlay').childElementCount)renderMultiCardCameraOverlay(slots);}},{{once:true}});
    $('cameraFeed').src='data:image/svg+xml,'+encodeURIComponent(art);
    </script></body></html>'''


class FakePrototype:
    def isolated_copy(self, _emit):
        return FakeWorker()


def overlay_viewport_page():
    """Real iframe viewports for camera-free 4K and portrait layout checks."""
    return '''<!doctype html><html><head><meta charset="utf-8"><title>Overlay viewport QA</title>
    <style>body{margin:0;background:#111821;color:#f4f7fa;font:14px system-ui}header{padding:16px;display:flex;gap:16px}select{padding:8px}#viewport{margin:16px;overflow:hidden;background:#293747}iframe{border:0;display:block;transform-origin:top left}</style></head><body>
    <header><label>Surface <select id="surface"><option value="/overlay/multi-card">Selected cards</option><option value="/overlay/landscape">Landscape</option><option value="/overlay/portrait">Portrait</option><option value="/overlay/current-card">Current card</option><option value="/overlay/graphics">Graphics</option><option value="/production-screen">Countdown</option><option value="/overlay/pokedex">Rare Intelligence</option></select></label>
    <label>Viewport <select id="size"><option>1280x720</option><option>1920x1080</option><option>3840x2160</option><option>1080x1920</option></select></label><span>Isolated synthetic data only</span></header>
    <div id="viewport"><iframe title="Overlay under test"></iframe></div><script>
    const frame=document.querySelector('iframe'),viewport=document.getElementById('viewport'),surface=document.getElementById('surface'),size=document.getElementById('size');
    function layout(){const [w,h]=size.value.split('x').map(Number),scale=Math.min((innerWidth-32)/w,(innerHeight-110)/h);frame.style.width=w+'px';frame.style.height=h+'px';frame.style.transform=`scale(${scale})`;viewport.style.width=w*scale+'px';viewport.style.height=h*scale+'px';}
    surface.onchange=()=>frame.src=surface.value;size.onchange=layout;addEventListener('resize',layout);frame.src=surface.value;layout();
    </script></body></html>'''


def main():
    with tempfile.TemporaryDirectory(prefix="rareiq-grid-qa-") as directory:
        service = MultiCardRecognitionService(FakePrototype(), Path(directory) / "history.json", Path(directory) / "presentation.json")
        service._state = scenario("review")
        current = "review"
        started_at = time.time()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, body, mime="application/json", status=200):
                if not isinstance(body, bytes):
                    body = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    return self.send(page().encode(), "text/html; charset=utf-8")
                if path == "/qa/geometry":
                    return self.send(geometry_page().encode(), "text/html; charset=utf-8")
                if path == "/qa/speed":
                    return self.send(speed_page().encode(), "text/html; charset=utf-8")
                if path == "/qa/overlay":
                    return self.send(overlay_viewport_page().encode(), "text/html; charset=utf-8")
                if path == "/api/multi-card/status":
                    return self.send(service.status())
                overlays = {"/overlay/multi-card": "overlay_multicard.html", "/overlay/landscape": "overlay_landscape.html",
                            "/overlay/portrait": "overlay_portrait.html", "/overlay/current-card": "overlay_current_card.html",
                            "/overlay/graphics": "overlay_graphics.html", "/production-screen": "overlay_production_screen.html",
                            "/overlay/pokedex": "overlay_pokedex.html"}
                if path in overlays:
                    return self.send((STATIC / overlays[path]).read_bytes(), "text/html; charset=utf-8")
                if path == "/api/brand":
                    return self.send({"brand": {"creator_name": "Camera-free QA"}})
                if path == "/api/overlay/state":
                    return self.send({"state": {"current_card_status": "verified", "current_card": {
                        "card_name": "Sample full card", "set_name": "Synthetic reference set", "collector_number": "001/084",
                        "reference_image_url": "/qa/reference.svg"}}})
                if path == "/api/production/graphics":
                    return self.send({"graphic": {"visible": True, "kind": "card", "title": "Sample card graphic", "subtitle": "QA only · Synthetic reference", "image_url": "/qa/reference.svg"}})
                if path == "/api/production/screen":
                    return self.send({"screen": {"visible": True, "title": "Starting Soon", "message": "Camera-free production screen test", "started_at": started_at, "countdown_seconds": 300}})
                if path == "/api/rare-intelligence/current":
                    return self.send({"on_air": True, "pokemon": {"id": 1, "name": "Sample species", "genus": "QA only", "artwork_url": "/qa/reference.svg", "types": ["Sample"], "height_m": 1, "weight_kg": 10, "abilities": ["Sample ability"], "flavor_text": "Synthetic profile for browser layout testing, not real species data."}})
                if path == "/qa/reference.svg":
                    return self.send(b'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="700"><rect x="8" y="8" width="484" height="684" fill="#18222e" stroke="#8be8ca" stroke-width="12"/><text x="250" y="100" text-anchor="middle" fill="#f4f7fa" font-size="32">QA FULL CARD</text><rect x="40" y="150" width="420" height="310" fill="#293747"/><text x="250" y="660" text-anchor="middle" fill="#8be8ca" font-size="24">001/084 - Bottom edge</text></svg>', "image/svg+xml")
                if path.startswith("/static/"):
                    target = (STATIC / path.removeprefix("/static/")).resolve()
                    types = {".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png"}
                    if target.is_relative_to(STATIC) and target.is_file() and target.suffix in types:
                        return self.send(target.read_bytes(), types[target.suffix])
                return self.send({"reason": "not_found"}, status=404)

            def do_POST(self):
                nonlocal current
                length = int(self.headers.get("Content-Length") or 0)
                if length > 8192:
                    return self.send({"reason": "too_large"}, status=413)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/qa/scenario":
                    current = payload.get("scenario", "review")
                    service._state = scenario(current)
                    service._selected_slots = set()
                elif self.path == "/api/multi-card/capture":
                    service._state = {**scenario(current), "restored": False}
                elif self.path == "/api/multi-card/select":
                    result = service.select_slots(payload.get("slots", []))
                    return self.send(result, status=200 if result.get("ok") else 409)
                elif self.path == "/qa/shutdown":
                    threading.Thread(target=server.shutdown, daemon=True).start()
                else:
                    return self.send({"reason": "not_found"}, status=404)
                self.send(service.status())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        print(f"Multi-card camera-free preview: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.shutdown()


if __name__ == "__main__":
    main()
