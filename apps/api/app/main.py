from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import router as auth_router
from .config import PROJECT_ROOT, settings
from .collections import router as collections_router
from .database import initialize_database
from .imports import router as imports_router
from .observations import router as observations_router
from .photos import router as photos_router


WEB_DIR = PROJECT_ROOT / "apps" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=settings.storage_root, check_dir=False), name="media")
app.mount("/static", StaticFiles(directory=WEB_DIR, check_dir=False), name="static")
app.include_router(auth_router)
app.include_router(photos_router)
app.include_router(observations_router)
app.include_router(collections_router)
app.include_router(imports_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "birdmark-api"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        return "<!doctype html><title>Birdmark</title><h1>Birdmark web is not available.</h1>"
    return index_path.read_text(encoding="utf-8")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
