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


def save_crop_image(image: Image.Image, *, user_id: int, observation_id: int) -> str:
    rel_path = _dated_path("crops", user_id) / f"{observation_id}.png"
    abs_path = settings.storage_root / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(abs_path, format="PNG")
    return rel_path.as_posix()


def save_observation_context_preview(
    *,
    photo: dict,
    observation: dict,
    size: int = 256,
) -> str | None:
    observation_id = _observation_id(observation)
    if observation_id is None:
        return None

    return save_observation_context_previews(
        photo=photo,
        observations=[observation],
        size=size,
    ).get(observation_id)


def save_observation_context_previews(
    *,
    photo: dict,
    observations: list[dict],
    size: int = 256,
) -> dict[int, str]:
    user_id = photo.get("user_id")
    original_path = photo.get("original_path")
    if not user_id or not original_path:
        return {}

    previews: dict[int, str] = {}
    pending: list[tuple[int, dict, Path, Path]] = []
    for observation in observations:
        observation_id = _observation_id(observation)
        if observation_id is None:
            continue

        rel_path = _context_preview_path(user_id=int(user_id), observation_id=observation_id)
        abs_path = settings.storage_root / rel_path
        if abs_path.is_file():
            previews[observation_id] = rel_path.as_posix()
        else:
            pending.append((observation_id, observation, rel_path, abs_path))

    if not pending:
        return previews

    original_abs_path = settings.storage_root / str(original_path)
    if not original_abs_path.is_file():
        return previews

    try:
        with Image.open(original_abs_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            for observation_id, observation, rel_path, abs_path in pending:
                region = _expanded_observation_region(
                    observation=observation,
                    width=image.width,
                    height=image.height,
                )
                if region is None:
                    continue
                try:
                    preview = image.crop(region)
                    preview.thumbnail((size, size))
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    preview.save(abs_path, format="JPEG", quality=84, optimize=True)
                except (OSError, ValueError):
                    continue
                previews[observation_id] = rel_path.as_posix()
    except (OSError, ValueError):
        return previews

    return previews


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


def _observation_id(observation: dict) -> int | None:
    try:
        return int(observation["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _context_preview_path(*, user_id: int, observation_id: int) -> Path:
    return Path("contexts") / f"user_{user_id}" / f"{observation_id}.jpg"


def _expanded_observation_region(
    *,
    observation: dict,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    try:
        x1 = int(observation["bbox_x1"])
        y1 = int(observation["bbox_y1"])
        x2 = int(observation["bbox_x2"])
        y2 = int(observation["bbox_y2"])
    except (KeyError, TypeError, ValueError):
        return None

    left = max(0, min(x1, x2))
    top = max(0, min(y1, y2))
    right = min(width, max(x1, x2))
    bottom = min(height, max(y1, y2))
    box_width = right - left
    box_height = bottom - top
    if box_width <= 0 or box_height <= 0:
        return None

    padding_x = max(24, int(round(box_width * 0.65)))
    padding_y = max(24, int(round(box_height * 0.65)))
    region_left = max(0, left - padding_x)
    region_top = max(0, top - padding_y)
    region_right = min(width, right + padding_x)
    region_bottom = min(height, bottom + padding_y)

    region = _expand_region_to_aspect(
        region=(region_left, region_top, region_right, region_bottom),
        bounds=(0, 0, width, height),
        target_aspect=1.0,
    )
    if region[2] - region[0] <= box_width + 1 and region[3] - region[1] <= box_height + 1:
        return None
    return region


def _expand_region_to_aspect(
    *,
    region: tuple[int, int, int, int],
    bounds: tuple[int, int, int, int],
    target_aspect: float,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = region
    min_x, min_y, max_x, max_y = bounds
    region_width = right - left
    region_height = bottom - top
    if region_width <= 0 or region_height <= 0:
        return region

    aspect = region_width / region_height
    if aspect > target_aspect:
        desired_height = min(max_y - min_y, int(round(region_width / target_aspect)))
        if desired_height > region_height:
            center_y = (top + bottom) / 2
            top = int(round(center_y - desired_height / 2))
            bottom = top + desired_height
            if top < min_y:
                bottom += min_y - top
                top = min_y
            if bottom > max_y:
                top -= bottom - max_y
                bottom = max_y
            top = max(min_y, top)
            bottom = min(max_y, bottom)
    elif aspect < target_aspect:
        desired_width = min(max_x - min_x, int(round(region_height * target_aspect)))
        if desired_width > region_width:
            center_x = (left + right) / 2
            left = int(round(center_x - desired_width / 2))
            right = left + desired_width
            if left < min_x:
                right += min_x - left
                left = min_x
            if right > max_x:
                left -= right - max_x
                right = max_x
            left = max(min_x, left)
            right = min(max_x, right)

    return left, top, right, bottom
