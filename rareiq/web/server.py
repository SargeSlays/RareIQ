from __future__ import annotations
import asyncio
import csv
import html
import io
import json
import logging
import os
import signal
import threading
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs

import cv2
import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rareiq.core.events import EventBus
from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.core.secrets import secrets as secret_store
from rareiq.core.storage import storage
from rareiq.services.provenance_capture_service import ProvenanceCaptureService
from rareiq.services.spotify_service import spotify
from rareiq.services.instant_replay_service import InstantReplayService
from rareiq.services.inventory_service import MAX_RECEIPT_DATA_URL_CHARS
from rareiq.services.recording_service import RecordingService
from rareiq.services.obs_service import ObsService
from rareiq.services.broadcast_destination_service import BroadcastDestinationService
from rareiq.version import BUILD_DATE, CODENAME, VERSION, version_payload
from rareiq.web.remote_access import (
    REMOTE_ACCESS_COOKIE,
    PairingAttemptLimiter,
    RemoteAccessPolicy,
    is_loopback_client,
    private_ipv4_addresses,
    validate_server_binding,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CAPTURE_DIR = BASE_DIR.parent.parent / "captures"
SERVER_SESSION_ID = uuid.uuid4().hex
SERVER_STARTED_AT = time.time()
REMOTE_ACCESS = RemoteAccessPolicy.from_environment(
    SERVER_SESSION_ID,
    secret_store=secret_store,
)
REMOTE_PAIRING_LIMITER = PairingAttemptLimiter()
LOGGER = logging.getLogger(__name__)
CATALOG_REFRESH_INTERVAL_SECONDS = max(
    15 * 60,
    int(os.getenv("RAREIQ_CATALOG_REFRESH_SECONDS", str(60 * 60))),
)
MAX_CONTROL_REQUEST_BYTES = 64 * 1024
MAX_RECEIPT_REQUEST_BYTES = MAX_RECEIPT_DATA_URL_CHARS + 8 * 1024


class RequestBodyTooLarge(ValueError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"request body exceeds {max_bytes} bytes")
        self.max_bytes = max_bytes


async def _read_bounded_body(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_content_length") from exc
        if declared_size < 0:
            raise HTTPException(status_code=400, detail="invalid_content_length")
        if declared_size > max_bytes:
            raise RequestBodyTooLarge(max_bytes)
    body = bytearray()
    async for chunk in request.stream():
        if len(chunk) > max_bytes - len(body):
            raise RequestBodyTooLarge(max_bytes)
        body.extend(chunk)
    return bytes(body)


async def _read_bounded_json(request: Request, max_bytes: int = MAX_CONTROL_REQUEST_BYTES) -> dict[str, Any]:
    body = await _read_bounded_body(request, max_bytes)
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    orchestrator.set_loop(asyncio.get_running_loop())

    async def boot_in_background() -> None:
        await asyncio.sleep(0.15)
        await asyncio.to_thread(orchestrator.boot_manager.run, False)

    boot_task = asyncio.create_task(boot_in_background())
    async def warm_recognition_ocr() -> None:
        await asyncio.sleep(0.35)
        await asyncio.to_thread(orchestrator.recognition.warm_ocr)

    ocr_warmup_task = asyncio.create_task(warm_recognition_ocr())
    async def refresh_new_releases() -> None:
        # Catalog providers publish new localized expansions independently.
        # Reconcile periodically so RareIQ never depends on a server restart
        # or on the discovery snapshot from the beginning of a long build.
        await asyncio.sleep(10)
        while True:
            try:
                await asyncio.to_thread(
                    orchestrator.master_database_builder.refresh_new_releases
                )
            except Exception:
                LOGGER.exception("TCG catalog freshness scan failed")
            await asyncio.sleep(CATALOG_REFRESH_INTERVAL_SECONDS)

    freshness_task = asyncio.create_task(refresh_new_releases())
    instant_replay.start()
    try:
        yield
    finally:
        if not boot_task.done():
            boot_task.cancel()
            with suppress(asyncio.CancelledError):
                await boot_task
        if not ocr_warmup_task.done():
            ocr_warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await ocr_warmup_task
        freshness_task.cancel()
        with suppress(asyncio.CancelledError):
            await freshness_task
        await asyncio.to_thread(orchestrator.camera_manager.shutdown)
        await asyncio.to_thread(instant_replay.stop)


app = FastAPI(title=f"RareIQ v{VERSION}", lifespan=lifespan)


def _remote_access_page(
    *,
    error: str | None = None,
    status_code: int | None = None,
    retry_after: int | None = None,
) -> HTMLResponse:
    notice = (
        f'<p class="error" role="alert">{html.escape(error)}</p>'
        if error
        else '<p>Enter the pairing token configured on the RareIQ workstation.</p>'
    )
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pair with RareIQ</title><style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#031019;color:#eafaff;font:16px Inter,Segoe UI,sans-serif}}
main{{width:min(100%,420px);padding:28px;border:1px solid #1d5267;border-radius:20px;background:#081e2a;box-shadow:0 24px 80px #0009}}.brand{{color:#54ddfa;font-size:12px;font-weight:900;letter-spacing:.18em;text-transform:uppercase}}h1{{margin:10px 0 6px;font-size:28px}}p{{color:#9bb4c0;line-height:1.5}}label{{display:grid;gap:8px;margin-top:22px;font-weight:800}}input,button{{width:100%;min-height:48px;border-radius:11px;font:inherit}}input{{padding:0 13px;border:1px solid #28566a;background:#04151f;color:#fff}}button{{margin-top:14px;border:0;background:#55d9f4;color:#03202b;font-weight:900;cursor:pointer}}.error{{color:#ff9b9b}}
</style></head><body><main><span class="brand">RareIQ Studio X</span><h1>Pair this device</h1>{notice}<form method="post" action="/remote-access" autocomplete="off"><label>Pairing token<input name="token" type="password" minlength="24" required autofocus autocomplete="one-time-code"></label><button type="submit">Connect securely</button></form></main></body></html>'''
    headers = {"Cache-Control": "no-store", "X-Frame-Options": "DENY"}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return HTMLResponse(
        document,
        status_code=status_code or (401 if error else 200),
        headers=headers,
    )


@app.middleware("http")
async def enforce_remote_access(request: Request, call_next):
    client_host = request.client.host if request.client else None
    if REMOTE_ACCESS.authorizes(
        client_host,
        request.cookies.get(REMOTE_ACCESS_COOKIE),
    ):
        return await call_next(request)
    if request.url.path == "/remote-access" or (
        request.method == "GET" and request.url.path == "/api/boot/ping"
    ):
        return await call_next(request)
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/remote-access", status_code=303)
    return JSONResponse(
        status_code=401,
        content={"ok": False, "reason": "remote_pairing_required"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/remote-access")
async def remote_access_login():
    if not REMOTE_ACCESS.enabled:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "remote_access_disabled"},
        )
    return _remote_access_page()


@app.post("/remote-access")
async def remote_access_pair(request: Request):
    if not REMOTE_ACCESS.enabled:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "remote_access_disabled"},
        )
    client_host = request.client.host if request.client else None
    retry_after = REMOTE_PAIRING_LIMITER.retry_after(client_host)
    if retry_after:
        return _remote_access_page(
            error="Too many pairing attempts. Wait before trying again.",
            status_code=429,
            retry_after=retry_after,
        )
    try:
        body = await _read_bounded_body(request, 4096)
    except RequestBodyTooLarge:
        return _remote_access_page(error="Pairing request was too large.")
    values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    token = (values.get("token") or [""])[0]
    if not REMOTE_ACCESS.verify_pairing_token(token):
        retry_after = REMOTE_PAIRING_LIMITER.record_failure(client_host)
        if retry_after:
            return _remote_access_page(
                error="Too many pairing attempts. Wait before trying again.",
                status_code=429,
                retry_after=retry_after,
            )
        return _remote_access_page(error="Pairing token was not accepted.")
    REMOTE_PAIRING_LIMITER.clear(client_host)
    response = RedirectResponse("/control", status_code=303)
    response.set_cookie(
        REMOTE_ACCESS_COOKIE,
        REMOTE_ACCESS.cookie_value,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=12 * 60 * 60,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/remote-access/logout")
async def remote_access_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(REMOTE_ACCESS_COOKIE, path="/")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/remote-access/status")
async def remote_access_status(request: Request):
    client_host = request.client.host if request.client else None
    port = int(request.url.port or (443 if request.url.scheme == "https" else 80))
    lan_urls = (
        [f"{request.url.scheme}://{address}:{port}/control" for address in private_ipv4_addresses()]
        if REMOTE_ACCESS.enabled
        else []
    )
    return {
        "ok": True,
        "enabled": REMOTE_ACCESS.enabled,
        "mode": "authenticated-lan" if REMOTE_ACCESS.enabled else "local-only",
        "token_configured": REMOTE_ACCESS.token_configured,
        "pairing_required": REMOTE_ACCESS.enabled,
        "lan_urls": lan_urls,
        "paired": REMOTE_ACCESS.authorizes(
            client_host,
            request.cookies.get(REMOTE_ACCESS_COOKIE),
        ),
        "client_loopback": is_loopback_client(client_host),
        "server_session_id": SERVER_SESSION_ID,
    }

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


def _request_body_limit(request: Request) -> int | None:
    path = request.url.path
    if request.method == "POST" and path == "/api/creator/assets":
        mime = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        rule = orchestrator.reaction_assets.ALLOWED.get(mime)
        return rule[2] if rule else None
    if request.method == "POST" and path == "/api/inventory/expenses":
        return MAX_RECEIPT_REQUEST_BYTES
    if request.method == "POST" and path in {"/api/multi-card/select", "/api/multi-card/capture"}:
        return MAX_CONTROL_REQUEST_BYTES
    return None


@app.middleware("http")
async def enforce_bounded_request_bodies(request: Request, call_next):
    limit = _request_body_limit(request)
    if limit is None:
        return await call_next(request)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError:
            return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_content_length"})
        if declared_size < 0:
            return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_content_length"})
        if declared_size > limit:
            return JSONResponse(
                status_code=413,
                content={"ok": False, "reason": "request_too_large", "max_bytes": limit},
            )
    body = bytearray()
    async for chunk in request.stream():
        if len(chunk) > limit - len(body):
            return JSONResponse(
                status_code=413,
                content={"ok": False, "reason": "request_too_large", "max_bytes": limit},
            )
        body.extend(chunk)
    request._body = bytes(body)
    return await call_next(request)


def _active_camera_provenance_context() -> dict[str, Any]:
    status = orchestrator.camera_manager.status()
    active_slot = int(status.get("active_slot") or 1)
    slot = next(
        (
            item
            for item in status.get("camera_slots") or []
            if int(item.get("slot_id") or 0) == active_slot
        ),
        {},
    )
    source = dict(slot.get("source") or {})
    vision = dict(status.get("vision") or {})
    return {
        "slot_id": active_slot,
        "source_id": slot.get("source_id") or source.get("source_id"),
        "display_name": slot.get("display_name") or vision.get("camera_name"),
        "player_side": slot.get("side"),
        "frame_id": vision.get("frame_id"),
        "frame_timestamp": vision.get("frame_timestamp"),
        "card_crop_valid": bool(vision.get("visible") and vision.get("stable")),
    }


provenance_capture = ProvenanceCaptureService(
    storage.get_path("provenance_path"),
    legacy_roots=(BASE_DIR.parent / "data" / "provenance",),
    server_session_id=SERVER_SESSION_ID,
    frame_provider=orchestrator.camera_manager.latest_frame,
    crop_provider=orchestrator.camera_manager.latest_crop,
    camera_context_provider=_active_camera_provenance_context,
)


async def _evaluate_provenance_event(event: dict[str, Any]) -> None:
    if str(event.get("type") or "") != "recognition_update":
        return
    snapshot = orchestrator.recognition_state.snapshot()
    if int(snapshot.get("generation") or 0) != int(
        (event.get("payload") or {}).get("generation") or 0
    ):
        return
    # Disk and PNG work never blocks recognition/event publication.
    asyncio.create_task(asyncio.to_thread(provenance_capture.evaluate_recognition, snapshot))


event_bus.subscribe(_evaluate_provenance_event)


def _clear_recognition_after_camera_switch(payload: dict[str, Any]) -> None:
    status = orchestrator.camera_manager.status().get("vision") or {}
    orchestrator._emit_from_thread({
        "type": "card_removed",
        "payload": {
            "frame_id": status.get("frame_id"),
            "reason": "active_camera_changed",
            "camera_switch": payload,
        },
    })


orchestrator.camera_manager.set_active_change_hook(
    _clear_recognition_after_camera_switch
)


class SessionStartRequest(BaseModel):
    customer: str = Field(min_length=1, max_length=100)
    order_number: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=150)
    boxes_total: int = Field(default=1, ge=1, le=100)
    packs_per_box: int = Field(default=5, ge=1, le=100)


class CameraStartRequest(BaseModel):
    camera_index: int
    camera_backend: int


class CameraControlRequest(BaseModel):
    action: str
    speed: str = "medium"
    preset: int | None = None
    control: str | None = None
    value: float | None = None


class CameraSlotSourceRequest(BaseModel):
    source_id: str | None = None
    side: str | None = None


class ProvenanceSettingsRequest(BaseModel):
    settings: dict[str, Any] | None = None
    enabled: bool | None = None
    workflowMode: str | None = None
    triggerReason: str | None = None
    captureTypes: dict[str, bool] | None = None
    customerId: str | None = None
    vendorId: str | None = None
    packNumber: int | None = None
    turnNumber: int | None = None
    playerSide: str | None = None
    includeTimestamp: bool | None = None
    includeRecognitionEvidence: bool | None = None
    minimumConfidence: float | None = None


class ProvenanceCorrectionRequest(BaseModel):
    identity: dict[str, Any]
    reason: str | None = None

class AutoCaptureRequest(BaseModel):
    enabled: bool

class RecognitionToggleRequest(BaseModel):
    enabled: bool

class PackContextRenameRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)

class PackContextActivateRequest(BaseModel):
    reference_id: str = Field(min_length=1, max_length=255)

class PackProfileRequest(BaseModel):
    reference_id: str = Field(min_length=1, max_length=255)
    expected_cards: int = Field(ge=1, le=30)
    rare_slot: int = Field(ge=1, le=30)

class PackProfileObservationRequest(BaseModel):
    reference_id: str = Field(min_length=1, max_length=255)
    observed_cards: int = Field(ge=1, le=30)
    rare_slot: int | None = Field(default=None, ge=1, le=30)

class ActiveSetRequest(BaseModel):
    set_id: str

class RecognitionSetContextRequest(BaseModel):
    mode: str = "auto"
    set_id: str | None = None
    set_name: str | None = None
    language: str | None = None
    provider: str | None = None
    pack_label: str | None = Field(default=None, max_length=120)

class PackTransitionRemoveRequest(BaseModel):
    from_number: int = Field(ge=0, le=9999)
    to_number: int = Field(ge=0, le=9999)

class PackTransitionImportRequest(BaseModel):
    model: dict[str, Any]

class PackTransitionRestoreRequest(BaseModel):
    backup_id: str = Field(min_length=1, max_length=255)

class TCGSelectionRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|manual)$")
    game_id: str | None = None

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

class MasterBuilderPriorityRequest(BaseModel):
    query: str = Field(min_length=1, max_length=120)

class RecognitionCatalogSelectionRequest(BaseModel):
    state_id: str = Field(min_length=1, max_length=120)
    candidate: dict[str, Any]

class FastMetadataRequest(BaseModel):
    languages: list[str] | None = None

class BrandSettingsRequest(BaseModel):
    settings: dict[str, Any]

class OverlayStateRequest(BaseModel):
    state: dict[str, Any]

class PokedexOverlayRequest(BaseModel):
    enabled: bool

class RareIntelligenceThemeRequest(BaseModel):
    preset: str = Field(default="rareiq", pattern="^(rareiq|minimal|broadcast|custom)$")
    accent_color: str = Field(default="#53d5f2", pattern="^#[0-9a-fA-F]{6}$")
    secondary_color: str = Field(default="#b574ff", pattern="^#[0-9a-fA-F]{6}$")
    background_color: str = Field(default="#05111e", pattern="^#[0-9a-fA-F]{6}$")
    text_color: str = Field(default="#f7fbff", pattern="^#[0-9a-fA-F]{6}$")
    panel_opacity: float = Field(default=0.94, ge=0.2, le=1.0)
    corner_radius: int = Field(default=30, ge=0, le=60)
    scale: int = Field(default=100, ge=70, le=140)
    alignment: str = Field(default="left", pattern="^(left|center|right)$")
    font: str = Field(default="inter", pattern="^(inter|system|serif|mono)$")
    brand_text: str = Field(default="RAREIQ · LIVE INTELLIGENCE", max_length=64)
    show_art: bool = True
    show_facts: bool = True
    show_flavor: bool = True
    show_brand: bool = True

class BroadcastGraphicRequest(BaseModel):
    kind: str = "lower-third"
    style: str = "glass"
    title: str = Field(default="", max_length=80)
    subtitle: str = Field(default="", max_length=140)
    accent: str = "cyan"
    image_url: str = Field(default="", max_length=500)
    duration_ms: int = Field(default=0, ge=0, le=60000)

class ProductionScreenRequest(BaseModel):
    mode: str = "starting-soon"
    title: str = Field(default="Starting Soon", max_length=80)
    message: str = Field(default="The stream will begin shortly.", max_length=180)
    countdown_seconds: int = Field(default=300, ge=0, le=86400)
    accent: str = "cyan"

class CollectionAdjustmentRequest(BaseModel):
    version_key: str
    delta: int
    reason: str = "operator_correction"

class CollectionGoalRequest(BaseModel):
    target_type: str
    set_name: str
    collector_number: str | None = None
    language: str | None = None
    card_name: str | None = None
    target_quantity: int = Field(default=1, ge=1, le=9999)
    priority: str = "medium"
    notes: str = ""

class CollectionDispositionRequest(BaseModel):
    version_key: str
    trade: int = Field(default=0, ge=0)
    sell: int = Field(default=0, ge=0)

class CollectionImportRequest(BaseModel):
    backup: dict[str, Any]

class InventoryCreateRequest(BaseModel):
    card: dict[str, Any]
    cost_basis: float = Field(default=0, ge=0)
    asking_price: float | None = Field(default=None, ge=0)
    condition: str = "raw"
    location: str = ""
    notes: str = ""
    allocation_group: str = Field(default="", max_length=120)
    allocation_weight: float = Field(default=1.0, ge=0.1, le=100)

class ManualPriceRequest(BaseModel):
    market: float = Field(ge=0)
    low: float | None = Field(default=None, ge=0)
    high: float | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    note: str = Field(default="", max_length=300)

class PriceQuoteSelectionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    variant: str = Field(default="standard", min_length=1, max_length=120)
    currency: str = Field(min_length=3, max_length=8)
    reason: Literal["trusted-provider", "recent-sale", "variant-match", "regional-market", "other"] = "trusted-provider"
    note: str = Field(default="", max_length=300)

class PriceAlertRequest(BaseModel):
    direction: Literal["above", "below"] = "above"
    target: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    enabled: bool = True

class PriceAlertRemoveRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=200)

class InventoryBatchCreateRequest(InventoryCreateRequest):
    quantity: int = Field(default=1, ge=1, le=100)

class InventoryListingDraftRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    channel: Literal["in_person", "ebay", "tcgplayer", "whatnot", "shopify", "other"] = "other"
    fee_percent: float = Field(default=0, ge=0, le=95)
    shipping_cost: float = Field(default=0, ge=0)
    packaging_cost: float = Field(default=0, ge=0)
    desired_profit_percent: float = Field(default=25, ge=0, le=10000)

class InventoryListingStatusRequest(BaseModel):
    action: Literal["activate", "end"] = "activate"
    channel: Literal["in_person", "ebay", "tcgplayer", "whatnot", "shopify", "other"] = "other"
    listing_id: str = Field(default="", max_length=160)
    listing_url: str = Field(default="", max_length=500)
    asking_price: float | None = Field(default=None, ge=0)

class InventoryBulkListingRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal["end", "reprice"]
    price_adjustment_percent: float = Field(default=0, ge=-95, le=1000)

class InventorySmartRepriceRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    desired_profit_percent: float = Field(default=25, ge=0, le=10000)
    minimum_profit: float = Field(default=0, ge=0)
    channel_profiles: dict[str, dict[str, float]] = Field(default_factory=dict)
    apply: bool = False

class InventoryRepriceRollbackRequest(BaseModel):
    audit_id: str = Field(min_length=1, max_length=80)

class InventoryMarketplaceSyncActionRequest(BaseModel):
    action: Literal["approve", "retry", "simulate"]
    simulated_outcome: Literal["success", "failure"] = "success"

class InventorySaleRequest(BaseModel):
    sale_price: float = Field(ge=0)
    fees: float = Field(default=0, ge=0)
    shipping_cost: float = Field(default=0, ge=0)
    packaging_cost: float = Field(default=0, ge=0)
    channel: str = ""
    order_reference: str = ""

class InventoryVoidRequest(BaseModel):
    reason: str = "operator_void"

class InventoryAllocationRequest(BaseModel):
    group: str = Field(min_length=1, max_length=120)
    total_cost: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=8)

class InventoryAllocationLockRequest(BaseModel):
    group: str = Field(min_length=1, max_length=120)

class InventoryExpenseRequest(BaseModel):
    category: Literal["fees", "shipping", "supplies", "packs", "boxes", "other"] = "other"
    amount: float = Field(gt=0, le=1000000)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    note: str = Field(default="", max_length=300)
    incurred_at: float | None = None
    recurrence: Literal["none", "weekly", "monthly", "annual"] = "none"
    receipt_name: str = Field(default="", max_length=180)
    receipt_data_url: str = Field(default="", max_length=MAX_RECEIPT_DATA_URL_CHARS)

class InventoryExpenseUpdateRequest(BaseModel):
    category: Literal["fees", "shipping", "supplies", "packs", "boxes", "other"] | None = None
    amount: float | None = Field(default=None, gt=0, le=1000000)
    note: str | None = Field(default=None, max_length=300)
    incurred_at: float | None = None
    recurrence: Literal["none", "weekly", "monthly", "annual"] | None = None

class BusinessProfileRequest(BaseModel):
    company_name: str = Field(default="RareIQ Business", max_length=120)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    fiscal_year_start: int = Field(default=1, ge=1, le=12)
    reporting_basis: Literal["cash", "accrual"] = "cash"

class AccountingPeriodRequest(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)

class RecognitionCandidateSelectionRequest(BaseModel):
    state_id: str = Field(min_length=1, max_length=80)
    candidate_index: int = Field(ge=0, le=49)

class PackEconomicsRequest(BaseModel):
    pack_cost: float = Field(default=0, ge=0, le=100000)
    box_cost: float = Field(default=0, ge=0, le=1000000)
    packs_per_box: int = Field(default=1, ge=1, le=1000)
    currency: str = Field(default="USD", min_length=3, max_length=8)

class RevealSequenceConfigRequest(BaseModel):
    enabled: bool | None = None
    expected_cards: int | None = Field(default=None, ge=1, le=30)
    rare_slot: int | None = Field(default=None, ge=1, le=30)
    build_suspense: bool | None = None
    reaction_copy: dict[str, str] | None = None
    custom_grail_preset: str | None = None
    audio_enabled: bool | None = None
    animations_enabled: bool | None = None
    animation_intensity: int | None = Field(default=None, ge=0, le=100)
    animation_duration_ms: int | None = Field(default=None, ge=1200, le=10000)
    particles_enabled: bool | None = None
    flash_enabled: bool | None = None
    minimum_animation_tier: str | None = None
    medium_value_threshold: float | None = Field(default=None, ge=0, le=1000000)
    grail_value_threshold: float | None = Field(default=None, ge=0, le=1000000)
    arming_delay_ms: int | None = Field(default=None, ge=0, le=15000)

class RevealReplayRequest(BaseModel):
    reveal_id: str

class ReactionAssetMappingRequest(BaseModel):
    tier: str
    kind: str
    asset_id: str | None = None

class SoundboardConfigRequest(BaseModel):
    pads: list[dict[str, Any]] = Field(default_factory=list, max_length=50)

class SpotifyPlaybackRequest(BaseModel):
    action: str
    device_id: str | None = None
    uri: str | None = None
    position_ms: int | None = Field(default=None, ge=0)
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    state: bool | None = None
    repeat_state: str | None = None

class SpotifySetupRequest(BaseModel):
    client_id: str = Field(default="", max_length=128)
    redirect_uri: str = Field(default="http://127.0.0.1:8765/api/spotify/callback", max_length=300)

class ProductionSwitcherRequest(BaseModel):
    preview_slot: int | None = Field(default=None, ge=1, le=4)
    transition: str | None = None
    duration_ms: int | None = Field(default=None, ge=0, le=5000)

class ProductionSceneRequest(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=40)
    program_slot: int = Field(default=1, ge=1, le=4)
    preview_slot: int = Field(default=2, ge=1, le=4)
    transition: str = "fade"
    duration_ms: int = Field(default=500, ge=0, le=5000)
    spotify_action: str = "keep"
    soundboard_action: str = "keep"
    screen_action: str = "keep"
    screen_mode: str = "starting-soon"
    screen_title: str = Field(default="Starting Soon", max_length=80)
    screen_message: str = Field(default="The stream will begin shortly.", max_length=180)
    screen_countdown_seconds: int = Field(default=300, ge=0, le=86400)
    screen_accent: str = "cyan"

class ReplayMarkRequest(BaseModel):
    seconds: int = Field(default=8, ge=2, le=20)
    name: str = Field(default="Highlight", max_length=60)

class ReplayTakeRequest(BaseModel):
    highlight_id: str
    speed: float = Field(default=1.0, ge=.25, le=2.0)

class ProductionEventRequest(BaseModel):
    kind: str = Field(default="note", max_length=30)
    title: str = Field(min_length=1, max_length=80)
    detail: str = Field(default="", max_length=300)

class ProductionSessionMetadataRequest(BaseModel):
    name: str = Field(default="", max_length=80)
    customer: str = Field(default="", max_length=100)
    break_id: str = Field(default="", max_length=100)
    operator_notes: str = Field(default="", max_length=1000)

class StartShowRequest(ProductionSessionMetadataRequest):
    start_obs_stream: bool = False
    start_obs_recording: bool = False

class RecordingSettingsRequest(BaseModel):
    output_dir: str = Field(min_length=1, max_length=500)
    command_template: str = Field(default="", max_length=2000)
    preset: str = "balanced"
    minimum_free_gb: float = Field(default=2.0, ge=.1, le=1000)

class ObsSettingsRequest(BaseModel):
    host: str = Field(default="127.0.0.1", max_length=255)
    port: int = Field(default=4455, ge=1, le=65535)
    password: str = Field(default="", max_length=500)
    enabled: bool = False
    scene_map: dict[str, str] = Field(default_factory=dict)

class ObsCommandRequest(BaseModel):
    action: str
    scene: str | None = None

class ObsBootstrapRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    dry_run: bool = True

PRODUCTION_SWITCHER_STATE: dict[str, Any] = {"program_slot": 1, "preview_slot": 2, "transition": "fade", "duration_ms": 500, "generation": 0, "updated_at": time.time()}
PRODUCTION_SWITCHER_LOCK = threading.RLock()
PRODUCTION_SCENE_PATH = BASE_DIR.parent.parent / "production_scenes.json"
DEFAULT_PRODUCTION_SCENES = [
    {"id": "main-card", "name": "Main Card", "program_slot": 1, "preview_slot": 2, "transition": "fade", "duration_ms": 500, "spotify_action": "keep", "soundboard_action": "keep", "screen_action": "hide"},
    {"id": "overhead-grid", "name": "Overhead Grid", "program_slot": 2, "preview_slot": 1, "transition": "slide", "duration_ms": 500, "spotify_action": "keep", "soundboard_action": "keep"},
    {"id": "host", "name": "Host", "program_slot": 3, "preview_slot": 1, "transition": "fade", "duration_ms": 500, "spotify_action": "keep", "soundboard_action": "keep"},
    {"id": "break", "name": "Break", "program_slot": 4, "preview_slot": 1, "transition": "fade", "duration_ms": 750, "spotify_action": "play", "soundboard_action": "stop", "screen_action": "show", "screen_mode": "brb", "screen_title": "Be Right Back", "screen_message": "We are taking a short break.", "screen_countdown_seconds": 120, "screen_accent": "purple"},
    {"id": "starting-soon", "name": "Starting Soon", "program_slot": 4, "preview_slot": 1, "transition": "zoom", "duration_ms": 1000, "spotify_action": "play", "soundboard_action": "stop", "screen_action": "show", "screen_mode": "starting-soon", "screen_title": "Starting Soon", "screen_message": "The stream will begin shortly.", "screen_countdown_seconds": 300, "screen_accent": "cyan"},
]
def _load_production_scenes() -> list[dict[str, Any]]:
    try:
        value = json.loads(PRODUCTION_SCENE_PATH.read_text(encoding="utf-8"))
        return value[:20] if isinstance(value, list) else list(DEFAULT_PRODUCTION_SCENES)
    except (OSError, ValueError, TypeError):
        return list(DEFAULT_PRODUCTION_SCENES)
def _save_production_scenes(scenes: list[dict[str, Any]]) -> None:
    temp = PRODUCTION_SCENE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(scenes, indent=2), encoding="utf-8")
    temp.replace(PRODUCTION_SCENE_PATH)
PRODUCTION_SCENES = _load_production_scenes()
PRODUCTION_SESSION_LOCK = threading.RLock()
PRODUCTION_SESSION_PATH = BASE_DIR.parent.parent / "production_session.json"
PRODUCTION_HISTORY_PATH = BASE_DIR.parent.parent / "production_history.json"
PRODUCTION_SESSION: dict[str, Any] = {"active": False, "session_id": None, "started_at": 0.0, "ended_at": 0.0, "events": [], "metadata": {"name": "", "customer": "", "break_id": "", "operator_notes": ""}, "pack_economics": {"pack_cost": 0.0, "box_cost": 0.0, "packs_per_box": 1, "currency": "USD"}, "recording": {"configured": bool(os.getenv("RAREIQ_RECORDING_COMMAND")), "active": False, "mode": "hook"}}
def _save_production_session() -> None:
    temp = PRODUCTION_SESSION_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(PRODUCTION_SESSION, indent=2), encoding="utf-8")
    temp.replace(PRODUCTION_SESSION_PATH)
def _load_production_history() -> list[dict[str, Any]]:
    try:
        value = json.loads(PRODUCTION_HISTORY_PATH.read_text(encoding="utf-8"))
        return value[-100:] if isinstance(value, list) else []
    except (OSError, ValueError, TypeError):
        return []
def _save_production_history(history: list[dict[str, Any]]) -> None:
    temp = PRODUCTION_HISTORY_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(history[-100:], indent=2), encoding="utf-8")
    temp.replace(PRODUCTION_HISTORY_PATH)
def _production_event(kind: str, title: str, detail: str = "") -> dict[str, Any]:
    event = {"id": uuid.uuid4().hex[:12], "kind": str(kind)[:30], "title": str(title)[:80], "detail": str(detail)[:300], "timestamp": time.time()}
    PRODUCTION_SESSION["events"].append(event); PRODUCTION_SESSION["events"] = PRODUCTION_SESSION["events"][-500:]
    _save_production_session()
    return event
instant_replay = InstantReplayService(storage.get_path("replay_path"), orchestrator.camera_manager.slot_jpeg, lambda: int(PRODUCTION_SWITCHER_STATE["program_slot"]))
recording = RecordingService(
    storage.get_path("recording_path"),
    config_path=storage.get_path("config_path") / "recording_settings.json",
)
obs = ObsService(BASE_DIR.parent.parent / "obs_settings.json")
broadcast_destinations = BroadcastDestinationService()

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

@app.get("/")
async def root():
    return HTMLResponse(
        f'<h1>RareIQ v{VERSION} — {CODENAME}</h1>'
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
    client_host = ws.client.host if ws.client else None
    if not REMOTE_ACCESS.authorizes(
        client_host,
        ws.cookies.get(REMOTE_ACCESS_COOKIE),
    ):
        await ws.close(code=4401, reason="remote_pairing_required")
        return
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
        "slots": orchestrator.camera_manager.camera_slots(),
    }


@app.get("/api/camera-slots")
async def camera_slots():
    return {
        "ok": True,
        "active_slot": orchestrator.camera_manager.active_slot_id(),
        "slots": orchestrator.camera_manager.camera_slots(),
        "sessions": orchestrator.camera_manager.session_statuses(),
    }


@app.post("/api/camera-slots/{slot_id}/source")
@app.put("/api/camera-slots/{slot_id}/source")
async def assign_camera_slot(slot_id: int, req: CameraSlotSourceRequest):
    try:
        slot = await asyncio.to_thread(
            orchestrator.camera_manager.assign_slot,
            slot_id,
            req.source_id,
            req.side,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "invalid_assignment", "message": str(exc)},
        )
    return {"ok": True, "slot": slot}


@app.post("/api/camera-slots/{slot_id}/activate")
async def activate_camera_slot(slot_id: int):
    try:
        return await asyncio.to_thread(
            orchestrator.camera_manager.activate_slot, slot_id
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "invalid_activation", "message": str(exc)},
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "activation_failed", "message": str(exc)},
        )


@app.post("/api/cameras/{source_id}/reconnect")
async def reconnect_camera_source(source_id: str):
    try:
        status = await asyncio.to_thread(
            orchestrator.camera_manager.reconnect_source, source_id
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "source_not_found", "message": str(exc)},
        )
    return {"ok": True, "source": status}


@app.post("/api/cameras/{source_id}/restart")
async def restart_camera_source(source_id: str):
    try:
        status = await asyncio.to_thread(
            orchestrator.camera_manager.restart_source, source_id
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "source_not_found", "message": str(exc)},
        )
    return {"ok": True, "source": status}

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
    manager = status["manager"]
    return {
        "ok": bool(
            manager["state"] == "running"
            and manager["worker_alive"]
            and manager["frame_fresh"]
        ),
        "state": manager["state"],
        "message": manager["message"],
        "visible": bool(status["vision"].get("visible")),
        "frame_fresh": manager["frame_fresh"],
        "worker_alive": manager["worker_alive"],
        "stalled": manager["stalled"],
        "frame_age_seconds": manager["frame_age_seconds"],
        "last_frame_at": manager["last_frame_at"],
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


@app.post("/api/catalog/refresh-current")
async def catalog_refresh_current():
    card = orchestrator._current_recognition_card()
    if not card:
        raise HTTPException(status_code=409, detail="No verified card is available.")
    result = orchestrator.catalog.refresh(card)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    return result


@app.post("/api/catalog/manual-price")
async def catalog_manual_price(req: ManualPriceRequest):
    card = orchestrator._current_recognition_card()
    if not card:
        raise HTTPException(status_code=409, detail="No verified card is available.")
    result = orchestrator.catalog.set_manual_price(card, req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    orchestrator.recognition_state.refresh(
        vision=orchestrator.vision.status(),
        recognition=orchestrator.recognition.status(),
        catalog=orchestrator.catalog.status(),
    )
    return result

@app.post("/api/catalog/select-quote")
async def catalog_select_quote(req: PriceQuoteSelectionRequest):
    card = orchestrator._current_recognition_card()
    if not card:
        raise HTTPException(status_code=409, detail="No verified card is available.")
    result = orchestrator.catalog.select_price_quote(card, req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    orchestrator.recognition_state.refresh(
        vision=orchestrator.vision.status(), recognition=orchestrator.recognition.status(),
        catalog=orchestrator.catalog.status(),
    )
    return result

@app.post("/api/catalog/select-quote/undo")
async def catalog_undo_selected_quote():
    card = orchestrator._current_recognition_card()
    if not card:
        raise HTTPException(status_code=409, detail="No verified card is available.")
    result = orchestrator.catalog.undo_price_quote_selection(card)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    orchestrator.recognition_state.refresh(
        vision=orchestrator.vision.status(), recognition=orchestrator.recognition.status(),
        catalog=orchestrator.catalog.status(),
    )
    return result

@app.get("/api/catalog/quote-resolution-history")
async def catalog_quote_resolution_history():
    card = orchestrator._current_recognition_card()
    return {"ok": True, "history": orchestrator.catalog.price_resolution_history(card) if card else []}

@app.get("/api/catalog/quote-resolution-history/export")
async def catalog_quote_resolution_export(format: Literal["csv", "json"] = "csv"):
    report = orchestrator.catalog.price_resolution_report()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if format == "json":
        return Response(json.dumps(report, ensure_ascii=False, indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="rareiq-pricing-audit-{stamp}.json"'})
    fields = ["resolution_id", "set_code", "collector_number", "language", "card_variant",
              "provider", "quote_variant", "currency", "market", "reason", "note",
              "selected_at", "undone_at", "status"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(report["decisions"])
    return Response(output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rareiq-pricing-audit-{stamp}.csv"'})

@app.post("/api/catalog/price-alert")
async def catalog_price_alert(req: PriceAlertRequest):
    card = orchestrator._current_recognition_card()
    if not card:
        raise HTTPException(status_code=409, detail="No verified card is available.")
    result = orchestrator.catalog.set_price_alert(card, req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    return result

@app.get("/api/catalog/price-alerts")
async def catalog_price_alerts():
    return {"ok": True, **orchestrator.catalog.price_alert_dashboard()}

@app.post("/api/catalog/price-alerts/refresh")
async def catalog_price_alert_refresh():
    result = orchestrator.catalog.refresh_watched_prices()
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    return result

@app.post("/api/catalog/price-alerts/remove")
async def catalog_price_alert_remove(req: PriceAlertRemoveRequest):
    return orchestrator.catalog.remove_price_alert(req.identity)

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


@app.get("/api/camera/ptz")
async def camera_ptz_status(force: bool = False):
    return {
        "ok": True,
        "ptz": orchestrator.vision.ptz_status(),
        "cameras": await asyncio.to_thread(
            orchestrator.camera_manager.camera_control_devices, force
        ),
    }


@app.post("/api/camera/ptz")
async def camera_ptz_control(req: CameraControlRequest):
    try:
        result = await asyncio.to_thread(
            orchestrator.vision.camera_control,
            req.action,
            speed=req.speed,
            preset=req.preset,
            control=req.control,
            value=req.value,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_control", "message": str(exc)})
    return JSONResponse(status_code=200 if result.get("ok") else 409, content=result)

@app.get("/api/boot/ping")
async def boot_ping():
    uptime_seconds = max(0.0, time.time() - SERVER_STARTED_AT)
    return {
        "ok": True,
        "version": VERSION,
        "server_session_id": SERVER_SESSION_ID,
        "pid": os.getpid(),
        "started_at": SERVER_STARTED_AT,
        "uptime_seconds": round(uptime_seconds, 3),
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
    detailed_health = orchestrator.system_health.status()
    storage_health = storage.health()
    uptime_seconds = max(0.0, time.time() - SERVER_STARTED_AT)

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
        "storage": storage_health,
        "server": {
            "healthy": True,
            "state": "running",
            "message": f"RareIQ {VERSION} server process is running.",
            "pid": os.getpid(),
            "server_session_id": SERVER_SESSION_ID,
            "started_at": SERVER_STARTED_AT,
            "uptime_seconds": round(uptime_seconds, 3),
        },
    }

    return {
        "ok": all(component["healthy"] for component in components.values()),
        "timestamp": time.time(),
        "version": VERSION,
        "server_session_id": SERVER_SESSION_ID,
        "pid": os.getpid(),
        "uptime_seconds": round(uptime_seconds, 3),
        "components": components,
        "health": detailed_health,
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

@app.get("/api/production/graphics")
async def production_graphics_status():
    return {"ok": True, "graphic": orchestrator.overlay_state.get().get("broadcast_graphic")}

@app.post("/api/production/graphics/preview")
async def preview_production_graphic(request: BroadcastGraphicRequest):
    graphic = request.model_dump() | {"visible": False, "preview": True, "generation": int(orchestrator.overlay_state.get().get("broadcast_graphic", {}).get("generation", 0)) + 1}
    state = orchestrator.overlay_state.update({"broadcast_graphic": graphic})
    return {"ok": True, "graphic": state["broadcast_graphic"]}

@app.post("/api/production/graphics/take")
async def take_production_graphic(request: BroadcastGraphicRequest):
    graphic = request.model_dump() | {"visible": True, "preview": False, "shown_at": time.time(), "generation": int(orchestrator.overlay_state.get().get("broadcast_graphic", {}).get("generation", 0)) + 1}
    state = orchestrator.overlay_state.update({"broadcast_graphic": graphic})
    return {"ok": True, "graphic": state["broadcast_graphic"]}

@app.post("/api/production/graphics/hide")
async def hide_production_graphic():
    graphic = dict(orchestrator.overlay_state.get().get("broadcast_graphic") or {})
    graphic.update({"visible": False, "preview": False, "generation": int(graphic.get("generation", 0)) + 1})
    state = orchestrator.overlay_state.update({"broadcast_graphic": graphic})
    return {"ok": True, "graphic": state["broadcast_graphic"]}

@app.get("/api/production/screen")
async def production_screen_status():
    return {"ok": True, "screen": orchestrator.overlay_state.get().get("production_screen")}

@app.post("/api/production/screen/take")
async def take_production_screen(request: ProductionScreenRequest):
    if request.mode not in {"starting-soon", "brb", "ending", "countdown"} or request.accent not in {"cyan", "purple", "gold", "green", "red"}:
        return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_production_screen"})
    screen = request.model_dump() | {"visible": True, "started_at": time.time(), "generation": int(orchestrator.overlay_state.get().get("production_screen", {}).get("generation", 0)) + 1}
    state = orchestrator.overlay_state.update({"production_screen": screen})
    return {"ok": True, "screen": state["production_screen"]}

@app.post("/api/production/screen/hide")
async def hide_production_screen():
    screen = dict(orchestrator.overlay_state.get().get("production_screen") or {})
    screen.update({"visible": False, "generation": int(screen.get("generation", 0)) + 1})
    state = orchestrator.overlay_state.update({"production_screen": screen})
    return {"ok": True, "screen": state["production_screen"]}

@app.get("/api/production/replay")
async def production_replay_status():
    return {"ok": True, **instant_replay.snapshot()}

@app.post("/api/production/replay/mark")
async def mark_production_replay(request: ReplayMarkRequest):
    result = await asyncio.to_thread(instant_replay.mark, request.seconds, request.name)
    return _collection_mutation_response(result, "created")

@app.post("/api/production/replay/take")
async def take_production_replay(request: ReplayTakeRequest):
    result = instant_replay.take(request.highlight_id, request.speed)
    return _collection_mutation_response(result, "updated")

@app.post("/api/production/replay/stop")
async def stop_production_replay():
    return {"ok": True, **instant_replay.stop_playback()}

@app.get("/api/production/replay/{highlight_id}/frame/{index}")
async def production_replay_frame(highlight_id: str, index: int):
    path = instant_replay.frame(highlight_id, index)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"}) if path else JSONResponse(status_code=404, content={"ok": False, "reason": "replay_frame_not_found"})

@app.get("/api/creator/reveal-sequence")
async def reveal_sequence_status():
    state = orchestrator.reveal_sequence.snapshot()
    tier = state.get("reaction_tier")
    mapped = orchestrator.reaction_assets.snapshot().get("mapping", {})
    state["reaction_assets"] = mapped.get(tier, {}) if tier else {"audio": None, "visual": None}
    return {"ok": True, "state": state}

@app.post("/api/creator/reveal-sequence")
async def configure_reveal_sequence(request: RevealSequenceConfigRequest):
    payload = {key: value for key, value in request.model_dump().items() if value is not None}
    return {"ok": True, "state": orchestrator.reveal_sequence.configure(payload)}

@app.post("/api/creator/reveal-sequence/next-pack")
async def reset_reveal_sequence_pack():
    return {"ok": True, "state": orchestrator.reveal_sequence.next_pack()}

@app.post("/api/creator/reveal-sequence/release")
async def release_reveal_sequence_animation():
    return {"ok": True, "state": orchestrator.reveal_sequence.release_animation()}

@app.post("/api/creator/reveal-sequence/cancel")
async def cancel_reveal_sequence_animation():
    return {"ok": True, "state": orchestrator.reveal_sequence.cancel_animation()}

@app.post("/api/creator/reveal-sequence/replay")
async def replay_reveal_sequence_animation(request: RevealReplayRequest):
    return {"ok": True, "state": orchestrator.reveal_sequence.replay_animation(request.reveal_id)}

@app.get("/overlay/reveal-sequence")
async def reveal_sequence_overlay():
    return FileResponse(STATIC_DIR / "overlay_reveal_sequence.html")

@app.get("/api/creator/assets")
async def creator_assets():
    return {"ok": True, **orchestrator.reaction_assets.snapshot()}

@app.post("/api/creator/assets")
async def upload_creator_asset(request: Request):
    mime = (request.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().lower()
    rule = orchestrator.reaction_assets.ALLOWED.get(mime)
    if not rule:
        return _collection_mutation_response(
            {"created": False, "reason": "unsupported_media_type"}, "created"
        )
    limit = rule[2]
    try:
        body = await _read_bounded_body(request, limit)
    except RequestBodyTooLarge:
        return JSONResponse(
            status_code=413,
            content={"ok": False, "created": False, "reason": "asset_too_large", "max_bytes": limit},
        )
    result = orchestrator.reaction_assets.add(
        request.headers.get("X-RareIQ-Filename") or "asset",
        mime,
        body,
    )
    return _collection_mutation_response(result, "created")

@app.get("/api/creator/assets/{asset_id}")
async def creator_asset_file(asset_id: str):
    resolved = orchestrator.reaction_assets.get_path(asset_id)
    if not resolved:
        return JSONResponse(status_code=404, content={"ok": False, "reason": "asset_not_found"})
    path, mime = resolved
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=3600"})

@app.post("/api/creator/assets/map")
async def map_creator_asset(request: ReactionAssetMappingRequest):
    result = orchestrator.reaction_assets.map_tier(request.tier, request.kind, request.asset_id)
    return _collection_mutation_response(result, "updated")

@app.get("/api/soundboard")
async def soundboard_status():
    snapshot = orchestrator.reaction_assets.snapshot()
    return {"ok": True, "pads": snapshot.get("soundboard", []), "assets": snapshot.get("assets", [])}

@app.post("/api/soundboard")
async def configure_soundboard(request: SoundboardConfigRequest):
    result = orchestrator.reaction_assets.configure_soundboard(request.pads)
    return _collection_mutation_response(result, "updated")

@app.get("/api/spotify/status")
async def spotify_status():
    try:
        return {"ok": True, **await spotify.status()}
    except (ValueError, httpx.HTTPError) as exc:
        return JSONResponse(status_code=502, content={"ok": False, "reason": str(exc)})

@app.get("/api/spotify/setup")
async def spotify_setup_status():
    return {"ok": True, **spotify.setup()}

@app.post("/api/spotify/setup")
async def spotify_setup_save(request: SpotifySetupRequest):
    try:
        return {"ok": True, **spotify.configure(request.client_id, request.redirect_uri)}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "reason": str(exc)})

@app.get("/api/spotify/connect")
async def spotify_connect():
    try:
        return RedirectResponse(spotify.begin_auth())
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"ok": False, "reason": str(exc)})

@app.get("/api/spotify/callback")
async def spotify_callback(code: str, state: str):
    try:
        await spotify.finish_auth(code, state)
        return RedirectResponse("/control?spotify=connected")
    except (ValueError, httpx.HTTPError) as exc:
        return HTMLResponse(f"Spotify connection failed: {str(exc)}", status_code=400)

@app.get("/api/spotify/search")
async def spotify_search(q: str):
    try:
        return {"ok": True, "results": await spotify.request("GET", "/search", params={"q": q[:120], "type": "track,playlist", "limit": 20})}
    except (ValueError, httpx.HTTPError) as exc:
        return JSONResponse(status_code=502, content={"ok": False, "reason": str(exc)})

@app.get("/api/spotify/playlists")
async def spotify_playlists():
    try:
        return {"ok": True, "playlists": await spotify.request("GET", "/me/playlists", params={"limit": 50})}
    except (ValueError, httpx.HTTPError) as exc:
        return JSONResponse(status_code=502, content={"ok": False, "reason": str(exc)})

@app.post("/api/spotify/player")
async def spotify_player(request: SpotifyPlaybackRequest):
    action, params = request.action, ({"device_id": request.device_id} if request.device_id else {})
    try:
        if action == "play": await spotify.request("PUT", "/me/player/play", params=params, json={"uris": [request.uri]} if request.uri else None)
        elif action == "pause": await spotify.request("PUT", "/me/player/pause", params=params)
        elif action == "next": await spotify.request("POST", "/me/player/next", params=params)
        elif action == "previous": await spotify.request("POST", "/me/player/previous", params=params)
        elif action == "queue" and request.uri: await spotify.request("POST", "/me/player/queue", params=params | {"uri": request.uri})
        elif action == "seek" and request.position_ms is not None: await spotify.request("PUT", "/me/player/seek", params=params | {"position_ms": request.position_ms})
        elif action == "volume" and request.volume_percent is not None: await spotify.request("PUT", "/me/player/volume", params=params | {"volume_percent": request.volume_percent})
        elif action == "transfer" and request.device_id: await spotify.request("PUT", "/me/player", json={"device_ids": [request.device_id], "play": False})
        elif action == "shuffle" and request.state is not None: await spotify.request("PUT", "/me/player/shuffle", params=params | {"state": str(request.state).lower()})
        elif action == "repeat" and request.repeat_state in {"off", "track", "context"}: await spotify.request("PUT", "/me/player/repeat", params=params | {"state": request.repeat_state})
        else: return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_spotify_action"})
        return {"ok": True}
    except (ValueError, httpx.HTTPError) as exc:
        return JSONResponse(status_code=502, content={"ok": False, "reason": str(exc)})

@app.get("/api/production/switcher")
async def production_switcher_status():
    with PRODUCTION_SWITCHER_LOCK:
        return {"ok": True, **PRODUCTION_SWITCHER_STATE, "slots": orchestrator.camera_manager.camera_slots()}

@app.post("/api/production/switcher/preview")
async def production_switcher_preview(request: ProductionSwitcherRequest):
    with PRODUCTION_SWITCHER_LOCK:
        if request.preview_slot is not None:
            PRODUCTION_SWITCHER_STATE["preview_slot"] = request.preview_slot
        if request.transition in {"cut", "fade", "slide", "zoom"}:
            PRODUCTION_SWITCHER_STATE["transition"] = request.transition
        if request.duration_ms is not None:
            PRODUCTION_SWITCHER_STATE["duration_ms"] = request.duration_ms
        PRODUCTION_SWITCHER_STATE["updated_at"] = time.time()
        return {"ok": True, **PRODUCTION_SWITCHER_STATE}

@app.post("/api/production/switcher/take")
async def production_switcher_take(request: ProductionSwitcherRequest):
    with PRODUCTION_SWITCHER_LOCK:
        previous = int(PRODUCTION_SWITCHER_STATE["program_slot"])
        target = int(request.preview_slot or PRODUCTION_SWITCHER_STATE["preview_slot"])
        transition = request.transition if request.transition in {"cut", "fade", "slide", "zoom"} else PRODUCTION_SWITCHER_STATE["transition"]
        duration = request.duration_ms if request.duration_ms is not None else PRODUCTION_SWITCHER_STATE["duration_ms"]
        PRODUCTION_SWITCHER_STATE.update({"program_slot": target, "preview_slot": previous, "transition": transition, "duration_ms": 0 if transition == "cut" else duration, "generation": int(PRODUCTION_SWITCHER_STATE["generation"]) + 1, "updated_at": time.time()})
        return {"ok": True, **PRODUCTION_SWITCHER_STATE}

@app.get("/api/production/scenes")
async def production_scenes_status():
    with PRODUCTION_SWITCHER_LOCK:
        return {"ok": True, "scenes": list(PRODUCTION_SCENES)}


def _connected_production_camera_count(slots: list[dict[str, Any]]) -> int:
    """Count configured cameras from the slot state that owns each source."""
    return sum(
        1
        for slot in slots
        if slot.get("source_id") and slot.get("connected")
    )


@app.get("/api/production/operator-health")
async def production_operator_health():
    camera = orchestrator.camera_manager.status()
    slots = orchestrator.camera_manager.camera_slots()
    sessions = orchestrator.camera_manager.session_statuses()
    replay = instant_replay.snapshot()
    recognition = orchestrator.recognition_state.snapshot()
    overlay = orchestrator.overlay_state.get()
    connected = _connected_production_camera_count(slots)
    return {
        "ok": True,
        "timestamp": time.time(),
        "program_slot": PRODUCTION_SWITCHER_STATE.get("program_slot", 1),
        "active_scene_id": PRODUCTION_SWITCHER_STATE.get("active_scene_id"),
        "camera": camera,
        "slots": slots,
        "sessions": sessions,
        "connected_cameras": connected,
        "configured_cameras": sum(1 for slot in slots if slot.get("source_id")),
        "recognition_state": recognition.get("state") or recognition.get("status") or "ready",
        "recognition_confidence": recognition.get("confidence") or recognition.get("visual_confidence") or 0,
        "replay_buffered_frames": replay.get("buffered_frames", 0),
        "replay_fps": replay.get("fps", 5),
        "production_screen_visible": bool((overlay.get("production_screen") or {}).get("visible")),
        "graphic_visible": bool((overlay.get("broadcast_graphic") or {}).get("visible")),
    }

@app.get("/api/production/preflight")
async def production_preflight():
    """Return one operator-facing verdict before a show is put on air."""
    sessions = orchestrator.camera_manager.session_statuses()
    slots = orchestrator.camera_manager.camera_slots()
    recognition = orchestrator.recognition_state.snapshot()
    replay = instant_replay.snapshot()
    record_settings = recording.settings()
    record_status = recording.status()
    record_capabilities = recording.capabilities()
    obs_status = await asyncio.to_thread(obs.status)
    connected = _connected_production_camera_count(slots)
    configured = sum(1 for slot in slots if slot.get("source_id"))
    recognition_state = str(recognition.get("state") or recognition.get("status") or "ready").lower()
    replay_seconds = round(float(replay.get("buffered_frames", 0)) / max(1, float(replay.get("fps", 5))), 1)
    checks = []

    def add(check_id: str, label: str, state: str, detail: str, action: str = ""):
        checks.append({"id": check_id, "label": label, "state": state, "detail": detail, "action": action if state != "pass" else ""})

    if connected:
        add("camera", "Camera input", "pass", f"{connected} camera source{'s' if connected != 1 else ''} online")
    elif configured:
        add("camera", "Camera input", "fail", f"0 of {configured} configured cameras online", "Reconnect a camera before starting the show")
    else:
        add("camera", "Camera input", "warn", "No saved camera slots", "Select and connect the show camera")

    add("browser", "Browser outputs", "pass", "6 production-safe browser sources are available")
    add("scenes", "RareIQ scenes", "pass" if PRODUCTION_SCENES else "fail", f"{len(PRODUCTION_SCENES)} production scenes configured", "Create at least one production scene")
    add("recognition", "Recognition engine", "fail" if "error" in recognition_state or "fail" in recognition_state else "pass", recognition_state.replace("_", " ").title(), "Open Recognition diagnostics and clear the error")
    add("replay", "Instant replay", "pass" if replay_seconds >= 3 else "warn", f"{replay_seconds:g}s buffered", "Allow the rolling buffer to reach 3 seconds")

    if record_status.get("last_error"):
        add("recording", "Local recording", "fail", str(record_status["last_error"]), "Run the recording test and correct the encoder settings")
    elif record_settings.get("configured"):
        enough_disk = int(record_status.get("free_bytes", 0)) >= int(record_status.get("minimum_free_bytes", 0))
        add("recording", "Local recording", "pass" if enough_disk else "fail", "Encoder configured" if enough_disk else "Recording disk space is below the configured minimum", "Free disk space or choose another output folder")
    else:
        ffmpeg_ready = bool((record_capabilities.get("ffmpeg") or {}).get("installed"))
        add("recording", "Local recording", "warn", "Encoder not configured" + (" (FFmpeg available)" if ffmpeg_ready else ""), "Configure recording or use OBS recording")

    if obs_status.get("enabled"):
        diagnostic = obs_status.get("diagnostic") or {}
        add("obs", "OBS connection", "pass" if obs_status.get("connected") else "fail", "Authenticated and ready" if obs_status.get("connected") else diagnostic.get("message", "OBS is unavailable"), diagnostic.get("action", "Check OBS WebSocket settings"))
    else:
        add("obs", "OBS connection", "warn", "Optional integration is disabled", "Enable OBS only when this show uses it")

    blockers = [check for check in checks if check["state"] == "fail"]
    warnings = [check for check in checks if check["state"] == "warn"]
    return {"ok": True, "preflight": {"ready": not blockers, "blockers": blockers, "warnings": warnings, "checks": checks, "checked_at": time.time()}}

@app.get("/api/production/session")
async def production_session_status():
    with PRODUCTION_SESSION_LOCK:
        PRODUCTION_SESSION["recording"] = recording.status()
        return {"ok": True, "session": dict(PRODUCTION_SESSION), "duration_seconds": max(0, (time.time() if PRODUCTION_SESSION["active"] else PRODUCTION_SESSION.get("ended_at", 0)) - PRODUCTION_SESSION.get("started_at", 0)) if PRODUCTION_SESSION.get("started_at") else 0}

@app.get("/api/production/recording/settings")
async def recording_settings():
    return {"ok": True, "settings": recording.settings(), "status": recording.status(), "capabilities": recording.capabilities(), "browser_sources": {"program": "/program", "graphics": "/overlay/graphics", "production_screen": "/production-screen", "replay": "/replay", "rare_intelligence": "/overlay/pokedex", "multi_card": "/overlay/multi-card"}}

@app.post("/api/production/recording/settings")
async def update_recording_settings(request: RecordingSettingsRequest):
    result = recording.configure(**request.model_dump())
    return ({"ok": True, "settings": result} if result.get("updated") else JSONResponse(status_code=409, content={"ok": False, **result}))

@app.post("/api/production/recording/test")
async def test_recording_settings():
    test_id = f"test-{uuid.uuid4().hex[:8]}"
    started = recording.start(test_id)
    if not started.get("started"): return JSONResponse(status_code=409, content={"ok": False, **started})
    await asyncio.sleep(2)
    stopped = await asyncio.to_thread(recording.stop)
    return {"ok": bool(stopped.get("verified")), "test": stopped}

@app.get("/api/production/obs")
async def obs_status():
    return {"ok": True, "obs": await asyncio.to_thread(obs.status)}

@app.get("/api/production/destinations")
async def production_destinations():
    """Report platform capabilities without inferring unverified live states."""
    current_obs = await asyncio.to_thread(obs.status)
    return {
        "ok": True,
        **broadcast_destinations.snapshot(obs_status=current_obs),
    }

@app.post("/api/production/obs/settings")
async def update_obs_settings(request: ObsSettingsRequest):
    settings = await asyncio.to_thread(obs.configure, request.model_dump())
    return {"ok": True, "settings": settings, "obs": await asyncio.to_thread(obs.status)}

@app.post("/api/production/obs/command")
async def obs_command(request: ObsCommandRequest):
    if request.action not in {"start-stream", "stop-stream", "start-record", "stop-record", "set-scene"}:
        return JSONResponse(status_code=400, content={"ok": False, "reason": "unsupported_obs_action"})
    try: return {"ok": True, "obs": await asyncio.to_thread(obs.command, request.action, request.scene)}
    except (RuntimeError, ValueError, OSError) as exc: return JSONResponse(status_code=409, content={"ok": False, "reason": str(exc)})

@app.post("/api/production/obs/bootstrap")
async def bootstrap_obs(request: ObsBootstrapRequest):
    if not request.base_url.startswith(("http://", "https://")):
        return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_base_url"})
    try: return {"ok": True, "bootstrap": await asyncio.to_thread(obs.bootstrap, request.base_url, dry_run=request.dry_run)}
    except (RuntimeError, ValueError, OSError) as exc: return JSONResponse(status_code=409, content={"ok": False, "reason": str(exc)})

@app.post("/api/production/session/start")
async def start_production_session(request: ProductionSessionMetadataRequest):
    with PRODUCTION_SESSION_LOCK:
        if PRODUCTION_SESSION["active"]: return {"ok": True, "session": dict(PRODUCTION_SESSION), "already_active": True}
        PRODUCTION_SESSION.update({"active": True, "session_id": uuid.uuid4().hex, "started_at": time.time(), "ended_at": 0.0, "events": [], "metadata": request.model_dump()})
        PRODUCTION_SESSION["recording"] = recording.start(PRODUCTION_SESSION["session_id"])
        _production_event("session", "Production session started", "Encoder recording active" if PRODUCTION_SESSION["recording"].get("active") else f'Event logging active; recording {PRODUCTION_SESSION["recording"].get("reason", "not configured")}')
        return {"ok": True, "session": dict(PRODUCTION_SESSION)}

@app.post("/api/production/show/start")
async def start_production_show(request: StartShowRequest):
    """Run the guarded, operator-initiated show startup sequence."""
    preflight_payload = await production_preflight()
    preflight = preflight_payload["preflight"]
    if not preflight["ready"]:
        return JSONResponse(status_code=409, content={"ok": False, "reason": "preflight_blocked", "preflight": preflight, "steps": []})

    steps: list[dict[str, Any]] = []
    safe_state = await production_safe_recovery()
    steps.append({"id": "safe", "state": "pass", "detail": "Main Card selected; overlays, replay, and reveal automation reset"})
    metadata = ProductionSessionMetadataRequest(**request.model_dump(exclude={"start_obs_stream", "start_obs_recording"}))
    session_payload = await start_production_session(metadata)
    steps.append({"id": "session", "state": "pass", "detail": "Production event logging started"})
    recording_state = session_payload["session"].get("recording") or {}
    steps.append({"id": "recording", "state": "pass" if recording_state.get("active") else "skip", "detail": "Local recording started" if recording_state.get("active") else "Local recording not configured; session logging remains active"})

    obs_state = await asyncio.to_thread(obs.status)
    if request.start_obs_stream or request.start_obs_recording:
        if not obs_state.get("connected"):
            steps.append({"id": "obs", "state": "warn", "detail": "OBS actions skipped because OBS is not connected"})
        else:
            if request.start_obs_stream:
                obs_state = await asyncio.to_thread(obs.command, "start-stream", None)
                steps.append({"id": "obs-stream", "state": "pass", "detail": "OBS stream output started"})
            if request.start_obs_recording:
                obs_state = await asyncio.to_thread(obs.command, "start-record", None)
                steps.append({"id": "obs-record", "state": "pass", "detail": "OBS recording started"})
    else:
        steps.append({"id": "obs", "state": "skip", "detail": "OBS stream and recording were not requested"})

    with PRODUCTION_SESSION_LOCK:
        _production_event("show-start", "Show startup sequence complete", " · ".join(step["detail"] for step in steps))
        _save_production_session()
        session = dict(PRODUCTION_SESSION)
    return {"ok": True, "started": True, "preflight": preflight, "steps": steps, "safe": safe_state, "session": session, "obs": obs_state}

@app.post("/api/production/session/metadata")
async def update_production_session_metadata(request: ProductionSessionMetadataRequest):
    with PRODUCTION_SESSION_LOCK:
        PRODUCTION_SESSION["metadata"] = request.model_dump()
        _save_production_session()
        return {"ok": True, "session": dict(PRODUCTION_SESSION)}

@app.post("/api/production/session/stop")
async def stop_production_session():
    with PRODUCTION_SESSION_LOCK:
        if PRODUCTION_SESSION["active"]: _production_event("session", "Production session stopped")
        PRODUCTION_SESSION["recording"] = recording.stop()
        if PRODUCTION_SESSION["recording"].get("output_path"):
            _production_event("recording", "Recording finalized" if PRODUCTION_SESSION["recording"].get("verified") else "Recording output not verified", str(PRODUCTION_SESSION["recording"].get("output_path")))
        PRODUCTION_SESSION.update({"active": False, "ended_at": time.time()})
        _save_production_session()
        _archive_current_production_session()
        return {"ok": True, "session": dict(PRODUCTION_SESSION)}

@app.post("/api/production/show/stop")
async def stop_production_show():
    """Safely take the show off air and finalize every owned output."""
    steps: list[dict[str, Any]] = []
    safe_state = await production_safe_recovery()
    steps.append({"id": "safe", "state": "pass", "detail": "Main Card restored and takeover layers cleared"})

    obs_state = await asyncio.to_thread(obs.status)
    if obs_state.get("connected"):
        if obs_state.get("recording"):
            obs_state = await asyncio.to_thread(obs.command, "stop-record", None)
            steps.append({"id": "obs-record", "state": "pass", "detail": "OBS recording stopped"})
        else:
            steps.append({"id": "obs-record", "state": "skip", "detail": "OBS recording was already stopped"})
        if obs_state.get("streaming"):
            obs_state = await asyncio.to_thread(obs.command, "stop-stream", None)
            steps.append({"id": "obs-stream", "state": "pass", "detail": "OBS stream stopped"})
        else:
            steps.append({"id": "obs-stream", "state": "skip", "detail": "OBS stream was already stopped"})
    else:
        steps.append({"id": "obs", "state": "skip", "detail": "OBS was not connected"})

    session_was_active = bool(PRODUCTION_SESSION.get("active"))
    session_payload = await stop_production_session()
    recording_state = session_payload["session"].get("recording") or {}
    steps.append({"id": "recording", "state": "pass" if recording_state.get("verified") else "skip", "detail": "Local recording finalized and verified" if recording_state.get("verified") else "No verified local recording required"})
    steps.append({"id": "session", "state": "pass" if session_was_active else "skip", "detail": "Production session archived" if session_was_active else "Production session was already stopped"})
    return {"ok": True, "stopped": True, "steps": steps, "safe": safe_state, "session": session_payload["session"], "obs": obs_state}

@app.post("/api/production/session/events")
async def add_production_session_event(request: ProductionEventRequest):
    with PRODUCTION_SESSION_LOCK:
        return {"ok": True, "event": _production_event(request.kind, request.title, request.detail), "session": dict(PRODUCTION_SESSION)}

@app.get("/api/production/session/report")
async def production_session_report():
    with PRODUCTION_SESSION_LOCK:
        payload = {"schema": "rareiq-production-report-v1", "generated_at": time.time(), "session": dict(PRODUCTION_SESSION), "recording": recording.status(), "switcher": dict(PRODUCTION_SWITCHER_STATE), "camera_slots": orchestrator.camera_manager.camera_slots()}
    return Response(json.dumps(payload, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="rareiq-production-{PRODUCTION_SESSION.get("session_id") or "report"}.json"'})

@app.get("/production/session/report")
async def production_session_print_report():
    economics = _pack_economics_payload()
    history = list(orchestrator.reveal_sequence.snapshot().get("history") or [])
    with PRODUCTION_SESSION_LOCK:
        session = dict(PRODUCTION_SESSION); events = list(session.get("events") or [])
    started = float(session.get("started_at") or 0); ended = time.time() if session.get("active") else float(session.get("ended_at") or started)
    valued = []
    for card in history:
        try: value = float(card.get("market_value") or 0)
        except (TypeError, ValueError): value = 0
        if value > 0: valued.append(dict(card) | {"market_value": value})
    valued.sort(key=lambda card: -float(card["market_value"])); currency = str((economics.get("settings") or {}).get("currency") or "USD")
    money = lambda value: f'{html.escape(currency)} {float(value or 0):,.2f}'
    seconds = max(0, int((ended-started) if started else 0)); elapsed = f"{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}"
    top_rows = "".join(f'<tr><td>{html.escape(str(card.get("card_name") or "Unknown card"))}</td><td>{html.escape(str(card.get("set_name") or "Unknown set"))}</td><td>{html.escape(str(card.get("card_number") or "—"))}</td><td>{money(card["market_value"])}</td></tr>' for card in valued[:10]) or '<tr><td colspan="4">No cards with verified market pricing.</td></tr>'
    pack_rows = "".join(f'<tr><td>Pack {int(pack["pack_number"])}</td><td>{int(pack["cards"])}</td><td>{money(pack["cost"])}</td><td>{money(pack["verified_return"])}</td><td>{money(pack["verified_margin"])}</td><td>{int(pack["unresolved_cards"])}</td></tr>' for pack in economics.get("packs") or []) or '<tr><td colspan="6">No pack history recorded.</td></tr>'
    incident_rows = "".join(f'<li><b>{html.escape(str(event.get("title") or "Event"))}</b><span>{html.escape(str(event.get("detail") or ""))}</span></li>' for event in events if event.get("kind") in {"incident", "safety"}) or '<li>No incidents recorded.</li>'
    status = "Minimum verified return — unpriced cards excluded" if economics["unresolved_cards"] else "Complete verified valuation"
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RareIQ Break Report</title><style>:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#06111a;color:#eaf7ff;font:14px Inter,Segoe UI,sans-serif}}main{{max-width:1100px;margin:auto;padding:42px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;border-bottom:2px solid #42d5f5;padding-bottom:22px}}h1{{font-size:38px;margin:4px 0}}h2{{font-size:19px;margin:0 0 14px}}.eyebrow,.label{{color:#58daf5;text-transform:uppercase;letter-spacing:.14em;font-size:11px}}.actions{{display:flex;gap:8px}}button,a{{border:1px solid #25516a;border-radius:9px;padding:10px 14px;background:#102b3c;color:#eaf7ff;text-decoration:none;cursor:pointer}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}.metric,section{{border:1px solid #18384a;border-radius:16px;background:#091b27;padding:18px}}.metric strong{{display:block;font-size:24px;margin-top:8px}}.warning{{color:#ffd06a}}.positive{{color:#62e8b3}}.negative{{color:#ff8c9c}}section{{margin:16px 0}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:11px;border-bottom:1px solid #18384a}}th{{color:#809cab;font-size:10px;letter-spacing:.1em}}ul{{padding:0;list-style:none}}li{{display:grid;gap:4px;padding:10px 0;border-bottom:1px solid #18384a}}li span,footer{{color:#8da5b3}}footer{{margin-top:24px;font-size:11px}}@media(max-width:760px){{main{{padding:18px}}header{{align-items:start;flex-direction:column}}.metrics{{grid-template-columns:repeat(2,1fr)}}.table-wrap{{overflow:auto}}}}@media print{{:root{{color-scheme:light}}body{{background:#fff;color:#12212b}}main{{padding:20px;max-width:none}}.actions{{display:none}}.metric,section{{background:#fff;border-color:#cddbe3;break-inside:avoid}}th,td,li{{border-color:#dbe5ea}}footer,li span{{color:#536772}}}}</style></head><body><main><header><div><div class="eyebrow">RareIQ Production Intelligence</div><h1>Break Report</h1><span>Session {html.escape(str(session.get("session_id") or "not started"))}</span></div><div class="actions"><a href="/api/production/session/report">JSON data</a><button onclick="window.print()">Print / Save PDF</button></div></header><div class="metrics"><article class="metric"><span class="label">Duration</span><strong>{elapsed}</strong></article><article class="metric"><span class="label">Opened Packs</span><strong>{economics["opened_packs"]}</strong></article><article class="metric"><span class="label">Cards Revealed</span><strong>{len(history)}</strong></article><article class="metric"><span class="label">Production Events</span><strong>{len(events)}</strong></article><article class="metric"><span class="label">Total Cost</span><strong>{money(economics["total_cost"])}</strong></article><article class="metric"><span class="label">Verified Return</span><strong>{money(economics["verified_return"])}</strong></article><article class="metric"><span class="label">Break Even</span><strong>{economics["break_even_percent"]}%</strong></article><article class="metric"><span class="label">Verified Margin</span><strong class="{'positive' if economics['verified_margin'] >= 0 else 'negative'}">{money(economics["verified_margin"])}</strong></article></div><section><h2>Pack Economics</h2><p class="{'warning' if economics['unresolved_cards'] else 'positive'}">{status}. {economics['unresolved_cards']} card(s) remain unpriced.</p><div class="table-wrap"><table><thead><tr><th>Pack</th><th>Cards</th><th>Cost</th><th>Verified Return</th><th>Margin</th><th>Unpriced</th></tr></thead><tbody>{pack_rows}</tbody></table></div></section><section><h2>Strongest Verified Pulls</h2><div class="table-wrap"><table><thead><tr><th>Card</th><th>Set</th><th>Number</th><th>Verified Value</th></tr></thead><tbody>{top_rows}</tbody></table></div></section><section><h2>Operator Incidents</h2><ul>{incident_rows}</ul></section><footer>Values reflect available verified pricing at report generation time. Missing prices are excluded, never treated as zero. All-time inventory sales are intentionally excluded from this break’s margin.</footer></main></body></html>'''
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})

@app.get("/api/production/session/analytics")
async def production_session_analytics():
    with PRODUCTION_SESSION_LOCK:
        events = list(PRODUCTION_SESSION.get("events") or [])
        started = float(PRODUCTION_SESSION.get("started_at") or 0)
        ended = time.time() if PRODUCTION_SESSION.get("active") else float(PRODUCTION_SESSION.get("ended_at") or started)
    counts: dict[str, int] = {}
    camera_usage: dict[str, int] = {}
    scene_usage: dict[str, int] = {}
    incidents: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "other"); counts[kind] = counts.get(kind, 0) + 1
        title = str(event.get("title") or "")
        if kind == "camera": camera_usage[title] = camera_usage.get(title, 0) + 1
        if kind == "scene": scene_usage[title.removeprefix("Scene: ")] = scene_usage.get(title.removeprefix("Scene: "), 0) + 1
        if kind in {"incident", "safety"}: incidents.append(event)
    cue_times = [float(event.get("timestamp") or 0) for event in events if event.get("kind") in {"scene", "camera", "graphic", "replay", "screen"}]
    intervals = [b - a for a, b in zip(cue_times, cue_times[1:]) if b >= a]
    return {"ok": True, "analytics": {"duration_seconds": max(0, ended - started) if started else 0, "total_events": len(events), "counts": counts, "camera_usage": camera_usage, "scene_usage": scene_usage, "incidents": incidents, "average_cue_interval_seconds": round(sum(intervals) / len(intervals), 1) if intervals else 0, "recording_verified": bool((PRODUCTION_SESSION.get("recording") or {}).get("verified")), "started_at": started, "ended_at": ended}}

@app.get("/api/production/session/card-analytics")
async def production_card_analytics():
    reveal = orchestrator.reveal_sequence.snapshot()
    history = list(reveal.get("history") or [])
    inventory = orchestrator.inventory.dashboard()
    collection = orchestrator.collection.dashboard(orchestrator.catalog_intelligence.collection_reference_cards())
    tier_counts: dict[str, int] = {}
    rarity_counts: dict[str, int] = {}
    verified_values: list[dict[str, Any]] = []
    for card in history:
        tier = str(card.get("hit_tier") or "standard"); tier_counts[tier] = tier_counts.get(tier, 0) + 1
        rarity = str(card.get("rarity") or "Unknown"); rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
        try: value = float(card.get("market_value") or 0)
        except (TypeError, ValueError): value = 0
        if value > 0: verified_values.append(dict(card) | {"market_value": value})
    verified_values.sort(key=lambda item: -float(item["market_value"]))
    verified_times = sorted(float(card.get("verified_at") or 0) for card in history if float(card.get("verified_at") or 0) > 0)
    scan_intervals = [b - a for a, b in zip(verified_times, verified_times[1:]) if b >= a]
    valuation = collection.get("valuation") or {}
    return {"ok": True, "analytics": {"cards_revealed": len(history), "tier_counts": tier_counts, "rarity_counts": rarity_counts, "verified_value_total": round(sum(float(card["market_value"]) for card in verified_values), 2), "valued_cards": len(verified_values), "unvalued_cards": len(history) - len(verified_values), "top_pulls": verified_values[:5], "average_seconds_between_cards": round(sum(scan_intervals) / len(scan_intervals), 1) if scan_intervals else 0, "inventory_added": int(inventory.get("in_stock") or 0), "inventory_sold": int(inventory.get("sold_count") or 0), "collection_copies": int((collection.get("summary") or {}).get("total_copies") or 0), "portfolio_value": valuation.get("portfolio_value"), "portfolio_pricing_coverage": valuation.get("pricing_coverage_percent")}}

@app.get("/api/production/session/pack-tracker")
async def production_pack_tracker():
    reveal = orchestrator.reveal_sequence.snapshot(); history = list(reveal.get("history") or [])
    grouped: dict[int, list[dict[str, Any]]] = {}
    for card in history: grouped.setdefault(int(card.get("pack_number") or 1), []).append(card)
    packs = []
    for number, cards in sorted(grouped.items()):
        hits = [card for card in cards if str(card.get("hit_tier") or "standard") in {"low", "medium", "grail"}]
        valued = []
        for card in cards:
            try: value = float(card.get("market_value") or 0)
            except (TypeError, ValueError): value = 0
            if value > 0: valued.append(dict(card) | {"market_value": value})
        strongest = max(valued, key=lambda card: float(card["market_value"]), default=(hits[0] if hits else (cards[0] if cards else None)))
        packs.append({"pack_number": number, "cards": len(cards), "hits": len(hits), "hit_rate": round(len(hits) / len(cards) * 100, 1) if cards else 0, "verified_value": round(sum(float(card["market_value"]) for card in valued), 2), "valued_cards": len(valued), "unvalued_cards": len(cards)-len(valued), "strongest_pull": strongest})
    current_number = int(reveal.get("pack_number") or 1); current = next((pack for pack in packs if pack["pack_number"] == current_number), {"pack_number": current_number, "cards": int(reveal.get("position") or 0), "hits": 0, "hit_rate": 0, "verified_value": 0, "valued_cards": 0, "unvalued_cards": int(reveal.get("position") or 0), "strongest_pull": None})
    return {"ok": True, "tracker": {"current_pack": current, "expected_cards": int(reveal.get("expected_cards") or 6), "rare_slot": int(reveal.get("rare_slot") or 6), "position": int(reveal.get("position") or 0), "packs": sorted(packs, key=lambda pack: pack["pack_number"], reverse=True), "best_pack": max(packs, key=lambda pack: float(pack["verified_value"]), default=None), "total_packs": len(packs)}}

def _pack_economics_payload() -> dict[str, Any]:
    history = list(orchestrator.reveal_sequence.snapshot().get("history") or [])
    with PRODUCTION_SESSION_LOCK:
        settings = {"pack_cost": 0.0, "box_cost": 0.0, "packs_per_box": 1, "currency": "USD"} | dict(PRODUCTION_SESSION.get("pack_economics") or {})
    grouped: dict[int, list[dict[str, Any]]] = {}
    for card in history: grouped.setdefault(int(card.get("pack_number") or 1), []).append(card)
    effective_cost = float(settings["pack_cost"] or 0) or (float(settings["box_cost"] or 0) / max(1, int(settings["packs_per_box"] or 1)))
    packs: list[dict[str, Any]] = []
    for number, cards in sorted(grouped.items()):
        values: list[float] = []
        for card in cards:
            try: value = float(card.get("market_value") or 0)
            except (TypeError, ValueError): value = 0
            if value > 0: values.append(value)
        verified = round(sum(values), 2)
        packs.append({"pack_number": number, "cards": len(cards), "verified_return": verified, "unresolved_cards": len(cards)-len(values), "cost": round(effective_cost, 2), "verified_margin": round(verified-effective_cost, 2)})
    total_cost = round(effective_cost * len(packs), 2); verified_return = round(sum(pack["verified_return"] for pack in packs), 2)
    unresolved = sum(pack["unresolved_cards"] for pack in packs)
    inventory = orchestrator.inventory.dashboard()
    return {"settings": settings, "opened_packs": len(packs), "effective_pack_cost": round(effective_cost, 2), "total_cost": total_cost, "verified_return": verified_return, "verified_margin": round(verified_return-total_cost, 2), "break_even_percent": round(verified_return/total_cost*100, 1) if total_cost else 0, "unresolved_cards": unresolved, "valuation_status": "minimum_verified" if unresolved else "complete_verified", "inventory_realized_all_time": round(float(inventory.get("gross_sales") or 0), 2), "inventory_profit_all_time": round(float(inventory.get("net_profit") or 0), 2), "packs": sorted(packs, key=lambda pack: pack["pack_number"], reverse=True)}

@app.get("/api/production/session/pack-economics")
async def production_pack_economics():
    return {"ok": True, "economics": _pack_economics_payload()}

@app.post("/api/production/session/pack-economics")
async def save_production_pack_economics(request: PackEconomicsRequest):
    settings = request.model_dump(); settings["currency"] = settings["currency"].upper()
    with PRODUCTION_SESSION_LOCK:
        PRODUCTION_SESSION["pack_economics"] = settings
        _save_production_session()
    return {"ok": True, "economics": _pack_economics_payload()}

def _archive_current_production_session() -> dict[str, Any] | None:
    session_id = str(PRODUCTION_SESSION.get("session_id") or "")
    if not session_id: return None
    economics = _pack_economics_payload(); reveal = orchestrator.reveal_sequence.snapshot(); cards = list(reveal.get("history") or [])
    verified_times = sorted(float(card.get("verified_at") or 0) for card in cards if float(card.get("verified_at") or 0) > 0)
    intervals = [b-a for a,b in zip(verified_times, verified_times[1:]) if b >= a]
    strongest = None
    for card in cards:
        try: value = float(card.get("market_value") or 0)
        except (TypeError, ValueError): value = 0
        if value > 0 and (not strongest or value > strongest["market_value"]): strongest = {"card_name": str(card.get("card_name") or "Unknown card"), "set_name": str(card.get("set_name") or "Unknown set"), "card_number": str(card.get("card_number") or ""), "market_value": value, "reference_image_url": str(card.get("reference_image_url") or "")}
    started = float(PRODUCTION_SESSION.get("started_at") or 0); ended = float(PRODUCTION_SESSION.get("ended_at") or started); metadata = dict(PRODUCTION_SESSION.get("metadata") or {})
    snapshot = {"session_id": session_id, "started_at": started, "ended_at": ended, "duration_seconds": max(0, ended-started), "cards_revealed": len(cards), "average_seconds_between_cards": round(sum(intervals)/len(intervals), 1) if intervals else 0, "event_count": len(PRODUCTION_SESSION.get("events") or []), "recording_verified": bool((PRODUCTION_SESSION.get("recording") or {}).get("verified")), "economics": economics, "strongest_pull": strongest}
    snapshot["metadata"] = metadata
    history = _load_production_history(); index = next((i for i,item in enumerate(history) if item.get("session_id") == session_id), -1)
    if index >= 0: history[index] = snapshot
    else: history.append(snapshot)
    _save_production_history(history)
    return snapshot

@app.get("/api/production/session/history")
async def production_session_history():
    history = list(reversed(_load_production_history()))
    completed = [item for item in history if item.get("ended_at")]
    return {"ok": True, "history": completed, "summary": {"completed_sessions": len(completed), "opened_packs": sum(int((item.get("economics") or {}).get("opened_packs") or 0) for item in completed), "cards_revealed": sum(int(item.get("cards_revealed") or 0) for item in completed), "total_cost": round(sum(float((item.get("economics") or {}).get("total_cost") or 0) for item in completed), 2), "verified_return": round(sum(float((item.get("economics") or {}).get("verified_return") or 0) for item in completed), 2), "verified_margin": round(sum(float((item.get("economics") or {}).get("verified_margin") or 0) for item in completed), 2), "unresolved_cards": sum(int((item.get("economics") or {}).get("unresolved_cards") or 0) for item in completed)}}

@app.get("/api/production/session/history/{session_id}")
async def production_session_history_detail(session_id: str):
    snapshot = next((item for item in _load_production_history() if str(item.get("session_id")) == session_id), None)
    if not snapshot: return JSONResponse(status_code=404, content={"ok": False, "reason": "archived_session_not_found"})
    return {"ok": True, "snapshot": snapshot}

@app.get("/production/session/history/{session_id}/report")
async def archived_production_session_report(session_id: str):
    snapshot = next((item for item in _load_production_history() if str(item.get("session_id")) == session_id), None)
    if not snapshot: return HTMLResponse("<h1>Archived session not found</h1>", status_code=404)
    economics = dict(snapshot.get("economics") or {}); pull = snapshot.get("strongest_pull") or {}; currency = html.escape(str((economics.get("settings") or {}).get("currency") or "USD")); money = lambda value: f'{currency} {float(value or 0):,.2f}'
    ended = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(snapshot.get("ended_at") or 0))); unresolved = int(economics.get("unresolved_cards") or 0); margin = float(economics.get("verified_margin") or 0)
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Archived RareIQ Break</title><style>:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#06111a;color:#eaf7ff;font:14px Inter,Segoe UI,sans-serif}}main{{max-width:900px;margin:auto;padding:42px}}header{{border-bottom:2px solid #42d5f5;padding-bottom:20px}}h1{{font-size:38px;margin:5px 0}}.eyebrow,label{{color:#55d9f4;text-transform:uppercase;letter-spacing:.13em;font-size:11px}}.actions{{position:absolute;right:42px;top:42px}}button{{padding:10px 14px;border:1px solid #28546b;border-radius:9px;background:#102b3c;color:#fff}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}}article,section{{padding:18px;border:1px solid #19394a;border-radius:15px;background:#091b27}}article strong{{display:block;font-size:25px;margin-top:8px}}section{{margin-top:15px}}.warning{{color:#ffd06a}}.positive{{color:#62e8b3}}.negative{{color:#ff8c9c}}p{{color:#91a8b5}}@media(max-width:650px){{main{{padding:18px}}.actions{{position:static;margin-bottom:16px}}.grid{{grid-template-columns:repeat(2,1fr)}}}}@media print{{:root{{color-scheme:light}}body{{background:#fff;color:#12212b}}main{{padding:10px}}.actions{{display:none}}article,section{{background:#fff;border-color:#d4e1e7}}}}</style></head><body><main><div class="actions"><button onclick="window.print()">Print / Save PDF</button></div><header><div class="eyebrow">Frozen Historical Snapshot</div><h1>RareIQ Break Report</h1><span>{html.escape(ended)} · {html.escape(session_id)}</span></header><div class="grid"><article><label>Cards</label><strong>{int(snapshot.get("cards_revealed") or 0)}</strong></article><article><label>Packs</label><strong>{int(economics.get("opened_packs") or 0)}</strong></article><article><label>Duration</label><strong>{int(float(snapshot.get("duration_seconds") or 0)//60)}m</strong></article><article><label>Cost</label><strong>{money(economics.get("total_cost"))}</strong></article><article><label>Verified Return</label><strong>{money(economics.get("verified_return"))}</strong></article><article><label>Verified Margin</label><strong class="{'positive' if margin >= 0 else 'negative'}">{money(margin)}</strong></article></div><section><h2>Valuation Status</h2><p class="{'warning' if unresolved else 'positive'}">{'Minimum verified value' if unresolved else 'Complete verified valuation'} · {unresolved} unpriced card(s)</p></section><section><h2>Strongest Verified Pull</h2><h3>{html.escape(str(pull.get("card_name") or "No verified pull"))}</h3><p>{html.escape(str(pull.get("set_name") or ""))} {html.escape(str(pull.get("card_number") or ""))} · {money(pull.get("market_value")) if pull else 'Value unavailable'}</p></section><footer><p>This report is generated from a frozen end-of-session snapshot. It does not recalculate against current live scans or inventory.</p></footer></main></body></html>'''
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})

@app.post("/api/production/safe")
async def production_safe_recovery():
    with PRODUCTION_SWITCHER_LOCK:
        previous = int(PRODUCTION_SWITCHER_STATE.get("program_slot", 1))
        PRODUCTION_SWITCHER_STATE.update({"program_slot": 1, "preview_slot": previous if previous != 1 else 2, "transition": "cut", "duration_ms": 0, "generation": int(PRODUCTION_SWITCHER_STATE.get("generation", 0)) + 1, "updated_at": time.time(), "active_scene_id": "main-card"})
    overlay = orchestrator.overlay_state.get()
    screen = dict(overlay.get("production_screen") or {}) | {"visible": False, "generation": int((overlay.get("production_screen") or {}).get("generation", 0)) + 1}
    graphic = dict(overlay.get("broadcast_graphic") or {}) | {"visible": False, "preview": False, "generation": int((overlay.get("broadcast_graphic") or {}).get("generation", 0)) + 1}
    orchestrator.overlay_state.update({"production_screen": screen, "broadcast_graphic": graphic, "pokedex_on_air": False, "reaction": None})
    multi_card = orchestrator.multi_card_recognition.select_slots([])
    reveal = orchestrator.reveal_sequence.cancel_animation()
    instant_replay.stop_playback()
    response = {"ok": True, "safe": True, "screen": screen, "graphic": graphic, "multi_card": multi_card, "reveal": reveal, **PRODUCTION_SWITCHER_STATE}
    try:
        response["obs"] = await asyncio.to_thread(obs.sync_scene, "main-card")
    except (RuntimeError, ValueError, OSError) as exc:
        # Local recovery must always succeed even when the external switcher is
        # unavailable; the operator receives an explicit partial-state warning.
        response["obs_warning"] = str(exc)
    return response

@app.post("/api/production/scenes")
async def save_production_scene(request: ProductionSceneRequest):
    if request.transition not in {"cut", "fade", "slide", "zoom"} or request.spotify_action not in {"keep", "play", "pause"} or request.soundboard_action not in {"keep", "stop"} or request.screen_action not in {"keep", "show", "hide"} or request.screen_mode not in {"starting-soon", "brb", "ending", "countdown"} or request.screen_accent not in {"cyan", "purple", "gold", "green", "red"}:
        return JSONResponse(status_code=400, content={"ok": False, "reason": "invalid_scene_configuration"})
    scene = request.model_dump()
    scene["id"] = str(request.id or f"scene-{uuid.uuid4().hex[:10]}")[:60]
    with PRODUCTION_SWITCHER_LOCK:
        index = next((i for i, item in enumerate(PRODUCTION_SCENES) if item.get("id") == scene["id"]), -1)
        if index >= 0: PRODUCTION_SCENES[index] = scene
        elif len(PRODUCTION_SCENES) < 20: PRODUCTION_SCENES.append(scene)
        else: return JSONResponse(status_code=409, content={"ok": False, "reason": "scene_limit_reached"})
        _save_production_scenes(PRODUCTION_SCENES)
        return {"ok": True, "scene": scene, "scenes": list(PRODUCTION_SCENES)}

@app.delete("/api/production/scenes/{scene_id}")
async def delete_production_scene(scene_id: str):
    with PRODUCTION_SWITCHER_LOCK:
        before = len(PRODUCTION_SCENES)
        PRODUCTION_SCENES[:] = [scene for scene in PRODUCTION_SCENES if scene.get("id") != scene_id]
        if len(PRODUCTION_SCENES) == before: return JSONResponse(status_code=404, content={"ok": False, "reason": "scene_not_found"})
        _save_production_scenes(PRODUCTION_SCENES)
        return {"ok": True, "scenes": list(PRODUCTION_SCENES)}

@app.post("/api/production/scenes/{scene_id}/take")
async def take_production_scene(scene_id: str):
    with PRODUCTION_SWITCHER_LOCK:
        scene = next((item for item in PRODUCTION_SCENES if item.get("id") == scene_id), None)
        if not scene: return JSONResponse(status_code=404, content={"ok": False, "reason": "scene_not_found"})
        previous = int(PRODUCTION_SWITCHER_STATE["program_slot"])
        transition = str(scene.get("transition") or "fade")
        PRODUCTION_SWITCHER_STATE.update({"program_slot": int(scene["program_slot"]), "preview_slot": previous, "transition": transition, "duration_ms": 0 if transition == "cut" else int(scene.get("duration_ms") or 500), "generation": int(PRODUCTION_SWITCHER_STATE["generation"]) + 1, "updated_at": time.time(), "active_scene_id": scene_id})
        screen_action = str(scene.get("screen_action") or "keep")
        screen = dict(orchestrator.overlay_state.get().get("production_screen") or {})
        if screen_action == "show":
            screen.update({"visible": True, "mode": scene.get("screen_mode") or "starting-soon", "title": scene.get("screen_title") or "Starting Soon", "message": scene.get("screen_message") or "", "countdown_seconds": int(scene.get("screen_countdown_seconds") or 0), "accent": scene.get("screen_accent") or "cyan", "started_at": time.time(), "generation": int(screen.get("generation", 0)) + 1})
            orchestrator.overlay_state.update({"production_screen": screen})
        elif screen_action == "hide":
            screen.update({"visible": False, "generation": int(screen.get("generation", 0)) + 1})
            orchestrator.overlay_state.update({"production_screen": screen})
        response = {"ok": True, "scene": scene, "screen": screen, **PRODUCTION_SWITCHER_STATE}
    try: response["obs"] = await asyncio.to_thread(obs.sync_scene, scene_id)
    except (RuntimeError, ValueError, OSError) as exc: response["obs_warning"] = str(exc)
    return response

@app.get("/api/pokedex/current", include_in_schema=False)
@app.get("/api/rare-intelligence/current")
async def current_pokedex_entry():
    """Return species intelligence for the current card without certifying its printing."""
    multi_card = orchestrator.multi_card_recognition.status()
    selected_slots = set(multi_card.get("selected_slots") or [])
    selected_verified_slot = next(
        (
            slot for slot in multi_card.get("slots", [])
            if slot.get("slot") in selected_slots
            and slot.get("verified") is True
            and isinstance(slot.get("card"), dict)
        ),
        None,
    )
    current = orchestrator.recognition_state.snapshot()
    verified = bool(
        current.get("recognition_locked") is True
        and current.get("verification_state") == "VERIFIED"
        and current.get("result_current") is not False
    )
    candidate = selected_verified_slot.get("card") if selected_verified_slot else None
    profile_verified = bool(candidate)
    if not candidate and not selected_slots and verified:
        canonical = orchestrator.backend_test.normalize_current_card(
            orchestrator.recognition.status(),
            current,
        )
        if isinstance(canonical, dict):
            candidate = {
                **canonical,
                "id": canonical.get("card_id"),
                "name": canonical.get("card_name"),
            }
            profile_verified = True
    if not candidate and not selected_slots:
        current_candidate = current.get("primary_candidate")
        current_name = orchestrator.pokedex.pokemon_name(current_candidate)
        if (
            isinstance(current_candidate, dict)
            and current_name
            and current.get("result_current") is not False
            and bool(current.get("card_present") or current.get("recognition_locked"))
        ):
            candidate = current_candidate
            profile_verified = verified
    if not candidate and not selected_slots:
        verified_slot = next(
            (
                slot for slot in multi_card.get("slots", [])
                if slot.get("verified") is True
                and isinstance(slot.get("card"), dict)
            ),
            None,
        )
        candidate = verified_slot.get("card") if verified_slot else None
        profile_verified = bool(candidate)
    overlay = orchestrator.overlay_state.get()
    theme = overlay.get("rare_intelligence_theme") or RareIntelligenceThemeRequest().model_dump()
    if not candidate:
        # A visible card with no current candidate is an unresolved new card,
        # not permission to present the previous card's species as current.
        if bool(current.get("card_present") or current.get("recognition_locked")):
            return {
                "ok": True,
                "status": "pending",
                "reason": "current_species_pending",
                "pokemon": None,
                "identity": None,
                "provisional": True,
                "held": False,
                "on_air": bool(overlay.get("pokedex_on_air")),
                "theme": theme,
            }
        held = overlay.get("pokedex_current")
        if isinstance(held, dict) and held.get("pokemon"):
            return {
                **held,
                "ok": True,
                "on_air": bool(overlay.get("pokedex_on_air")),
                "held": True,
                "theme": theme,
            }
        return {
            "ok": True,
            "status": "empty",
            "pokemon": None,
            "identity": None,
            "on_air": bool(overlay.get("pokedex_on_air")),
            "theme": theme,
        }
    result = await asyncio.to_thread(orchestrator.pokedex.resolve, candidate)
    reveal = orchestrator.experiences.for_card(candidate)
    response = {
        "ok": True,
        **result,
        "identity": {
            "card_id": candidate.get("id"),
            "card_name": candidate.get("name") or candidate.get("english_name"),
            "set_name": candidate.get("set_name"),
            "collector_number": candidate.get("collector_number"),
            "rarity": candidate.get("rarity"),
            "verified": profile_verified,
        },
        "provisional": not profile_verified,
        "held": False,
        "reveal": reveal,
        "on_air": bool(overlay.get("pokedex_on_air")),
        "theme": theme,
    }
    orchestrator.overlay_state.update({"pokedex_current": response})
    return response

@app.post("/api/pokedex/on-air", include_in_schema=False)
@app.post("/api/rare-intelligence/on-air")
async def set_pokedex_on_air(request: PokedexOverlayRequest):
    state = orchestrator.overlay_state.update({"pokedex_on_air": request.enabled})
    return {"ok": True, "on_air": bool(state.get("pokedex_on_air")), "state": state}

@app.get("/api/rare-intelligence/theme")
async def get_rare_intelligence_theme():
    theme = orchestrator.overlay_state.get().get("rare_intelligence_theme")
    return {"ok": True, "theme": theme or RareIntelligenceThemeRequest().model_dump()}

@app.post("/api/rare-intelligence/theme")
async def set_rare_intelligence_theme(request: RareIntelligenceThemeRequest):
    theme = request.model_dump()
    state = orchestrator.overlay_state.update({"rare_intelligence_theme": theme})
    return {"ok": True, "theme": state.get("rare_intelligence_theme")}

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

@app.get("/overlay/graphics")
async def broadcast_graphics_overlay():
    return FileResponse(STATIC_DIR / "overlay_graphics.html")

@app.get("/replay")
@app.get("/overlay/replay")
async def instant_replay_overlay():
    return FileResponse(STATIC_DIR / "overlay_replay.html")

@app.get("/production-screen")
@app.get("/overlay/production-screen")
async def production_screen_overlay():
    return FileResponse(STATIC_DIR / "overlay_production_screen.html")

@app.get("/overlay/pokedex", include_in_schema=False)
@app.get("/overlay/rare-intelligence")
async def pokedex_overlay():
    return FileResponse(STATIC_DIR / "overlay_pokedex.html")

@app.get("/overlay/multi-card")
async def multi_card_overlay():
    return FileResponse(STATIC_DIR / "overlay_multicard.html")

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

@app.get("/api/master-builder/coverage")
async def master_builder_coverage(
    query: str = "",
    language: str = "",
    limit: int = 100,
):
    return await asyncio.to_thread(
        orchestrator.master_database_builder.coverage,
        query=query,
        language=language,
        limit=limit,
    )

@app.post("/api/master-builder/prioritize")
async def master_builder_prioritize(req: MasterBuilderPriorityRequest):
    return orchestrator.master_database_builder.prioritize(req.query)


@app.post("/api/master-builder/refresh")
async def master_builder_refresh():
    return await asyncio.to_thread(
        orchestrator.master_database_builder.refresh_new_releases
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
    legacy_path = (
        orchestrator.catalog_intelligence.sets_dir
        / safe_folder
        / "images"
        / safe_filename
    )
    # Worldwide catalog sync stores artwork in the configured image library,
    # while older imports live beside their set manifests. Support both so a
    # valid recognized candidate never renders a broken reference tile.
    language, separator, set_id = safe_folder.partition("_")
    library_path = (
        storage.get_path("image_path")
        / "pokemon"
        / language
        / set_id
        / safe_filename
        if separator and language and set_id
        else None
    )
    path = next(
        (
            candidate
            for candidate in (legacy_path, library_path)
            if candidate is not None and candidate.exists() and candidate.is_file()
        ),
        None,
    )
    if path is None:
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
        "server_session_id": SERVER_SESSION_ID,
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
        "server_session_id": SERVER_SESSION_ID,
        "trigger": orchestrator.trigger_manager.status(),
        "continuous": orchestrator.recognition_trigger_status(),
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
    snapshot = orchestrator.recognition_state.snapshot()
    return {
        "ok": True,
        "server_session_id": SERVER_SESSION_ID,
        "tcg": orchestrator.tcg_registry.selection(),
        "recognition_state": snapshot,
        "current_card": orchestrator.backend_test.normalize_current_card(
            orchestrator.recognition.status(),
            snapshot,
        ),
        "provenance": provenance_capture.capability(),
    }


@app.get("/api/tcg/games")
async def tcg_games():
    return orchestrator.tcg_registry.status()


@app.post("/api/tcg/selection")
async def tcg_selection(req: TCGSelectionRequest):
    try:
        previous = orchestrator.tcg_registry.selection().get("resolved_game_id")
        result = orchestrator.tcg_registry.configure_selection(req.mode, req.game_id)
        current = result["selection"].get("resolved_game_id")
        if current != previous:
            orchestrator.recognition.set_catalog.configure(mode="auto")
            orchestrator.recognition.artwork_index.set_pack_context("default")
            orchestrator.recognition.artwork_index.set_active_filter(None, None, None)
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})

@app.get("/api/multi-card/status")
async def multi_card_status():
    return {"ok": True, **orchestrator.multi_card_recognition.status()}

@app.post("/api/multi-card/select")
async def multi_card_select(request: Request):
    try:
        payload = await _read_bounded_json(request)
    except RequestBodyTooLarge as exc:
        return JSONResponse(status_code=413, content={"ok": False, "reason": "request_too_large", "max_bytes": exc.max_bytes})
    slots = payload.get("slots") if isinstance(payload.get("slots"), list) else []
    state = orchestrator.multi_card_recognition.select_slots(slots)
    # Resolve immediately so the held Rare Intelligence profile follows the
    # operator's numbered output selection without waiting for another poll.
    rare_intelligence = await current_pokedex_entry()
    return {"ok": True, **state, "rare_intelligence": rare_intelligence}

@app.post("/api/multi-card/capture")
async def multi_card_capture(request: Request):
    try:
        options = await _read_bounded_json(request)
    except RequestBodyTooLarge as exc:
        return JSONResponse(status_code=413, content={"ok": False, "reason": "request_too_large", "max_bytes": exc.max_bytes})
    max_cards = max(2, min(12, int(options.get("max_cards", 6) or 6)))
    frame = None
    best_detections = []
    best_count = -1
    # Camera exposure and foil glare can briefly hide one or two contours.
    # Sample a bounded burst and recognize the strongest geometry frame.
    for attempt in range(6):
        candidate = await asyncio.to_thread(orchestrator.vision.latest_frame)
        detections = await asyncio.to_thread(
            orchestrator.multi_card_recognition.detect_candidates,
            candidate,
            max_cards,
        )
        count = len(detections)
        if count > best_count:
            frame = candidate
            best_count = count
            best_detections = detections
        if count >= max_cards:
            break
        if attempt < 5:
            await asyncio.sleep(0.12)
    return await asyncio.to_thread(
        orchestrator.multi_card_recognition.capture,
        frame,
        unique_variants=bool(options.get("unique_variants", False)),
        max_cards=max_cards,
        detections=best_detections,
    )

@app.get("/api/single-card/regions")
async def single_card_regions():
    frame = await asyncio.to_thread(orchestrator.vision.latest_frame)
    result = await asyncio.to_thread(
        orchestrator.multi_card_recognition.detect_regions, frame, 12
    )
    return {"ok": True, **result}

@app.post("/api/single-card/pick/{slot}")
async def single_card_pick(slot: int):
    if slot < 1 or slot > 12:
        raise HTTPException(status_code=400, detail="slot_out_of_range")
    frame = await asyncio.to_thread(orchestrator.vision.latest_frame)
    region = await asyncio.to_thread(
        orchestrator.multi_card_recognition.crop_region, frame, slot, 12
    )
    if not region:
        raise HTTPException(status_code=404, detail="card_region_not_found")
    return await asyncio.to_thread(
        orchestrator.recognize_picked_region,
        region["crop"],
        slot,
        polygon=region.get("polygon"),
    )


@app.post("/api/recognition/clear")
async def clear_recognition():
    """Advance the scan lifecycle and rearm exactly one operator-requested capture."""
    vision = orchestrator.camera_manager.vision
    vision_status = await asyncio.to_thread(vision.prepare_next_card)
    frame_id = vision_status.get("frame_id")
    orchestrator._emit_from_thread({
        "type": "card_removed",
        "payload": {
            "frame_id": frame_id,
            "timestamp": time.time(),
            "removal_confirmed": True,
            "operator_clear": True,
            "acquisition_epoch": vision_status.get("acquisition_epoch"),
        },
    })
    orchestrator._set_continuous_state(
        "CHANGING",
        frame_id=frame_id,
        present=True,
        clear=True,
    )
    return {
        "ok": True,
        "recognition_state": orchestrator.recognition_state.snapshot(),
        "vision": vision_status,
    }


@app.get("/api/provenance/settings")
async def provenance_settings():
    return {"ok": True, **provenance_capture.capability()}


@app.put("/api/provenance/settings")
async def update_provenance_settings(req: ProvenanceSettingsRequest):
    payload = req.settings if req.settings is not None else req.model_dump(exclude_none=True)
    try:
        settings = await asyncio.to_thread(provenance_capture.save_settings, payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "invalid_settings", "message": str(exc)},
        )
    return {"ok": True, "settings": settings, "status": provenance_capture.capability()["status"]}


@app.post("/api/provenance/capture")
async def capture_provenance_screenshot():
    snapshot = orchestrator.recognition_state.snapshot()
    result = await asyncio.to_thread(
        provenance_capture.capture,
        trigger="manual",
        snapshot=snapshot,
    )
    if not result.get("ok"):
        LOGGER.error(
            "provenance_manual_capture_failed reason=%s error=%s",
            result.get("reason"),
            result.get("error"),
        )
        return JSONResponse(status_code=409, content=result)
    return result


@app.get("/api/provenance/events")
async def provenance_events(limit: int = 20):
    return {"ok": True, "events": provenance_capture.list_events(limit)}


@app.get("/api/provenance/events/{event_id}")
async def provenance_event(event_id: str):
    event = provenance_capture.get_event(event_id)
    if event is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "event_not_found"},
        )
    return {"ok": True, "event": event}


@app.post("/api/provenance/events/{event_id}/correct")
async def correct_provenance_event(event_id: str, req: ProvenanceCorrectionRequest):
    try:
        revision = await asyncio.to_thread(
            provenance_capture.correct_event,
            event_id,
            req.model_dump(),
        )
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "event_not_found"},
        )
    return {"ok": True, "revision": revision}


@app.get("/api/provenance/events/{event_id}/assets/{asset_id}")
async def provenance_asset(event_id: str, asset_id: str):
    path = provenance_capture.asset_path(event_id, asset_id)
    if path is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "asset_not_found"},
        )
    return FileResponse(
        path,
        media_type="image/png",
        filename=path.name,
        headers={"Cache-Control": "private, no-store"},
    )

@app.get("/api/reference-image")
async def reference_image(
    path: str,
):
    """Serve a local catalog image safely to Studio X."""

    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    project_root = Path(
        __file__
    ).resolve().parents[2]

    requested = Path(
        str(
            path
        )
    )

    if not requested.is_absolute():
        requested = (
            project_root
            / requested
        )

    try:
        resolved = requested.resolve(
            strict=True
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Reference image not found.",
        ) from exc

    allowed_roots = (
        (
            project_root
            / "catalog_master"
        ).resolve(),
        (
            project_root
            / "rareiq"
            / "data"
        ).resolve(),
        storage.get_path("image_path").resolve(),
    )

    is_allowed = any(
        resolved == root
        or root in resolved.parents
        for root in allowed_roots
    )

    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Reference image is outside "
                "the allowed catalog folders."
            ),
        )

    supported_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".avif",
        ".bmp",
    }

    if (
        not resolved.is_file()
        or resolved.suffix.lower()
        not in supported_extensions
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Reference image is unavailable "
                "or unsupported."
            ),
        )

    return FileResponse(
        path=str(
            resolved
        ),
        headers={
            "Cache-Control": (
                "public, max-age=3600"
            ),
        },
    )
@app.get("/api/artwork-index/status")
async def artwork_index_status():
    return {
        "ok": True,
        "index": orchestrator.recognition.artwork_index.status(),
    }

@app.get("/api/sets")
async def list_sets():
    selection = orchestrator.tcg_registry.selection()
    game_id = selection.get("resolved_game_id")
    sets = []
    if game_id == "pokemon":
        sets = await asyncio.to_thread(
            orchestrator.master_database_builder.set_options,
            limit=2500,
        )
        if not sets:
            sets = orchestrator.recognition.set_catalog.list_sets()
    return {
        "ok": True,
        "tcg": selection,
        "sets": sets,
        "status": {
            **orchestrator.recognition.set_catalog.status(),
            "game_id": game_id,
        },
    }


@app.get("/api/recognition/set-context")
async def recognition_set_context():
    return {
        "ok": True,
        "tcg": orchestrator.tcg_registry.selection(),
        **orchestrator.recognition.set_catalog.status(),
    }


@app.post("/api/recognition/set-context")
async def configure_recognition_set_context(req: RecognitionSetContextRequest):
    try:
        game_id = orchestrator.tcg_registry.selection().get("resolved_game_id")
        if game_id != "pokemon":
            return JSONResponse(
                {"ok": False, "error": f"Set adapter is not installed for {game_id}."},
                status_code=409,
            )
        status = orchestrator.recognition.set_catalog.configure(
            mode=req.mode,
            set_id=req.set_id,
            set_name=req.set_name,
            language=req.language,
            provider=req.provider,
        )
        active = status.get("active_set") or {}
        orchestrator.recognition.artwork_index.set_pack_context("manual", "Manual set selection")
        orchestrator.recognition.artwork_index.set_active_filter(
            active.get("name") if status.get("locked") else None,
            active.get("language") if status.get("locked") else None,
            active.get("set_id") or active.get("id"),
        )
        await orchestrator.publish("active_set_update", status)
        return {"ok": True, **status}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/recognition/scan-pack")
async def scan_pack_for_set():
    result = await asyncio.to_thread(
        orchestrator.pack_artwork_recognition.identify,
        orchestrator.vision.latest_frame(),
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=422)
    candidate = result["match"]
    set_id = str(candidate.get("set_id") or "").strip()
    set_name = str(candidate.get("set_name") or "").strip()
    status = orchestrator.recognition.set_catalog.configure(
        mode="pack",
        set_id=set_id,
        set_name=set_name,
        language=candidate.get("language"),
    )
    active = status.get("active_set") or {}
    orchestrator.recognition.artwork_index.set_pack_context(
        candidate.get("id") or candidate.get("reference_id") or "pack-scan",
        candidate.get("pack_label") or f"{set_name} · Learned wrapper",
    )
    orchestrator.recognition.artwork_index.set_active_filter(
        active.get("name"),
        active.get("language"),
        active.get("set_id") or active.get("id"),
    )
    await orchestrator.publish("active_set_update", status)
    return {"ok": True, **status, "pack_match": candidate}


@app.get("/api/recognition/pack-learning")
async def pack_learning_status():
    status = orchestrator.recognition.artwork_index.transition_context_status()
    scope = status.get("scope") or []
    reference = orchestrator.pack_artwork_recognition.reference_summary(
        scope[3] if len(scope) > 3 else ""
    )
    references = orchestrator.pack_artwork_recognition.status().get("references") or []
    return {"ok": True, **status, "pack_reference": reference,
            "pack_references": references}


@app.post("/api/recognition/pack-learning/enabled")
async def set_pack_learning_enabled(req: RecognitionToggleRequest):
    return {"ok": True, **orchestrator.recognition.artwork_index.set_transition_context_enabled(req.enabled)}


@app.post("/api/recognition/pack-learning/rename")
async def rename_pack_learning_context(req: PackContextRenameRequest):
    try:
        result = orchestrator.recognition.artwork_index.rename_active_pack_context(req.label)
        result["reference_updated"] = orchestrator.pack_artwork_recognition.rename_reference(
            result["context"], result["context_label"]
        )
        return {"ok": True, **result}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/recognition/pack-learning/activate")
async def activate_pack_learning_context(req: PackContextActivateRequest):
    reference = orchestrator.pack_artwork_recognition.reference_summary(req.reference_id)
    if reference is None:
        return JSONResponse({"ok": False, "error": "Pack reference not found."}, status_code=404)
    status = orchestrator.recognition.set_catalog.configure(
        mode="pack",
        set_id=reference.get("set_id"),
        set_name=reference.get("set_name"),
        language=reference.get("language"),
    )
    active = status.get("active_set") or {}
    orchestrator.recognition.artwork_index.set_pack_context(
        reference["id"], reference.get("pack_label") or "Learned pack wrapper"
    )
    orchestrator.recognition.artwork_index.set_active_filter(
        active.get("name") or reference.get("set_name"),
        active.get("language") or reference.get("language"),
        active.get("set_id") or active.get("id") or reference.get("set_id"),
    )
    await orchestrator.publish("active_set_update", status)
    return {"ok": True, **status, "pack_reference": reference}


@app.post("/api/recognition/pack-learning/reset")
async def reset_pack_learning():
    return {"ok": True, **orchestrator.recognition.artwork_index.reset_transition_context()}


@app.post("/api/recognition/pack-learning/remove-transition")
async def remove_pack_learning_transition(req: PackTransitionRemoveRequest):
    return {"ok": True, **orchestrator.recognition.artwork_index.remove_transition(
        req.from_number, req.to_number
    )}


@app.post("/api/recognition/pack-learning/undo-transition")
async def undo_pack_learning_transition():
    return {"ok": True, **orchestrator.recognition.artwork_index.undo_transition_removal()}


@app.get("/api/recognition/pack-learning/export")
async def export_pack_learning():
    return {"ok": True, "model": orchestrator.recognition.artwork_index.export_transition_context()}


@app.post("/api/recognition/pack-learning/import-preview")
async def preview_pack_learning_import(req: PackTransitionImportRequest):
    return {"ok": True, **orchestrator.recognition.artwork_index.preview_transition_import(req.model)}


@app.post("/api/recognition/pack-learning/import")
async def import_pack_learning(req: PackTransitionImportRequest):
    try:
        return {"ok": True, **orchestrator.recognition.artwork_index.import_transition_context(req.model)}
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.get("/api/recognition/pack-learning/backups")
async def list_pack_learning_backups():
    return {"ok": True, "backups": orchestrator.recognition.artwork_index.list_transition_backups()}


@app.post("/api/recognition/pack-learning/restore")
async def restore_pack_learning_backup(req: PackTransitionRestoreRequest):
    try:
        return {"ok": True, **orchestrator.recognition.artwork_index.restore_transition_backup(req.backup_id)}
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/recognition/learn-pack")
async def learn_pack_artwork(req: RecognitionSetContextRequest):
    result = await asyncio.to_thread(
        orchestrator.pack_artwork_recognition.enroll,
        orchestrator.vision.latest_frame(),
        req.model_dump(),
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=422)
    return result


@app.get("/api/recognition/pack-index")
async def pack_artwork_index_status():
    return orchestrator.pack_artwork_recognition.status()


@app.post("/api/recognition/pack-profile")
async def update_pack_profile(req: PackProfileRequest):
    profile = orchestrator.pack_artwork_recognition.update_reference_profile(
        req.reference_id, req.expected_cards, req.rare_slot
    )
    if profile is None:
        return JSONResponse({"ok": False, "error": "Pack reference not found."}, status_code=404)
    return {"ok": True, "reference_id": req.reference_id, "pack_profile": profile}


@app.post("/api/recognition/pack-profile/observe")
async def observe_pack_profile(req: PackProfileObservationRequest):
    learning = orchestrator.pack_artwork_recognition.observe_reference_profile(
        req.reference_id, req.observed_cards, req.rare_slot
    )
    if learning is None:
        return JSONResponse({"ok": False, "error": "Pack reference not found."}, status_code=404)
    return {"ok": True, "reference_id": req.reference_id, "profile_learning": learning}


@app.get("/api/recognition/pack-reference/{reference_id}")
async def pack_artwork_reference(reference_id: str):
    path = orchestrator.pack_artwork_recognition.reference_path(reference_id)
    if path is None:
        return JSONResponse({"ok": False, "error": "Pack reference not found."}, status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


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
        orchestrator.recognition.artwork_index.set_pack_context("manual", "Manual set selection")
        orchestrator.recognition.artwork_index.set_active_filter(
            active.get("name"),
            active.get("language"),
            active.get("set_id") or active.get("id"),
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
    result = orchestrator.force_manual_capture()
    return {
        **result,
        "path": result.get("crop_path"),
        "error": None if result.get("ok") else result.get("reason"),
    }



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


@app.get("/api/camera-slots/{slot_id}/stream")
async def camera_slot_stream(slot_id: int):
    if slot_id not in {1, 2, 3, 4}:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "invalid_slot", "message": "Camera slot must be between 1 and 4."},
        )
    slot = orchestrator.camera_manager.camera_slots()[slot_id - 1]
    if not slot.get("source_id"):
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "unassigned", "message": "Camera slot is not assigned."},
        )

    async def frames():
        orchestrator.camera_manager.subscribe_slot(slot_id)
        try:
            while True:
                jpg = orchestrator.camera_manager.slot_jpeg(slot_id)
                if jpg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                await asyncio.sleep(0.04)
        except (asyncio.CancelledError, GeneratorExit, BrokenPipeError, ConnectionResetError):
            return
        finally:
            orchestrator.camera_manager.unsubscribe_slot(slot_id)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

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

@app.post("/api/session/confirm-recognition-candidate")
async def confirm_recognition_candidate(request: RecognitionCandidateSelectionRequest):
    snapshot=orchestrator.recognition_state.snapshot()
    if str(snapshot.get("state_id") or "")!=request.state_id:
        raise HTTPException(status_code=409,detail="Recognition changed; review the current card again.")
    candidates=snapshot.get("candidates") or []
    if request.candidate_index>=len(candidates):
        raise HTTPException(status_code=404,detail="Candidate is no longer available.")
    candidate=dict(candidates[request.candidate_index]); candidate["source"]="operator_selected_candidate"; candidate["operator_selected"]=True
    result=await orchestrator.confirm_recognition(automatic=False,card_override=candidate)
    if result.get("ok"):
        result["learning"]=orchestrator.learning_queue.add_correction(fingerprint=snapshot.get("artwork_fingerprint") or "",candidate=candidate,state_id=request.state_id)
    return result

@app.get("/api/intelligence/catalog-search")
async def intelligence_catalog_search(q: str, limit: int = 24):
    query=str(q or "").strip()
    if len(query)<2:
        return {"ok":True,"query":query,"results":[]}
    results=orchestrator.recognition.global_visual_index.text_search(query,limit=limit)
    return {"ok":True,"query":query,"results":results,"count":len(results)}

@app.post("/api/session/confirm-recognition-catalog-candidate")
async def confirm_recognition_catalog_candidate(request: RecognitionCatalogSelectionRequest):
    snapshot=orchestrator.recognition_state.snapshot()
    if str(snapshot.get("state_id") or "")!=request.state_id:
        raise HTTPException(status_code=409,detail="Recognition changed; review the current card again.")
    candidate=dict(request.candidate or {})
    if not (candidate.get("id") or (candidate.get("set_id") and candidate.get("collector_number"))):
        raise HTTPException(status_code=422,detail="The selected catalog card has no stable identity.")
    candidate["source"]="operator_catalog_search"
    candidate["operator_selected"]=True
    result=await orchestrator.confirm_recognition(automatic=False,card_override=candidate)
    if result.get("ok"):
        result["learning"]=orchestrator.learning_queue.add_correction(fingerprint=snapshot.get("artwork_fingerprint") or "",candidate=candidate,state_id=request.state_id)
    return result

@app.get("/api/intelligence/corrections")
async def intelligence_corrections(limit: int = 100):
    return {"ok":True,**orchestrator.learning_queue.corrections(limit)}

@app.delete("/api/intelligence/corrections/{correction_id}")
async def revoke_intelligence_correction(correction_id: str):
    return _collection_mutation_response(orchestrator.learning_queue.revoke_correction(correction_id),"revoked")

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

@app.get("/api/collection")
async def collection_status():
    references = orchestrator.catalog_intelligence.collection_reference_cards()
    dashboard = orchestrator.collection.dashboard(references)
    return {"ok": True, **dashboard}

@app.get("/api/inventory")
async def inventory_status():
    return {"ok": True, **orchestrator.inventory.dashboard()}

@app.get("/api/inventory/valuation")
async def inventory_valuation():
    dashboard = orchestrator.inventory.dashboard()
    return {"ok": True, **orchestrator.catalog.inventory_valuation(dashboard.get("items") or [])}

@app.get("/api/inventory/break-performance")
async def inventory_break_performance(period: Literal["daily", "weekly", "monthly", "lifetime"] = "lifetime", set_filter: str = ""):
    dashboard = orchestrator.inventory.dashboard()
    items = dashboard.get("items") or []
    seconds = {"daily": 86400, "weekly": 604800, "monthly": 2592000}.get(period)
    if seconds:
        cutoff = time.time() - seconds
        items = [item for item in items if float(item.get("created_at") or 0) >= cutoff]
    set_key = set_filter.strip().lower()
    if set_key:
        items = [item for item in items if set_key in str(item.get("set_name") or item.get("set_code") or "").lower()]
    return {"ok": True, "period": period, "set_filter": set_filter.strip(), **orchestrator.catalog.inventory_break_performance(items)}

@app.get("/api/inventory/break-performance.csv")
async def inventory_break_performance_csv(period: Literal["daily", "weekly", "monthly", "lifetime"] = "lifetime", set_filter: str = ""):
    payload = await inventory_break_performance(period, set_filter)
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["rank", "period", "set_filter", "pack_group", "pack_number", "cards", "hits", "hit_rate", "coverage_percent", "cost", "verified_value", "realized_sales", "total_return", "profit", "roi_percent", "strongest_pull", "strongest_pull_value"])
    for index, pack in enumerate(payload["packs"], 1):
        strongest = pack.get("strongest_pull") or {}
        writer.writerow([index, period, set_filter, pack.get("group"), pack.get("pack_number"), pack.get("cards"), pack.get("hits"), pack.get("hit_rate"), pack.get("coverage_percent"), pack.get("cost"), pack.get("verified_value"), pack.get("realized_sales"), pack.get("total_return"), pack.get("profit"), pack.get("roi_percent"), strongest.get("card_name"), strongest.get("value")])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rareiq-break-performance-{period}.csv"'})

@app.get("/api/inventory/business-trends")
async def inventory_business_trends(days: int = 30):
    return {"ok": True, **orchestrator.inventory.business_trends(days)}

@app.post("/api/inventory/expenses")
async def create_inventory_expense(request: InventoryExpenseRequest):
    result = orchestrator.inventory.add_expense(**request.model_dump())
    return _collection_mutation_response(result, "created")

@app.delete("/api/inventory/expenses/{expense_id}")
async def delete_inventory_expense(expense_id: str):
    result = orchestrator.inventory.remove_expense(expense_id)
    return _collection_mutation_response(result, "removed")

@app.patch("/api/inventory/expenses/{expense_id}")
async def update_inventory_expense(expense_id: str, request: InventoryExpenseUpdateRequest):
    result = orchestrator.inventory.update_expense(expense_id, **request.model_dump())
    return _collection_mutation_response(result, "updated")

@app.get("/api/inventory/expenses/{expense_id}/receipt")
async def inventory_expense_receipt(expense_id: str):
    path = orchestrator.inventory.expense_receipt(expense_id)
    if not path: raise HTTPException(status_code=404, detail="expense_receipt_not_found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})

@app.get("/api/inventory/expenses.csv")
async def inventory_expenses_csv(days: int = 3650):
    data = orchestrator.inventory.business_trends(days); output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["expense_id", "category", "tax_category", "amount", "currency", "incurred_at", "recurrence", "note", "receipt_url"])
    for expense in data["expenses"]: writer.writerow([expense.get("expense_id"), expense.get("category"), expense.get("tax_category"), expense.get("amount"), expense.get("currency"), expense.get("incurred_at"), expense.get("recurrence"), expense.get("note"), expense.get("receipt_url")])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="rareiq-expenses.csv"'})

@app.get("/api/inventory/tax-summary")
async def inventory_tax_summary(year: int = time.localtime().tm_year):
    return {"ok": True, **orchestrator.inventory.tax_summary(year)}

@app.get("/api/inventory/tax-comparison")
async def inventory_tax_comparison(year: int = time.localtime().tm_year):
    return {"ok": True, **orchestrator.inventory.tax_comparison(year)}

@app.get("/api/inventory/business-profile")
async def inventory_business_profile():
    return {"ok": True, "profile": orchestrator.inventory.business_profile(), "backup": orchestrator.inventory.backup_status()}

@app.patch("/api/inventory/business-profile")
async def update_inventory_business_profile(request: BusinessProfileRequest):
    result = orchestrator.inventory.update_business_profile(**request.model_dump())
    return _collection_mutation_response(result, "updated")

@app.get("/api/inventory/audit-log")
async def inventory_audit_log(limit: int = 200):
    return {"ok": True, **orchestrator.inventory.audit_log(limit)}

@app.get("/api/inventory/accounting/periods")
async def inventory_accounting_periods():
    return {"ok": True, **orchestrator.inventory.period_closes()}

@app.get("/api/inventory/profit-and-loss")
async def inventory_profit_and_loss(year: int = time.localtime().tm_year, month: int = time.localtime().tm_mon):
    return {"ok": True, **orchestrator.inventory.profit_and_loss(year, month)}

@app.post("/api/inventory/accounting/close")
async def close_inventory_accounting_period(request: AccountingPeriodRequest):
    return _collection_mutation_response(orchestrator.inventory.close_period(request.year, request.month), "closed")

@app.get("/api/inventory/profit-and-loss.csv")
async def inventory_profit_and_loss_csv(year: int = time.localtime().tm_year, month: int = time.localtime().tm_mon):
    data=orchestrator.inventory.profit_and_loss(year,month); statement=data["statement"]; output=io.StringIO(); writer=csv.writer(output)
    writer.writerow([data["company_name"]]); writer.writerow(["Profit and Loss",data["period"],"Closed" if data["closed"] else "Open"]); writer.writerow([]); writer.writerow(["Account","Amount","Currency"])
    for label,key in (("Revenue","revenue"),("Cost of goods sold","card_cost"),("Gross profit","gross_profit"),("Marketplace fees","fees"),("Shipping","shipping"),("Operating expenses","operating_expenses"),("Net income","net_income")): writer.writerow([label,statement[key],data["currency"]])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="rareiq-profit-loss-{data["period"]}.csv"'})

@app.get("/api/inventory/tax-summary.csv")
async def inventory_tax_summary_csv(year: int = time.localtime().tm_year):
    data = orchestrator.inventory.tax_summary(year); output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["month", "revenue", "marketplace_fees", "shipping", "card_cost", "operating_expenses", "net_income", "currency"])
    for row in data["months"]: writer.writerow([row["month"], row["revenue"], row["fees"], row["shipping"], row["card_cost"], row["operating_expenses"], row["net_income"], data["currency"]])
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rareiq-tax-summary-{data["year"]}.csv"'})


@app.get("/api/inventory/labels/print")
async def print_inventory_labels(item_ids: str = ""):
    requested = [value.strip().upper() for value in item_ids.split(",") if value.strip()][:100]
    items = [orchestrator.inventory.get(item_id) for item_id in requested]
    items = [item for item in items if item]
    if not items:
        raise HTTPException(status_code=404, detail="inventory_labels_not_found")
    labels = "".join(
        f'<article><img src="/api/inventory/items/{html.escape(str(item["item_id"]))}/label.png" alt="{html.escape(str(item["item_id"]))}"><small>{html.escape(str(item["item_id"]))}</small></article>'
        for item in items
    )
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RareIQ Inventory Labels</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#e9eef1;color:#10242e;font:12px Inter,Arial,sans-serif}}header{{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:#071824;color:#eefaff}}header h1{{margin:0;font-size:18px}}button{{padding:9px 14px;border:0;border-radius:8px;background:#51d7f3;font-weight:800;cursor:pointer}}main{{display:grid;grid-template-columns:repeat(3,2.5in);gap:.18in;justify-content:center;padding:.25in}}article{{display:grid;place-items:center;break-inside:avoid;background:#fff;border:1px dashed #a8b8c0;padding:.06in}}article img{{display:block;width:2.35in;height:auto}}article small{{display:none}}@page{{margin:.25in}}@media(max-width:800px){{main{{grid-template-columns:repeat(2,minmax(0,2.5in))}}}}@media print{{body{{background:#fff}}header{{display:none}}main{{padding:0;gap:.12in}}article{{border:0}}}}</style></head><body><header><h1>RareIQ · {len(items)} Inventory Labels</h1><button onclick="window.print()">Print Labels</button></header><main>{labels}</main></body></html>'''
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})

@app.post("/api/inventory/items")
async def create_inventory_item(request: InventoryCreateRequest):
    result = orchestrator.inventory.create(**request.model_dump())
    return _collection_mutation_response(result, "created")

@app.post("/api/inventory/items/batch")
async def create_inventory_batch(request: InventoryBatchCreateRequest):
    payload = request.model_dump()
    quantity = payload.pop("quantity")
    result = orchestrator.inventory.create_many(quantity=quantity, **payload)
    return _collection_mutation_response(result, "created")

@app.post("/api/inventory/allocations/rebalance")
async def rebalance_inventory_allocation(request: InventoryAllocationRequest):
    result = orchestrator.inventory.rebalance_allocation(**request.model_dump())
    return _collection_mutation_response(result, "rebalanced")

@app.post("/api/inventory/allocations/lock")
async def lock_inventory_allocation(request: InventoryAllocationLockRequest):
    result = orchestrator.inventory.lock_allocation(request.group)
    return _collection_mutation_response(result, "locked")

@app.get("/api/inventory/allocations/{group}/report")
async def inventory_allocation_report(group: str):
    snapshot = orchestrator.inventory.allocation_snapshot(group)
    if not snapshot["found"]:
        raise HTTPException(status_code=404, detail="allocation_group_not_found")
    valuation = orchestrator.catalog.inventory_valuation(snapshot["items"])
    summary = next((item for item in valuation.get("allocation_groups") or [] if item["group"] == group), {})
    money = lambda value: f'${float(value or 0):,.2f}'
    rows = "".join(
        f'<tr><td><img src="{html.escape(str(item.get("reference_image_url") or ""))}" alt=""></td><td><strong>{html.escape(str(item.get("card_name") or "Card"))}</strong><small>{html.escape(str(item.get("set_name") or ""))} #{html.escape(str(item.get("collector_number") or "--"))}</small></td><td>{html.escape(str(item.get("item_id") or ""))}</td><td>{float(item.get("allocation_weight") or 1):g}×</td><td>{money(item.get("cost_basis"))}</td><td>{money(item.get("market")) if item.get("priced") else "Unpriced"}</td><td>{money(item.get("unrealized_profit")) if item.get("unrealized_profit") is not None else "--"}</td></tr>'
        for item in summary.get("items") or []
    )
    strongest = summary.get("strongest_pull") or {}
    title = html.escape(group.split(":")[-1].replace("pack-", "Pack "))
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RareIQ · {title} Report</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#06131d;color:#eaf8fd;font:14px Inter,Arial,sans-serif}}header,main{{max-width:1100px;margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;padding:28px 20px 18px}}h1{{margin:3px 0;font-size:28px}}.eyebrow{{color:#61ddf7;font-size:11px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}}button,a{{border:1px solid #244859;border-radius:9px;padding:10px 14px;background:#102938;color:#eefaff;text-decoration:none;cursor:pointer}}main{{padding:0 20px 30px}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px}}.metrics div{{padding:14px;border:1px solid #173544;border-radius:12px;background:#0a202c}}.metrics span,small{{display:block;color:#7e9ca9;font-size:10px;text-transform:uppercase}}.metrics strong{{display:block;margin-top:6px;font-size:18px}}.pull{{padding:16px;border:1px solid #315278;border-radius:12px;background:linear-gradient(135deg,#0d2c38,#171f41);margin-bottom:16px}}table{{width:100%;border-collapse:collapse;background:#091c27;border-radius:12px;overflow:hidden}}th,td{{padding:11px;border-bottom:1px solid #15303d;text-align:left}}th{{color:#75dff5;font-size:10px;text-transform:uppercase}}td img{{width:42px;height:58px;object-fit:contain}}@media(max-width:760px){{.metrics{{grid-template-columns:repeat(2,1fr)}}table{{font-size:11px}}}}@media print{{body{{background:#fff;color:#111}}header button,header a{{display:none}}.metrics div,.pull,table{{background:#fff;border-color:#ccc}}}}</style></head><body><header><div><span class="eyebrow">RareIQ Inventory Intelligence</span><h1>{title} Profitability Report</h1><small>{html.escape(group)} · {"Locked" if snapshot["locked"] else "Open ledger"}</small></div><div><a href="/api/inventory/allocations/{html.escape(group)}/report.csv">Download CSV</a> <button onclick="window.print()">Print / Save PDF</button></div></header><main><section class="metrics"><div><span>Cards</span><strong>{summary.get("cards", 0)}</strong></div><div><span>Allocated Cost</span><strong>{money(summary.get("cost_basis"))}</strong></div><div><span>Verified Value</span><strong>{money(summary.get("verified_value"))}</strong></div><div><span>Profit / Loss</span><strong>{money(summary.get("unrealized_profit"))}</strong></div><div><span>ROI</span><strong>{str(summary.get("roi_percent")) + "%" if summary.get("roi_percent") is not None else "--"}</strong></div></section><section class="pull"><span class="eyebrow">Strongest Pull</span><h2>{html.escape(str(strongest.get("card_name") or "Waiting for verified pricing"))}</h2><strong>{money(strongest.get("market")) if strongest else "--"}</strong></section><table><thead><tr><th>Card</th><th>Identity</th><th>Inventory ID</th><th>Weight</th><th>Cost</th><th>Market</th><th>P/L</th></tr></thead><tbody>{rows}</tbody></table></main></body></html>'''
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})

@app.get("/api/inventory/allocations/{group}/report.csv")
async def inventory_allocation_report_csv(group: str):
    snapshot = orchestrator.inventory.allocation_snapshot(group)
    if not snapshot["found"]:
        raise HTTPException(status_code=404, detail="allocation_group_not_found")
    valuation = orchestrator.catalog.inventory_valuation(snapshot["items"])
    summary = next((item for item in valuation.get("allocation_groups") or [] if item["group"] == group), {})
    output = io.StringIO(); writer = csv.writer(output)
    writer.writerow(["pack_group", "locked", "item_id", "card", "set", "collector_number", "weight", "allocated_cost", "verified_market", "unrealized_profit", "currency"])
    for item in summary.get("items") or []:
        writer.writerow([group, snapshot["locked"], item.get("item_id"), item.get("card_name"), item.get("set_name"), item.get("collector_number"), item.get("allocation_weight"), item.get("cost_basis"), item.get("market"), item.get("unrealized_profit"), item.get("currency")])
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", group).strip("-") or "pack"
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rareiq-{filename}.csv"'})

@app.get("/api/inventory/items/{item_id}")
async def inventory_item(item_id: str):
    item = orchestrator.inventory.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    return {"ok": True, "item": item}

@app.get("/api/inventory/items/{item_id}/valuation-history")
async def inventory_item_valuation_history(item_id: str):
    item = orchestrator.inventory.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    return {"ok": True, "item": item, "timeline": orchestrator.catalog.inventory_item_timeline(item)}

@app.post("/api/inventory/items/{item_id}/price-alert")
async def inventory_item_price_alert(item_id: str, req: PriceAlertRequest):
    item = orchestrator.inventory.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    result = orchestrator.catalog.set_inventory_price_alert(item, req.model_dump())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error"))
    return result

@app.get("/api/inventory/items/{item_id}/sell-recommendation")
async def inventory_item_sell_recommendation(item_id: str, fee_percent: float = 13.25, shipping_cost: float = 0, packaging_cost: float = 0, desired_profit_percent: float = 25):
    item = orchestrator.inventory.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    timeline = orchestrator.catalog.inventory_item_timeline(item)
    recommendation = orchestrator.inventory.sell_recommendation(item, timeline.get("current_market"), fee_percent=fee_percent, shipping_cost=shipping_cost, packaging_cost=packaging_cost, desired_profit_percent=desired_profit_percent)
    return {"ok": True, "item_id": item["item_id"], "recommendation": recommendation}

@app.post("/api/inventory/listing-drafts")
async def inventory_listing_drafts(req: InventoryListingDraftRequest):
    drafts, skipped, seen = [], [], set()
    for raw_item_id in req.item_ids:
        item_id = str(raw_item_id or "").upper()
        if item_id in seen: continue
        seen.add(item_id)
        item = orchestrator.inventory.get(item_id)
        if not item or item.get("status") != "in_stock":
            skipped.append({"item_id": item_id, "reason": "not_in_stock" if item else "not_found"}); continue
        timeline = orchestrator.catalog.inventory_item_timeline(item)
        pricing = orchestrator.inventory.sell_recommendation(item, timeline.get("current_market"), fee_percent=req.fee_percent, shipping_cost=req.shipping_cost, packaging_cost=req.packaging_cost, desired_profit_percent=req.desired_profit_percent)
        name = str(item.get("english_name") or item.get("card_name") or "Trading Card").strip()
        set_name = str(item.get("set_name") or item.get("set_code") or "").strip()
        number = str(item.get("collector_number") or "").strip()
        condition = str(item.get("condition") or "raw").replace("_", " ").title()
        title = " · ".join(part for part in (name, set_name, f"#{number}" if number else "", condition) if part)[:160]
        drafts.append({"status": "draft", "channel": req.channel, "sku": item_id, "title": title, "description": f"{name} from {set_name or 'the listed set'}, collector number {number or 'shown'}. Condition: {condition}. RareIQ inventory ID: {item_id}.", "price": pricing["recommended_price"], "currency": pricing["currency"], "quantity": 1, "condition": condition, "set_name": set_name, "collector_number": number, "language": item.get("language") or "", "rarity": item.get("rarity") or "", "reference_image_url": item.get("reference_image_url") or "", "verified_market": pricing.get("verified_market"), "cost_basis": pricing.get("cost_basis"), "expected_fees": pricing.get("expected_fees"), "shipping_cost": pricing.get("shipping_cost"), "packaging_cost": pricing.get("packaging_cost"), "expected_profit": pricing.get("expected_profit"), "profile_url": item.get("profile_url")})
    return {"ok": True, "channel": req.channel, "drafts": drafts, "created": len(drafts), "skipped": skipped}

@app.post("/api/inventory/items/{item_id}/listing")
async def inventory_item_listing(item_id: str, req: InventoryListingStatusRequest):
    result = orchestrator.inventory.update_listing(item_id, **req.model_dump())
    if not result.get("updated"):
        status = 404 if result.get("reason") == "item_not_found" else 409
        return JSONResponse(status_code=status, content={"ok": False, **result})
    return {"ok": True, **result}

@app.get("/api/inventory/listing-dashboard")
async def inventory_listing_dashboard(stale_days: int = 30):
    return {"ok": True, **orchestrator.inventory.listing_dashboard(stale_days)}

@app.post("/api/inventory/listings/bulk")
async def inventory_bulk_listings(req: InventoryBulkListingRequest):
    result = orchestrator.inventory.bulk_update_listings(**req.model_dump())
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    return result

@app.post("/api/inventory/listings/smart-reprice")
async def inventory_smart_reprice(req: InventorySmartRepriceRequest):
    recommendations, skipped, seen = [], [], set()
    for raw_item_id in req.item_ids:
        item_id = str(raw_item_id or "").upper()
        if not item_id or item_id in seen: continue
        seen.add(item_id); item = orchestrator.inventory.get(item_id); listing = (item or {}).get("active_listing")
        if not item or not listing:
            skipped.append({"item_id": item_id, "reason": "item_not_found" if not item else "active_listing_not_found"}); continue
        channel = str(listing.get("channel") or "other"); profile = req.channel_profiles.get(channel) or req.channel_profiles.get("other") or {}
        fee_percent = max(0.0, min(95.0, float(profile.get("fee_percent") or 0))); shipping = max(0.0, float(profile.get("shipping_cost") or 0)); packaging = max(0.0, float(profile.get("packaging_cost") or 0))
        timeline = orchestrator.catalog.inventory_item_timeline(item)
        pricing = orchestrator.inventory.sell_recommendation(item, timeline.get("current_market"), fee_percent=fee_percent, shipping_cost=shipping, packaging_cost=packaging, desired_profit_percent=req.desired_profit_percent)
        fee_rate = fee_percent / 100; profit_floor_price = round((float(item.get("cost_basis") or 0) + req.minimum_profit + shipping + packaging) / max(.05, 1 - fee_rate), 2)
        recommended = round(max(float(pricing["recommended_price"]), profit_floor_price), 2); expected_fees = round(recommended * fee_rate, 2); expected_profit = round(recommended - expected_fees - shipping - packaging - float(item.get("cost_basis") or 0), 2); current_price = listing.get("asking_price"); current_profit = round(float(current_price) * (1 - fee_rate) - shipping - packaging - float(item.get("cost_basis") or 0), 2) if isinstance(current_price, (int, float)) else None; profit_delta = round(expected_profit - current_profit, 2) if current_profit is not None else None
        recommendations.append({"item_id": item_id, "card_name": item.get("english_name") or item.get("card_name"), "channel": channel, "current_price": current_price, "recommended_price": recommended, "verified_market": pricing.get("verified_market"), "expected_profit": expected_profit, "current_profit": current_profit, "profit_delta": profit_delta, "minimum_profit": req.minimum_profit, "currency": item.get("currency") or "USD"})
    applied = orchestrator.inventory.apply_listing_price_targets([{"item_id": row["item_id"], "asking_price": row["recommended_price"], "expected_profit": row["expected_profit"], "profit_delta": row["profit_delta"], "verified_market": row["verified_market"]} for row in recommendations]) if req.apply else None
    return {"ok": True, "mode": "applied" if req.apply else "preview", "recommendations": recommendations, "eligible": len(recommendations), "skipped": skipped, "applied": applied}

@app.get("/api/inventory/listings/reprice-history")
async def inventory_reprice_history(limit: int = 100):
    return {"ok": True, **orchestrator.inventory.listing_reprice_history(limit)}

@app.post("/api/inventory/listings/reprice-rollback")
async def inventory_reprice_rollback(req: InventoryRepriceRollbackRequest):
    result = orchestrator.inventory.rollback_listing_reprice(req.audit_id)
    if not result.get("rolled_back"):
        return JSONResponse(status_code=409, content={"ok": False, **result})
    return {"ok": True, **result}

@app.get("/api/inventory/marketplace-sync")
async def inventory_marketplace_sync(limit: int = 200):
    return {"ok": True, **orchestrator.inventory.marketplace_sync_queue(limit)}

@app.post("/api/inventory/marketplace-sync/{job_id}")
async def inventory_marketplace_sync_action(job_id: str, req: InventoryMarketplaceSyncActionRequest):
    result = orchestrator.inventory.update_marketplace_sync_job(job_id, **req.model_dump())
    if not result.get("updated"):
        status = 404 if result.get("reason") == "sync_job_not_found" else 409
        return JSONResponse(status_code=status, content={"ok": False, **result})
    return {"ok": True, **result}

@app.get("/inventory/item/{item_id}")
async def inventory_item_profile(item_id: str):
    item = orchestrator.inventory.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    timeline = orchestrator.catalog.inventory_item_timeline(item)
    esc = lambda value: html.escape(str(value if value not in (None, "") else "--"))
    def cash(value: Any, currency: str | None = None) -> str:
        return "--" if not isinstance(value, (int, float)) else f'{esc(currency or timeline["currency"])} {float(value):,.2f}'
    event_rows = "".join(f'<li class="{esc(event.get("kind"))}"><b>{esc(event.get("kind"))}</b><span>{cash(event.get("market") if event.get("kind") != "sale" else event.get("net_proceeds"), event.get("currency"))}</span><small>{esc(time.strftime("%Y-%m-%d %H:%M", time.localtime(float(event.get("timestamp") or 0))))} · {esc(event.get("provider") or event.get("channel"))}</small></li>' for event in timeline["events"])
    name = esc(item.get("english_name") or item.get("card_name") or "Inventory Card")
    document = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>RareIQ · {name}</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#06131d;color:#eefaff;font:15px Inter,Arial,sans-serif}}main{{max-width:1050px;margin:auto;padding:30px 20px}}header{{display:flex;gap:22px;align-items:center;margin-bottom:22px}}header img{{width:130px;max-height:180px;object-fit:contain;border-radius:12px}}h1{{margin:5px 0}}.eyebrow{{color:#62ddf7;font-size:11px;font-weight:900;letter-spacing:.14em;text-transform:uppercase}}.metrics{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}.metric,section{{border:1px solid #193b4b;background:#0a202c;border-radius:15px;padding:17px}}.metric span,small{{display:block;color:#8ca7b4}}.metric strong{{display:block;font-size:22px;margin-top:7px}}section{{margin-top:16px}}ul{{list-style:none;padding:0;margin:12px 0 0}}li{{display:grid;grid-template-columns:120px 1fr auto;gap:12px;padding:15px;border-top:1px solid #173441;text-transform:capitalize}}li span{{font-weight:800}}a{{color:#7ee8fb}}@media(max-width:850px){{.metrics{{grid-template-columns:repeat(2,1fr)}}header{{align-items:flex-start}}li{{grid-template-columns:90px 1fr}}li small{{grid-column:1/-1}}}}</style></head><body><main><header><img src="{esc(item.get("reference_image_url"))}" alt="{name}"><div><span class="eyebrow">RareIQ Inventory Profile</span><h1>{name}</h1><p>{esc(item.get("set_name") or item.get("set_code"))} #{esc(item.get("collector_number"))} · {esc(item.get("item_id"))} · {esc(item.get("status")).replace("_", " ")}</p><a href="/control">Return to Studio</a></div></header><div class="metrics"><div class="metric"><span>Cost basis</span><strong>{cash(item.get("cost_basis"))}</strong></div><div class="metric"><span>Acquired market</span><strong>{cash(timeline.get("acquisition_market"))}</strong></div><div class="metric"><span>Current verified</span><strong>{cash(timeline.get("current_market"))}</strong></div><div class="metric"><span>Tracked low</span><strong>{cash(timeline.get("market_low"))}</strong></div><div class="metric"><span>Tracked high</span><strong>{cash(timeline.get("market_high"))}</strong></div><div class="metric"><span>{"Realized ROI" if item.get("status") == "sold" else "Market change"}</span><strong>{esc(timeline.get("realized_roi_percent") if item.get("status") == "sold" else timeline.get("market_change_percent"))}%</strong></div></div><section><span class="eyebrow">Valuation Timeline · {timeline.get("checkpoint_count", 0)} automatic checkpoints</span><h2>Permanent item history</h2><ul>{event_rows or '<li><b>Waiting</b><span>No verified valuation events yet</span></li>'}</ul></section></main></body></html>'''
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})

@app.post("/api/inventory/items/{item_id}/sell")
async def sell_inventory_item(item_id: str, request: InventorySaleRequest):
    result = orchestrator.inventory.sell(item_id, **request.model_dump())
    return _collection_mutation_response(result, "sold")

@app.post("/api/inventory/items/{item_id}/void-sale")
async def void_inventory_sale(item_id: str, request: InventoryVoidRequest):
    result = orchestrator.inventory.void_sale(item_id, request.reason)
    return _collection_mutation_response(result, "voided")

@app.get("/api/inventory/sales.csv")
async def export_inventory_sales():
    rows = orchestrator.inventory.sales_rows()
    output = io.StringIO()
    fields = ["item_id", "card_name", "set_name", "collector_number", "cost_basis", "gross_sale", "fees", "shipping_cost", "packaging_cost", "net_proceeds", "profit", "channel", "order_reference", "sold_at", "currency", "pricing_resolution_id", "acquisition_market", "acquisition_market_currency", "acquisition_market_provider"]
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="rareiq_inventory_sales.csv"'})

@app.get("/api/inventory/items/{item_id}/qr.png")
async def inventory_qr(item_id: str):
    payload = orchestrator.inventory.qr_png(item_id)
    if not payload:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    return Response(content=payload, media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})

@app.get("/api/inventory/items/{item_id}/label.png")
async def inventory_label(item_id: str):
    payload = orchestrator.inventory.label_png(item_id)
    if not payload:
        raise HTTPException(status_code=404, detail="inventory_item_not_found")
    return Response(content=payload, media_type="image/png", headers={"Content-Disposition": f'inline; filename="{item_id}-label.png"'})

def _collection_mutation_response(result: dict[str, Any], success_key: str):
    if result.get(success_key):
        return {"ok": True, **result}
    reason = str(result.get("reason") or "collection_operation_failed")
    status = 404 if reason in {"card_not_found", "goal_not_found", "correction_not_found", "event_not_found"} else 409 if reason in {"already_archived", "already_undone", "allocation_exceeds_quantity", "quantity_below_zero"} else 422
    return JSONResponse(status_code=status, content={"ok": False, **result})

@app.get("/api/collection/export.json")
async def export_collection_json():
    payload = orchestrator.collection.backup()
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="rareiq_collection.json"'},
    )

@app.post("/api/collection/import/preview")
async def preview_collection_import(request: CollectionImportRequest):
    result = orchestrator.collection.preview_import(request.backup)
    return _collection_mutation_response(result, "valid")

@app.post("/api/collection/import/merge")
async def merge_collection_import(request: CollectionImportRequest):
    result = orchestrator.collection.merge_backup(request.backup)
    return _collection_mutation_response(result, "merged")

@app.get("/api/collection/export.csv")
async def export_collection_csv():
    output = io.StringIO(newline="")
    fields = [
        "card_name", "printed_name", "english_name", "set_name", "set_code",
        "collector_number", "language", "rarity", "quantity", "first_seen_at",
        "last_seen_at", "version_key",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(orchestrator.collection.snapshot()["cards"])
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="rareiq_collection.csv"'},
    )

@app.post("/api/collection/adjust")
async def adjust_collection(request: CollectionAdjustmentRequest):
    result = orchestrator.collection.adjust_quantity(
        request.version_key,
        request.delta,
        request.reason,
    )
    return _collection_mutation_response(result, "adjusted")

@app.post("/api/collection/corrections/{correction_id}/undo")
async def undo_collection_correction(correction_id: str):
    result = orchestrator.collection.undo_correction(correction_id)
    return _collection_mutation_response(result, "undone")

@app.post("/api/collection/goals")
async def create_collection_goal(request: CollectionGoalRequest):
    result = orchestrator.collection.add_goal(**request.model_dump())
    return _collection_mutation_response(result, "created")

@app.post("/api/collection/goals/{goal_id}/archive")
async def archive_collection_goal(goal_id: str):
    result = orchestrator.collection.archive_goal(goal_id)
    return _collection_mutation_response(result, "archived")

@app.post("/api/collection/disposition")
async def set_collection_disposition(request: CollectionDispositionRequest):
    result = orchestrator.collection.set_disposition(
        request.version_key, trade=request.trade, sell=request.sell
    )
    return _collection_mutation_response(result, "updated")

def _disposition_csv(kind: str) -> Response:
    rows = [
        item for item in orchestrator.collection.disposition_queue()["disposition_cards"]
        if int(item.get(f"{kind}_quantity") or 0) > 0
    ]
    fields = ["card_name", "english_name", "set_name", "set_code", "collector_number", "language", "rarity", f"{kind}_quantity", "market_price", "currency", "pricing_source", "version_key"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rareiq_{kind}_list.csv"'})

@app.get("/api/collection/trade-list.csv")
async def export_collection_trade_list():
    return _disposition_csv("trade")

@app.get("/api/collection/sell-list.csv")
async def export_collection_sell_list():
    return _disposition_csv("sell")

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
    host = os.getenv("RAREIQ_HOST", "127.0.0.1").strip().lower()
    host = validate_server_binding(host, REMOTE_ACCESS)
    try:
        port = int(os.getenv("RAREIQ_PORT", "8765"))
    except ValueError as exc:
        raise RuntimeError("RAREIQ_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("RAREIQ_PORT must be between 1 and 65535.")
    display_host = f"[{host}]" if ":" in host else host
    print()
    print("=" * 58)
    print("RareIQ Vision")
    print(f"Version {VERSION} — {CODENAME}")
    print(f"Build {BUILD_DATE}")
    print("Project Digital Jazz")
    print("=" * 58)
    print(f"Control: http://{display_host}:{port}/control")
    print(f"About:  http://{display_host}:{port}/about")
    print()
    uvicorn.run(
        "rareiq.web.server:app",
        host=host,
        port=port,
        reload=False,
    )




