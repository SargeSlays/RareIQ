"""Isolated multi-browser guest-production fixture. Never starts real hardware.

Supply a NEW directory on the data drive. All writes use that directory, all other
mutations and nonessential API reads are blocked. Only loopback is bound.
"""
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from fastapi.responses import Response, HTMLResponse, JSONResponse
import uvicorn
from rareiq.web import server
from rareiq.services.greenroom_service import GreenroomService
from rareiq.services.production_scene_store import ProductionSceneStore
from rareiq.services.voice_rule_store import VoiceRuleStore
from rareiq.services.reaction_asset_service import ReactionAssetService
from rareiq.services.production_source_store import ProductionSourceStore


def main(*, native_desktop=False, extra_setup=None, extra_api_paths=()):
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("Supply a NEW isolated evidence directory and optional loopback port")
    port = int(sys.argv[2]) if len(sys.argv) == 3 else 8768
    if not 1024 <= port <= 65535:
        raise SystemExit("Invalid fixture port")
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    service = GreenroomService(root / "greenroom.sqlite3")
    server.greenroom_service = service
    server.greenroom_hub.service = service
    server.orchestrator.reaction_assets = ReactionAssetService(root / "creator_assets", root / "reaction_assets.json")
    server.production_source_store = ProductionSourceStore(root / "production_sources.sqlite3")
    server.greenroom_hub.source_available = server._production_source_available
    server.PRODUCTION_SWITCHER_STATE = {"program_slot": 1, "preview_slot": 2, "transition": "fade", "duration_ms": 500, "generation": 0, "updated_at": time.time()}
    server.production_scene_store = ProductionSceneStore(root / "scenes.sqlite3", root / "absent.json", [])
    server.PRODUCTION_SCENES = []
    server.audience_service.path = root / "audience.sqlite3"
    server.voice_commands.rules = VoiceRuleStore(root / "voice-rules.sqlite3", server.production_actions.validate_parameters)
    server.obs.sync_scene = lambda scene: {"ok": True, "simulated": True}
    server._production_slot_is_ready = lambda slot, slots: slot in {1, 2, 3, 4}
    server.orchestrator.camera_manager.camera_slots = lambda: [
        {"slot_id": i, "source_id": f"fixture-{i}", "connected": True,
         "production_readiness": {"ready": True}} for i in range(1, 5)]
    server._program_camera_readiness = lambda slots, slot, **kwargs: {"ready": True, "slot_id": slot, "detail": "Synthetic fixture camera"}
    image = Image.new("RGB", (640, 360), "#1d485f")
    encoded = BytesIO()
    image.save(encoded, format="JPEG")
    jpeg = encoded.getvalue()
    server.orchestrator.camera_manager.slot_jpeg = lambda slot: jpeg
    server.vision_controller.frame_provider = lambda slot: jpeg

    @asynccontextmanager
    async def no_hardware(app):
        yield
    server.app.router.lifespan_context = no_hardware

    if extra_setup is not None:
        extra_setup(server, root)

    allowed_read = ("/api/creator/assets", "/api/production/sources/", "/api/production/greenroom", "/api/production/scenes", "/api/production/audience",
                    "/api/production/switcher", "/api/production/voice/rules", "/api/production/vision", "/api/production/actions")
    allowed_write = ("/api/creator/assets", "/api/production/sources/", "/api/production/greenroom/", "/api/production/switcher/", "/api/production/scenes",
                     "/api/production/audience/", "/api/production/voice/rules", "/api/production/vision/")
    allowed_read += tuple(extra_api_paths)
    allowed_write += tuple(extra_api_paths)
    native_reads = {"/api/production/native-preflight", "/api/desktop/status"} if native_desktop else set()
    native_writes = {"/api/desktop/encoding-status"} if native_desktop else set()

    @server.app.middleware("http")
    async def isolate(request, call_next):
        path = request.url.path
        if path.startswith("/output/camera/") and request.method == "GET":
            return HTMLResponse('<!doctype html><html><body style="margin:0;background:#1d485f;overflow:hidden"><img class="live" alt="Synthetic camera" style="width:100vw;height:100vh;object-fit:contain" src="/api/camera-slots/1/stream"></body></html>')
        if path.startswith("/api/camera-slots/") and path.endswith("/stream") and request.method == "GET":
            return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
        if request.method not in {"GET", "HEAD"}:
            if path not in native_writes and path not in {"/guest/join", "/guest/leave", "/guest/chat"} and not path.startswith(allowed_write):
                return JSONResponse({"ok": False, "reason": "mutation_blocked_in_guest_fixture"}, status_code=403)
        elif path.startswith("/api/") and path not in native_reads and not path.startswith(allowed_read):
            return JSONResponse({"ok": False, "reason": "read_blocked_in_guest_fixture"}, status_code=503)
        return await call_next(request)

    @server.app.get("/__qa__/guest-fixture")
    async def marker():
        return {"isolated_guest_fixture": True, "native_desktop_fixture": native_desktop,
                "hardware": False, "external_broadcast": False}

    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="error", access_log=False)


if __name__ == "__main__":
    main()
