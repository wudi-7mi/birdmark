from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from bird_recognition import BirdSpeciesRecognizer, get_device_name, synchronize_if_needed


DEFAULT_BIRDS525_ROOT = Path("datasets") / "BIRDS-525-SPECIES-IMAGE-CLASSIFICATION-main"
DEFAULT_CUB_ROOT = Path("datasets") / "CUB_200_2011" / "CUB_200_2011"
DEFAULT_HIFSOD_ROOT = Path("datasets") / "HIFSOD"
DEFAULT_HIFSOD_ANN = DEFAULT_HIFSOD_ROOT / "new_annos" / "datasplit" / "8k.json"
DEFAULT_OUTPUT_ROOT = Path("res") / "classification_eval"


@dataclass(frozen=True)
class EvaluationSample:
    image_path: Path
    label: str
    aliases: tuple[str, ...]
    dataset: str
    class_id: str = ""
    scientific_name: str = ""


@dataclass(frozen=True)
class PredictionView:
    names: tuple[str, ...]
    display_name: str
    species: str
    common_name: str
    score: float | None


@dataclass(frozen=True)
class SampleResult:
    sample: EvaluationSample
    rank: int | None
    predictions: list[dict[str, object]]
    elapsed_seconds: float


@dataclass
class ClassStats:
    samples: int = 0
    top1_correct: int = 0
    best_topk_correct: int = 0
    reciprocal_rank_sum: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Birdmark bird species classification on local datasets."
    )
    parser.add_argument(
        "--dataset",
        choices=("birds525", "cub", "hifsod"),
        default="birds525",
        help="Dataset to evaluate. Default: birds525.",
    )
    parser.add_argument(
        "--split",
        default=None,
        help=(
            "Dataset split. birds525: train/valid/test/all; "
            "cub: train/test/all. Default: test where available."
        ),
    )
    parser.add_argument("--birds525-root", type=Path, default=DEFAULT_BIRDS525_ROOT)
    parser.add_argument("--cub-root", type=Path, default=DEFAULT_CUB_ROOT)
    parser.add_argument("--hifsod-root", type=Path, default=DEFAULT_HIFSOD_ROOT)
    parser.add_argument("--hifsod-ann", type=Path, default=DEFAULT_HIFSOD_ANN)
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=[1, 3, 5],
        help="Top-k accuracies to report. Default: 1 3 5.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Classifier inference batch size. Default: 10.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Torch device passed to BirdSpeciesRecognizer, for example cuda or cpu.",
    )
    parser.add_argument(
        "--min-prob",
        type=float,
        default=1e-9,
        help="Minimum prediction probability passed to BioCLIP. Default: 1e-9.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Evaluate at most this many samples after split filtering.",
    )
    parser.add_argument(
        "--max-per-class",
        type=int,
        default=None,
        help="Evaluate at most this many samples per class.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed used when --limit or --max-per-class is set. Default: 0.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for summary.json, per_class.csv and mistakes.csv.",
    )
    parser.add_argument(
        "--report-only-dir",
        type=Path,
        default=None,
        help="Build tables and error-example images from an existing evaluation directory.",
    )
    parser.add_argument(
        "--compare-dirs",
        type=Path,
        nargs="+",
        default=None,
        help="Build one comparison table from multiple existing evaluation directories.",
    )
    parser.add_argument(
        "--compare-output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Output directory for --compare-dirs tables. Default: res/classification_eval.",
    )
    parser.add_argument(
        "--error-image-count",
        type=int,
        default=24,
        help="Number of confident mistake images to export. Use 0 to disable. Default: 24.",
    )
    parser.add_argument(
        "--report-table-limit",
        type=int,
        default=30,
        help="Maximum rows in compact Markdown report tables. Default: 30.",
    )
    parser.add_argument(
        "--include-missing",
        action="store_true",
        help="Keep samples whose image files are missing and count them as failures.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    top_ks = sorted(set(k for k in args.top_k if k > 0))
    if not top_ks:
        raise SystemExit("--top-k must contain at least one positive integer")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be > 0")
    if args.max_per_class is not None and args.max_per_class <= 0:
        raise SystemExit("--max-per-class must be > 0")
    if args.error_image_count < 0:
        raise SystemExit("--error-image-count must be >= 0")
    if args.report_table_limit <= 0:
        raise SystemExit("--report-table-limit must be > 0")

    if args.compare_dirs is not None:
        write_comparison_outputs(args.compare_output_dir, args.compare_dirs)
        print(f"comparison table written to: {args.compare_output_dir / 'comparison_table.md'}")
        return

    if args.report_only_dir is not None:
        output_dir = args.report_only_dir
        summary, per_class_rows, mistake_rows = read_existing_outputs(output_dir)
        write_report_outputs(
            output_dir,
            summary,
            per_class_rows,
            mistake_rows,
            error_image_count=args.error_image_count,
            table_limit=args.report_table_limit,
        )
        print_summary(summary)
        print(f"report written to: {output_dir / 'report.md'}")
        return

    samples = load_samples(args)
    if not args.include_missing:
        samples = [sample for sample in samples if sample.image_path.exists()]
    samples = sample_subset(
        samples,
        limit=args.limit,
        max_per_class=args.max_per_class,
        seed=args.seed,
    )
    if not samples:
        raise SystemExit("No evaluation samples found")

    output_dir = args.output_dir or (
        DEFAULT_OUTPUT_ROOT
        / f"{args.dataset}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Dataset: {args.dataset}")
    print(f"Samples: {len(samples)}")
    print(f"Classes: {len({sample.class_id or sample.label for sample in samples})}")
    print(f"Top-k: {', '.join(str(k) for k in top_ks)}")
    print(f"Output: {output_dir}")

    recognizer = BirdSpeciesRecognizer(device=args.device)
    synchronize_if_needed(recognizer.device)
    device_name = get_device_name(recognizer.device)
    print(f"Device: {recognizer.device}" + (f" ({device_name})" if device_name else ""))

    started = time.perf_counter()
    results = evaluate_samples(
        recognizer=recognizer,
        samples=samples,
        top_k=max(top_ks),
        batch_size=args.batch_size,
        min_prob=args.min_prob,
    )
    synchronize_if_needed(recognizer.device)
    elapsed_seconds = time.perf_counter() - started

    summary, per_class_rows, mistake_rows = summarize_results(
        results,
        dataset=args.dataset,
        split=resolve_split(args.dataset, args.split),
        top_ks=top_ks,
        elapsed_seconds=elapsed_seconds,
        device=recognizer.device,
        device_name=device_name,
    )
    write_outputs(output_dir, summary, per_class_rows, mistake_rows)
    write_report_outputs(
        output_dir,
        summary,
        per_class_rows,
        mistake_rows,
        error_image_count=args.error_image_count,
        table_limit=args.report_table_limit,
    )
    print_summary(summary)


def load_samples(args: argparse.Namespace) -> list[EvaluationSample]:
    if args.dataset == "birds525":
        return load_birds525(args.birds525_root, resolve_split(args.dataset, args.split))
    if args.dataset == "cub":
        return load_cub(args.cub_root, resolve_split(args.dataset, args.split))
    if args.dataset == "hifsod":
        return load_hifsod(args.hifsod_root, args.hifsod_ann)
    raise ValueError(f"Unsupported dataset: {args.dataset}")


def resolve_split(dataset: str, split: str | None) -> str:
    if split is not None:
        return split.lower()
    if dataset in {"birds525", "cub"}:
        return "test"
    return "all"


def load_birds525(root: Path, split: str) -> list[EvaluationSample]:
    csv_path = root / "birds.csv"
    if not csv_path.exists():
        raise SystemExit(f"birds.csv not found: {csv_path}")

    valid_splits = {"train", "valid", "test", "all"}
    if split not in valid_splits:
        raise SystemExit(f"Invalid birds525 split '{split}'. Use one of {sorted(valid_splits)}")

    samples: list[EvaluationSample] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_split = row.get("data set", "").strip().lower()
            if split != "all" and row_split != split:
                continue
            label = row.get("labels", "").strip()
            scientific_name = row.get("scientific name", "").strip()
            if not label:
                continue
            samples.append(
                EvaluationSample(
                    image_path=root / row["filepaths"],
                    label=label,
                    aliases=make_aliases(label, scientific_name),
                    dataset="birds525",
                    class_id=str(row.get("class id", "")).strip(),
                    scientific_name=scientific_name,
                )
            )
    return samples


def load_cub(root: Path, split: str) -> list[EvaluationSample]:
    valid_splits = {"train", "test", "all"}
    if split not in valid_splits:
        raise SystemExit(f"Invalid cub split '{split}'. Use one of {sorted(valid_splits)}")

    images = read_id_map(root / "images.txt")
    labels = read_id_map(root / "image_class_labels.txt")
    classes = read_id_map(root / "classes.txt")
    train_flags = read_id_map(root / "train_test_split.txt")

    samples: list[EvaluationSample] = []
    for image_id, relative_path in images.items():
        is_train = train_flags[image_id] == "1"
        if split == "train" and not is_train:
            continue
        if split == "test" and is_train:
            continue
        class_id = labels[image_id]
        raw_class_name = classes[class_id]
        label = cub_label_to_common_name(raw_class_name)
        samples.append(
            EvaluationSample(
                image_path=root / "images" / relative_path,
                label=label,
                aliases=make_aliases(label, raw_class_name),
                dataset="cub",
                class_id=class_id,
            )
        )
    return samples


def load_hifsod(root: Path, ann_path: Path) -> list[EvaluationSample]:
    if not ann_path.exists():
        raise SystemExit(f"HIFSOD annotation file not found: {ann_path}")

    with ann_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    categories = {
        str(category["id"]): str(category["name"])
        for category in data.get("categories", [])
    }
    category_ids_by_image: dict[str, set[str]] = defaultdict(set)
    for annotation in data.get("annotations", []):
        category_ids_by_image[str(annotation["image_id"])].add(str(annotation["category_id"]))

    samples: list[EvaluationSample] = []
    for image in data.get("images", []):
        image_id = str(image["id"])
        category_ids = category_ids_by_image.get(image_id, set())
        if len(category_ids) != 1:
            continue
        class_id = next(iter(category_ids))
        raw_name = categories.get(class_id, class_id)
        label = hifsod_label_to_common_name(raw_name)
        samples.append(
            EvaluationSample(
                image_path=root / "images" / str(image["file_name"]),
                label=label,
                aliases=make_aliases(label, raw_name),
                dataset="hifsod",
                class_id=class_id,
            )
        )
    return samples


def read_id_map(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"Required file not found: {path}")
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            key, value = line.split(maxsplit=1)
            mapping[key] = value
    return mapping


def sample_subset(
    samples: list[EvaluationSample],
    *,
    limit: int | None,
    max_per_class: int | None,
    seed: int,
) -> list[EvaluationSample]:
    if limit is None and max_per_class is None:
        return samples

    rng = random.Random(seed)
    shuffled = list(samples)
    rng.shuffle(shuffled)

    if max_per_class is not None:
        counts: Counter[str] = Counter()
        capped: list[EvaluationSample] = []
        for sample in shuffled:
            key = sample.class_id or sample.label
            if counts[key] >= max_per_class:
                continue
            counts[key] += 1
            capped.append(sample)
        shuffled = capped

    if limit is not None:
        shuffled = shuffled[:limit]

    return sorted(shuffled, key=lambda sample: str(sample.image_path))


def evaluate_samples(
    *,
    recognizer: BirdSpeciesRecognizer,
    samples: Sequence[EvaluationSample],
    top_k: int,
    batch_size: int,
    min_prob: float,
) -> list[SampleResult]:
    results: list[SampleResult] = []
    total = len(samples)
    for start in range(0, total, batch_size):
        batch = list(samples[start : start + batch_size])
        batch_started = time.perf_counter()
        existing_images = [sample.image_path for sample in batch if sample.image_path.exists()]
        predictions_by_existing = recognizer.predict(
            existing_images,
            min_prob=min_prob,
            k=top_k,
            batch_size=batch_size,
        )
        elapsed = time.perf_counter() - batch_started
        predictions_by_path = {
            str(path): predictions
            for path, predictions in zip(existing_images, predictions_by_existing)
        }
        for sample in batch:
            predictions = predictions_by_path.get(str(sample.image_path), [])
            rank = first_correct_rank(sample.aliases, predictions)
            results.append(
                SampleResult(
                    sample=sample,
                    rank=rank,
                    predictions=predictions,
                    elapsed_seconds=elapsed / max(1, len(batch)),
                )
            )
        processed = min(start + len(batch), total)
        print(f"Evaluated {processed}/{total}", flush=True)
    return results


def first_correct_rank(
    aliases: Sequence[str],
    predictions: Sequence[dict[str, object]],
) -> int | None:
    alias_set = set(aliases)
    for index, prediction in enumerate(predictions, start=1):
        prediction_view = prediction_to_view(prediction)
        if alias_set.intersection(prediction_view.names):
            return index
    return None


def summarize_results(
    results: Sequence[SampleResult],
    *,
    dataset: str,
    split: str,
    top_ks: Sequence[int],
    elapsed_seconds: float,
    device: str,
    device_name: str | None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    total = len(results)
    topk_correct = {
        k: sum(1 for result in results if result.rank is not None and result.rank <= k)
        for k in top_ks
    }
    reciprocal_rank_sum = sum(
        1.0 / result.rank for result in results if result.rank is not None
    )
    missing_images = sum(1 for result in results if not result.sample.image_path.exists())
    empty_predictions = sum(1 for result in results if not result.predictions)
    best_k = max(top_ks)

    stats_by_class: dict[str, ClassStats] = defaultdict(ClassStats)
    label_by_class: dict[str, str] = {}
    scientific_by_class: dict[str, str] = {}
    for result in results:
        class_key = result.sample.class_id or result.sample.label
        label_by_class[class_key] = result.sample.label
        scientific_by_class[class_key] = result.sample.scientific_name
        stats = stats_by_class[class_key]
        stats.samples += 1
        if result.rank == 1:
            stats.top1_correct += 1
        if result.rank is not None and result.rank <= best_k:
            stats.best_topk_correct += 1
            stats.reciprocal_rank_sum += 1.0 / result.rank

    per_class_rows: list[dict[str, object]] = []
    for class_key, stats in sorted(
        stats_by_class.items(),
        key=lambda item: (label_by_class[item[0]], item[0]),
    ):
        per_class_rows.append(
            {
                "class_id": class_key,
                "label": label_by_class[class_key],
                "scientific_name": scientific_by_class[class_key],
                "samples": stats.samples,
                "top1_correct": stats.top1_correct,
                "top1_accuracy": safe_divide(stats.top1_correct, stats.samples),
                f"top{best_k}_correct": stats.best_topk_correct,
                f"top{best_k}_accuracy": safe_divide(stats.best_topk_correct, stats.samples),
                "mrr": safe_divide(stats.reciprocal_rank_sum, stats.samples),
            }
        )

    mistake_rows = [
        mistake_row(result)
        for result in results
        if result.rank is None or result.rank > best_k
    ]

    summary: dict[str, object] = {
        "dataset": dataset,
        "split": split,
        "samples": total,
        "classes": len(stats_by_class),
        "elapsed_seconds": elapsed_seconds,
        "images_per_second": safe_divide(total, elapsed_seconds),
        "device": device,
        "device_name": device_name,
        "missing_images": missing_images,
        "empty_predictions": empty_predictions,
        "mrr": safe_divide(reciprocal_rank_sum, total),
        "macro_top1_accuracy": mean(
            row["top1_accuracy"] for row in per_class_rows
        ),
        f"macro_top{best_k}_accuracy": mean(
            row[f"top{best_k}_accuracy"] for row in per_class_rows
        ),
        "topk": {
            str(k): {
                "correct": topk_correct[k],
                "accuracy": safe_divide(topk_correct[k], total),
            }
            for k in top_ks
        },
    }
    return summary, per_class_rows, mistake_rows


def mistake_row(result: SampleResult) -> dict[str, object]:
    top1 = prediction_to_view(result.predictions[0]) if result.predictions else None
    return {
        "image_path": str(result.sample.image_path),
        "class_id": result.sample.class_id,
        "label": result.sample.label,
        "scientific_name": result.sample.scientific_name,
        "correct_rank": result.rank if result.rank is not None else "",
        "top1_display": top1.display_name if top1 else "",
        "top1_species": top1.species if top1 else "",
        "top1_common_name": top1.common_name if top1 else "",
        "top1_score": top1.score if top1 and top1.score is not None else "",
        "predictions_json": json.dumps(result.predictions, ensure_ascii=False),
    }


def write_outputs(
    output_dir: Path,
    summary: dict[str, object],
    per_class_rows: Sequence[dict[str, object]],
    mistake_rows: Sequence[dict[str, object]],
) -> None:
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_csv(output_dir / "per_class.csv", per_class_rows)
    write_csv(output_dir / "mistakes.csv", mistake_rows)


def read_existing_outputs(
    output_dir: Path,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"summary.json not found: {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    per_class_rows = read_csv_rows(output_dir / "per_class.csv")
    mistake_rows = read_csv_rows(output_dir / "mistakes.csv")
    return summary, per_class_rows, mistake_rows


def read_csv_rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"CSV not found: {path}")
    if path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_report_outputs(
    output_dir: Path,
    summary: dict[str, object],
    per_class_rows: Sequence[dict[str, object]],
    mistake_rows: Sequence[dict[str, object]],
    *,
    error_image_count: int,
    table_limit: int,
) -> None:
    summary_rows = [make_summary_table_row(summary)]
    worst_class_rows = make_worst_class_rows(per_class_rows, limit=table_limit)
    mistake_table_rows = make_mistake_table_rows(mistake_rows, limit=table_limit)
    error_example_rows = export_error_images(
        output_dir,
        mistake_rows,
        count=error_image_count,
    )

    write_csv(output_dir / "summary_table.csv", summary_rows)
    (output_dir / "summary_table.md").write_text(
        markdown_table(summary_rows),
        encoding="utf-8",
    )
    write_csv(output_dir / "per_class_worst.csv", worst_class_rows)
    (output_dir / "per_class_worst.md").write_text(
        markdown_table(worst_class_rows),
        encoding="utf-8",
    )
    write_csv(output_dir / "mistakes_top.csv", mistake_table_rows)
    (output_dir / "mistakes_top.md").write_text(
        markdown_table(mistake_table_rows),
        encoding="utf-8",
    )
    write_csv(output_dir / "error_examples.csv", error_example_rows)
    (output_dir / "report.md").write_text(
        build_markdown_report(
            summary_rows=summary_rows,
            worst_class_rows=worst_class_rows,
            mistake_rows=mistake_table_rows,
            error_example_rows=error_example_rows,
        ),
        encoding="utf-8",
    )


def write_comparison_outputs(output_dir: Path, run_dirs: Sequence[Path]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for run_dir in run_dirs:
        summary_path = run_dir / "summary.json"
        if not summary_path.exists():
            raise SystemExit(f"summary.json not found: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        row = make_summary_table_row(summary)
        row["run_dir"] = str(run_dir)
        rows.append(row)

    write_csv(output_dir / "comparison_table.csv", rows)
    table = markdown_table(rows)
    (output_dir / "comparison_table.md").write_text(table, encoding="utf-8")
    (output_dir / "comparison_report.md").write_text(
        "\n".join(
            [
                "# Classification Evaluation Comparison",
                "",
                table,
                "",
            ]
        ),
        encoding="utf-8",
    )


def make_summary_table_row(summary: dict[str, object]) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset": summary.get("dataset", ""),
        "split": summary.get("split", ""),
        "samples": summary.get("samples", ""),
        "classes": summary.get("classes", ""),
    }
    topk = summary.get("topk", {})
    if isinstance(topk, dict):
        for key in sorted(topk, key=lambda item: int(str(item))):
            metrics = topk[key]
            if not isinstance(metrics, dict):
                continue
            row[f"top{key}_accuracy"] = format_percent(metrics.get("accuracy"))
            row[f"top{key}_correct"] = metrics.get("correct", "")
    row["mrr"] = format_decimal(summary.get("mrr"), places=4)
    row["macro_top1_accuracy"] = format_percent(summary.get("macro_top1_accuracy"))
    macro_top_key = highest_metric_key(summary, prefix="macro_top", suffix="_accuracy")
    if macro_top_key and macro_top_key != "macro_top1_accuracy":
        row[macro_top_key] = format_percent(summary.get(macro_top_key))
    row["images_per_second"] = format_decimal(summary.get("images_per_second"), places=2)
    row["elapsed_seconds"] = format_decimal(summary.get("elapsed_seconds"), places=2)
    row["missing_images"] = summary.get("missing_images", "")
    row["empty_predictions"] = summary.get("empty_predictions", "")
    return row


def make_worst_class_rows(
    per_class_rows: Sequence[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    if not per_class_rows:
        return []
    best_top_key = highest_metric_key(per_class_rows[0], prefix="top", suffix="_accuracy")
    selected = sorted(
        per_class_rows,
        key=lambda row: (
            as_float(row.get("top1_accuracy")),
            as_float(row.get(best_top_key)) if best_top_key else 0.0,
            -as_float(row.get("samples")),
            str(row.get("label", "")),
        ),
    )[:limit]
    table_rows: list[dict[str, object]] = []
    for index, row in enumerate(selected, start=1):
        table_row: dict[str, object] = {
            "rank": index,
            "class_id": row.get("class_id", ""),
            "label": row.get("label", ""),
            "samples": row.get("samples", ""),
            "top1_accuracy": format_percent(row.get("top1_accuracy")),
        }
        if best_top_key and best_top_key != "top1_accuracy":
            table_row[best_top_key] = format_percent(row.get(best_top_key))
        table_row["mrr"] = format_decimal(row.get("mrr"), places=4)
        table_rows.append(table_row)
    return table_rows


def make_mistake_table_rows(
    mistake_rows: Sequence[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    selected = sort_mistakes(mistake_rows)[:limit]
    table_rows: list[dict[str, object]] = []
    for index, row in enumerate(selected, start=1):
        table_rows.append(
            {
                "rank": index,
                "label": row.get("label", ""),
                "scientific_name": row.get("scientific_name", ""),
                "top1_prediction": mistake_prediction_name(row),
                "top1_score": format_decimal(row.get("top1_score"), places=4),
                "correct_rank": row.get("correct_rank", ""),
                "image": Path(str(row.get("image_path", ""))).name,
            }
        )
    return table_rows


def export_error_images(
    output_dir: Path,
    mistake_rows: Sequence[dict[str, object]],
    *,
    count: int,
) -> list[dict[str, object]]:
    image_dir = output_dir / "error_examples"
    if count == 0:
        return []
    image_dir.mkdir(parents=True, exist_ok=True)
    for old_path in image_dir.glob("*.jpg"):
        old_path.unlink()

    exported_rows: list[dict[str, object]] = []
    for row in sort_mistakes(mistake_rows):
        if len(exported_rows) >= count:
            break
        image_path = Path(str(row.get("image_path", "")))
        if not image_path.exists():
            continue
        prediction_name = mistake_prediction_name(row)
        output_path = image_dir / (
            f"{len(exported_rows) + 1:03d}_"
            f"{sanitize_filename(str(row.get('label', 'unknown')))}"
            f"__pred_{sanitize_filename(prediction_name or 'unknown')}.jpg"
        )
        try:
            annotate_error_image(row, image_path, output_path)
        except (OSError, UnidentifiedImageError):
            continue
        exported_rows.append(
            {
                "rank": len(exported_rows) + 1,
                "example_image": relative_posix(output_path, output_dir),
                "source_image": str(image_path),
                "label": row.get("label", ""),
                "scientific_name": row.get("scientific_name", ""),
                "top1_prediction": prediction_name,
                "top1_score": format_decimal(row.get("top1_score"), places=4),
                "correct_rank": row.get("correct_rank", ""),
            }
        )
    return exported_rows


def annotate_error_image(
    row: dict[str, object],
    image_path: Path,
    output_path: Path,
) -> None:
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((900, 900), Image.Resampling.LANCZOS)

        font = ImageFont.load_default()
        scratch = Image.new("RGB", (1, 1), "white")
        draw = ImageDraw.Draw(scratch)
        canvas_width = max(image.width, 900)
        text_width = canvas_width - 24
        lines = [
            ("TRUE", f"TRUE: {row.get('label', '')} | {row.get('scientific_name', '')}"),
            (
                "PRED",
                (
                    f"TOP-1: {mistake_prediction_name(row)}"
                    f"  score={format_decimal(row.get('top1_score'), places=4)}"
                ),
            ),
            ("FILE", f"FILE: {image_path.name}"),
        ]
        wrapped_lines: list[tuple[str, str]] = []
        for kind, text in lines:
            for wrapped in wrap_text_for_width(draw, text, font, text_width):
                wrapped_lines.append((kind, wrapped))

        line_height = text_pixel_height(draw, font) + 4
        header_height = 16 + len(wrapped_lines) * line_height
        canvas = Image.new("RGB", (canvas_width, header_height + image.height), "white")
        canvas_draw = ImageDraw.Draw(canvas)

        y = 8
        colors = {
            "TRUE": (18, 83, 45),
            "PRED": (145, 38, 38),
            "FILE": (70, 70, 70),
        }
        for kind, text in wrapped_lines:
            canvas_draw.text((12, y), text, fill=colors.get(kind, (20, 20, 20)), font=font)
            y += line_height
        canvas_draw.line((0, header_height - 1, canvas_width, header_height - 1), fill=(210, 210, 210))
        canvas.paste(image, ((canvas_width - image.width) // 2, header_height))
        canvas.save(output_path, format="JPEG", quality=92)


def build_markdown_report(
    *,
    summary_rows: Sequence[dict[str, object]],
    worst_class_rows: Sequence[dict[str, object]],
    mistake_rows: Sequence[dict[str, object]],
    error_example_rows: Sequence[dict[str, object]],
) -> str:
    lines = [
        "# Classification Evaluation Report",
        "",
        "## Summary",
        "",
        markdown_table(summary_rows),
        "",
        "## Worst Classes",
        "",
        markdown_table(worst_class_rows),
        "",
        "## Confident Mistakes",
        "",
        markdown_table(mistake_rows),
        "",
        "## Error Examples",
        "",
    ]
    if error_example_rows:
        image_rows = [
            {
                "rank": row.get("rank", ""),
                "example": f"![]({row.get('example_image', '')})",
                "label": row.get("label", ""),
                "top1_prediction": row.get("top1_prediction", ""),
                "top1_score": row.get("top1_score", ""),
            }
            for row in error_example_rows
        ]
        lines.append(markdown_table(image_rows))
    else:
        lines.append("_No error example images exported._")
    lines.append("")
    return "\n".join(lines)


def markdown_table(rows: Sequence[dict[str, object]]) -> str:
    if not rows:
        return "_No rows._"
    columns = list(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| "
        + " | ".join(markdown_cell(row.get(column, "")) for column in columns)
        + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def markdown_cell(value: object) -> str:
    text = str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def sort_mistakes(
    mistake_rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        mistake_rows,
        key=lambda row: (
            -as_float(row.get("top1_score")),
            str(row.get("label", "")),
            str(row.get("image_path", "")),
        ),
    )


def mistake_prediction_name(row: dict[str, object]) -> str:
    return str(
        row.get("top1_common_name")
        or row.get("top1_species")
        or row.get("top1_display")
        or ""
    )


def wrap_text_for_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if text_pixel_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def text_pixel_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def text_pixel_height(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
) -> int:
    _left, top, _right, bottom = draw.textbbox((0, 0), "Ag", font=font)
    return bottom - top


def highest_metric_key(
    row: dict[str, object],
    *,
    prefix: str,
    suffix: str,
) -> str | None:
    keys = [
        key
        for key in row
        if str(key).startswith(prefix) and str(key).endswith(suffix)
    ]
    if not keys:
        return None
    return max(keys, key=metric_key_number)


def metric_key_number(key: object) -> int:
    match = re.search(r"(\d+)", str(key))
    if match is None:
        return 0
    return int(match.group(1))


def format_percent(value: object) -> str:
    return f"{as_float(value) * 100:.2f}%"


def format_decimal(value: object, *, places: int) -> str:
    if value in (None, ""):
        return ""
    return f"{as_float(value):.{places}f}"


def as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.endswith("%"):
        text = text[:-1]
        try:
            return float(text) / 100.0
        except ValueError:
            return default
    try:
        return float(text)
    except ValueError:
        return default


def sanitize_filename(value: str, *, max_length: int = 60) -> str:
    normalized = normalize_name(value)
    normalized = normalized.replace(" ", "_")
    if not normalized:
        normalized = "unknown"
    return normalized[:max_length]


def relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(summary: dict[str, object]) -> None:
    print("")
    print("Summary")
    print(f"  samples: {summary['samples']}")
    print(f"  classes: {summary['classes']}")
    for k, metrics in summary["topk"].items():  # type: ignore[union-attr]
        print(f"  top-{k}: {metrics['accuracy']:.4f} ({metrics['correct']}/{summary['samples']})")
    print(f"  mrr: {summary['mrr']:.4f}")
    print(f"  macro top-1: {summary['macro_top1_accuracy']:.4f}")
    print(f"  elapsed: {summary['elapsed_seconds']:.2f}s")


def prediction_to_view(prediction: dict[str, object]) -> PredictionView:
    species = str(prediction.get("species") or "")
    common_name = str(prediction.get("common_name") or "")
    genus = str(prediction.get("genus") or "")
    species_epithet = str(prediction.get("species_epithet") or "")
    display_name = species or common_name or genus or "unknown"
    score_value = prediction.get("score")
    score = float(score_value) if isinstance(score_value, (float, int)) else None

    names = make_aliases(
        species,
        common_name,
        " ".join(part for part in (genus, species_epithet) if part),
    )
    return PredictionView(
        names=names,
        display_name=display_name,
        species=species,
        common_name=common_name,
        score=score,
    )


def make_aliases(*values: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in values:
        for candidate in expand_label_variants(value):
            normalized = normalize_name(candidate)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
    return tuple(aliases)


def expand_label_variants(value: str) -> Iterable[str]:
    cleaned = value.strip()
    if not cleaned:
        return []
    variants = [cleaned]
    variants.append(cleaned.replace("_", " "))
    variants.append(cleaned.replace("-", " "))
    variants.append(cleaned.replace(".", " "))
    if "." in cleaned:
        variants.append(cleaned.split(".")[-1].replace("_", " "))
    return variants


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"['`]", "", normalized)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def cub_label_to_common_name(raw_class_name: str) -> str:
    without_id = re.sub(r"^\d+\.", "", raw_class_name)
    return without_id.replace("_", " ")


def hifsod_label_to_common_name(raw_name: str) -> str:
    return raw_name.split(".")[-1].replace("_", " ")


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def mean(values: Iterable[object]) -> float:
    numeric_values = [float(value) for value in values]
    if not numeric_values:
        return 0.0
    return sum(numeric_values) / len(numeric_values)


if __name__ == "__main__":
    main()
