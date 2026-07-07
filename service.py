from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Condition, Event, Lock, Thread
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from bird_recognition import (
    BirdSpeciesRecognizer,
    Prediction,
    get_device_name,
    synchronize_if_needed,
)
from birdcut import (
    DEFAULT_DETECT_BATCH_SIZE,
    detect_bird_crops,
    warmup_detection_model,
)


OUTPUT_DIR = Path("res") / "service_runs"
DEFAULT_DETECT_CONF = 0.04
DEFAULT_DETECT_FALLBACK_CONF = 0.01
DEFAULT_DETECT_IOU = 0.85
DEFAULT_DETECT_IMGSZ = 960
DEFAULT_RECOGNITION_TOP_K = 5
DEFAULT_RECOGNITION_BATCH_SIZE = 10
DEFAULT_RECOGNITION_QUEUE_MAX_IMAGES = 64
DEFAULT_RECOGNITION_BATCH_WAIT_MS = 10.0

logger = logging.getLogger("birdmark.service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if _preload_models_enabled():
        _preload_models()
    else:
        logger.info("Model preload disabled by BIRDMARK_PRELOAD_MODELS.")
    try:
        yield
    finally:
        _stop_recognition_batcher()


app = FastAPI(title="Birdmark AI Inference Service", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web"), name="static")
app.mount("/outputs", StaticFiles(directory="res", check_dir=False), name="outputs")

_recognizer: BirdSpeciesRecognizer | None = None
_recognizer_lock = Lock()
_recognition_batcher: RecognitionBatcher | None = None
_recognition_batcher_lock = Lock()
_analysis_lock = Lock()


@dataclass(frozen=True)
class AnalysisCrop:
    image: Image.Image
    box: tuple[int, int, int, int]
    detection_confidence: float | None
    source: str


@dataclass(frozen=True)
class RecognitionBatchResult:
    predictions_by_image: list[list[Prediction]]
    device: str
    device_name: str | None


@dataclass
class _RecognitionJob:
    images: list[Image.Image]
    k: int
    batch_size: int
    event: Event
    result: RecognitionBatchResult | None = None
    error: BaseException | None = None


class RecognitionBatcher:
    def __init__(
        self,
        *,
        max_wait_ms: float = DEFAULT_RECOGNITION_BATCH_WAIT_MS,
        max_image_count: int = DEFAULT_RECOGNITION_QUEUE_MAX_IMAGES,
    ) -> None:
        self._max_wait_seconds = max(0.0, max_wait_ms / 1000.0)
        self._max_image_count = max(1, max_image_count)
        self._condition = Condition()
        self._jobs: list[_RecognitionJob] = []
        self._closed = False
        self._thread = Thread(
            target=self._run,
            name="birdmark-recognition-batcher",
            daemon=True,
        )
        self._thread.start()

    def submit(
        self,
        images: list[Image.Image],
        *,
        k: int,
        batch_size: int,
    ) -> RecognitionBatchResult:
        if not images:
            recognizer = _get_recognizer()
            return RecognitionBatchResult(
                predictions_by_image=[],
                device=recognizer.device,
                device_name=get_device_name(recognizer.device),
            )

        job = _RecognitionJob(
            images=images,
            k=k,
            batch_size=batch_size,
            event=Event(),
        )
        with self._condition:
            if self._closed:
                raise RuntimeError("Recognition batcher has been stopped")
            self._jobs.append(job)
            self._condition.notify()

        job.event.wait()
        if job.error is not None:
            raise job.error
        if job.result is None:
            raise RuntimeError("Recognition batcher did not return a result")
        return job.result

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            jobs = self._take_jobs()
            if jobs is None:
                return
            self._process_jobs(jobs)

    def _take_jobs(self) -> list[_RecognitionJob] | None:
        with self._condition:
            while not self._jobs and not self._closed:
                self._condition.wait()

            if not self._jobs and self._closed:
                return None

            deadline = time.perf_counter() + self._max_wait_seconds
            while not self._closed:
                queued_image_count = sum(len(job.images) for job in self._jobs)
                if queued_image_count >= self._max_image_count:
                    break

                remaining_seconds = deadline - time.perf_counter()
                if remaining_seconds <= 0:
                    break
                self._condition.wait(remaining_seconds)

            jobs: list[_RecognitionJob] = []
            image_count = 0
            while self._jobs:
                next_job = self._jobs[0]
                next_count = len(next_job.images)
                if jobs and image_count + next_count > self._max_image_count:
                    break
                jobs.append(self._jobs.pop(0))
                image_count += next_count
                if image_count >= self._max_image_count:
                    break

            return jobs

    def _process_jobs(self, jobs: list[_RecognitionJob]) -> None:
        try:
            images = [image for job in jobs for image in job.images]
            max_k = max(job.k for job in jobs)
            model_batch_size = min(
                self._max_image_count,
                max(job.batch_size for job in jobs),
                len(images),
            )

            with _analysis_lock:
                recognizer = _get_recognizer()
                predictions_by_image = recognizer.predict(
                    images,
                    k=max_k,
                    batch_size=model_batch_size,
                )
                synchronize_if_needed(recognizer.device)
                device = recognizer.device
                device_name = get_device_name(recognizer.device)

            offset = 0
            for job in jobs:
                count = len(job.images)
                job_predictions = [
                    predictions[: job.k]
                    for predictions in predictions_by_image[offset : offset + count]
                ]
                job.result = RecognitionBatchResult(
                    predictions_by_image=job_predictions,
                    device=device,
                    device_name=device_name,
                )
                offset += count
        except BaseException as exc:
            for job in jobs:
                job.error = exc
        finally:
            for job in jobs:
                job.event.set()


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
    detect_batch_size: Annotated[
        int,
        Query(
            gt=0,
            le=DEFAULT_DETECT_BATCH_SIZE,
            description="YOLO detector batch size",
        ),
    ] = DEFAULT_DETECT_BATCH_SIZE,
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
    image = _read_upload_image(file)
    return _analyze_image(
        image,
        filename=file.filename,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        detect_batch_size=detect_batch_size,
        top_k=top_k,
        batch_size=batch_size,
        fallback_conf=fallback_conf,
        full_image_fallback=full_image_fallback,
        save_crops=save_crops,
        include_crop_images=False,
    )


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
    batch_size: Annotated[
        int,
        Query(gt=0, le=64, description="BioCLIP recognition batch size"),
    ] = DEFAULT_RECOGNITION_BATCH_SIZE,
    save_crop: bool = True,
) -> dict[str, object]:
    image = _read_upload_image(file)
    return _recognize_box_in_image(
        image,
        filename=file.filename,
        box_values=(x1, y1, x2, y2),
        top_k=top_k,
        batch_size=batch_size,
        save_crop=save_crop,
        include_crop_image=False,
    )


@app.get("/internal/health")
def internal_health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "birdmark-ai-inference",
        "role": "ai_inference",
    }


@app.get("/internal/models")
def internal_models() -> dict[str, object]:
    recognizer_loaded = _recognizer is not None
    recognition_device = _recognizer.device if _recognizer is not None else None
    return {
        "detector": {
            "name": "yolo",
            "batch_size": DEFAULT_DETECT_BATCH_SIZE,
            "default_conf": DEFAULT_DETECT_CONF,
            "default_iou": DEFAULT_DETECT_IOU,
            "default_imgsz": DEFAULT_DETECT_IMGSZ,
        },
        "recognizer": {
            "name": "bioclip",
            "loaded": recognizer_loaded,
            "device": recognition_device,
            "device_name": (
                get_device_name(recognition_device)
                if recognition_device is not None
                else None
            ),
            "default_top_k": DEFAULT_RECOGNITION_TOP_K,
            "default_batch_size": DEFAULT_RECOGNITION_BATCH_SIZE,
        },
    }


@app.post("/internal/analyze-image")
def internal_analyze_image(
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
    detect_batch_size: Annotated[
        int,
        Query(
            gt=0,
            le=DEFAULT_DETECT_BATCH_SIZE,
            description="YOLO detector batch size",
        ),
    ] = DEFAULT_DETECT_BATCH_SIZE,
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
    full_image_fallback: bool = False,
    include_crop_images: bool = True,
) -> dict[str, object]:
    image = _read_upload_image(file)
    return _analyze_image(
        image,
        filename=file.filename,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        detect_batch_size=detect_batch_size,
        top_k=top_k,
        batch_size=batch_size,
        fallback_conf=fallback_conf,
        full_image_fallback=full_image_fallback,
        save_crops=False,
        include_crop_images=include_crop_images,
    )


@app.post("/internal/detect")
def internal_detect(
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
    detect_batch_size: Annotated[
        int,
        Query(
            gt=0,
            le=DEFAULT_DETECT_BATCH_SIZE,
            description="YOLO detector batch size",
        ),
    ] = DEFAULT_DETECT_BATCH_SIZE,
    fallback_conf: Annotated[
        float,
        Query(ge=0.0, le=1.0, description="Retry confidence when no birds are detected"),
    ] = DEFAULT_DETECT_FALLBACK_CONF,
    full_image_fallback: bool = False,
    include_crop_images: bool = True,
) -> dict[str, object]:
    request_start = time.perf_counter()
    image = _read_upload_image(file)
    crop_entries, detect_seconds = _detect_analysis_crops(
        image,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        detect_batch_size=detect_batch_size,
        fallback_conf=fallback_conf,
        full_image_fallback=full_image_fallback,
    )
    results = [
        _format_crop_result(
            crop_index,
            crop,
            crop_path=None,
            predictions=[],
            include_crop_image=include_crop_images,
        )
        for crop_index, crop in enumerate(crop_entries, start=1)
    ]
    total_seconds = time.perf_counter() - request_start
    return {
        "filename": file.filename,
        "image_size": image.size,
        "crop_count": len(crop_entries),
        "timing": {
            "detect_seconds": detect_seconds,
            "recognize_seconds": 0.0,
            "total_seconds": total_seconds,
        },
        "results": results,
    }


@app.post("/internal/recognize-crops")
def internal_recognize_crops(
    files: Annotated[list[UploadFile], File()],
    top_k: Annotated[
        int,
        Query(gt=0, le=20, description="BioCLIP top-k species predictions"),
    ] = DEFAULT_RECOGNITION_TOP_K,
    batch_size: Annotated[
        int,
        Query(gt=0, le=64, description="BioCLIP recognition batch size"),
    ] = DEFAULT_RECOGNITION_BATCH_SIZE,
) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one crop file is required")

    request_start = time.perf_counter()
    images = [_read_upload_image(file) for file in files]
    recognize_start = time.perf_counter()
    recognition_result = _recognize_images(
        images,
        k=top_k,
        batch_size=batch_size,
    )
    recognize_seconds = time.perf_counter() - recognize_start
    total_seconds = time.perf_counter() - request_start

    results = []
    for crop_index, (file, image, predictions) in enumerate(
        zip(files, images, recognition_result.predictions_by_image),
        start=1,
    ):
        results.append(
            {
                "index": crop_index,
                "filename": file.filename,
                "image_size": image.size,
                "predictions": predictions,
            }
        )

    return {
        "crop_count": len(images),
        "device": recognition_result.device,
        "device_name": recognition_result.device_name,
        "timing": {
            "detect_seconds": 0.0,
            "recognize_seconds": recognize_seconds,
            "total_seconds": total_seconds,
        },
        "results": results,
    }


@app.post("/internal/recognize-box")
def internal_recognize_box(
    file: Annotated[UploadFile, File()],
    x1: Annotated[float, Form()],
    y1: Annotated[float, Form()],
    x2: Annotated[float, Form()],
    y2: Annotated[float, Form()],
    top_k: Annotated[
        int,
        Query(gt=0, le=20, description="BioCLIP top-k species predictions"),
    ] = DEFAULT_RECOGNITION_TOP_K,
    batch_size: Annotated[
        int,
        Query(gt=0, le=64, description="BioCLIP recognition batch size"),
    ] = DEFAULT_RECOGNITION_BATCH_SIZE,
    include_crop_image: bool = True,
) -> dict[str, object]:
    image = _read_upload_image(file)
    return _recognize_box_in_image(
        image,
        filename=file.filename,
        box_values=(x1, y1, x2, y2),
        top_k=top_k,
        batch_size=batch_size,
        save_crop=False,
        include_crop_image=include_crop_image,
    )


def _analyze_image(
    image: Image.Image,
    *,
    filename: str | None,
    conf: float,
    iou: float,
    imgsz: int,
    detect_batch_size: int,
    top_k: int,
    batch_size: int,
    fallback_conf: float,
    full_image_fallback: bool,
    save_crops: bool,
    include_crop_images: bool,
) -> dict[str, object]:
    request_start = time.perf_counter()
    run_dir = _create_run_dir() if save_crops else None
    crop_entries, detect_seconds = _detect_analysis_crops(
        image,
        conf=conf,
        iou=iou,
        imgsz=imgsz,
        detect_batch_size=detect_batch_size,
        fallback_conf=fallback_conf,
        full_image_fallback=full_image_fallback,
    )
    crop_paths = [
        _save_crop(run_dir, filename, crop_index, crop.image)
        for crop_index, crop in enumerate(crop_entries, start=1)
    ]

    if crop_entries:
        recognize_start = time.perf_counter()
        recognition_result = _recognize_images(
            [crop.image for crop in crop_entries],
            k=top_k,
            batch_size=batch_size,
        )
        recognize_seconds = time.perf_counter() - recognize_start
        predictions_by_crop = recognition_result.predictions_by_image
        device = recognition_result.device
        device_name = recognition_result.device_name
    else:
        predictions_by_crop = []
        recognize_seconds = 0.0
        device = None
        device_name = None

    results = [
        _format_crop_result(
            crop_index,
            crop,
            crop_path=crop_path,
            predictions=predictions,
            include_crop_image=include_crop_images,
        )
        for crop_index, (crop, crop_path, predictions) in enumerate(
            zip(crop_entries, crop_paths, predictions_by_crop),
            start=1,
        )
    ]
    total_seconds = time.perf_counter() - request_start
    return {
        "filename": filename,
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


def _detect_analysis_crops(
    image: Image.Image,
    *,
    conf: float,
    iou: float,
    imgsz: int,
    detect_batch_size: int,
    fallback_conf: float,
    full_image_fallback: bool,
) -> tuple[list[AnalysisCrop], float]:
    with _analysis_lock:
        detect_start = time.perf_counter()
        detected_crops = detect_bird_crops(
            image,
            conf=conf,
            iou=iou,
            imgsz=imgsz,
            detect_batch_size=detect_batch_size,
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
                detect_batch_size=detect_batch_size,
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

    return crop_entries, detect_seconds


def _recognize_box_in_image(
    image: Image.Image,
    *,
    filename: str | None,
    box_values: tuple[float, float, float, float],
    top_k: int,
    batch_size: int,
    save_crop: bool,
    include_crop_image: bool,
) -> dict[str, object]:
    request_start = time.perf_counter()
    box = _normalize_box(box_values, image.size)
    crop_image = image.crop(box)
    run_dir = _create_run_dir() if save_crop else None
    crop_path = _save_crop(run_dir, filename, 1, crop_image)

    recognize_start = time.perf_counter()
    recognition_result = _recognize_images(
        [crop_image],
        k=top_k,
        batch_size=batch_size,
    )
    recognize_seconds = time.perf_counter() - recognize_start
    predictions = recognition_result.predictions_by_image[0]
    total_seconds = time.perf_counter() - request_start

    crop = AnalysisCrop(
        image=crop_image,
        box=box,
        detection_confidence=None,
        source="manual",
    )
    return {
        "filename": filename,
        "image_size": image.size,
        "crop_count": 1,
        "output_dir": str(run_dir) if run_dir is not None else None,
        "device": recognition_result.device,
        "device_name": recognition_result.device_name,
        "timing": {
            "detect_seconds": 0.0,
            "recognize_seconds": recognize_seconds,
            "total_seconds": total_seconds,
        },
        "results": [
            _format_crop_result(
                1,
                crop,
                crop_path=crop_path,
                predictions=predictions,
                include_crop_image=include_crop_image,
            )
        ],
    }


def _format_crop_result(
    crop_index: int,
    crop: AnalysisCrop,
    *,
    crop_path: Path | None,
    predictions: list[Prediction],
    include_crop_image: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "index": crop_index,
        "box": crop.box,
        "detection_confidence": crop.detection_confidence,
        "source": crop.source,
        "crop_path": str(crop_path) if crop_path is not None else None,
        "predictions": predictions,
    }
    if include_crop_image:
        result["crop_image"] = {
            "content_type": "image/png",
            "base64": _encode_png_base64(crop.image),
        }
    return result


def _encode_png_base64(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


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


def _recognize_images(
    images: list[Image.Image],
    *,
    k: int,
    batch_size: int,
) -> RecognitionBatchResult:
    return _get_recognition_batcher().submit(
        images,
        k=k,
        batch_size=batch_size,
    )


def _get_recognition_batcher() -> RecognitionBatcher:
    global _recognition_batcher

    if _recognition_batcher is None:
        with _recognition_batcher_lock:
            if _recognition_batcher is None:
                _recognition_batcher = RecognitionBatcher(
                    max_wait_ms=_read_non_negative_float_env(
                        "BIRDMARK_RECOGNITION_BATCH_WAIT_MS",
                        DEFAULT_RECOGNITION_BATCH_WAIT_MS,
                    ),
                    max_image_count=_read_positive_int_env(
                        "BIRDMARK_RECOGNITION_QUEUE_MAX_IMAGES",
                        DEFAULT_RECOGNITION_QUEUE_MAX_IMAGES,
                    ),
                )

    return _recognition_batcher


def _stop_recognition_batcher() -> None:
    global _recognition_batcher

    if _recognition_batcher is None:
        return

    with _recognition_batcher_lock:
        if _recognition_batcher is not None:
            _recognition_batcher.close()
            _recognition_batcher = None


def _read_positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _read_non_negative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(0.0, value)


def _preload_models() -> None:
    preload_start = time.perf_counter()
    logger.info("Preloading detector and recognizer models...")

    with _analysis_lock:
        detect_start = time.perf_counter()
        warmup_detection_model(
            conf=DEFAULT_DETECT_CONF,
            iou=DEFAULT_DETECT_IOU,
            imgsz=DEFAULT_DETECT_IMGSZ,
            detect_batch_size=DEFAULT_DETECT_BATCH_SIZE,
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
