"""AI image generation (OpenAI Images API) – produces Instagram-ready 1080x1350 JPGs.

If brand/style/ holds poster images, they are sent as visual references so every
generated image matches the Circus of Dreams look (purple & gold, ornate frames,
red velvet curtains, balloons, striped tents, crystals).
"""
from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path

import requests

from .config import ROOT

log = logging.getLogger(__name__)
STYLE_DIR = ROOT / "brand" / "style"

STYLE = (
    "Instagram post image for 'Circus of Dreams' (קרקס החלומות) by Bravo Circus. "
    "Match the exact visual style of the reference posters: deep purple night sky full of golden sparkles, "
    "ornate gold baroque frames and scrolls, red velvet stage curtains with warm string lights, "
    "purple-and-gold striped circus tents, hot-air balloons, a glowing ferris wheel, hanging amethyst crystals, "
    "illustrated circus artists (aerialists on red silks, jugglers, ring acrobats) in purple-and-gold costumes. "
    "Rich, magical, festive, family-friendly, polished digital-painting look. "
    "Do NOT write any text, letters, numbers or logos in the image (text is added separately). "
    "No real or famous people, no copyrighted characters. Scene: "
)


def enabled() -> bool:
    """AI images are OFF unless USE_AI_IMAGES=true (the brand's own posters are used instead)."""
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("USE_AI_IMAGES", "false").lower() == "true"


def _refs() -> list[Path]:
    if not STYLE_DIR.exists():
        return []
    return sorted(p for p in STYLE_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})[:4]


def generate(prompt: str, out: Path, size: str = "1024x1536") -> Path:
    """Generate an image from `prompt` and save it as a 1080x1350 (4:5) JPG."""
    from PIL import Image, ImageOps

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = os.getenv("IMAGE_MODEL", "gpt-image-2")
    quality = os.getenv("IMAGE_QUALITY", "medium")
    headers = {"Authorization": f"Bearer {key}"}
    refs = _refs()

    if refs:  # style-reference mode: the posters guide the look
        files = [("image[]", (p.name, p.read_bytes(), "image/jpeg" if p.suffix.lower() != ".png" else "image/png"))
                 for p in refs]
        r = requests.post(
            "https://api.openai.com/v1/images/edits", headers=headers, files=files,
            data={"model": model, "prompt": STYLE + prompt, "size": size, "quality": quality, "n": "1"},
            timeout=300,
        )
        if r.status_code >= 400:
            log.warning("reference-image mode failed (%s) – falling back to text-only", r.text[:200])
            refs = []
    if not refs:
        r = requests.post(
            "https://api.openai.com/v1/images/generations", headers=headers,
            json={"model": model, "prompt": STYLE + prompt, "size": size, "quality": quality, "n": 1},
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
    log.info("AI image saved: %s (style refs: %d)", out, len(refs))
    return out
