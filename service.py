from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from bird_recognition import (
    BirdSpeciesRecognizer,
    get_device_name,
    synchronize_if_needed,
)
from birdcut import detect_bird_crops, warmup_detection_model


OUTPUT_DIR = Path("res") / "service_runs"
DEFAULT_DETECT_CONF = 0.04
DEFAULT_DETECT_FALLBACK_CONF = 0.01
DEFAULT_DETECT_IOU = 0.85
DEFAULT_DETECT_IMGSZ = 960
DEFAULT_RECOGNITION_TOP_K = 5
DEFAULT_RECOGNITION_BATCH_SIZE = 10

logger = logging.getLogger("birdmark.service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if _preload_models_enabled():
        _preload_models()
    else:
        logger.info("Model preload disabled by BIRDMARK_PRELOAD_MODELS.")
    yield


app = FastAPI(title="Birdmark Service", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web"), name="static")
app.mount("/outputs", StaticFiles(directory="res", check_dir=False), name="outputs")

_recognizer: BirdSpeciesRecognizer | None = None
_recognizer_lock = Lock()
_analysis_lock = Lock()


@dataclass(frozen=True)
class AnalysisCrop:
    image: Image.Image
    box: tuple[int, int, int, int]
    detection_confidence: float | None
    source: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    index_path = Path("web") / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not available")
    return index_path.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.post("/analyze")
def analyze(
    file: Annotated[UploadFile, File()],
    conf: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="YOLO bird detection confidence"),
    ] = DEFAULT_DETECT_CONF,
    iou: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="YOLO NMS IoU threshold"),
    ] = DEFAULT_DETECT_IOU,
    imgsz: Annotated[
        int,
        Query(gt=0, description="YOLO inference image size"),
    ] = DEFAULT_DETECT_IMGSZ,
    top_k: Annotated[
        int,
        Query(gt=0, le=20, description="BioCLIP top-k species predictions"),
    ] = DEFAULT_RECOGNITION_TOP_K,
    batch_size: Annotated[
        int,
        Query(gt=0, le=64, description="BioCLIP recognition batch size"),
    ] = DEFAULT_RECOGNITION_BATCH_SIZE,
    fallback_conf: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="Retry confidence when no birds are detected"),
    ] = DEFAULT_DETECT_FALLBACK_CONF,
    full_image_fallback: bool = True,
    save_crops: bool = True,
) -> dict[str, object]:
    request_start = time.perf_counter()
    image = _read_upload_image(file)
    run_dir = _create_run_dir() if save_crops else None

    with _analysis_lock:
        detect_start = time.perf_counter()
        detected_crops = detect_bird_crops(
            image,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
        )

        detection_source = "detector"
        if not detected_crops and fallback_conf < conf:
            logger.info(
                "No birds detected at conf %.3f; retrying at conf %.3f.",
                conf,
                fallback_conf,
            )
            detected_crops = detect_bird_crops(
                image,
                conf=fallback_conf,
                iou=iou,
                imgsz=imgsz,
            )
            detection_source = "detector_retry"

        crop_entries = [
            AnalysisCrop(
                image=crop.image,
                box=crop.box,
                detection_confidence=crop.confidence,
                source=detection_source,
            )
            for crop in detected_crops
        ]

        if not crop_entries and full_image_fallback:
            width, height = image.size
            crop_entries = [
                AnalysisCrop(
                    image=image.copy(),
                    box=(0, 0, width, height),
                    detection_confidence=None,
                    source="full_image",
                )
            ]
        detect_seconds = time.perf_counter() - detect_start

        crop_paths = [
            _save_crop(run_dir, file.filename, crop_index, crop.image)
            for crop_index, crop in enumerate(crop_entries, start=1)
        ]

        if crop_entries:
            recognize_start = time.perf_counter()
            recognizer = _get_recognizer()
            predictions_by_crop = recognizer.predict(
                [crop.image for crop in crop_entries],
                k=top_k,
                batch_size=batch_size,
            )
            synchronize_if_needed(recognizer.device)
            recognize_seconds = time.perf_counter() - recognize_start
            device = recognizer.device
            device_name = get_device_name(recognizer.device)
        else:
            predictions_by_crop = []
            recognize_seconds = 0.0
            device = None
            device_name = None

    results = []
    for crop_index, (crop, crop_path, predictions) in enumerate(
        zip(crop_entries, crop_paths, predictions_by_crop),
        start=1,
    ):
        results.append(
            {
                "index": crop_index,
                "box": crop.box,
                "detection_confidence": crop.detection_confidence,
                "source": crop.source,
                "crop_path": str(crop_path) if crop_path is not None else None,
                "predictions": predictions,
            }
        )

    total_seconds = time.perf_counter() - request_start
    return {
        "filename": file.filename,
        "image_size": image.size,
        "crop_count": len(crop_entries),
        "output_dir": str(run_dir) if run_dir is not None else None,
        "device": device,
        "device_name": device_name,
        "timing": {
            "detect_seconds": detect_seconds,
            "recognize_seconds": recognize_seconds,
            "total_seconds": total_seconds,
        },
        "results": results,
    }


@app.post("/recognize-box")
def recognize_box(
    file: Annotated[UploadFile, File()],
    x1: Annotated[float, Form()],
    y1: Annotated[float, Form()],
    x2: Annotated[float, Form()],
    y2: Annotated[float, Form()],
    top_k: Annotated[
        int,
        Query(gt=0, le=20, description="BioCLIP top-k species predictions"),
    ] = DEFAULT_RECOGNITION_TOP_K,
    save_crop: bool = True,
) -> dict[str, object]:
    request_start = time.perf_counter()
    image = _read_upload_image(file)
    box = _normalize_box((x1, y1, x2, y2), image.size)
    crop_image = image.crop(box)
    run_dir = _create_run_dir() if save_crop else None
    crop_path = _save_crop(run_dir, file.filename, 1, crop_image)

    with _analysis_lock:
        recognize_start = time.perf_counter()
        recognizer = _get_recognizer()
        predictions = recognizer.predict_one(crop_image, k=top_k)
        synchronize_if_needed(recognizer.device)
        recognize_seconds = time.perf_counter() - recognize_start
        device = recognizer.device
        device_name = get_device_name(recognizer.device)

    total_seconds = time.perf_counter() - request_start
    return {
        "filename": file.filename,
        "image_size": image.size,
        "crop_count": 1,
        "output_dir": str(run_dir) if run_dir is not None else None,
        "device": device,
        "device_name": device_name,
        "timing": {
            "detect_seconds": 0.0,
            "recognize_seconds": recognize_seconds,
            "total_seconds": total_seconds,
        },
        "results": [
            {
                "index": 1,
                "box": box,
                "detection_confidence": None,
                "source": "manual",
                "crop_path": str(crop_path) if crop_path is not None else None,
                "predictions": predictions,
            }
        ],
    }


def _read_upload_image(file: UploadFile) -> Image.Image:
    try:
        contents = file.file.read()
        with Image.open(BytesIO(contents)) as opened:
            return ImageOps.exif_transpose(opened).convert("RGB")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not an image") from exc


def _normalize_box(
    box: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    width, height = image_size
    x1, y1, x2, y2 = box
    left = max(0, min(width, round(min(x1, x2))))
    top = max(0, min(height, round(min(y1, y2))))
    right = max(0, min(width, round(max(x1, x2))))
    bottom = max(0, min(height, round(max(y1, y2))))

    if right - left < 5 or bottom - top < 5:
        raise HTTPException(status_code=400, detail="Selected box is too small")

    return left, top, right, bottom


def _create_run_dir() -> Path:
    run_dir = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _save_crop(
    run_dir: Path | None,
    filename: str | None,
    crop_index: int,
    crop_image: Image.Image,
) -> Path | None:
    if run_dir is None:
        return None

    stem = Path(filename or "upload").stem or "upload"
    crop_path = run_dir / f"{stem}_crop_{crop_index:03d}.png"
    crop_image.save(crop_path)
    return crop_path


def _preload_models_enabled() -> bool:
    value = os.environ.get("BIRDMARK_PRELOAD_MODELS", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _preload_models() -> None:
    preload_start = time.perf_counter()
    logger.info("Preloading detector and recognizer models...")

    with _analysis_lock:
        detect_start = time.perf_counter()
        warmup_detection_model(
            conf=DEFAULT_DETECT_CONF,
            iou=DEFAULT_DETECT_IOU,
            imgsz=DEFAULT_DETECT_IMGSZ,
        )
        logger.info(
            "Detector warmup completed in %.2fs.",
            time.perf_counter() - detect_start,
        )

        recognize_start = time.perf_counter()
        recognizer = _get_recognizer()
        recognizer.predict_one(Image.new("RGB", (64, 64), "black"), k=1)
        synchronize_if_needed(recognizer.device)
        logger.info(
            "Recognizer warmup completed in %.2fs.",
            time.perf_counter() - recognize_start,
        )

    logger.info(
        "Model preload completed in %.2fs.",
        time.perf_counter() - preload_start,
    )


def _get_recognizer() -> BirdSpeciesRecognizer:
    global _recognizer

    if _recognizer is None:
        with _recognizer_lock:
            if _recognizer is None:
                _recognizer = BirdSpeciesRecognizer()

    return _recognizer


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("service:app", host="127.0.0.1", port=8000)
