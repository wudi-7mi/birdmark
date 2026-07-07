from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import initialize_database
from .photos import router as photos_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.mount("/media", StaticFiles(directory=settings.storage_root, check_dir=False), name="media")
app.include_router(photos_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "birdmark-api"}
