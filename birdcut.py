from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal, Sequence

import numpy as np
from PIL import Image, ImageOps
from ultralytics import YOLO


def _read_positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


DEFAULT_MODEL_PT_PATH = Path(__file__).resolve().parent / "models" / "yolo26m.pt"
DEFAULT_MODEL_ENGINE_PATH = DEFAULT_MODEL_PT_PATH.with_suffix(".engine")
DEFAULT_MODEL_PATH = Path(
    os.environ.get(
        "BIRDMARK_DETECT_MODEL",
        str(
            DEFAULT_MODEL_ENGINE_PATH
            if DEFAULT_MODEL_ENGINE_PATH.exists()
            else DEFAULT_MODEL_PT_PATH
        ),
    )
)
DEFAULT_DETECT_BATCH_SIZE = _read_positive_int_env("BIRDMARK_DETECT_BATCH_SIZE", 8)
BIRD_CLASS_NAME = "bird"
ImageInput = str | Path | Image.Image | np.ndarray
ArrayColorOrder = Literal["bgr", "rgb"]
InferenceMode = Literal["auto", "full", "tiled"]

_MODEL_CACHE: dict[Path, YOLO] = {}
_MODEL_LOCK = Lock()
_TORCH_LOAD_PATCH_LOCK = Lock()
_TORCH_LOAD_PATCHED = False


@dataclass(frozen=True)
class BirdCrop:
    image: Image.Image
    box: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class _Detection:
    box: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class _TileInference:
    image: Image.Image
    left: int
    top: int
    right: int
    bottom: int
    keep_x1: float
    keep_y1: float
    keep_x2: float
    keep_y2: float


def birdcut(
    image: ImageInput,
    *,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    conf: float = 0.25,
    iou: float = 0.7,
    imgsz: int | None = None,
    max_det: int = 300,
    padding_ratio: float = 0.05,
    array_color_order: ArrayColorOrder = "bgr",
    mode: InferenceMode = "auto",
    tile_size: int = 1200,
    tile_overlap: float = 0.3,
    merge_iou: float = 0.45,
    detect_batch_size: int = DEFAULT_DETECT_BATCH_SIZE,
) -> list[Image.Image]:
    """Detect birds in an image and return cropped bird images.

    `image` accepts a file path, PIL image, or ndarray. Ndarray input defaults to
    OpenCV BGR order to match `cv2.imread(...)`. Use `mode="tiled"` for large
    images with many small birds, or leave `mode="auto"` to tile only when the
    image is larger than `tile_size`.
    """
    return [
        crop.image
        for crop in detect_bird_crops(
            image,
            model_path=model_path,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            max_det=max_det,
            padding_ratio=padding_ratio,
            array_color_order=array_color_order,
            mode=mode,
            tile_size=tile_size,
            tile_overlap=tile_overlap,
            merge_iou=merge_iou,
            detect_batch_size=detect_batch_size,
        )
    ]


def detect_bird_crops(
    image: ImageInput,
    *,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    conf: float = 0.25,
    iou: float = 0.7,
    imgsz: int | None = None,
    max_det: int = 300,
    padding_ratio: float = 0.05,
    array_color_order: ArrayColorOrder = "bgr",
    mode: InferenceMode = "auto",
    tile_size: int = 1200,
    tile_overlap: float = 0.3,
    merge_iou: float = 0.45,
    detect_batch_size: int = DEFAULT_DETECT_BATCH_SIZE,
) -> list[BirdCrop]:
    """Detect birds and return crops with box and confidence metadata."""
    _validate_options(
        padding_ratio=padding_ratio,
        imgsz=imgsz,
        max_det=max_det,
        mode=mode,
        tile_size=tile_size,
        tile_overlap=tile_overlap,
        merge_iou=merge_iou,
        detect_batch_size=detect_batch_size,
    )

    pil_image = _to_pil_image(image, array_color_order=array_color_order)
    model = _get_model(model_path)
    bird_class_ids = _get_class_ids(model, BIRD_CLASS_NAME)

    width, height = pil_image.size
    active_mode = _resolve_mode(mode, width=width, height=height, tile_size=tile_size)
    if active_mode == "tiled":
        detections = _predict_tiled(
            model=model,
            image=pil_image,
            class_ids=bird_class_ids,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            max_det=max_det,
            tile_size=tile_size,
            tile_overlap=tile_overlap,
            merge_iou=merge_iou,
            detect_batch_size=detect_batch_size,
        )
    else:
        detections = _predict_full(
            model=model,
            image=pil_image,
            class_ids=bird_class_ids,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            max_det=max_det,
            detect_batch_size=detect_batch_size,
        )

    crops: list[BirdCrop] = []
    for detection in detections:
        x1, y1, x2, y2 = _expand_box(
            list(detection.box),
            image_width=width,
            image_height=height,
            padding_ratio=padding_ratio,
        )
        if x2 <= x1 or y2 <= y1:
            continue

        crops.append(
            BirdCrop(
                image=pil_image.crop((x1, y1, x2, y2)),
                box=(x1, y1, x2, y2),
                confidence=detection.confidence,
            )
        )

    return crops


def preload_detection_model(
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> YOLO:
    """Load the detector into the process cache before the first request."""
    return _get_model(model_path)


def warmup_detection_model(
    *,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    conf: float = 0.25,
    iou: float = 0.7,
    imgsz: int | None = None,
    detect_batch_size: int = DEFAULT_DETECT_BATCH_SIZE,
) -> None:
    """Run a tiny detector pass so first user inference does not pay setup cost."""
    detect_bird_crops(
        Image.new("RGB", (64, 64), "black"),
        model_path=model_path,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        max_det=1,
        mode="full",
        detect_batch_size=detect_batch_size,
    )


def _validate_options(
    *,
    padding_ratio: float,
    imgsz: int | None,
    max_det: int,
    mode: str,
    tile_size: int,
    tile_overlap: float,
    merge_iou: float,
    detect_batch_size: int,
) -> None:
    if padding_ratio < 0:
        raise ValueError("padding_ratio must be >= 0")
    if imgsz is not None and imgsz <= 0:
        raise ValueError("imgsz must be > 0")
    if max_det <= 0:
        raise ValueError("max_det must be > 0")
    if mode not in {"auto", "full", "tiled"}:
        raise ValueError("mode must be 'auto', 'full', or 'tiled'")
    if tile_size <= 0:
        raise ValueError("tile_size must be > 0")
    if not 0 <= tile_overlap < 1:
        raise ValueError("tile_overlap must be >= 0 and < 1")
    if not 0 <= merge_iou <= 1:
        raise ValueError("merge_iou must be >= 0 and <= 1")
    if detect_batch_size <= 0:
        raise ValueError("detect_batch_size must be > 0")


def _resolve_mode(
    mode: InferenceMode,
    *,
    width: int,
    height: int,
    tile_size: int,
) -> Literal["full", "tiled"]:
    if mode == "auto":
        return "tiled" if max(width, height) > tile_size else "full"
    if mode == "tiled":
        return "tiled"
    return "full"


def _predict_full(
    *,
    model: YOLO,
    image: Image.Image,
    class_ids: list[int],
    conf: float,
    iou: float,
    imgsz: int | None,
    max_det: int,
    detect_batch_size: int,
) -> list[_Detection]:
    return _predict_image(
        model=model,
        image=image,
        class_ids=class_ids,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        max_det=max_det,
        detect_batch_size=detect_batch_size,
    )


def _predict_tiled(
    *,
    model: YOLO,
    image: Image.Image,
    class_ids: list[int],
    conf: float,
    iou: float,
    imgsz: int | None,
    max_det: int,
    tile_size: int,
    tile_overlap: float,
    merge_iou: float,
    detect_batch_size: int,
) -> list[_Detection]:
    width, height = image.size
    stride = max(1, round(tile_size * (1 - tile_overlap)))
    x_origins = _tile_origins(width, tile_size, stride)
    y_origins = _tile_origins(height, tile_size, stride)
    x_keep_regions = _tile_keep_regions(width, x_origins, tile_size)
    y_keep_regions = _tile_keep_regions(height, y_origins, tile_size)
    tile_inputs: list[_TileInference] = []

    for y_index, top in enumerate(y_origins):
        keep_y1, keep_y2 = y_keep_regions[y_index]
        for x_index, left in enumerate(x_origins):
            keep_x1, keep_x2 = x_keep_regions[x_index]
            right = min(width, left + tile_size)
            bottom = min(height, top + tile_size)
            tile_inputs.append(
                _TileInference(
                    image=image.crop((left, top, right, bottom)),
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    keep_x1=keep_x1,
                    keep_y1=keep_y1,
                    keep_x2=keep_x2,
                    keep_y2=keep_y2,
                )
            )

    detections: list[_Detection] = []
    for start in range(0, len(tile_inputs), detect_batch_size):
        tile_batch = tile_inputs[start : start + detect_batch_size]
        detections_by_tile = _predict_images(
            model=model,
            images=[tile.image for tile in tile_batch],
            class_ids=class_ids,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            max_det=max_det,
            detect_batch_size=detect_batch_size,
        )
        for tile, tile_detections in zip(tile_batch, detections_by_tile):
            for detection in tile_detections:
                x1, y1, x2, y2 = detection.box
                if _touches_internal_tile_edge(
                    detection.box,
                    tile_width=tile.right - tile.left,
                    tile_height=tile.bottom - tile.top,
                    touches_image_left=tile.left == 0,
                    touches_image_top=tile.top == 0,
                    touches_image_right=tile.right == width,
                    touches_image_bottom=tile.bottom == height,
                    margin=2.0,
                ):
                    continue

                global_box = (
                    x1 + tile.left,
                    y1 + tile.top,
                    x2 + tile.left,
                    y2 + tile.top,
                )
                if not _box_center_in_region(
                    global_box,
                    x1=tile.keep_x1,
                    y1=tile.keep_y1,
                    x2=tile.keep_x2,
                    y2=tile.keep_y2,
                ):
                    continue

                detections.append(
                    _Detection(
                        box=global_box,
                        confidence=detection.confidence,
                    )
                )

    merged_detections = _nms(detections, iou_threshold=merge_iou)
    deduped_detections = _remove_contained_detections(
        merged_detections,
        containment_threshold=0.9,
    )
    return _remove_center_duplicate_detections(
        deduped_detections,
        overlap_threshold=0.35,
    )


def _predict_image(
    *,
    model: YOLO,
    image: Image.Image,
    class_ids: list[int],
    conf: float,
    iou: float,
    imgsz: int | None,
    max_det: int,
    detect_batch_size: int,
) -> list[_Detection]:
    detections_by_image = _predict_images(
        model=model,
        images=[image],
        class_ids=class_ids,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        max_det=max_det,
        detect_batch_size=detect_batch_size,
    )
    return detections_by_image[0] if detections_by_image else []


def _predict_images(
    *,
    model: YOLO,
    images: Sequence[Image.Image],
    class_ids: list[int],
    conf: float,
    iou: float,
    imgsz: int | None,
    max_det: int,
    detect_batch_size: int,
) -> list[list[_Detection]]:
    if not images:
        return []

    predict_kwargs = {
        "source": list(images),
        "classes": class_ids,
        "conf": conf,
        "iou": iou,
        "max_det": max_det,
        "batch": min(detect_batch_size, len(images)),
        "verbose": False,
    }
    if imgsz is not None:
        predict_kwargs["imgsz"] = imgsz

    results = model.predict(**predict_kwargs)
    detections_by_image: list[list[_Detection]] = []
    for result in results:
        boxes = result.boxes
        if boxes is None:
            detections_by_image.append([])
            continue

        detections: list[_Detection] = []
        for box in boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            detections.append(
                _Detection(
                    box=(float(x1), float(y1), float(x2), float(y2)),
                    confidence=float(box.conf[0].item()),
                )
            )
        detections_by_image.append(detections)

    return detections_by_image


def _tile_origins(length: int, tile_size: int, stride: int) -> list[int]:
    if length <= tile_size:
        return [0]

    origins = list(range(0, length - tile_size + 1, stride))
    final_origin = length - tile_size
    if origins[-1] != final_origin:
        origins.append(final_origin)

    return origins


def _tile_keep_regions(
    length: int,
    origins: list[int],
    tile_size: int,
) -> list[tuple[float, float]]:
    tile_bounds = [
        (origin, min(length, origin + tile_size))
        for origin in origins
    ]
    keep_regions: list[tuple[float, float]] = []

    for index, (start, end) in enumerate(tile_bounds):
        keep_start = 0.0
        keep_end = float(length)
        if index > 0:
            previous_end = tile_bounds[index - 1][1]
            keep_start = (previous_end + start) / 2
        if index < len(tile_bounds) - 1:
            next_start = tile_bounds[index + 1][0]
            keep_end = (end + next_start) / 2

        keep_regions.append((keep_start, keep_end))

    return keep_regions


def _box_center_in_region(
    box: tuple[float, float, float, float],
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    box_x1, box_y1, box_x2, box_y2 = box
    center_x = (box_x1 + box_x2) / 2
    center_y = (box_y1 + box_y2) / 2

    return x1 <= center_x <= x2 and y1 <= center_y <= y2


def _touches_internal_tile_edge(
    box: tuple[float, float, float, float],
    *,
    tile_width: int,
    tile_height: int,
    touches_image_left: bool,
    touches_image_top: bool,
    touches_image_right: bool,
    touches_image_bottom: bool,
    margin: float,
) -> bool:
    x1, y1, x2, y2 = box
    touches_left = not touches_image_left and x1 <= margin
    touches_top = not touches_image_top and y1 <= margin
    touches_right = not touches_image_right and tile_width - x2 <= margin
    touches_bottom = not touches_image_bottom and tile_height - y2 <= margin

    return touches_left or touches_top or touches_right or touches_bottom


def _nms(
    detections: list[_Detection],
    *,
    iou_threshold: float,
) -> list[_Detection]:
    kept: list[_Detection] = []
    sorted_detections = sorted(
        detections,
        key=lambda item: item.confidence,
        reverse=True,
    )
    for detection in sorted_detections:
        if all(
            _box_iou(detection.box, kept_detection.box) <= iou_threshold
            for kept_detection in kept
        ):
            kept.append(detection)

    return kept


def _remove_contained_detections(
    detections: list[_Detection],
    *,
    containment_threshold: float,
) -> list[_Detection]:
    filtered: list[_Detection] = []

    for index, detection in enumerate(detections):
        area = _box_area(detection.box)
        if area <= 0:
            continue

        is_contained = any(
            _box_area(other_detection.box) > area
            and _box_intersection_area(detection.box, other_detection.box) / area
            >= containment_threshold
            for other_index, other_detection in enumerate(detections)
            if other_index != index
        )
        if not is_contained:
            filtered.append(detection)

    return filtered


def _remove_center_duplicate_detections(
    detections: list[_Detection],
    *,
    overlap_threshold: float,
) -> list[_Detection]:
    filtered: list[_Detection] = []

    for index, detection in enumerate(detections):
        area = _box_area(detection.box)
        if area <= 0:
            continue

        center_x, center_y = _box_center(detection.box)
        is_duplicate = any(
            other_detection.confidence >= detection.confidence
            and _point_in_box(center_x, center_y, other_detection.box)
            and _box_intersection_area(detection.box, other_detection.box) / area
            >= overlap_threshold
            for other_index, other_detection in enumerate(detections)
            if other_index != index
        )
        if not is_duplicate:
            filtered.append(detection)

    return filtered


def _box_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    intersection = _box_intersection_area(a, b)
    area_a = _box_area(a)
    area_b = _box_area(b)
    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0
    return intersection / union


def _box_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    intersection_width = max(0.0, ix2 - ix1)
    intersection_height = max(0.0, iy2 - iy1)
    return intersection_width * intersection_height


def _box_area(box: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def _point_in_box(
    x: float,
    y: float,
    box: tuple[float, float, float, float],
) -> bool:
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def _get_model(model_path: str | Path) -> YOLO:
    resolved_path = Path(model_path).expanduser().resolve()
    if resolved_path not in _MODEL_CACHE:
        with _MODEL_LOCK:
            if resolved_path not in _MODEL_CACHE:
                if resolved_path.suffix.lower() == ".pt":
                    _allow_trusted_ultralytics_checkpoint_load()
                _MODEL_CACHE[resolved_path] = YOLO(str(resolved_path), task="detect")
    return _MODEL_CACHE[resolved_path]


def _allow_trusted_ultralytics_checkpoint_load() -> None:
    """Keep local YOLO checkpoints loadable with PyTorch's safer defaults.

    PyTorch 2.6 changed torch.load to default to weights_only=True. Some
    Ultralytics checkpoints store a DetectionModel object and need the old
    weights_only=False behavior. This app only loads the local configured
    detector checkpoint, so we apply the compatibility patch before YOLO load.
    """
    global _TORCH_LOAD_PATCHED

    if _TORCH_LOAD_PATCHED:
        return

    with _TORCH_LOAD_PATCH_LOCK:
        if _TORCH_LOAD_PATCHED:
            return

        import inspect
        import torch
        import ultralytics.nn.tasks as tasks
        import ultralytics.utils.patches as patches

        if "weights_only" not in inspect.signature(torch.load).parameters:
            _TORCH_LOAD_PATCHED = True
            return

        original_task_torch_load = tasks.torch_load
        original_patch_torch_load = patches.torch_load

        def task_torch_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_task_torch_load(*args, **kwargs)

        def patch_torch_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return original_patch_torch_load(*args, **kwargs)

        tasks.torch_load = task_torch_load
        patches.torch_load = patch_torch_load
        _TORCH_LOAD_PATCHED = True


def _get_class_ids(model: YOLO, class_name: str) -> list[int]:
    class_ids = [
        class_id
        for class_id, name in model.names.items()
        if name.lower() == class_name.lower()
    ]
    if not class_ids:
        raise ValueError(f"Model does not contain class: {class_name}")
    return class_ids


def _to_pil_image(
    image: ImageInput,
    *,
    array_color_order: ArrayColorOrder,
) -> Image.Image:
    if isinstance(image, Image.Image):
        return ImageOps.exif_transpose(image).convert("RGB")

    if isinstance(image, (str, Path)):
        with Image.open(image) as opened:
            return ImageOps.exif_transpose(opened).convert("RGB")

    if isinstance(image, np.ndarray):
        array = _normalize_image_array(image)
        if array.ndim == 2:
            return Image.fromarray(array).convert("RGB")
        if array.ndim == 3 and array.shape[2] == 3:
            if array_color_order == "bgr":
                array = array[:, :, ::-1]
            return Image.fromarray(array).convert("RGB")
        if array.ndim == 3 and array.shape[2] == 4:
            if array_color_order == "bgr":
                array = array[:, :, [2, 1, 0, 3]]
            return Image.fromarray(array).convert("RGB")

    raise TypeError("image must be a path, PIL.Image.Image, or numpy.ndarray")


def _normalize_image_array(image: np.ndarray) -> np.ndarray:
    if image.dtype == np.uint8:
        return image

    if np.issubdtype(image.dtype, np.floating):
        max_value = 1.0 if image.max(initial=0) <= 1.0 else 255.0
        image = image * (255.0 / max_value)

    return np.clip(image, 0, 255).astype(np.uint8)


def _expand_box(
    xyxy: list[float],
    *,
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = xyxy
    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = box_width * padding_ratio
    pad_y = box_height * padding_ratio

    return (
        max(0, round(x1 - pad_x)),
        max(0, round(y1 - pad_y)),
        min(image_width, round(x2 + pad_x)),
        min(image_height, round(y2 + pad_y)),
    )


if __name__ == "__main__":
    output_dir = Path("res")
    output_dir.mkdir(exist_ok=True)
    crops = birdcut("birds/11.jpg", conf=0.04, iou=0.85, imgsz=960)
    for index, crop in enumerate(crops, start=1):
        crop.save(output_dir / f"bird_crop_{index}.png")
    print(f"saved {len(crops)} crop(s)")
