from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import CurrentUser, get_current_user
from .collections import update_collection_entry
from .database import connect, loads_json, row_to_dict
from .species import ensure_species, ensure_species_for_prediction
from .storage import media_url


router = APIRouter(tags=["observations"])


class ConfirmObservationRequest(BaseModel):
    species_id: int | None = None
    prediction_index: int | None = Field(default=0, ge=0)
    scientific_name: str | None = None
    common_name: str | None = None
    chinese_name: str | None = None


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
        collection_entry = update_collection_entry(
            db,
            user_id=user_id,
            species_id=species_id,
        )
        if previous_species_id is not None and int(previous_species_id) != species_id:
            update_collection_entry(db, user_id=user_id, species_id=int(previous_species_id))
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
            SET status = 'recognized', updated_at = CURRENT_TIMESTAMP
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
            SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
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


def _get_observation_response(db, observation_id: int) -> dict[str, Any]:
    observation = row_to_dict(
        db.execute(
            "SELECT * FROM bird_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
    )
    if observation is None:
        raise HTTPException(status_code=404, detail="Observation not found")

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
        "identification": identification,
    }
