"""Isolated browser-QA server; supply a NEW evidence directory on the data drive.

Run this, then qa_studio_scene_activity.cjs. Never uses the production scene database
or starts application lifespan tasks (cameras, replay, OCR, recording, etc.).
"""
from contextlib import asynccontextmanager
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rareiq.web import server
from rareiq.services.production_scene_store import ProductionSceneStore
import uvicorn


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Supply a new, isolated evidence directory")
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    legacy = root / "empty.json"
    legacy.write_text("[]", encoding="utf-8")
    server.production_scene_store = ProductionSceneStore(root / "scene-qa.sqlite3", legacy, [])
    server.PRODUCTION_SCENES = []

    @asynccontextmanager
    async def no_hardware_lifespan(app):
        yield

    server.app.router.lifespan_context = no_hardware_lifespan

    @server.app.middleware("http")
    async def block_other_mutations(request, call_next):
        if request.method not in {"GET", "HEAD"} and not (
            request.method == "POST" and request.url.path == "/api/production/scenes"
        ):
            return server.JSONResponse(status_code=403, content={"reason": "blocked_in_scene_fixture"})
        return await call_next(request)

    @server.app.get("/__qa__/scene-fixture")
    async def fixture_marker():
        return {"isolated_scene_fixture": True}

    uvicorn.run(server.app, host="127.0.0.1", port=8767, log_level="error")


if __name__ == "__main__":
    main()
