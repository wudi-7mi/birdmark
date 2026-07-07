from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import router as auth_router
from .config import settings
from .collections import router as collections_router
from .database import initialize_database
from .imports import router as imports_router
from .observations import router as observations_router
from .photos import router as photos_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=settings.storage_root, check_dir=False), name="media")
app.include_router(auth_router)
app.include_router(photos_router)
app.include_router(observations_router)
app.include_router(collections_router)
app.include_router(imports_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "birdmark-api"}
