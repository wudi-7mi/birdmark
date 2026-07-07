from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from PIL import Image

if TYPE_CHECKING:
    from bioclip import Rank
    from bioclip.predict import TreeOfLifeClassifier


BioClipImage = str | Path | Image.Image
Prediction = dict[str, object]


def resolve_device(device: str | None = None) -> str:
    if device is not None:
        return device
    torch = _get_torch()
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_device_name(device: str) -> str | None:
    torch = _get_torch()
    if device == "cuda" and torch.cuda.is_available():
        return torch.cuda.get_device_name(0)
    return None


def synchronize_if_needed(device: str) -> None:
    torch = _get_torch()
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()


class BirdSpeciesRecognizer:
    def __init__(
        self,
        *,
        device: str | None = None,
        classifier: TreeOfLifeClassifier | None = None,
    ) -> None:
        self.device = resolve_device(device)
        classifier_class = _get_tree_classifier_class()
        self.classifier = classifier or classifier_class(device=self.device)

    def predict(
        self,
        images: BioClipImage | Sequence[BioClipImage],
        *,
        rank: Rank | None = None,
        min_prob: float = 1e-9,
        k: int = 5,
        batch_size: int = 10,
    ) -> list[list[Prediction]]:
        normalized_images = _normalize_images(images)
        if not normalized_images:
            return []

        predict_inputs = [
            str(image) if isinstance(image, Path) else image
            for image in normalized_images
        ]
        predictions = self.classifier.predict(
            predict_inputs,
            rank or _get_species_rank(),
            min_prob=min_prob,
            k=k,
            batch_size=batch_size,
        )
        return _group_predictions(predictions, predict_inputs)

    def predict_one(
        self,
        image: BioClipImage,
        *,
        rank: Rank | None = None,
        min_prob: float = 1e-9,
        k: int = 5,
    ) -> list[Prediction]:
        return self.predict(
            image,
            rank=rank,
            min_prob=min_prob,
            k=k,
            batch_size=1,
        )[0]


def format_predictions(predictions: Sequence[Prediction]) -> str:
    if not predictions:
        return "no prediction"

    formatted_predictions: list[str] = []
    for prediction in predictions:
        name = (
            prediction.get("species")
            or prediction.get("genus")
            or prediction.get("family")
            or prediction.get("common_name")
            or "unknown"
        )
        score = prediction.get("score")
        if isinstance(score, (float, int)):
            formatted_predictions.append(f"{name}={score:.4f}")
        else:
            formatted_predictions.append(str(name))

    return "; ".join(formatted_predictions)


def _get_torch():
    import torch

    return torch


def _get_species_rank():
    from bioclip import Rank

    return Rank.SPECIES


def _get_tree_classifier_class():
    from bioclip.predict import TreeOfLifeClassifier

    return TreeOfLifeClassifier


def _normalize_images(
    images: BioClipImage | Sequence[BioClipImage],
) -> list[BioClipImage]:
    if isinstance(images, (str, Path, Image.Image)):
        return [images]
    return list(images)


def _group_predictions(
    predictions: Sequence[Prediction],
    images: Sequence[str | Image.Image],
) -> list[list[Prediction]]:
    grouped_predictions = {
        _prediction_key(image, index): []
        for index, image in enumerate(images)
    }

    for prediction in predictions:
        file_name = prediction.get("file_name")
        if file_name is None:
            continue
        grouped_predictions.setdefault(str(file_name), []).append(prediction)

    return [
        grouped_predictions.get(_prediction_key(image, index), [])
        for index, image in enumerate(images)
    ]


def _prediction_key(image: str | Image.Image, index: int) -> str:
    if isinstance(image, Image.Image):
        return str(index)
    return image
