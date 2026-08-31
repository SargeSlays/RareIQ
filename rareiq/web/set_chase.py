"""Small independent router; no camera, recognition or OBS mutations."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse

from rareiq.services.set_chase_service import RevisionConflict, image_path


def create_set_chase_router(service, index, read_json, static: Path):
    router = APIRouter()

    @router.get("/overlay/set-chase")
    async def overlay():
        return FileResponse(static / "overlay_set_chase.html", headers={"Cache-Control": "no-store, max-age=0"})

    @router.get("/creator/set-chase")
    async def editor():
        return FileResponse(static / "set_chase_editor.html", headers={"Cache-Control": "no-store, max-age=0"})

    @router.get("/api/creator/set-chase")
    async def settings():
        return service.settings()

    @router.get("/api/creator/set-chase/status")
    async def status(preview: bool = False):
        return service.snapshot(preview=preview)

    @router.post("/api/creator/set-chase/{action}")
    async def change(action: str, request: Request):
        body = await read_json(request)
        if set(body) - {"revision", "config"}:
            raise HTTPException(422, "Unknown set-chase fields")
        try:
            return await asyncio.to_thread(service.change, action, body.get("revision"), body.get("config"))
        except RevisionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503, "Settings were not saved. Check storage and retry.") from exc

    @router.get("/api/creator/set-chase/sets")
    async def sets():
        return {"ok": True, "sets": await asyncio.to_thread(index.set_options)}

    @router.get("/api/creator/set-chase/cards")
    async def cards(set_id: str = Query(min_length=1, max_length=120), language: str = Query(min_length=1, max_length=120),
                    q: str = Query(default="", max_length=120), rarity: list[str] | None = Query(default=None, max_length=64),
                    highest: bool = False):
        if rarity is not None and (highest or any(len(value) > 120 for value in rarity)):
            raise HTTPException(422, "Choose explicit rarities or highest rarity, with labels up to 120 characters")
        search = await asyncio.to_thread(index.catalog_search, q.strip(), limit=100, set_id=set_id, language=language,
                                         rarity=rarity, rarity_first=True, highest_rarity_only=highest)
        results = []
        for row in search["results"]:
            try:
                art = image_path(row.get("reference_image_url") or "")
            except ValueError:
                art = ""
            results.append({"id": str(row.get("id") or ""), "name": str(row.get("printed_name") or row.get("name") or "Unnamed card"),
                "set_id": str(row.get("set_id") or ""), "language": str(row.get("language") or ""),
                "collector_number": str(row.get("collector_number") or ""), "image_url": art,
                "rarity": str(row.get("rarity") or "")})
        return {"ok": True, "results": results, "limit": 100, "total": search["total"],
                "set_total": search["set_total"], "rarities": search["rarities"],
                "selected_rarities": search.get("selected_rarities")}

    return router
