from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from .auth import CurrentUser, get_current_user
from .config import settings
from .collections import update_collection_entry
from .database import connect, dumps_json, loads_json, row_to_dict
from .inference_client import InferenceClientError, analyze_image
from .species import ensure_species, ensure_species_for_prediction
from .storage import media_url, save_crop_image, save_observation_context_preview


router = APIRouter(tags=["observations"])


class ConfirmObservationRequest(BaseModel):
    species_id: int | None = None
    prediction_index: int | None = Field(default=0, ge=0)
    scientific_name: str | None = None
    common_name: str | None = None
    chinese_name: str | None = None


class ManualObservationRequest(BaseModel):
    bbox_x1: int = Field(ge=0)
    bbox_y1: int = Field(ge=0)
    bbox_x2: int = Field(ge=0)
    bbox_y2: int = Field(ge=0)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/photos/{photo_id}/observations/manual")
def create_manual_observation(
    photo_id: int,
    payload: ManualObservationRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user["id"])
    with connect() as db:
        photo = row_to_dict(
            db.execute(
                """
                SELECT *
                FROM photos
                WHERE id = ?
                    AND user_id = ?
                    AND deleted_at IS NULL
                """,
                (photo_id, user_id),
            ).fetchone()
        )
        if photo is None:
            raise HTTPException(status_code=404, detail="Photo not found")

        x1, y1, x2, y2 = _validate_bbox(
            payload,
            width=int(photo["width"]),
            height=int(photo["height"]),
        )
        if not photo.get("original_path"):
            raise HTTPException(status_code=404, detail="Original image file not found")
        original_path = settings.storage_root / photo["original_path"]
        if not original_path.is_file():
            raise HTTPException(status_code=404, detail="Original image file not found")

        try:
            with Image.open(original_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                crop = image.crop((x1, y1, x2, y2)).copy()
        except OSError as exc:
            raise HTTPException(status_code=400, detail="Original image could not be read") from exc

        cursor = db.execute(
            """
            INSERT INTO bird_observations (
                photo_id, crop_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                detection_confidence, detection_source, status
            )
            VALUES (?, '', ?, ?, ?, ?, NULL, 'manual', 'detected')
            """,
            (photo_id, x1, y1, x2, y2),
        )
        observation_id = int(cursor.lastrowid)
        crop_path = save_crop_image(crop, user_id=user_id, observation_id=observation_id)
        db.execute(
            """
            UPDATE bird_observations
            SET crop_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (crop_path, observation_id),
        )
        save_observation_context_preview(
            photo=photo,
            observation={
                "id": observation_id,
                "bbox_x1": x1,
                "bbox_y1": y1,
                "bbox_x2": x2,
                "bbox_y2": y2,
            },
        )
        db.commit()

    crop_buffer = BytesIO()
    crop.save(crop_buffer, format="PNG")
    try:
        inference_result = analyze_image(
            crop_buffer.getvalue(),
            filename=f"manual_observation_{observation_id}.png",
            top_k=payload.top_k,
            include_crop_images=False,
            full_image_fallback=True,
        )
    except InferenceClientError as exc:
        with connect() as db:
            db.execute(
                """
                UPDATE bird_observations
                SET status = 'failed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (observation_id,),
            )
            db.commit()
        raise HTTPException(
            status_code=502,
            detail={
                "photo_id": photo_id,
                "observation_id": observation_id,
                "error": str(exc),
            },
        ) from exc

    predictions = _extract_predictions(inference_result)
    with connect() as db:
        suggested_species_id = ensure_species_for_prediction(db, predictions[0]) if predictions else None
        db.execute(
            """
            INSERT INTO identifications (
                observation_id, model_name, model_version, top_k_results,
                suggested_species_id, status
            )
            VALUES (?, 'bioclip', NULL, ?, ?, ?)
            """,
            (
                observation_id,
                dumps_json(predictions),
                suggested_species_id,
                "suggested" if predictions else "failed",
            ),
        )
        db.execute(
            """
            UPDATE bird_observations
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ("recognized" if predictions else "failed", observation_id),
        )
        db.execute(
            """
            UPDATE photos
            SET status = 'ready', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (photo_id,),
        )
        db.commit()
        observation = _get_observation_response(db, observation_id)

    return {"observation": observation}


@router.post("/observations/{observation_id}/confirm")
def confirm_observation(
    observation_id: int,
    payload: ConfirmObservationRequest | None = None,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    request = payload or ConfirmObservationRequest()

    with connect() as db:
        user_id = int(current_user["id"])
        observation = _get_owned_observation(db, observation_id, user_id)
        identification = _get_latest_identification(db, observation_id)
        if identification is None:
            raise HTTPException(status_code=404, detail="Identification not found")

        top_k = loads_json(identification["top_k_results"])
        previous_species_id = identification["confirmed_species_id"]
        species_id = _resolve_confirmed_species_id(
            db,
            request=request,
            top_k=top_k,
        )

        db.execute(
            """
            UPDATE identifications
            SET confirmed_species_id = ?,
                confirmed_by_user_id = ?,
                status = ?,
                confirmed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                species_id,
                user_id,
                "corrected" if request.scientific_name or request.species_id else "confirmed",
                identification["id"],
            ),
        )
        db.execute(
            """
            UPDATE bird_observations
            SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (observation_id,),
        )
        collection_entry = None
        if observation.get("collected_at"):
            collection_entry = _nullable_collection_entry(
                update_collection_entry(
                    db,
                    user_id=user_id,
                    species_id=species_id,
                )
            )
        if previous_species_id is not None and int(previous_species_id) != species_id:
            update_collection_entry(db, user_id=user_id, species_id=int(previous_species_id))
        db.commit()

        updated = _get_observation_response(db, observation_id)

    return {
        "observation": updated,
        "collection_entry": collection_entry,
    }


@router.post("/observations/{observation_id}/collect")
def collect_observation(
    observation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        _get_owned_observation(db, observation_id, user_id)
        identification = _get_latest_identification(db, observation_id)
        if identification is None:
            raise HTTPException(status_code=404, detail="Identification not found")

        top_k = loads_json(identification["top_k_results"])
        previous_species_id = identification["confirmed_species_id"]
        species_id = int(previous_species_id) if previous_species_id is not None else _resolve_confirmed_species_id(
            db,
            request=ConfirmObservationRequest(prediction_index=0),
            top_k=top_k,
        )

        db.execute(
            """
            UPDATE identifications
            SET confirmed_species_id = ?,
                confirmed_by_user_id = ?,
                status = CASE
                    WHEN status = 'corrected' THEN status
                    ELSE 'confirmed'
                END,
                confirmed_at = COALESCE(confirmed_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (species_id, user_id, identification["id"]),
        )
        db.execute(
            """
            UPDATE bird_observations
            SET status = 'confirmed',
                collected_by_user_id = ?,
                collected_at = COALESCE(collected_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id, observation_id),
        )
        collection_entry = _nullable_collection_entry(
            update_collection_entry(
                db,
                user_id=user_id,
                species_id=species_id,
            )
        )
        if previous_species_id is not None and int(previous_species_id) != species_id:
            update_collection_entry(db, user_id=user_id, species_id=int(previous_species_id))
        db.commit()
        updated = _get_observation_response(db, observation_id)

    return {
        "observation": updated,
        "collection_entry": collection_entry,
    }


@router.post("/observations/{observation_id}/uncollect")
def uncollect_observation(
    observation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        _get_owned_observation(db, observation_id, user_id)
        identification = _get_latest_identification(db, observation_id)
        previous_species_id = (
            int(identification["confirmed_species_id"])
            if identification is not None and identification["confirmed_species_id"] is not None
            else None
        )
        db.execute(
            """
            UPDATE bird_observations
            SET collected_by_user_id = NULL,
                collected_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (observation_id,),
        )
        collection_entry = _nullable_collection_entry(
            update_collection_entry(db, user_id=user_id, species_id=previous_species_id)
        ) if previous_species_id is not None else None
        db.commit()
        updated = _get_observation_response(db, observation_id)

    return {
        "observation": updated,
        "collection_entry": collection_entry,
    }


@router.post("/observations/{observation_id}/mark-unknown")
def mark_observation_unknown(
    observation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        _get_owned_observation(db, observation_id, user_id)
        identification = _get_latest_identification(db, observation_id)
        if identification is None:
            raise HTTPException(status_code=404, detail="Identification not found")

        previous_species_id = identification["confirmed_species_id"]
        db.execute(
            """
            UPDATE identifications
            SET confirmed_species_id = NULL,
                confirmed_by_user_id = NULL,
                status = 'unknown',
                confirmed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (identification["id"],),
        )
        db.execute(
            """
            UPDATE bird_observations
            SET status = 'recognized',
                collected_by_user_id = NULL,
                collected_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (observation_id,),
        )
        if previous_species_id is not None:
            update_collection_entry(db, user_id=user_id, species_id=int(previous_species_id))
        db.commit()
        updated = _get_observation_response(db, observation_id)

    return {"observation": updated}


@router.post("/observations/{observation_id}/reject")
def reject_observation(
    observation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    with connect() as db:
        user_id = int(current_user["id"])
        _get_owned_observation(db, observation_id, user_id)
        identification = _get_latest_identification(db, observation_id)
        previous_species_id = (
            identification["confirmed_species_id"]
            if identification is not None
            else None
        )

        if identification is not None:
            db.execute(
                """
                UPDATE identifications
                SET confirmed_species_id = NULL,
                    confirmed_by_user_id = NULL,
                    status = 'unknown',
                    confirmed_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (identification["id"],),
            )
        db.execute(
            """
            UPDATE bird_observations
            SET status = 'rejected',
                collected_by_user_id = NULL,
                collected_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (observation_id,),
        )
        if previous_species_id is not None:
            update_collection_entry(db, user_id=user_id, species_id=int(previous_species_id))
        db.commit()
        updated = _get_observation_response(db, observation_id)

    return {"observation": updated}


def _resolve_confirmed_species_id(
    db,
    *,
    request: ConfirmObservationRequest,
    top_k: list[dict[str, Any]],
) -> int:
    if request.species_id is not None:
        existing = db.execute(
            "SELECT id FROM species WHERE id = ?",
            (request.species_id,),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=400, detail="species_id does not exist")
        return int(request.species_id)

    if request.scientific_name:
        try:
            return ensure_species(
                db,
                scientific_name=request.scientific_name,
                common_name=request.common_name,
                chinese_name=request.chinese_name,
                source="manual",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    prediction_index = request.prediction_index or 0
    if prediction_index >= len(top_k):
        raise HTTPException(status_code=400, detail="prediction_index is out of range")

    species_id = ensure_species_for_prediction(db, top_k[prediction_index])
    if species_id is None:
        raise HTTPException(status_code=400, detail="Prediction has no species")
    return species_id


def _validate_bbox(
    payload: ManualObservationRequest,
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x1 = min(payload.bbox_x1, payload.bbox_x2)
    y1 = min(payload.bbox_y1, payload.bbox_y2)
    x2 = max(payload.bbox_x1, payload.bbox_x2)
    y2 = max(payload.bbox_y1, payload.bbox_y2)

    if x2 > width or y2 > height:
        raise HTTPException(status_code=400, detail="bbox is outside the photo bounds")
    if x2 - x1 < 10 or y2 - y1 < 10:
        raise HTTPException(status_code=400, detail="bbox is too small")
    return x1, y1, x2, y2


def _extract_predictions(result: dict[str, Any]) -> list[dict[str, Any]]:
    direct = result.get("predictions")
    if isinstance(direct, list):
        return direct

    for item in result.get("results") or []:
        if not isinstance(item, dict):
            continue
        predictions = item.get("predictions") or item.get("top_k_results") or item.get("top_k")
        if isinstance(predictions, list):
            return predictions
    return []


def _get_owned_observation(db, observation_id: int, user_id: int) -> dict[str, Any]:
    observation = row_to_dict(
        db.execute(
            """
            SELECT observations.*
            FROM bird_observations AS observations
            JOIN photos ON photos.id = observations.photo_id
            WHERE observations.id = ?
                AND photos.user_id = ?
                AND observations.deleted_at IS NULL
                AND photos.deleted_at IS NULL
            """,
            (observation_id, user_id),
        ).fetchone()
    )
    if observation is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation


def _get_latest_identification(db, observation_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        db.execute(
            """
            SELECT *
            FROM identifications
            WHERE observation_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (observation_id,),
        ).fetchone()
    )


def _nullable_collection_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    return entry or None


def _get_observation_response(db, observation_id: int) -> dict[str, Any]:
    observation = row_to_dict(
        db.execute(
            "SELECT * FROM bird_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    )
    if observation is None:
        raise HTTPException(status_code=404, detail="Observation not found")

    photo = row_to_dict(
        db.execute(
            "SELECT * FROM photos WHERE id = ?",
            (observation["photo_id"],),
        ).fetchone()
    )
    context_path = (
        save_observation_context_preview(photo=photo, observation=observation)
        if photo is not None
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
            WHERE identifications.observation_id = ?
            ORDER BY identifications.id DESC
            LIMIT 1
            """,
            (observation_id,),
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
