from __future__ import annotations

import argparse
from pathlib import Path

from birdcut import DEFAULT_DETECT_BATCH_SIZE, DEFAULT_MODEL_PT_PATH


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the default Birdmark YOLO detector to TensorRT.",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL_PT_PATH,
        help="Path to the source Ultralytics .pt model.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=960,
        help="Export image size. Keep this aligned with the service default.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_DETECT_BATCH_SIZE,
        help="Maximum TensorRT inference batch size.",
    )
    parser.add_argument(
        "--device",
        default="0",
        help="CUDA device for TensorRT export.",
    )
    parser.add_argument(
        "--precision",
        choices=("fp32", "fp16", "int8"),
        default="fp16",
        help="TensorRT precision.",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Disable dynamic TensorRT profiles.",
    )
    parser.add_argument(
        "--workspace",
        type=int,
        default=None,
        help="TensorRT workspace size in GiB. Leave unset for Ultralytics default.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Calibration dataset YAML, required for INT8 export.",
    )
    parser.add_argument(
        "--fraction",
        type=float,
        default=None,
        help="Fraction of calibration data to use for INT8 export.",
    )
    parser.add_argument(
        "--nms",
        action="store_true",
        help="Bake NMS into the exported engine.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model.expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"Model does not exist: {model_path}")
    if args.batch <= 0:
        raise ValueError("--batch must be > 0")
    if args.imgsz <= 0:
        raise ValueError("--imgsz must be > 0")
    if args.precision == "int8" and args.data is None:
        raise ValueError("--data is required for INT8 calibration export")

    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise RuntimeError("TensorRT export requires a CUDA GPU")

    quantize = {
        "fp32": 32,
        "fp16": 16,
        "int8": 8,
    }[args.precision]

    export_kwargs: dict[str, object] = {
        "format": "engine",
        "imgsz": args.imgsz,
        "batch": args.batch,
        "device": args.device,
        "dynamic": not args.static,
        "quantize": quantize,
        "nms": args.nms,
    }
    if args.workspace is not None:
        export_kwargs["workspace"] = args.workspace
    if args.data is not None:
        export_kwargs["data"] = str(args.data.expanduser().resolve())
    if args.fraction is not None:
        export_kwargs["fraction"] = args.fraction

    print(f"Source model: {model_path}")
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    print(f"Export args: {export_kwargs}")

    model = YOLO(str(model_path))
    exported_path = model.export(**export_kwargs)
    print(f"TensorRT engine written to: {exported_path}")
    print("Restart the service so Birdmark can load the .engine file.")


if __name__ == "__main__":
    main()
