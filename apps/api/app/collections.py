from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from .auth import CurrentUser, get_current_user
from .database import connect
from .storage import media_url


router = APIRouter(tags=["collections"])


@router.get("/me/collection")
def list_my_collection(
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        rows = db.execute(
            """
            SELECT
                collection_entries.*,
                species.scientific_name,
                species.common_name,
                species.chinese_name,
                photos.thumb_path,
                observations.crop_path
            FROM collection_entries
            JOIN species ON species.id = collection_entries.species_id
            LEFT JOIN photos ON photos.id = collection_entries.representative_photo_id
            LEFT JOIN bird_observations AS observations
                ON observations.id = collection_entries.representative_observation_id
            WHERE collection_entries.user_id = ?
            ORDER BY collection_entries.last_seen_at DESC, collection_entries.id DESC
            """,
            (user_id,),
        ).fetchall()

    return {"results": [_format_collection_entry(dict(row)) for row in rows]}


def update_collection_entry(
    db: sqlite3.Connection,
    *,
    user_id: int,
    species_id: int,
) -> dict[str, Any]:
    confirmed_rows = db.execute(
        """
        SELECT
            observations.id AS observation_id,
            observations.photo_id AS photo_id,
            observations.created_at AS observed_at
        FROM bird_observations AS observations
        JOIN photos ON photos.id = observations.photo_id
        JOIN identifications ON identifications.observation_id = observations.id
        WHERE photos.user_id = ?
            AND observations.status = 'confirmed'
            AND observations.collected_at IS NOT NULL
            AND observations.deleted_at IS NULL
            AND photos.deleted_at IS NULL
            AND identifications.confirmed_species_id = ?
        ORDER BY observations.created_at ASC, observations.id ASC
        """,
        (user_id, species_id),
    ).fetchall()

    existing = db.execute(
        """
        SELECT id FROM collection_entries
        WHERE user_id = ? AND species_id = ?
        """,
        (user_id, species_id),
    ).fetchone()

    if not confirmed_rows:
        if existing is not None:
            db.execute("DELETE FROM collection_entries WHERE id = ?", (existing["id"],))
        return {}

    first = confirmed_rows[0]
    last = confirmed_rows[-1]
    values = (
        int(first["observation_id"]),
        int(first["observation_id"]),
        int(first["photo_id"]),
        len(confirmed_rows),
        first["observed_at"],
        last["observed_at"],
    )

    if existing is None:
        cursor = db.execute(
            """
            INSERT INTO collection_entries (
                user_id, species_id, first_observation_id,
                representative_observation_id, representative_photo_id,
                observation_count, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, species_id, *values),
        )
        collection_id = int(cursor.lastrowid)
    else:
        collection_id = int(existing["id"])
        db.execute(
            """
            UPDATE collection_entries
            SET first_observation_id = ?,
                representative_observation_id = ?,
                representative_photo_id = ?,
                observation_count = ?,
                first_seen_at = ?,
                last_seen_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*values, collection_id),
        )

    return dict(
        db.execute(
            """
            SELECT
                collection_entries.*,
                species.scientific_name,
                species.common_name,
                species.chinese_name
            FROM collection_entries
            JOIN species ON species.id = collection_entries.species_id
            WHERE collection_entries.id = ?
            """,
            (collection_id,),
        ).fetchone()
    )


def _format_collection_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        **entry,
        "thumb_url": media_url(entry.get("thumb_path")),
        "crop_url": media_url(entry.get("crop_path")),
    }
