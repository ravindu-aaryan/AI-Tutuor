"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import lessons, sessions, students, textbooks
from .config import get_settings
from .db import init_db
from .llm import llm_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AI Personal Tutor", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for router in (students.router, textbooks.router, lessons.router, sessions.router):
        app.include_router(router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "llm": llm_status()}

    # Serve the built frontend (npm run build) from the same origin when present.
    dist = get_settings().frontend_dist
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = dist / path
            if path and candidate.is_file() and dist in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
