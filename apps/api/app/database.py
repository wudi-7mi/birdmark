from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    avatar_path TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT,
    original_path TEXT,
    thumb_path TEXT,
    content_hash TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    taken_at TEXT,
    location_name TEXT,
    latitude REAL,
    longitude REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    succeeded_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS import_batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES import_batches(id),
    photo_id INTEGER REFERENCES photos(id),
    filename TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bird_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL REFERENCES photos(id),
    crop_path TEXT,
    bbox_x1 INTEGER NOT NULL,
    bbox_y1 INTEGER NOT NULL,
    bbox_x2 INTEGER NOT NULL,
    bbox_y2 INTEGER NOT NULL,
    detection_confidence REAL,
    detection_source TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    collected_by_user_id INTEGER REFERENCES users(id),
    collected_at TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS species (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scientific_name TEXT NOT NULL UNIQUE,
    common_name TEXT,
    chinese_name TEXT,
    genus TEXT,
    family TEXT,
    order_name TEXT,
    source TEXT,
    external_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS identifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id INTEGER NOT NULL REFERENCES bird_observations(id),
    model_name TEXT NOT NULL,
    model_version TEXT,
    top_k_results TEXT NOT NULL,
    suggested_species_id INTEGER REFERENCES species(id),
    confirmed_species_id INTEGER REFERENCES species(id),
    confirmed_by_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL,
    confirmed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collection_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    species_id INTEGER NOT NULL REFERENCES species(id),
    first_observation_id INTEGER REFERENCES bird_observations(id),
    representative_observation_id INTEGER REFERENCES bird_observations(id),
    representative_photo_id INTEGER REFERENCES photos(id),
    observation_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, species_id)
);
"""


def initialize_database() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)
        migrate_database(db)
        ensure_default_user(db)
        db.commit()


def migrate_database(db: sqlite3.Connection) -> None:
    _ensure_column(
        db,
        table="bird_observations",
        column="collected_by_user_id",
        ddl="ALTER TABLE bird_observations ADD COLUMN collected_by_user_id INTEGER REFERENCES users(id)",
    )
    _ensure_column(
        db,
        table="bird_observations",
        column="collected_at",
        ddl="ALTER TABLE bird_observations ADD COLUMN collected_at TEXT",
    )
    db.execute(
        """
        UPDATE bird_observations
        SET collected_by_user_id = COALESCE(
                collected_by_user_id,
                (SELECT photos.user_id FROM photos WHERE photos.id = bird_observations.photo_id)
            ),
            collected_at = COALESCE(
                collected_at,
                (
                    SELECT identifications.confirmed_at
                    FROM identifications
                    WHERE identifications.observation_id = bird_observations.id
                        AND identifications.confirmed_species_id IS NOT NULL
                    ORDER BY identifications.id DESC
                    LIMIT 1
                ),
                CURRENT_TIMESTAMP
            )
        WHERE collected_at IS NULL
            AND status = 'confirmed'
            AND EXISTS (
                SELECT 1
                FROM identifications
                WHERE identifications.observation_id = bird_observations.id
                    AND identifications.confirmed_species_id IS NOT NULL
            )
        """
    )


def _ensure_column(
    db: sqlite3.Connection,
    *,
    table: str,
    column: str,
    ddl: str,
) -> None:
    existing_columns = {
        str(row["name"])
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing_columns:
        db.execute(ddl)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(settings.database_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
    finally:
        db.close()


def ensure_default_user(db: sqlite3.Connection) -> int:
    existing = db.execute(
        "SELECT id FROM users WHERE email = ?",
        (settings.default_user_email,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    cursor = db.execute(
        """
        INSERT INTO users (email, username, display_name, password_hash)
        VALUES (?, ?, ?, ?)
        """,
        (
            settings.default_user_email,
            settings.default_username,
            settings.default_display_name,
            None,
        ),
    )
    return int(cursor.lastrowid)


def get_default_user_id(db: sqlite3.Connection) -> int:
    return ensure_default_user(db)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads_json(value: str) -> Any:
    return json.loads(value)
