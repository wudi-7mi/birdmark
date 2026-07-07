from __future__ import annotations

import httpx

from .config import settings


class InferenceClientError(RuntimeError):
    pass


def analyze_image(
    image_bytes: bytes,
    *,
    filename: str,
    top_k: int = 5,
) -> dict[str, object]:
    url = f"{settings.inference_base_url}/internal/analyze-image"
    files = {"file": (filename, image_bytes, "application/octet-stream")}
    params = {
        "top_k": top_k,
        "include_crop_images": "true",
        "full_image_fallback": "false",
    }
    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, files=files, params=params)
    except httpx.HTTPError as exc:
        raise InferenceClientError(f"Could not reach inference service: {exc}") from exc

    if response.status_code >= 400:
        raise InferenceClientError(
            f"Inference service returned {response.status_code}: {response.text}"
        )
    return response.json()
