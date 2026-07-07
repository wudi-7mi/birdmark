from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.birdmark_ml.bird_recognition import (
    BirdSpeciesRecognizer,
    format_predictions,
    get_device_name,
    synchronize_if_needed,
)
from packages.birdmark_ml.birdcut import BirdCrop, detect_bird_crops


BIRD_DIR = PROJECT_ROOT / "birds"
LOG_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "res"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

DETECT_CONF = 0.04
DETECT_IOU = 0.85
DETECT_IMGSZ = 960
RECOGNITION_TOP_K = 5
RECOGNITION_BATCH_SIZE = 10


@dataclass(frozen=True)
class CropRecord:
    image_path: Path
    crop_index: int
    crop: BirdCrop
    crop_path: Path


def get_image_paths(image_dir: Path = BIRD_DIR) -> list[Path]:
    return sorted(
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def setup_logger() -> tuple[logging.Logger, Path]:
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"bird_pipeline_{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger("bird_pipeline")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger, log_path


def create_run_output_dir() -> Path:
    output_dir = OUTPUT_DIR / f"bird_pipeline_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_crop(
    crop: BirdCrop,
    *,
    image_path: Path,
    crop_index: int,
    output_dir: Path,
) -> Path:
    crop_path = output_dir / f"{image_path.stem}_crop_{crop_index:03d}.png"
    crop.image.save(crop_path)
    return crop_path


def main() -> None:
    logger, log_path = setup_logger()
    output_dir = create_run_output_dir()
    image_paths = get_image_paths()

    if not image_paths:
        logger.warning("No images found in %s", BIRD_DIR)
        print(f"log written to: {log_path}")
        return

    logger.info("Image directory: %s", BIRD_DIR.resolve())
    logger.info("Image count: %d", len(image_paths))
    logger.info("Crop output directory: %s", output_dir.resolve())
    logger.info(
        "Detection args: conf=%.3f iou=%.3f imgsz=%s",
        DETECT_CONF,
        DETECT_IOU,
        DETECT_IMGSZ,
    )

    total_detect_seconds = 0.0
    crop_records: list[CropRecord] = []

    for image_index, image_path in enumerate(image_paths, start=1):
        detect_start = time.perf_counter()
        crops = detect_bird_crops(
            image_path,
            conf=DETECT_CONF,
            iou=DETECT_IOU,
            imgsz=DETECT_IMGSZ,
        )
        detect_seconds = time.perf_counter() - detect_start
        total_detect_seconds += detect_seconds

        logger.info(
            "[%d/%d] %s | detected %d bird crop(s) | %.4fs",
            image_index,
            len(image_paths),
            image_path,
            len(crops),
            detect_seconds,
        )

        if not crops:
            continue

        for crop_index, crop in enumerate(crops, start=1):
            crop_path = save_crop(
                crop,
                image_path=image_path,
                crop_index=crop_index,
                output_dir=output_dir,
            )
            crop_records.append(
                CropRecord(
                    image_path=image_path,
                    crop_index=crop_index,
                    crop=crop,
                    crop_path=crop_path,
                )
            )

    logger.info("Total detected crop count: %d", len(crop_records))
    logger.info("Detection total time: %.4fs", total_detect_seconds)

    if not crop_records:
        logger.warning("No bird crops detected; recognition skipped")
        print(f"log written to: {log_path}")
        print(f"crop output written to: {output_dir}")
        return

    load_start = time.perf_counter()
    recognizer = BirdSpeciesRecognizer()
    synchronize_if_needed(recognizer.device)
    load_seconds = time.perf_counter() - load_start

    logger.info("Recognition device: %s", recognizer.device)
    device_name = get_device_name(recognizer.device)
    if device_name is not None:
        logger.info("GPU: %s", device_name)
    logger.info("BioCLIP model load time: %.4fs", load_seconds)

    recognize_start = time.perf_counter()
    grouped_predictions = recognizer.predict(
        [record.crop.image for record in crop_records],
        k=RECOGNITION_TOP_K,
        batch_size=RECOGNITION_BATCH_SIZE,
    )
    synchronize_if_needed(recognizer.device)
    total_recognize_seconds = time.perf_counter() - recognize_start

    logger.info(
        "Recognized %d crop(s) | %.4fs",
        len(crop_records),
        total_recognize_seconds,
    )

    for record, predictions in zip(crop_records, grouped_predictions):
        logger.info(
            "%s crop %03d | box=%s | detect_conf=%.4f | file=%s | %s",
            record.image_path,
            record.crop_index,
            record.crop.box,
            record.crop.confidence,
            record.crop_path,
            format_predictions(predictions),
        )

    end_to_end_seconds = load_seconds + total_detect_seconds + total_recognize_seconds
    logger.info("Recognition total time: %.4fs", total_recognize_seconds)
    logger.info("End-to-end time including BioCLIP load: %.4fs", end_to_end_seconds)

    print(f"log written to: {log_path}")
    print(f"crop output written to: {output_dir}")


if __name__ == "__main__":
    main()
