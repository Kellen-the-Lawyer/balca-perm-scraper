"""
PERM Decisions Research API — application assembly.
Domain logic lives in core.py and routers/.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import database, ensure_operational_schema
import kanban as kanban_module
from routers import (aao, balca, checklists, eb_inventory, extraction, govinfo, ina,
                     oflc, perm_verify, policy, processing_times, projects, rag, regulations,
                     search_all, soc_suggest, visa_bulletin, wage_level, wages)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    await ensure_operational_schema()
    await kanban_module.ensure_kanban_schema(database)
    yield
    await database.disconnect()


app = FastAPI(title="PERM Decisions Research API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(kanban_module.register_routes(database))
for _r in (balca, projects, aao, regulations, policy, govinfo, search_all, extraction,
           ina, checklists, rag, oflc, visa_bulletin, eb_inventory, wages, wage_level,
           perm_verify, soc_suggest):
    app.include_router(_r.router)
app.include_router(processing_times.router)

FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Serve the Vite app in production while preserving API 404s."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        requested_file = FRONTEND_DIST / full_path
        if full_path and requested_file.is_file():
            return FileResponse(requested_file)

        # index.html must never be cached — it references content-hashed
        # bundles, and a stale copy points browsers at deleted JS after deploys.
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache"},
        )
