from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings


@dataclass(frozen=True)
class PreparedImage:
    original_bytes: bytes
    image: Image.Image
    content_hash: str
    width: int
    height: int
    extension: str


def prepare_upload(contents: bytes, filename: str | None) -> PreparedImage:
    try:
        with Image.open(BytesIO(contents)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("Uploaded file is not an image") from exc

    content_hash = hashlib.sha256(contents).hexdigest()
    return PreparedImage(
        original_bytes=contents,
        image=image,
        content_hash=content_hash,
        width=image.width,
        height=image.height,
        extension=_extension_for(filename),
    )


def save_original(prepared: PreparedImage, *, user_id: int, photo_id: int) -> str:
    rel_path = _dated_path("originals", user_id) / f"{photo_id}_{prepared.content_hash[:12]}{prepared.extension}"
    abs_path = settings.storage_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(prepared.original_bytes)
    return rel_path.as_posix()


def save_thumbnail(prepared: PreparedImage, *, user_id: int, photo_id: int) -> str:
    rel_path = _dated_path("thumbs", user_id) / f"{photo_id}.jpg"
    abs_path = settings.storage_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    thumb = prepared.image.copy()
    thumb.thumbnail((640, 640))
    thumb.save(abs_path, format="JPEG", quality=86, optimize=True)
    return rel_path.as_posix()


def save_crop_base64(crop_base64: str, *, user_id: int, observation_id: int) -> str:
    rel_path = _dated_path("crops", user_id) / f"{observation_id}.png"
    abs_path = settings.storage_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(base64.b64decode(crop_base64))
    return rel_path.as_posix()


def media_url(path: str | None) -> str | None:
    if not path:
        return None
    return f"/media/{path}"


def _dated_path(kind: str, user_id: int) -> Path:
    now = datetime.now()
    return Path(kind) / f"{now:%Y}" / f"{now:%m}" / f"user_{user_id}"


def _extension_for(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"
