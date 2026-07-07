from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from .auth import CurrentUser, get_current_user
from .database import connect, row_to_dict
from .photos import PhotoAnalysisFailed, ingest_photo_contents
from .storage import media_url


router = APIRouter(tags=["imports"])
MAX_BATCH_FILES = 50


@dataclass(frozen=True)
class QueuedBatchUpload:
    item_id: int
    filename: str | None
    contents: bytes


@router.post("/import-batches")
def create_import_batch(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
    top_k: int = Query(default=5, ge=1, le=20),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Batch upload supports at most {MAX_BATCH_FILES} files",
        )

    user_id = int(current_user["id"])
    queued_uploads: list[QueuedBatchUpload] = []
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO import_batches (
                user_id, status, total_count,
                processed_count, succeeded_count, failed_count
            )
            VALUES (?, 'queued', ?, 0, 0, 0)
            """,
            (user_id, len(files)),
        )
        batch_id = int(cursor.lastrowid)
        for file in files:
            item_cursor = db.execute(
                """
                INSERT INTO import_batch_items (batch_id, filename, status)
                VALUES (?, ?, 'queued')
                """,
                (batch_id, file.filename),
            )
            queued_uploads.append(
                QueuedBatchUpload(
                    item_id=int(item_cursor.lastrowid),
                    filename=file.filename,
                    contents=file.file.read(),
                )
            )
        db.commit()

    background_tasks.add_task(
        _process_import_batch,
        batch_id=batch_id,
        user_id=user_id,
        uploads=queued_uploads,
        top_k=top_k,
    )
    return _get_batch_response(batch_id=batch_id, user_id=user_id)


@router.get("/me/import-batches")
def list_my_import_batches(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user["id"])
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM import_batches
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, limit, offset),
        ).fetchall()
    results = [dict(row) for row in rows]
    return {
        "results": results,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(results) if len(results) == limit else None,
    }


@router.get("/import-batches/{batch_id}")
def get_import_batch(
    batch_id: int,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _get_batch_response(batch_id=batch_id, user_id=int(current_user["id"]))


def _process_import_batch(
    *,
    batch_id: int,
    user_id: int,
    uploads: list[QueuedBatchUpload],
    top_k: int,
) -> None:
    _mark_batch_processing(batch_id)
    try:
        for upload in uploads:
            _mark_item_processing(batch_id=batch_id, item_id=upload.item_id)
            try:
                photo_id = ingest_photo_contents(
                    user_id=user_id,
                    filename=upload.filename,
                    contents=upload.contents,
                    top_k=top_k,
                )
            except PhotoAnalysisFailed as exc:
                _mark_item_failed(
                    batch_id=batch_id,
                    item_id=upload.item_id,
                    photo_id=exc.photo_id,
                    error_message=exc.message,
                )
            except ValueError as exc:
                _mark_item_failed(
                    batch_id=batch_id,
                    item_id=upload.item_id,
                    photo_id=None,
                    error_message=str(exc),
                )
            except Exception as exc:
                _mark_item_failed(
                    batch_id=batch_id,
                    item_id=upload.item_id,
                    photo_id=None,
                    error_message=f"Unexpected import error: {exc}",
                )
            else:
                _mark_item_completed(
                    batch_id=batch_id,
                    item_id=upload.item_id,
                    photo_id=photo_id,
                )
    except Exception:
        _mark_batch_failed(batch_id)
        raise

    _finish_batch(batch_id)


def _mark_batch_processing(batch_id: int) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE import_batches
            SET status = 'processing', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (batch_id,),
        )
        db.commit()


def _mark_batch_failed(batch_id: int) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE import_batches
            SET status = 'failed',
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (batch_id,),
        )
        db.commit()


def _mark_item_processing(*, batch_id: int, item_id: int) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE import_batch_items
            SET status = 'processing',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        _refresh_batch_progress(db, batch_id=batch_id)
        db.commit()


def _mark_item_completed(*, batch_id: int, item_id: int, photo_id: int) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE import_batch_items
            SET status = 'completed',
                photo_id = ?,
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (photo_id, item_id),
        )
        _refresh_batch_progress(db, batch_id=batch_id)
        db.commit()


def _mark_item_failed(
    *,
    batch_id: int,
    item_id: int,
    photo_id: int | None,
    error_message: str,
) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE import_batch_items
            SET status = 'failed',
                photo_id = ?,
                error_message = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (photo_id, error_message, item_id),
        )
        _refresh_batch_progress(db, batch_id=batch_id)
        db.commit()


def _finish_batch(batch_id: int) -> None:
    with connect() as db:
        counts = _batch_counts(db, batch_id)
        status = "completed" if counts["failed_count"] == 0 else "completed_with_errors"
        _refresh_batch_progress(db, batch_id=batch_id, status=status, completed=True)
        db.commit()


def _refresh_batch_progress(
    db,
    *,
    batch_id: int,
    status: str = "processing",
    completed: bool = False,
) -> None:
    counts = _batch_counts(db, batch_id)
    completed_sql = ", completed_at = CURRENT_TIMESTAMP" if completed else ""
    db.execute(
        f"""
        UPDATE import_batches
        SET status = ?,
            processed_count = ?,
            succeeded_count = ?,
            failed_count = ?,
            updated_at = CURRENT_TIMESTAMP
            {completed_sql}
        WHERE id = ?
        """,
        (
            status,
            counts["processed_count"],
            counts["succeeded_count"],
            counts["failed_count"],
            batch_id,
        ),
    )


def _batch_counts(db, batch_id: int) -> dict[str, int]:
    row = db.execute(
        """
        SELECT
            SUM(CASE WHEN status IN ('completed', 'failed') THEN 1 ELSE 0 END)
                AS processed_count,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)
                AS succeeded_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)
                AS failed_count
        FROM import_batch_items
        WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    return {
        "processed_count": int(row["processed_count"] or 0),
        "succeeded_count": int(row["succeeded_count"] or 0),
        "failed_count": int(row["failed_count"] or 0),
    }


def _get_batch_response(*, batch_id: int, user_id: int) -> dict[str, Any]:
    with connect() as db:
        batch = row_to_dict(
            db.execute(
                """
                SELECT *
                FROM import_batches
                WHERE id = ? AND user_id = ?
                """,
                (batch_id, user_id),
            ).fetchone()
        )
        if batch is None:
            raise HTTPException(status_code=404, detail="Import batch not found")

        rows = db.execute(
            """
            SELECT
                import_batch_items.*,
                photos.original_path,
                photos.thumb_path,
                photos.status AS photo_status
            FROM import_batch_items
            LEFT JOIN photos ON photos.id = import_batch_items.photo_id
            WHERE import_batch_items.batch_id = ?
            ORDER BY import_batch_items.id ASC
            """,
            (batch_id,),
        ).fetchall()

    return {
        "batch": batch,
        "items": [_format_batch_item(dict(row)) for row in rows],
    }


def _format_batch_item(item: dict[str, Any]) -> dict[str, Any]:
    photo_id = item.pop("photo_id")
    original_path = item.pop("original_path")
    thumb_path = item.pop("thumb_path")
    photo_status = item.pop("photo_status")
    item["photo"] = None
    if photo_id is not None:
        item["photo"] = {
            "id": photo_id,
            "status": photo_status,
            "original_url": media_url(original_path),
            "thumb_url": media_url(thumb_path),
        }
    return item
