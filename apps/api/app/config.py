from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Birdmark Business API"
    database_path: Path = PROJECT_ROOT / "storage" / "birdmark.sqlite3"
    storage_root: Path = PROJECT_ROOT / "storage"
    inference_base_url: str = os.environ.get(
        "BIRDMARK_INFERENCE_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")
    default_user_email: str = "local@birdmark"
    default_username: str = "local"
    default_display_name: str = "Local User"


settings = Settings()
