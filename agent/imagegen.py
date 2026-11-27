"""AI image generation (OpenAI Images API) – produces Instagram-ready 1080x1350 JPGs."""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path

import requests

log = logging.getLogger(__name__)

STYLE = (
    "Vibrant, magical, family-friendly circus illustration for an Instagram post. "
    "Rich red, gold and deep purple palette, warm stage lights, sparkles. "
    "Absolutely no text, letters, numbers, logos or watermarks anywhere in the image. "
    "No real or famous people, no copyrighted characters. "
)


def enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def generate(prompt: str, out: Path, size: str = "1024x1536") -> Path:
    """Generate an image from `prompt` and save it as a 1080x1350 (4:5) JPG."""
    from PIL import Image, ImageOps

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = os.getenv("IMAGE_MODEL", "gpt-image-2")
    r = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "prompt": STYLE + prompt, "size": size,
              "quality": os.getenv("IMAGE_QUALITY", "medium"), "n": 1},
        timeout=300,
    )
    data = r.json()
    if r.status_code >= 400 or "data" not in data:
        raise RuntimeError(f"image generation failed: {data.get('error', data)}")
    img = Image.open(io.BytesIO(base64.b64decode(data["data"][0]["b64_json"]))).convert("RGB")
    # Instagram feed accepts 4:5 at most – crop/resize to 1080x1350.
    img = ImageOps.fit(img, (1080, 1350), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=92)
    log.info("AI image saved: %s", out)
    return out
