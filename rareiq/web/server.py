from __future__ import annotations
import asyncio
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rareiq.core.events import EventBus
from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.core.storage import storage
from rareiq.version import BUILD_DATE, CODENAME, VERSION, version_payload

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CAPTURE_DIR = BASE_DIR.parent.parent / "captures"

app = FastAPI(title=f"RareIQ v{VERSION}")

@app.exception_handler(Exception)
async def json_api_exception_handler(request: Request, exc: Exception):
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "path": request.url.path,
            },
        )
    raise exc

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

class MasterCatalogImportRequest(BaseModel):
    set_id: str
    language: str = "Chinese"
    max_cards: int | None = None

class MasterCatalogConfigRequest(BaseModel):
    dropbox_local_path: str | None = None
    mirror_enabled: bool | None = None
    preferred_language: str | None = None

class PokemonWorldBuildRequest(BaseModel):
    languages: list[str] | None = None
    provider_ids: list[str] | None = None
    resume: bool = True
    max_sets: int | None = None

class PokemonAutoSyncConfigRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = None

class FastMetadataRequest(BaseModel):
    languages: list[str] | None = None

class BrandSettingsRequest(BaseModel):
    settings: dict[str, Any]

class OverlayStateRequest(BaseModel):
    state: dict[str, Any]

class LearningQueueRequest(BaseModel):
    scan_payload: dict[str, Any]
    reason: str
    correct_card_id: str | None = None

class FastImageRequest(BaseModel):
    workers: int = Field(default=12, ge=2, le=24)

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
            "catalog": orchestrator.catalog.status(),
            "recognition_state": orchestrator.recognition_state.refresh(
                vision=orchestrator.vision.status(),
                recognition=orchestrator.recognition.status(),
                catalog=orchestrator.catalog.status(),
            )
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
async def startup():
    orchestrator.set_loop(asyncio.get_running_loop())

    async def boot_in_background() -> None:
        await asyncio.sleep(0.15)
        await asyncio.to_thread(orchestrator.boot_manager.run, False)

    asyncio.create_task(boot_in_background())

@app.on_event("shutdown")
async def shutdown(): orchestrator.vision.stop()

@app.get("/")
async def root():
    return HTMLResponse(
        f'<h1>RareIQ v{VERSION} â€” {CODENAME}</h1>'
        '<p><a href="/control">Open RareIQ Operator Console</a></p>'
        '<p><a href="/about">Build diagnostics</a></p>',
        headers={"Cache-Control": "no-store"},
    )

@app.get("/control")
async def control():
    return FileResponse(
        STATIC_DIR / "control.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/control-legacy")
async def control_legacy():
    return FileResponse(
        STATIC_DIR / "control_legacy.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/about")
async def about():
    return FileResponse(
        STATIC_DIR / "about.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/storage/status")
async def storage_status():
    return {"ok": True, "storage": storage.status()}

@app.get("/api/version")
async def api_version():
    payload = version_payload()
    payload.update(
        {
            "python_runtime": "3.13 target",
            "ocr_engine": "RapidOCR",
            "catalog": "TCGdex + RareIQ Master Catalog",
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
async def list_cameras(force: bool = False):
    cameras = await asyncio.to_thread(
        orchestrator.camera_manager.discover,
        force,
    )
    return {
        "ok": True,
        "cameras": cameras,
        "selected_camera": orchestrator.camera_manager.selected_camera(),
        "manager": orchestrator.camera_manager.status()["manager"],
    }

@app.post("/api/camera/start")
async def camera_start(req: CameraStartRequest):
    status = await asyncio.to_thread(
        orchestrator.camera_manager.start,
        req.camera_index,
        req.camera_backend,
        True,
    )
    await orchestrator.publish("camera_manager_status", status)
    return status

@app.post("/api/camera/stop")
async def camera_stop():
    status = await asyncio.to_thread(orchestrator.camera_manager.stop)
    await orchestrator.publish("camera_manager_status", status)
    return status

@app.post("/api/camera/recover")
async def camera_recover():
    status = await asyncio.to_thread(orchestrator.camera_manager.recover)
    await orchestrator.publish("camera_manager_status", status)
    return status

@app.get("/api/camera/ready")
async def camera_ready():
    status = orchestrator.camera_manager.status()
    return {
        "ok": status["manager"]["state"] == "running",
        "state": status["manager"]["state"],
        "message": status["manager"]["message"],
        "visible": bool(status["vision"].get("visible")),
        "last_frame_at": status["manager"]["last_frame_at"],
    }


@app.post("/api/system/shutdown")
async def system_shutdown():
    """Gracefully stop the local RareIQ process after responding."""
    def stop_process():
        time.sleep(0.35)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=stop_process, daemon=True).start()
    return {"ok": True, "message": "RareIQ is shutting down."}

@app.get("/api/catalog/status")
async def catalog_status():
    return {"ok": True, "catalog": orchestrator.catalog.status()}

@app.get("/api/catalog-engine/status")
async def catalog_engine_status():
    return {
        "ok": True,
        "catalog_engine": orchestrator.catalog_intelligence.status(),
    }

@app.get("/api/pokemon-master/status")
async def pokemon_master_status():
    return {
        "ok": True,
        "pokemon_master": orchestrator.pokemon_master_database.status(),
    }

@app.post("/api/pokemon-master/discover")
async def pokemon_master_discover(req: PokemonWorldBuildRequest):
    result = await asyncio.to_thread(
        orchestrator.pokemon_master_database.discover_all,
        req.languages,
    )
    return result

@app.post("/api/pokemon-master/build")
async def pokemon_master_build(req: PokemonWorldBuildRequest):
    return orchestrator.pokemon_master_database.start_world_build(
        languages=req.languages,
        provider_ids=req.provider_ids,
        resume=req.resume,
        max_sets=req.max_sets,
    )

@app.post("/api/pokemon-master/cancel")
async def pokemon_master_cancel():
    return orchestrator.pokemon_master_database.cancel()

@app.get("/api/pokemon-vision/status")
async def pokemon_vision_status():
    return {
        "ok": True,
        "visual_index": orchestrator.global_visual_index.status(),
        "auto_sync": orchestrator.pokemon_auto_sync.status(),
    }

@app.post("/api/pokemon-vision/rebuild")
async def pokemon_vision_rebuild():
    return await asyncio.to_thread(
        orchestrator.global_visual_index.rebuild
    )

@app.post("/api/pokemon-vision/sync-now")
async def pokemon_vision_sync_now():
    return orchestrator.pokemon_auto_sync.start(force=True)

@app.post("/api/pokemon-vision/stop-sync")
async def pokemon_vision_stop_sync():
    return orchestrator.pokemon_auto_sync.stop()


@app.get("/api/providers/status")
async def provider_status():
    return {
        "ok": True,
        "diagnostics": orchestrator.provider_diagnostics.status(),
    }

@app.post("/api/providers/check")
async def provider_check():
    return await asyncio.to_thread(
        orchestrator.provider_diagnostics.run
    )





@app.get("/api/camera/status")
async def camera_status_compatibility():
    return orchestrator.camera_manager.status()

@app.get("/api/boot/ping")
async def boot_ping():
    return {
        "ok": True,
        "version": VERSION,
        "message": "Boot API online.",
    }

@app.get("/api/boot/status")
async def boot_status():
    return orchestrator.boot_manager.status()

@app.post("/api/boot/run")
async def boot_run(force: bool = False):
    return await asyncio.to_thread(orchestrator.boot_manager.run, force)

@app.get("/api/system/health")
async def system_health():
    camera = orchestrator.camera_manager.health()
    recognition = orchestrator.recognition.status()
    catalog = orchestrator.catalog.status()
    index = orchestrator.index_activation.status()

    components = {
        "camera": camera,
        "recognition": {
            "healthy": not bool(recognition.get("error")),
            "state": "ready" if not recognition.get("error") else "error",
            "message": recognition.get("error") or "Recognition service available.",
        },
        "catalog": {
            "healthy": not bool(catalog.get("error")),
            "state": "ready" if not catalog.get("error") else "error",
            "message": catalog.get("error") or "Catalog service available.",
        },
        "index": {
            "healthy": not bool(index.get("error")),
            "state": index.get("state") or "unknown",
            "message": index.get("error") or "Index activation service available.",
        },
        "storage": {
            "healthy": True,
            "state": "ready",
            "message": "Configured storage paths are available.",
        },
    }

    return {
        "ok": all(component["healthy"] for component in components.values()),
        "timestamp": time.time(),
        "components": components,
    }

@app.get("/api/index-activation/status")
async def index_activation_status():
    return {
        "ok": True,
        "activation": orchestrator.index_activation.status(),
    }

@app.post("/api/index-activation/start")
async def index_activation_start():
    return orchestrator.index_activation.start()

@app.post("/api/index-activation/stop")
async def index_activation_stop():
    return orchestrator.index_activation.stop()




@app.get("/api/brand")
async def get_brand_settings():
    return {"ok": True, "brand": orchestrator.brand_settings.get()}

@app.post("/api/brand")
async def save_brand_settings(request: BrandSettingsRequest):
    return orchestrator.brand_settings.save(request.settings)

@app.get("/api/overlay/state")
async def get_overlay_state():
    return {"ok": True, "state": orchestrator.overlay_state.get()}

@app.post("/api/overlay/state")
async def update_overlay_state(request: OverlayStateRequest):
    return {
        "ok": True,
        "state": orchestrator.overlay_state.update(request.state),
    }

@app.post("/api/overlay/reset")
async def reset_overlay_state():
    return {"ok": True, "state": orchestrator.overlay_state.reset()}

@app.get("/camera-popout")
async def camera_popout_view():
    return FileResponse(STATIC_DIR / "camera_popout.html")

@app.get("/studiox-611")
async def studiox_611_fallback():
    return FileResponse(STATIC_DIR / "studiox_611_fallback.html")

@app.get("/studiox-604")
async def studiox_604_fallback():
    return FileResponse(STATIC_DIR / "studiox_604_fallback.html")

@app.get("/studiox-50")
async def studiox_50_fallback():
    return FileResponse(STATIC_DIR / "studiox_50_fallback.html")

@app.get("/studiox-402")
async def studiox_402_fallback():
    return FileResponse(STATIC_DIR / "studiox_402_fallback.html")

@app.get("/studiox-401")
async def studiox_401_fallback():
    return FileResponse(STATIC_DIR / "studiox_401_fallback.html")

@app.get("/studiox-40")
async def studiox_40_fallback():
    return FileResponse(STATIC_DIR / "studiox_40_fallback.html")

@app.get("/studiox-30")
async def studiox_30_fallback():
    return FileResponse(STATIC_DIR / "studiox_30_fallback.html")

@app.get("/studiox-25")
async def studiox_25_fallback():
    return FileResponse(STATIC_DIR / "studiox_25_fallback.html")

@app.get("/studiox-241")
async def studiox_241_fallback():
    return FileResponse(STATIC_DIR / "studiox_241_fallback.html")

@app.get("/studiox-23")
async def studiox_23_fallback():
    return FileResponse(STATIC_DIR / "studiox_23_fallback.html")

@app.get("/studiox-22")
async def studiox_22_fallback():
    return FileResponse(STATIC_DIR / "studiox_22_fallback.html")

@app.get("/studiox-21")
async def studiox_21_fallback():
    return FileResponse(STATIC_DIR / "studiox_21_fallback.html")

@app.get("/studiox-sprint2")
async def studiox_sprint2_fallback():
    return FileResponse(STATIC_DIR / "studiox_sprint2_fallback.html")

@app.get("/studiox-sprint1")
async def studiox_sprint1_fallback():
    return FileResponse(STATIC_DIR / "studiox_sprint1_fallback.html")

@app.get("/studio501")
async def studio501_fallback():
    return FileResponse(STATIC_DIR / "studio501_fallback.html")

@app.get("/studio40")
async def studio40_fallback():
    return FileResponse(STATIC_DIR / "studio40_fallback.html")

@app.get("/studio31")
async def studio31_fallback():
    return FileResponse(STATIC_DIR / "studio31_legacy.html")

@app.get("/legacy-control")
async def legacy_control():
    return FileResponse(STATIC_DIR / "legacy_control.html")

@app.get("/studio")
async def studio_page():
    return FileResponse(STATIC_DIR / "control.html")

@app.get("/program")
async def program_page():
    return FileResponse(STATIC_DIR / "program_view.html")

@app.get("/overlay/landscape")
async def landscape_overlay():
    return FileResponse(STATIC_DIR / "overlay_landscape.html")

@app.get("/overlay/portrait")
async def portrait_overlay():
    return FileResponse(STATIC_DIR / "overlay_portrait.html")

@app.get("/overlay/current-card")
async def current_card_overlay():
    return FileResponse(STATIC_DIR / "overlay_current_card.html")

@app.get("/api/intelligence/status")
async def intelligence_status():
    return {
        "ok": True,
        "version": "X7",
        "learning_queue": orchestrator.learning_queue.status(),
        "visual_index": orchestrator.global_visual_index.status(),
    }

@app.post("/api/intelligence/benchmark")
async def intelligence_benchmark():
    return await asyncio.to_thread(
        orchestrator.x7_benchmarks.run,
        100,
    )

@app.post("/api/intelligence/learning")
async def intelligence_learning(request: LearningQueueRequest):
    return orchestrator.learning_queue.add(
        scan_payload=request.scan_payload,
        reason=request.reason,
        correct_card_id=request.correct_card_id,
    )

@app.get("/api/system/health")
async def system_health():
    return {
        "ok": True,
        "health": orchestrator.system_health.status(),
    }

@app.get("/api/jobs/status")
async def job_status():
    return {
        "ok": True,
        "jobs": orchestrator.job_queue.status(),
    }

@app.post("/api/library/optimize")
async def optimize_library():
    job = orchestrator.job_queue.submit(
        "Optimize RareIQ Library",
        orchestrator.library_optimizer.run,
    )
    return {"ok": True, "job": job}

@app.post("/api/index/incremental")
async def incremental_index():
    job = orchestrator.job_queue.submit(
        "Incremental Recognition Index",
        orchestrator.global_visual_index.incremental_update,
    )
    return {"ok": True, "job": job}

@app.post("/api/system/auto-index/{enabled}")
async def set_auto_index(enabled: bool):
    return orchestrator.system_health.set_auto_index(enabled)

@app.get("/api/war-room/status")
async def war_room_status():
    return {
        "ok": True,
        "war_room": orchestrator.war_room.status(),
    }

@app.post("/api/assets/scan")
async def scan_assets():
    return await asyncio.to_thread(
        orchestrator.asset_manager.scan_images
    )

@app.get("/api/assets/status")
async def asset_status():
    return {
        "ok": True,
        "assets": orchestrator.asset_manager.status(),
    }

@app.post("/api/benchmarks/fusion")
async def run_fusion_benchmark():
    return await asyncio.to_thread(
        orchestrator.benchmarks.run_fusion_benchmark,
        10000,
    )

@app.get("/api/benchmarks/latest")
async def latest_benchmark():
    return orchestrator.benchmarks.latest()

@app.get("/api/fast-pipeline/status")
async def fast_pipeline_status():
    return {
        "ok": True,
        "pipeline": orchestrator.fast_pipeline.status(),
    }

@app.post("/api/fast-pipeline/metadata/start")
async def fast_pipeline_metadata_start(request: FastMetadataRequest):
    return orchestrator.fast_pipeline.start_metadata(request.languages)

@app.post("/api/fast-pipeline/images/start")
async def fast_pipeline_images_start(request: FastImageRequest):
    return orchestrator.fast_pipeline.start_images(request.workers)

@app.post("/api/fast-pipeline/stop")
async def fast_pipeline_stop():
    return orchestrator.fast_pipeline.stop()

@app.post("/api/fast-pipeline/index")
async def fast_pipeline_index():
    return await asyncio.to_thread(
        orchestrator.fast_pipeline.build_visual_index
    )

@app.get("/api/master-builder/status")
async def master_builder_status():
    return {
        "ok": True,
        "builder": orchestrator.master_database_builder.status(),
    }

@app.post("/api/master-builder/start")
async def master_builder_start():
    return orchestrator.master_database_builder.start(resume=True)

@app.post("/api/master-builder/stop")
async def master_builder_stop():
    return orchestrator.master_database_builder.cancel()

@app.post("/api/master-builder/rebuild-index")
async def master_builder_rebuild_index():
    return await asyncio.to_thread(
        orchestrator.master_database_builder.rebuild_visual_index
    )

@app.post("/api/pokemon-vision/config")
async def pokemon_vision_config(req: PokemonAutoSyncConfigRequest):
    return orchestrator.pokemon_auto_sync.configure(
        enabled=req.enabled,
        interval_hours=req.interval_hours,
    )

@app.post("/api/catalog-engine/import-set")
async def catalog_engine_import_set(req: MasterCatalogImportRequest):
    result = await asyncio.to_thread(
        orchestrator.catalog_intelligence.import_tcgdex_set,
        req.set_id,
        req.language,
        req.max_cards,
    )
    await orchestrator.publish("master_catalog_update", result)
    return result

@app.post("/api/catalog-engine/rebuild")
async def catalog_engine_rebuild():
    result = await asyncio.to_thread(
        orchestrator.catalog_intelligence.rebuild_master_index
    )
    await orchestrator.publish("master_catalog_update", result)
    return result

@app.post("/api/catalog-engine/config")
async def catalog_engine_config(req: MasterCatalogConfigRequest):
    return orchestrator.catalog_intelligence.configure(
        dropbox_local_path=req.dropbox_local_path,
        mirror_enabled=req.mirror_enabled,
        preferred_language=req.preferred_language,
    )

@app.get("/api/catalog-engine/image/{set_folder}/{filename}")
async def catalog_engine_image(set_folder: str, filename: str):
    safe_folder = Path(set_folder).name
    safe_filename = Path(filename).name
    path = (
        orchestrator.catalog_intelligence.sets_dir
        / safe_folder
        / "images"
        / safe_filename
    )
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path)




def _live_frame_heartbeat():
    """Return the real frame heartbeat published by VisionService."""
    try:
        status = orchestrator.camera_manager.status()
        vision = status.get("vision") or {}
        frame_available = bool(vision.get("frame_available"))
        return {
            "frame_available": frame_available,
            "frame_id": vision.get("frame_id"),
            "frame_timestamp": vision.get("frame_timestamp"),
            "frame_shape": vision.get("frame_shape"),
            "frame_error": vision.get("error"),
            "camera_running": bool(vision.get("running")),
            "camera_name": vision.get("camera_name"),
            "manager_state": (status.get("manager") or {}).get("state"),
        }
    except Exception as exc:
        return {
            "frame_available": False,
            "frame_id": None,
            "frame_timestamp": None,
            "frame_shape": None,
            "frame_error": str(exc),
            "camera_running": False,
            "camera_name": None,
            "manager_state": "error",
        }


@app.get("/api/mission-control")
async def mission_control():
    camera = orchestrator.camera_manager.status()
    recognition = orchestrator.recognition.status()
    return {
        "ok": True,
        "timestamp": time.time(),
        "camera": {
            "manager": camera.get("manager"),
            "vision": camera.get("vision"),
        },
        "trigger": orchestrator.trigger_manager.status(),
        "pipeline": orchestrator.pipeline_state.snapshot(),
        "recognition": {
            "enabled": recognition.get("enabled"),
            "busy": recognition.get("busy"),
            "verification_state": recognition.get(
                "verification_state"
            ),
            "candidate_count": recognition.get(
                "candidate_count"
            ),
            "pipeline_stages": recognition.get(
                "pipeline_stages"
            ),
            "error": recognition.get("error"),
            "updated_at": recognition.get("updated_at"),
        },
    }


@app.get("/api/trigger/status")
async def trigger_status():
    return {
        "ok": True,
        "trigger": orchestrator.trigger_manager.status(),
        "pipeline": orchestrator.pipeline_state.snapshot(),
    }

@app.get("/api/pipeline/frame-heartbeat")
async def pipeline_frame_heartbeat():
    heartbeat = await asyncio.to_thread(_live_frame_heartbeat)
    return {
        "ok": bool(heartbeat.get("frame_available")),
        **heartbeat,
    }
@app.get("/api/pipeline/state")
async def pipeline_state():
    snapshot = await asyncio.to_thread(
        orchestrator.backend_test.runtime_snapshot
    )
    heartbeat = await asyncio.to_thread(_live_frame_heartbeat)

    camera = dict(snapshot.get("camera") or {})
    camera.update(heartbeat)
    snapshot["camera"] = camera

    frame_id = heartbeat.get("frame_id")
    if frame_id is not None:
        orchestrator.pipeline_state._frame_id = int(frame_id)

    return {
        "ok": True,
        "pipeline": orchestrator.pipeline_state.sync_from_snapshot(snapshot),
        "runtime_summary": {
            "camera": snapshot.get("camera"),
            "current_card": snapshot.get("current_card"),
            "recognition_state": snapshot.get("recognition_state"),
        },
    }
@app.post("/api/pipeline/test-latest-crop")
async def pipeline_test_latest_crop():
    orchestrator.pipeline_state.reset()

    snapshot = await asyncio.to_thread(
        orchestrator.backend_test.runtime_snapshot
    )
    orchestrator.pipeline_state.sync_from_snapshot(snapshot)

    result = await asyncio.to_thread(
        orchestrator.backend_test.submit_latest_crop_for_recognition
    )

    if not result.get("ok"):
        orchestrator.pipeline_state.fail(
            "crop",
            str(result.get("error") or "No corrected crop available"),
            "Recognition test could not start",
        )
        return {
            "ok": False,
            "result": result,
            "pipeline": orchestrator.pipeline_state.snapshot(),
        }

    orchestrator.pipeline_state.start(
        "ocr",
        "Latest corrected crop submitted to recognition",
    )

    await asyncio.sleep(0.35)

    updated = await asyncio.to_thread(
        orchestrator.backend_test.runtime_snapshot
    )
    return {
        "ok": True,
        "result": result,
        "pipeline": orchestrator.pipeline_state.sync_from_snapshot(updated),
    }
@app.post("/api/pipeline/reset")
async def pipeline_reset():
    return {
        "ok": True,
        "pipeline": orchestrator.pipeline_state.reset(),
    }
@app.get("/api/runtime/snapshot")
async def runtime_snapshot():
    return await asyncio.to_thread(
        orchestrator.backend_test.runtime_snapshot
    )

@app.get("/api/current-card")
async def current_card():
    snapshot = await asyncio.to_thread(
        orchestrator.backend_test.runtime_snapshot
    )
    return {
        "ok": True,
        "card": snapshot.get("current_card"),
        "recognition_state": snapshot.get("recognition_state"),
    }

@app.get("/api/recent-pulls")
async def recent_pulls(limit: int = 20):
    return {
        "ok": True,
        "cards": orchestrator.sessions.recent_cards(
            max(1, min(int(limit), 200))
        ),
    }

@app.post("/api/test/recognize-latest-crop")
async def test_recognize_latest_crop():
    return await asyncio.to_thread(
        orchestrator.backend_test.submit_latest_crop_for_recognition
    )

@app.get("/api/test/smoke")
async def backend_smoke_test():
    return await asyncio.to_thread(
        orchestrator.backend_test.smoke_test
    )

@app.post("/api/test/diagnostic-report")
async def backend_diagnostic_report():
    path = await asyncio.to_thread(
        orchestrator.backend_test.write_report
    )
    return {
        "ok": True,
        "filename": path.name,
        "download_url": f"/api/test/diagnostic-report/{path.name}",
    }

@app.get("/api/test/diagnostic-report/{filename}")
async def download_backend_diagnostic_report(filename: str):
    safe_name = Path(filename).name
    path = orchestrator.backend_test.report_dir / safe_name
    if not path.exists() or not path.is_file():
        return JSONResponse(
            {"ok": False, "error": "Diagnostic report not found."},
            status_code=404,
        )
    return FileResponse(
        path,
        media_type="application/json",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )

@app.get("/api/recognition/status")
async def recognition_status():
    return {"ok": True, "recognition": orchestrator.recognition.status()}

@app.get("/api/recognition-state")
async def recognition_state():
    # Read-only snapshot. Recognition producers update this store through
    # events; dashboard polling must never rebuild the recognition pipeline.
    return {
        "ok": True,
        "recognition_state": orchestrator.recognition_state.snapshot(),
    }

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



@app.get("/api/camera/crop.jpg")
async def camera_crop_still():
    """Return the latest corrected card crop without crashing the UI."""
    try:
        crop = orchestrator.vision.latest_crop()
        if crop is None or getattr(crop, "size", 0) == 0:
            placeholder = np.zeros((560, 400, 3), dtype=np.uint8)
            cv2.putText(
                placeholder,
                "Waiting for card crop",
                (48, 285),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (125, 150, 175),
                2,
                cv2.LINE_AA,
            )
            crop = placeholder

        ok, buffer = cv2.imencode(
            ".jpg",
            crop,
            [int(cv2.IMWRITE_JPEG_QUALITY), 92],
        )
        if not ok:
            return Response(status_code=204)

        return Response(
            content=buffer.tobytes(),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
    except Exception:
        return Response(status_code=204)

@app.get("/api/camera/crop-stream")
async def camera_crop_stream():
    async def frames():
        try:
            while True:
                crop = orchestrator.vision.latest_crop()
                if crop is not None:
                    ok, buffer = cv2.imencode(
                        ".jpg",
                        crop,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 88],
                    )
                    if ok:
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n"
                            + buffer.tobytes()
                            + b"\r\n"
                        )
                await asyncio.sleep(0.08)
        except (asyncio.CancelledError, GeneratorExit, BrokenPipeError, ConnectionResetError):
            return

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/api/camera/stream")
async def camera_stream():
    async def frames():
        while True:
            jpg = orchestrator.camera_manager.latest_jpeg()
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
@app.post("/api/session/confirm-recognition")
async def confirm_recognition():
    return await orchestrator.confirm_recognition(automatic=False)

@app.post("/api/session/auto-confirm-recognition")
async def auto_confirm_recognition(state_id: str | None = None):
    current = orchestrator.recognition_state.refresh(
        vision=orchestrator.vision.status(),
        recognition=orchestrator.recognition.status(),
        catalog=orchestrator.catalog.status(),
    )
    if state_id and current.get("state_id") != state_id:
        return {
            "ok": False,
            "error": "Recognition changed before Auto-add completed.",
            "reason": "stale_recognition_state",
            "expected_state_id": state_id,
            "current_state_id": current.get("state_id"),
        }
    return await orchestrator.confirm_recognition(automatic=True)

@app.post("/api/session/test-auto-confirm-recognition")
async def test_auto_confirm_recognition(state_id: str | None = None):
    current = orchestrator.recognition_state.refresh(
        vision=orchestrator.vision.status(),
        recognition=orchestrator.recognition.status(),
        catalog=orchestrator.catalog.status(),
    )
    if state_id and current.get("state_id") != state_id:
        return {
            "ok": False,
            "error": "Recognition changed before Auto-add completed.",
            "reason": "stale_recognition_state",
            "expected_state_id": state_id,
            "current_state_id": current.get("state_id"),
        }
    return await orchestrator.confirm_recognition(
        automatic=True,
        allow_unverified_test=True,
    )

@app.post("/api/session/reject-recognition")
async def reject_recognition():
    return await orchestrator.reject_recognition()

@app.get("/api/session/status")
async def session_status():
    return {"ok": True, **(await orchestrator.session_snapshot())}

@app.get("/api/session/export")
async def session_export():
    payload = orchestrator.sessions.export()
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="rareiq_session.json"',
            "Cache-Control": "no-store",
        },
    )

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
    print(f"Version {VERSION} â€” {CODENAME}")
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




