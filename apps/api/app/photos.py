from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from .auth import CurrentUser, get_current_user
from .collections import update_collection_entry
from .database import (
    connect,
    dumps_json,
    loads_json,
    row_to_dict,
)
from .inference_client import InferenceClientError, analyze_image
from .species import ensure_species_for_prediction
from .storage import (
    media_url,
    prepare_upload,
    save_crop_base64,
    save_observation_context_preview,
    save_observation_context_previews,
    save_original,
    save_thumbnail,
)


router = APIRouter(tags=["photos"])


class PhotoAnalysisFailed(Exception):
    def __init__(self, photo_id: int, message: str) -> None:
        self.photo_id = photo_id
        self.message = message
        super().__init__(message)


@router.get("/photos")
def list_photos(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ = current_user
    with connect() as db:
        rows = db.execute(
            """
            SELECT photos.*, users.username, users.display_name
            FROM photos
            JOIN users ON users.id = photos.user_id
            WHERE photos.deleted_at IS NULL
            ORDER BY photos.created_at DESC, photos.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        results = [_build_photo_detail(db, row) for row in rows]

    return {
        "results": results,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(results) if len(results) == limit else None,
    }


@router.post("/photos")
def create_photo(
    file: Annotated[UploadFile, File()],
    top_k: int = Query(default=5, ge=1, le=20),
    auto_analyze: bool = Query(default=True),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    contents = file.file.read()
    try:
        photo_id = ingest_photo_contents(
            user_id=int(current_user["id"]),
            filename=file.filename,
            contents=contents,
            top_k=top_k,
            auto_analyze=auto_analyze,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PhotoAnalysisFailed as exc:
        raise HTTPException(
            status_code=502,
            detail={"photo_id": exc.photo_id, "error": exc.message},
        ) from exc

    return get_photo(photo_id, current_user=current_user)


@router.get("/photos/{photo_id}")
def get_photo(
    photo_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    _ = current_user
    with connect() as db:
        photo = row_to_dict(
            db.execute(
                """
                SELECT photos.*, users.username, users.display_name
                FROM photos
                JOIN users ON users.id = photos.user_id
                WHERE photos.id = ? AND photos.deleted_at IS NULL
                """,
                (photo_id,),
            ).fetchone()
        )
        if photo is None:
            raise HTTPException(status_code=404, detail="Photo not found")

        observation_rows = db.execute(
            """
            SELECT *
            FROM bird_observations
            WHERE photo_id = ? AND deleted_at IS NULL
            ORDER BY id ASC
            """,
            (photo_id,),
        ).fetchall()
        context_paths = save_observation_context_previews(
            photo=photo,
            observations=[dict(row) for row in observation_rows],
        )
        observations = [
            _build_observation(
                db,
                row,
                context_path=context_paths.get(int(row["id"])),
            )
            for row in observation_rows
        ]

    return _build_photo_response(photo, observations)


@router.delete("/photos/{photo_id}")
def delete_photo(
    photo_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user["id"])
    with connect() as db:
        photo = row_to_dict(
            db.execute(
                """
                SELECT id
                FROM photos
                WHERE id = ? AND user_id = ? AND deleted_at IS NULL
                """,
                (photo_id, user_id),
            ).fetchone()
        )
        if photo is None:
            raise HTTPException(status_code=404, detail="Photo not found")

        affected_species_ids = [
            int(row["species_id"])
            for row in db.execute(
                """
                SELECT DISTINCT identifications.confirmed_species_id AS species_id
                FROM bird_observations AS observations
                JOIN identifications
                    ON identifications.observation_id = observations.id
                WHERE observations.photo_id = ?
                    AND observations.deleted_at IS NULL
                    AND identifications.confirmed_species_id IS NOT NULL
                """,
                (photo_id,),
            ).fetchall()
        ]
        db.execute(
            """
            UPDATE photos
            SET status = 'deleted',
                deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (photo_id,),
        )
        db.execute(
            """
            UPDATE bird_observations
            SET deleted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE photo_id = ? AND deleted_at IS NULL
            """,
            (photo_id,),
        )
        updated_collection_entries = [
            update_collection_entry(db, user_id=user_id, species_id=species_id)
            for species_id in affected_species_ids
        ]
        db.commit()

    return {
        "status": "deleted",
        "photo_id": photo_id,
        "updated_collection_entries": updated_collection_entries,
    }


@router.get("/me/photos")
def list_my_photos(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_observations: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        rows = db.execute(
            """
            SELECT photos.*, users.username, users.display_name
            FROM photos
            JOIN users ON users.id = photos.user_id
            WHERE photos.user_id = ? AND photos.deleted_at IS NULL
            ORDER BY photos.created_at DESC, photos.id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
        if include_observations:
            results = [_build_photo_detail(db, row) for row in rows]
        else:
            results = [_format_photo(dict(row)) for row in rows]

    return {
        "results": results,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(results) if len(results) == limit else None,
    }


def ingest_photo_contents(
    *,
    user_id: int,
    filename: str | None,
    contents: bytes,
    top_k: int,
    auto_analyze: bool = True,
) -> int:
    if not contents:
        raise ValueError("Uploaded file is empty")

    prepared = prepare_upload(contents, filename)
    with connect() as db:
        photo_id = _insert_photo(
            db,
            user_id=user_id,
            filename=filename,
            prepared=prepared,
        )
        original_path = save_original(prepared, user_id=user_id, photo_id=photo_id)
        thumb_path = save_thumbnail(prepared, user_id=user_id, photo_id=photo_id)
        db.execute(
            """
            UPDATE photos
            SET original_path = ?,
                thumb_path = ?,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (original_path, thumb_path, "processing" if auto_analyze else "ready", photo_id),
        )
        db.commit()

    if not auto_analyze:
        return photo_id

    try:
        inference_result = analyze_image(
            contents,
            filename=filename or "upload",
            top_k=top_k,
        )
    except InferenceClientError as exc:
        with connect() as db:
            db.execute(
                """
                UPDATE photos
                SET status = 'failed', error_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(exc), photo_id),
            )
            db.commit()
        raise PhotoAnalysisFailed(photo_id, str(exc)) from exc

    with connect() as db:
        _save_inference_result(db, user_id=user_id, photo_id=photo_id, result=inference_result)
        db.execute(
            """
            UPDATE photos
            SET status = 'ready', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (photo_id,),
        )
        db.commit()

    return photo_id


def _insert_photo(
    db: sqlite3.Connection,
    *,
    user_id: int,
    filename: str | None,
    prepared,
) -> int:
    cursor = db.execute(
        """
        INSERT INTO photos (
            user_id, filename, original_path, thumb_path, content_hash,
            width, height, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'processing')
        """,
        (
            user_id,
            filename,
            "",
            "",
            prepared.content_hash,
            prepared.width,
            prepared.height,
        ),
    )
    return int(cursor.lastrowid)


def _save_inference_result(
    db: sqlite3.Connection,
    *,
    user_id: int,
    photo_id: int,
    result: dict[str, Any],
) -> None:
    photo = row_to_dict(
        db.execute(
            "SELECT * FROM photos WHERE id = ?",
            (photo_id,),
        ).fetchone()
    )
    observations_for_context: list[dict[str, Any]] = []
    for item in result.get("results", []):
        box = item.get("box") or [0, 0, 0, 0]
        bbox_x1 = int(box[0])
        bbox_y1 = int(box[1])
        bbox_x2 = int(box[2])
        bbox_y2 = int(box[3])
        cursor = db.execute(
            """
            INSERT INTO bird_observations (
                photo_id, crop_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                detection_confidence, detection_source, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'recognized')
            """,
            (
                photo_id,
                "",
                bbox_x1,
                bbox_y1,
                bbox_x2,
                bbox_y2,
                item.get("detection_confidence"),
                item.get("source") or "detector",
            ),
        )
        observation_id = int(cursor.lastrowid)
        observations_for_context.append(
            {
                "id": observation_id,
                "bbox_x1": bbox_x1,
                "bbox_y1": bbox_y1,
                "bbox_x2": bbox_x2,
                "bbox_y2": bbox_y2,
            }
        )

        crop_image = item.get("crop_image") or {}
        crop_path = ""
        if crop_image.get("base64"):
            crop_path = save_crop_base64(
                crop_image["base64"],
                user_id=user_id,
                observation_id=observation_id,
            )
            db.execute(
                "UPDATE bird_observations SET crop_path = ? WHERE id = ?",
                (crop_path, observation_id),
            )

        predictions = item.get("predictions") or []
        suggested_species_id = ensure_species_for_prediction(db, predictions[0]) if predictions else None
        db.execute(
            """
            INSERT INTO identifications (
                observation_id, model_name, model_version, top_k_results,
                suggested_species_id, status
            )
            VALUES (?, 'bioclip', NULL, ?, ?, 'suggested')
            """,
            (observation_id, dumps_json(predictions), suggested_species_id),
        )
    if photo is not None:
        save_observation_context_previews(
            photo=photo,
            observations=observations_for_context,
        )


def _build_photo_detail(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    photo = dict(row)
    observations = [
        _build_observation(db, observation_row, photo=photo, include_context_preview=False)
        for observation_row in db.execute(
            """
            SELECT *
            FROM bird_observations
            WHERE photo_id = ? AND deleted_at IS NULL
            ORDER BY id ASC
            """,
            (photo["id"],),
        ).fetchall()
    ]
    return _build_photo_response(photo, observations)


def _build_observation(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    photo: dict[str, Any] | None = None,
    include_context_preview: bool = False,
    context_path: str | None = None,
) -> dict[str, Any]:
    observation = dict(row)
    context_path = context_path or (
        save_observation_context_preview(photo=photo, observation=observation)
        if include_context_preview and photo is not None
        else None
    )
    identification = row_to_dict(
        db.execute(
            """
                SELECT
                    identifications.*,
                    suggested.scientific_name AS suggested_scientific_name,
                    suggested.common_name AS suggested_common_name,
                    confirmed.scientific_name AS confirmed_scientific_name,
                    confirmed.common_name AS confirmed_common_name
                FROM identifications
                LEFT JOIN species AS suggested
                    ON suggested.id = identifications.suggested_species_id
                LEFT JOIN species AS confirmed
                    ON confirmed.id = identifications.confirmed_species_id
                WHERE observation_id = ?
                ORDER BY identifications.id DESC
                LIMIT 1
            """,
            (observation["id"],),
        ).fetchone()
    )
    if identification is not None:
        identification["top_k_results"] = loads_json(identification["top_k_results"])
    return {
        **observation,
        "crop_url": media_url(observation.get("crop_path")),
        "context_url": media_url(context_path),
        "identification": identification,
    }


def _build_photo_response(
    photo: dict[str, Any],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "photo": _format_photo(photo),
        "observations": observations,
    }


def _format_photo(photo: dict[str, Any]) -> dict[str, Any]:
    return {
        **photo,
        "original_url": media_url(photo.get("original_path")),
        "thumb_url": media_url(photo.get("thumb_path")),
    }
