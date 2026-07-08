from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip().strip("\"'")
        os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    raw_value = os.environ.get(name)
    if not raw_value:
        return default

    value = Path(os.path.expandvars(os.path.expanduser(raw_value)))
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str = "Birdmark Business API"
    storage_root: Path = _path_from_env("BIRDMARK_STORAGE_ROOT", PROJECT_ROOT / "storage")
    database_path: Path = _path_from_env(
        "BIRDMARK_DATABASE_PATH",
        storage_root / "birdmark.sqlite3",
    )
    web_dir: Path = _path_from_env("BIRDMARK_WEB_DIR", PROJECT_ROOT / "apps" / "web")
    inference_base_url: str = os.environ.get(
        "BIRDMARK_INFERENCE_URL",
        "http://127.0.0.1:8000",
    ).rstrip("/")
    default_user_email: str = "local@birdmark"
    default_username: str = "local"
    default_display_name: str = "Local User"


settings = Settings()
