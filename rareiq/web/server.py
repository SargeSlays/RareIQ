from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rareiq.core.events import EventBus
from rareiq.core.orchestrator import RareIQOrchestrator

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="RareIQ v0.2")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

event_bus = EventBus()
orchestrator = RareIQOrchestrator(event_bus)


class SessionStartRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=100)
    order_number: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=150)
    boxes_total: int = Field(default=1, ge=1, le=100)
    packs_per_box: int = Field(default=5, ge=1, le=100)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)
        await websocket.send_json({
            "type": "snapshot",
            "payload": {"session": orchestrator.sessions.snapshot()},
        })

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.connections):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
event_bus.subscribe(manager.broadcast)

DEMO_CARDS = {
    "common": {
        "card_name": "Froakie",
        "rarity": "COMMON",
        "raw_value": 0.12,
        "card_number": "001/100",
        "set_name": "Greninja Jumbo Box",
        "language": "Simplified Chinese",
        "market_low": 0.08,
        "market_high": 0.20,
        "price_confidence": "Medium",
    },
    "rare": {
        "card_name": "Greninja",
        "rarity": "RARE",
        "raw_value": 1.80,
        "card_number": "025/100",
        "set_name": "Greninja Jumbo Box",
        "language": "Simplified Chinese",
        "market_low": 1.25,
        "market_high": 2.40,
        "price_confidence": "Medium",
    },
    "double_rare": {
        "card_name": "Greninja ex",
        "rarity": "DOUBLE RARE",
        "raw_value": 6.75,
        "card_number": "042/100",
        "set_name": "Greninja Jumbo Box",
        "language": "Simplified Chinese",
        "market_low": 5.50,
        "market_high": 8.25,
        "price_confidence": "High",
    },
    "illustration_rare": {
        "card_name": "Greninja Illustration Rare",
        "rarity": "ILLUSTRATION RARE",
        "raw_value": 38.00,
        "card_number": "088/100",
        "set_name": "Greninja Jumbo Box",
        "language": "Simplified Chinese",
        "market_low": 32.00,
        "market_high": 46.00,
        "price_confidence": "Medium",
    },
    "grail": {
        "card_name": "Greninja ex Special Art Rare",
        "rarity": "GRAIL",
        "raw_value": 182.35,
        "card_number": "095/100",
        "set_name": "Greninja Jumbo Box",
        "language": "Simplified Chinese",
        "market_low": 170.00,
        "market_high": 195.00,
        "price_confidence": "High",
    },
}


@app.get("/")
async def root() -> HTMLResponse:
    return HTMLResponse('<a href="/control">Open RareIQ Control Center</a>')


@app.get("/control")
async def control() -> FileResponse:
    return FileResponse(STATIC_DIR / "control.html")


@app.get("/overlay/data")
async def data_overlay() -> FileResponse:
    return FileResponse(STATIC_DIR / "data_overlay.html")


@app.get("/overlay/pack")
async def pack_overlay() -> FileResponse:
    return FileResponse(STATIC_DIR / "pack_overlay.html")


@app.get("/overlay/fx")
async def fx_overlay() -> FileResponse:
    return FileResponse(STATIC_DIR / "fx_overlay.html")


@app.get("/overlay/card")
async def card_overlay() -> FileResponse:
    return FileResponse(STATIC_DIR / "card_overlay.html")


@app.get("/overlay/audio")
async def audio_overlay() -> FileResponse:
    return FileResponse(STATIC_DIR / "audio_overlay.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/session/start")
async def start_session(request: SessionStartRequest) -> dict[str, Any]:
    session = await orchestrator.start_session(**request.model_dump())
    return {"ok": True, "session": session}


@app.post("/api/session/next-pack")
async def next_pack() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.next_pack()}


@app.post("/api/session/previous-pack")
async def previous_pack() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.previous_pack()}


@app.post("/api/session/next-box")
async def next_box() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.next_box()}


@app.post("/api/session/previous-box")
async def previous_box() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.previous_box()}


@app.post("/api/session/undo")
async def undo() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.undo()}


@app.post("/api/session/close")
async def close_session() -> dict[str, Any]:
    return {"ok": True, "session": await orchestrator.close_session()}


@app.post("/api/demo/{tier}")
async def demo_card(tier: str) -> dict[str, Any]:
    if tier not in DEMO_CARDS:
        return {"ok": False, "error": "Unknown tier"}
    session = await orchestrator.add_demo_card(DEMO_CARDS[tier])
    return {"ok": True, "session": session}


def run() -> None:
    uvicorn.run("rareiq.web.server:app", host="127.0.0.1", port=8765, reload=False)
