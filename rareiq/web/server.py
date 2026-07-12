from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rareiq.core.events import EventBus
from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.version import BUILD_DATE, CODENAME, VERSION, version_payload

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CAPTURE_DIR = BASE_DIR.parent.parent / "captures"

app = FastAPI(title=f"RareIQ v{VERSION}")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
event_bus = EventBus()
orchestrator = RareIQOrchestrator(event_bus, CAPTURE_DIR)


class SessionStartRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=100)
    order_number: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=150)
    boxes_total: int = Field(default=1, ge=1, le=100)
    packs_per_box: int = Field(default=5, ge=1, le=100)


class CameraStartRequest(BaseModel):
    camera_index: int
    camera_backend: int

class AutoCaptureRequest(BaseModel):
    enabled: bool

class RecognitionToggleRequest(BaseModel):
    enabled: bool

class ActiveSetRequest(BaseModel):
    set_id: str

class LiveSetImportRequest(BaseModel):
    set_id: str
    language: str = "English"
    max_cards: int | None = None

class CardGraderRegisterRequest(BaseModel):
    name: str = "RareIQ"
    contact_email: str | None = None

class CardGraderKeyRequest(BaseModel):
    api_key: str

class CardGraderSubmitRequest(BaseModel):
    module: str = "grade"
    include_back: bool = False


class ConnectionManager:
    def __init__(self): self.connections = []

    async def connect(self, ws):
        await ws.accept()
        self.connections.append(ws)
        await ws.send_json({"type": "snapshot", "payload": {
            "session": orchestrator.sessions.snapshot(),
            "vision": orchestrator.vision.status(),
            "recognition": orchestrator.recognition.status(),
            "catalog": orchestrator.catalog.status()
        }})

    def disconnect(self, ws):
        if ws in self.connections: self.connections.remove(ws)

    async def broadcast(self, event):
        dead = []
        for ws in list(self.connections):
            try: await ws.send_json(event)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)


manager = ConnectionManager()
event_bus.subscribe(manager.broadcast)

DEMO_CARDS = {
    "common":{"card_name":"Froakie","rarity":"COMMON","raw_value":0.12,"card_number":"001/100","set_name":"Greninja Jumbo Box","language":"Simplified Chinese","market_low":0.08,"market_high":0.20,"price_confidence":"Medium"},
    "rare":{"card_name":"Greninja","rarity":"RARE","raw_value":1.80,"card_number":"025/100","set_name":"Greninja Jumbo Box","language":"Simplified Chinese","market_low":1.25,"market_high":2.40,"price_confidence":"Medium"},
    "double_rare":{"card_name":"Greninja ex","rarity":"DOUBLE RARE","raw_value":6.75,"card_number":"042/100","set_name":"Greninja Jumbo Box","language":"Simplified Chinese","market_low":5.50,"market_high":8.25,"price_confidence":"High"},
    "illustration_rare":{"card_name":"Greninja Illustration Rare","rarity":"ILLUSTRATION RARE","raw_value":38.00,"card_number":"088/100","set_name":"Greninja Jumbo Box","language":"Simplified Chinese","market_low":32.00,"market_high":46.00,"price_confidence":"Medium"},
    "grail":{"card_name":"Greninja ex Special Art Rare","rarity":"GRAIL","raw_value":182.35,"card_number":"095/100","set_name":"Greninja Jumbo Box","language":"Simplified Chinese","market_low":170.00,"market_high":195.00,"price_confidence":"High"}
}

@app.on_event("startup")
async def startup(): orchestrator.set_loop(asyncio.get_running_loop())

@app.on_event("shutdown")
async def shutdown(): orchestrator.vision.stop()

@app.get("/")
async def root():
    return HTMLResponse(
        f'<h1>RareIQ v{VERSION} — {CODENAME}</h1>'
        '<p><a href="/control">Open RareIQ Control Center</a></p>'
        '<p><a href="/about">Build diagnostics</a></p>',
        headers={"Cache-Control": "no-store"},
    )

@app.get("/control")
async def control():
    return FileResponse(
        STATIC_DIR / "control.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/about")
async def about():
    return FileResponse(
        STATIC_DIR / "about.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/api/version")
async def api_version():
    payload = version_payload()
    payload.update(
        {
            "python_runtime": "3.13 target",
            "ocr_engine": "RapidOCR",
            "catalog": "TCGdex",
            "camera": orchestrator.vision.status().get("camera_name"),
        }
    )
    return {"ok": True, "version": payload}

@app.get("/overlay/data")
async def data(): return FileResponse(STATIC_DIR/"data_overlay.html")

@app.get("/overlay/pack")
async def pack(): return FileResponse(STATIC_DIR/"pack_overlay.html")

@app.get("/overlay/fx")
async def fx(): return FileResponse(STATIC_DIR/"fx_overlay.html")

@app.get("/overlay/card")
async def card(): return FileResponse(STATIC_DIR/"card_overlay.html")

@app.get("/overlay/audio")
async def audio(): return FileResponse(STATIC_DIR/"audio_overlay.html")

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)

@app.get("/api/cameras")
async def list_cameras():
    return {"ok": True, "cameras": orchestrator.vision.list_cameras()}

@app.post("/api/camera/start")
async def camera_start(req: CameraStartRequest):
    status = orchestrator.vision.start(req.camera_index, req.camera_backend)
    await orchestrator.publish("vision_status", status)
    return {"ok": True, "vision": status}

@app.post("/api/camera/stop")
async def camera_stop():
    status = orchestrator.vision.stop()
    await orchestrator.publish("vision_status", status)
    return {"ok": True, "vision": status}

@app.get("/api/catalog/status")
async def catalog_status():
    return {"ok": True, "catalog": orchestrator.catalog.status()}

@app.get("/api/recognition/status")
async def recognition_status():
    return {"ok": True, "recognition": orchestrator.recognition.status()}

@app.get("/api/artwork-index/status")
async def artwork_index_status():
    return {
        "ok": True,
        "index": orchestrator.recognition.artwork_index.status(),
    }

@app.get("/api/sets")
async def list_sets():
    return {
        "ok": True,
        "sets": orchestrator.recognition.set_catalog.list_sets(),
        "status": orchestrator.recognition.set_catalog.status(),
    }


@app.get("/api/cardgrader/status")
async def cardgrader_status():
    return {"ok": True, "cardgrader": orchestrator.cardgrader.status()}

@app.post("/api/cardgrader/register")
async def cardgrader_register(req: CardGraderRegisterRequest):
    try:
        return await asyncio.to_thread(
            orchestrator.cardgrader.register_agent,
            req.name,
            req.contact_email,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.post("/api/cardgrader/key")
async def cardgrader_set_key(req: CardGraderKeyRequest):
    try:
        return await asyncio.to_thread(
            orchestrator.cardgrader.configure_key,
            req.api_key,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.post("/api/cardgrader/capture-front")
async def cardgrader_capture_front():
    frame = orchestrator.vision.latest_frame()
    if frame is None:
        return {"ok": False, "error": "No live camera frame is available."}
    try:
        path = await asyncio.to_thread(
            orchestrator.cardgrader.save_frame,
            frame,
            "front",
        )
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.post("/api/cardgrader/capture-back")
async def cardgrader_capture_back():
    frame = orchestrator.vision.latest_frame()
    if frame is None:
        return {"ok": False, "error": "No live camera frame is available."}
    try:
        path = await asyncio.to_thread(
            orchestrator.cardgrader.save_frame,
            frame,
            "back",
        )
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.post("/api/cardgrader/submit")
async def cardgrader_submit(req: CardGraderSubmitRequest):
    fronts = sorted(
        orchestrator.cardgrader.capture_dir.glob("front_*.jpg"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not fronts:
        return {"ok": False, "error": "Capture the front of the card first."}

    back_path = None
    if req.include_back:
        backs = sorted(
            orchestrator.cardgrader.capture_dir.glob("back_*.jpg"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if backs:
            back_path = backs[0]

    try:
        return await asyncio.to_thread(
            orchestrator.cardgrader.submit_scan,
            fronts[0],
            back_path,
            req.module,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.get("/api/cardgrader/scan/{scan_id}")
async def cardgrader_poll(scan_id: int):
    try:
        return await asyncio.to_thread(
            orchestrator.cardgrader.poll_scan,
            scan_id,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

@app.get("/api/live-catalog/status")
async def live_catalog_status():
    return {
        "ok": True,
        "catalog": orchestrator.recognition.live_catalog.status(),
    }

@app.post("/api/live-catalog/import-set")
async def import_live_set(req: LiveSetImportRequest):
    result = await asyncio.to_thread(
        orchestrator.recognition.live_catalog.import_set,
        req.set_id,
        req.language,
        req.max_cards,
    )
    await orchestrator.publish("live_catalog_update", result)
    return result

@app.post("/api/sets/active")
async def set_active_set(req: ActiveSetRequest):
    try:
        active = orchestrator.recognition.set_catalog.set_active(req.set_id)
        orchestrator.recognition.artwork_index.set_active_filter(
            active.get("name"),
            active.get("language"),
        )
        payload = {
            "active_set": active,
            "set_status": orchestrator.recognition.set_catalog.status(),
            "index_status": orchestrator.recognition.artwork_index.status(),
        }
        await orchestrator.publish("active_set_update", payload)
        return {"ok": True, **payload}
    except ValueError as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc)},
            status_code=400,
        )

@app.post("/api/artwork-index/rebuild")
async def artwork_index_rebuild():
    result = orchestrator.recognition.artwork_index.rebuild()
    await orchestrator.publish(
        "artwork_index_update",
        result.get("status", {}),
    )
    return result

@app.get("/api/artwork-index/image/{card_id}")
async def artwork_index_image(card_id: str):
    record = orchestrator.recognition.artwork_index.get_record(card_id)
    if not record:
        return JSONResponse(
            {"ok": False, "error": "Reference card not found."},
            status_code=404,
        )

    image_path = record.get("image_path")
    if not image_path:
        return JSONResponse(
            {"ok": False, "error": "Reference image is unavailable."},
            status_code=404,
        )

    path = Path(str(image_path)).resolve()
    reference_root = (
        orchestrator.recognition.artwork_index.reference_dir.resolve()
    )

    if reference_root not in path.parents:
        return JSONResponse(
            {"ok": False, "error": "Invalid reference image path."},
            status_code=403,
        )

    if not path.exists() or not path.is_file():
        return JSONResponse(
            {"ok": False, "error": "Reference image file is missing."},
            status_code=404,
        )

    return FileResponse(
        path,
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.post("/api/recognition/toggle")
async def recognition_toggle(req: RecognitionToggleRequest):
    status = orchestrator.recognition.set_enabled(req.enabled)
    await orchestrator.publish("recognition_update", status)
    return {"ok": True, "recognition": status}

@app.post("/api/camera/auto-capture")
async def camera_auto_capture(req: AutoCaptureRequest):
    status = orchestrator.vision.set_auto_capture(req.enabled)
    await orchestrator.publish("vision_status", status)
    return {"ok": True, "vision": status}

@app.post("/api/camera/capture")
async def camera_capture():
    path = orchestrator.vision.save_latest_crop(source="manual")
    return {"ok": bool(path), "path": path, "error": None if path else "No corrected card image available yet."}

@app.get("/api/camera/stream")
async def camera_stream():
    async def frames():
        while True:
            jpg = orchestrator.vision.latest_jpeg()
            if jpg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+jpg+b"\r\n"
            await asyncio.sleep(0.04)
    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/api/session/start")
async def start_session(req: SessionStartRequest): return {"ok":True,"session":await orchestrator.start_session(**req.model_dump())}
@app.post("/api/session/next-pack")
async def next_pack(): return {"ok":True,"session":await orchestrator.next_pack()}
@app.post("/api/session/previous-pack")
async def previous_pack(): return {"ok":True,"session":await orchestrator.previous_pack()}
@app.post("/api/session/next-box")
async def next_box(): return {"ok":True,"session":await orchestrator.next_box()}
@app.post("/api/session/previous-box")
async def previous_box(): return {"ok":True,"session":await orchestrator.previous_box()}
@app.post("/api/session/undo")
async def undo(): return {"ok":True,"session":await orchestrator.undo()}
@app.post("/api/session/close")
async def close(): return {"ok":True,"session":await orchestrator.close_session()}

@app.post("/api/demo/{tier}")
async def demo(tier: str):
    if tier not in DEMO_CARDS: return {"ok":False,"error":"Unknown tier"}
    return {"ok":True,"session":await orchestrator.add_demo_card(DEMO_CARDS[tier])}

def run():
    print()
    print("=" * 58)
    print("RareIQ Vision")
    print(f"Version {VERSION} — {CODENAME}")
    print(f"Build {BUILD_DATE}")
    print("Project Digital Jazz")
    print("=" * 58)
    print("Control: http://127.0.0.1:8765/control")
    print("About:  http://127.0.0.1:8765/about")
    print()
    uvicorn.run(
        "rareiq.web.server:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )
