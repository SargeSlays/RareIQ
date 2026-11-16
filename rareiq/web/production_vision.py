"""Loopback-only vision prototype routes, within the existing operator boundary."""
import ipaddress
import json

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from rareiq.services.production_vision_service import ProductionVisionController
from rareiq.services.vision_assets import DEFAULT_VISION_CACHE, VisionAssets


def local_host(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def create_production_vision_router(production_actions, action_validator, camera_ready, frame_provider,
                                    *, cache_dir=DEFAULT_VISION_CACHE, enabled=False):
    assets = VisionAssets(cache_dir)
    controller = ProductionVisionController(production_actions, action_validator, camera_ready, frame_provider,
                                            assets, enabled=enabled)
    router = APIRouter()

    def check(request):
        origin = request.headers.get("origin")
        if (not request.client or not local_host(request.client.host)
                or not local_host(request.url.hostname)
                or request.headers.get("sec-fetch-site") == "cross-site"
                or origin is not None and origin.rstrip("/") != str(request.base_url).rstrip("/")):
            raise ValueError("vision_local_operator_only")

    def result(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def failure(error):
        reason = str(error) if str(error).startswith("vision_") else "vision_invalid_request"
        return result({"ok": False, "reason": reason}, 403 if reason == "vision_local_operator_only" else 409)

    async def body(request):
        check(request)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise ValueError("vision_invalid_request")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 8192:
                raise ValueError("vision_request_too_large")
            data.extend(chunk)
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("vision_invalid_request")
        return value

    @router.get("/api/production/vision")
    async def status(request: Request):
        try:
            check(request)
            return result(await run_in_threadpool(controller.status))
        except (ValueError, TypeError):
            return failure(ValueError("vision_local_operator_only"))

    @router.post("/api/production/vision/{operation}")
    async def mutate(operation: str, request: Request):
        try:
            data = await body(request)
            nonce = request.headers.get("x-studio-vision-session", "")
            if operation == "session" and set(data) == {"mode", "tracking_camera", "bindings"}:
                payload = await run_in_threadpool(controller.start, **data)
            elif operation == "observe":
                payload = await run_in_threadpool(controller.observe, nonce, data)
            elif operation == "calibrate" and set(data) == {"target_slot"}:
                payload = controller.calibrate(nonce, data["target_slot"])
            elif operation == "arm" and set(data) == {"practice"}:
                payload = controller.arm(nonce, data["practice"])
            elif operation == "stop" and not data:
                payload = controller.stop(nonce)
            else:
                raise ValueError("vision_invalid_request")
            return result(payload)
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)
        except Exception:
            controller.stop(request.headers.get("x-studio-vision-session", ""))
            return result({"ok": False, "reason": "vision_unavailable"}, 503)

    @router.get("/api/production/vision/frame/{slot}")
    async def frame(slot: int, request: Request):
        try:
            check(request)
            data, frame_id = await run_in_threadpool(controller.frame, request.headers.get("x-studio-vision-session", ""), slot)
            return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store", "X-Vision-Frame": frame_id})
        except (ValueError, TypeError, KeyError) as error:
            return failure(error)

    @router.get("/api/production/vision/assets/{asset_path:path}")
    async def asset(asset_path: str, request: Request):
        try:
            check(request)
            # FilesetResolver uses a wasm subdirectory; no other path segments accepted.
            name = asset_path[5:] if asset_path.startswith("wasm/") else asset_path
            if "/" in name or "\\" in name or (asset_path.startswith("wasm/") != name.startswith("vision_wasm_")):
                raise ValueError("vision_asset_not_allowed")
            path = await run_in_threadpool(assets.resolve, name)
            mime = "application/javascript" if path.suffix in {".js", ".mjs"} else "application/wasm" if path.suffix == ".wasm" else "application/octet-stream"
            return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except (OSError, ValueError, TypeError) as error:
            return failure(error)

    return router, controller
