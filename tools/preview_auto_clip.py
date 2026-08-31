"""Camera-free Auto Clip QA: actual UI/functions + services, temporary storage only.

Run: .venv\\Scripts\\python.exe -B tools\\preview_auto_clip.py
Only binds loopback. Does not import/start the application, devices, or integrations.
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

import cv2
import numpy as np

from rareiq.services.auto_clip_service import AutoClipService
from rareiq.services.instant_replay_service import InstantReplayService

STATIC = ROOT / "rareiq/web/static"


def page() -> str:
    control = (STATIC / "control.html").read_text(encoding="utf-8")
    css = "\n".join(re.findall(r'<link rel="stylesheet"[^>]+>', control))
    start = control.index('  <section class="production-replay">')
    end = control.index('  <section class="production-screens">', start)
    source = (STATIC / "studiox.js").read_text(encoding="utf-8")
    js = source[source.index("function renderProductionReplay("):source.index("let productionReplayMarkPending=")]
    handlers = "\n".join(line for line in source.splitlines() if '$("productionAutoClip' in line and "addEventListener" in line)
    return f'''<!doctype html><html data-theme="dark"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>RareIQ Auto Clip · isolated QA</title>{css}
      <style>body.studiox-command-deck{{display:block!important;overflow:auto!important;padding:24px;min-width:0}}main{{max-width:1300px;margin:auto}}.qa-toolbar{{display:flex;gap:12px;flex-wrap:wrap;margin:16px}}.qa-toolbar button{{padding:12px}}h1{{font-size:24px;margin:16px}}.qa-note{{margin:16px;color:var(--sx-text-soft)}}body .production-replay{{margin:0}}</style></head>
      <body class="studiox-ui4 studiox-premium studiox-command-deck" data-studiox-visual-system="unified" data-ui4-workspace="broadcast">
      <main class="workspace active studiox-app-workspace--broadcast" data-workspace="broadcast" style="display:block!important;position:static!important"><h1>Auto Clip · isolated QA</h1><p class="qa-note">Synthetic Program frames. Temporary storage. No camera, microphone, OBS, or live server.</p>
      <nav class="qa-toolbar"><button id="qaPull">Simulate verified pull</button><button id="qaCamera">Interrupt synthetic camera</button></nav>
      {control[start:end]}<p id="qaNotice" class="qa-note" role="status"></p></main><script>
      const $=id=>document.getElementById(id);
      async function api(path,options={{}}){{const response=await fetch(path,{{headers:{{'Content-Type':'application/json'}},...options}});const result=await response.json();if(!response.ok)throw new Error(result.reason||'Request failed');return result;}}
      function notify(title,message){{$('qaNotice').textContent=title+': '+message;}}
      async function takeProductionReplay(id){{await api('/qa/take',{{method:'POST',body:JSON.stringify({{id}})}});notify('Replay ready','Isolated playback only; nothing goes on air.');}}
      {js}
      {handlers}
      $('qaPull').addEventListener('click',async()=>{{await api('/qa/pull',{{method:'POST'}});await loadProductionReplay();}});
      $('qaCamera').addEventListener('click',async()=>{{await api('/qa/interrupt',{{method:'POST'}});await loadProductionReplay();}});
      $('productionReplayMark').addEventListener('click',async()=>{{await api('/qa/mark',{{method:'POST'}});await loadProductionReplay();}});
      $('productionReplayStop').addEventListener('click',()=>api('/qa/stop-replay',{{method:'POST'}}));
      loadProductionReplay();
      </script></body></html>'''


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rareiq-auto-clip-qa-") as directory:
        root = Path(directory)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        frame[:] = (33, 24, 17)
        cv2.rectangle(frame, (20, 20), (620, 340), (202, 232, 139), 4)
        cv2.putText(frame, "RAREIQ - SYNTHETIC QA", (72, 180), cv2.FONT_HERSHEY_SIMPLEX, .8, (245, 245, 245), 2)
        jpeg = cv2.imencode(".jpg", frame)[1].tobytes()
        replay = InstantReplayService(root / "replay", lambda _: jpeg, lambda: 1)
        auto = AutoClipService(replay, root / "settings.json")
        generation = 0

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, body: bytes, mime: str, status: int = 200, attachment: bool = False):
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if attachment:
                    self.send_header("Content-Disposition", 'attachment; filename="RareIQ-synthetic-test.mp4"')
                self.end_headers()
                self.wfile.write(body)

            def result(self, result, key=None):
                self.send(json.dumps(result).encode(), "application/json", 409 if key and not result.get(key) else 200)

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    return self.send(page().encode(), "text/html; charset=utf-8")
                if path == "/api/production/replay":
                    return self.result({**replay.snapshot(), "auto_clip": auto.snapshot()})
                if path.startswith("/static/"):
                    target = (STATIC / path.removeprefix("/static/")).resolve()
                    if target.is_relative_to(STATIC) and target.is_file() and target.suffix == ".css":
                        return self.send(target.read_bytes(), "text/css")
                match = re.fullmatch(r"/api/production/replay/([a-f0-9]+)/download", path)
                if match and (target := replay.video(match[1])):
                    return self.send(target.read_bytes(), "video/mp4", attachment=True)
                self.send(b"Not found", "text/plain", 404)

            def do_POST(self):
                nonlocal generation
                size = int(self.headers.get("Content-Length") or 0)
                if size > 8192:
                    return self.send(b"Too large", "text/plain", 413)
                payload = json.loads(self.rfile.read(size) or b"{}")
                if self.path == "/api/production/auto-clip/settings":
                    return self.result(auto.configure(payload), "updated")
                if self.path == "/api/production/auto-clip/arm":
                    return self.result(auto.arm(payload.get("enabled") is True, baseline_generation=generation), "updated")
                if self.path == "/qa/pull":
                    generation += 1
                    auto.observe({"generation": generation, "updated_at": time.time(), "verification_state": "VERIFIED", "has_reference_evidence": True, "identity_consistent": True, "recognition_locked": True, "result_current": True, "card_present": True, "primary_candidate": {"english_name": f"Synthetic pull {generation}", "hit_tier": "grail"}})
                elif self.path == "/qa/interrupt":
                    replay.stop()
                    replay.start()
                elif self.path == "/qa/mark":
                    return self.result(replay.mark(name="Manual synthetic highlight"), "created")
                elif self.path == "/qa/take":
                    return self.result(replay.take(payload["id"]), "updated")
                elif self.path == "/qa/stop-replay":
                    return self.result(replay.stop_playback())
                elif self.path == "/qa/shutdown":
                    threading.Thread(target=server.shutdown, daemon=True).start()
                else:
                    return self.send(b"Not found", "text/plain", 404)
                self.result({"ok": True})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        print(f"Auto Clip QA: http://127.0.0.1:{server.server_port}/", flush=True)
        replay.start()
        auto.start()
        try:
            server.serve_forever()
        finally:
            auto.stop()
            replay.stop()
            server.server_close()


if __name__ == "__main__":
    main()
