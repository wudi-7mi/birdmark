from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from .database import (
    connect,
    dumps_json,
    get_default_user_id,
    loads_json,
    row_to_dict,
)
from .inference_client import InferenceClientError, analyze_image
from .storage import media_url, prepare_upload, save_crop_base64, save_original, save_thumbnail


router = APIRouter(tags=["photos"])


@router.post("/photos")
def create_photo(
    file: Annotated[UploadFile, File()],
    top_k: int = 5,
) -> dict[str, Any]:
    contents = file.file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        prepared = prepare_upload(contents, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with connect() as db:
        user_id = get_default_user_id(db)
        photo_id = _insert_photo(db, user_id=user_id, file=file, prepared=prepared)
        original_path = save_original(prepared, user_id=user_id, photo_id=photo_id)
        thumb_path = save_thumbnail(prepared, user_id=user_id, photo_id=photo_id)
        db.execute(
            """
            UPDATE photos
            SET original_path = ?, thumb_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (original_path, thumb_path, photo_id),
        )
        db.commit()

    try:
        inference_result = analyze_image(
            contents,
            filename=file.filename or "upload",
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
        raise HTTPException(
            status_code=502,
            detail={"photo_id": photo_id, "error": str(exc)},
        ) from exc

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

    return get_photo(photo_id)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int) -> dict[str, Any]:
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

        observations = [
            _build_observation(db, row)
            for row in db.execute(
                """
                SELECT *
                FROM bird_observations
                WHERE photo_id = ? AND deleted_at IS NULL
                ORDER BY id ASC
                """,
                (photo_id,),
            ).fetchall()
        ]

    return {
        "photo": _format_photo(photo),
        "observations": observations,
    }


@router.get("/me/photos")
def list_my_photos() -> dict[str, Any]:
    with connect() as db:
        user_id = get_default_user_id(db)
        rows = db.execute(
            """
            SELECT *
            FROM photos
            WHERE user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 100
            """,
            (user_id,),
        ).fetchall()
    return {"results": [_format_photo(dict(row)) for row in rows]}


def _insert_photo(
    db: sqlite3.Connection,
    *,
    user_id: int,
    file: UploadFile,
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
            file.filename,
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
    for item in result.get("results", []):
        box = item.get("box") or [0, 0, 0, 0]
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
                int(box[0]),
                int(box[1]),
                int(box[2]),
                int(box[3]),
                item.get("detection_confidence"),
                item.get("source") or "detector",
            ),
        )
        observation_id = int(cursor.lastrowid)

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
        suggested_species_id = _ensure_species_for_prediction(db, predictions[0]) if predictions else None
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


def _ensure_species_for_prediction(
    db: sqlite3.Connection,
    prediction: dict[str, Any],
) -> int | None:
    scientific_name = prediction.get("species")
    if not scientific_name:
        return None

    existing = db.execute(
        "SELECT id FROM species WHERE scientific_name = ?",
        (scientific_name,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])

    cursor = db.execute(
        """
        INSERT INTO species (
            scientific_name, common_name, genus, family, source
        )
        VALUES (?, ?, ?, ?, 'bioclip')
        """,
        (
            scientific_name,
            prediction.get("common_name"),
            prediction.get("genus"),
            prediction.get("family"),
        ),
    )
    return int(cursor.lastrowid)


def _build_observation(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    observation = dict(row)
    identification = row_to_dict(
        db.execute(
            """
            SELECT identifications.*, species.scientific_name, species.common_name
            FROM identifications
            LEFT JOIN species ON species.id = identifications.suggested_species_id
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
        "identification": identification,
    }


def _format_photo(photo: dict[str, Any]) -> dict[str, Any]:
    return {
        **photo,
        "original_url": media_url(photo.get("original_path")),
        "thumb_url": media_url(photo.get("thumb_path")),
    }
