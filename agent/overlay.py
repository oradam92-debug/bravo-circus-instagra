"""Add the Circus of Dreams branding (logo band + Hebrew footer) to a generated image."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from .config import ROOT

FONT = ROOT / "brand" / "fonts" / "SecularOne-Regular.ttf"
LOGO = ROOT / "brand" / "templates" / "logo_band.jpg"
URL = "kupat.co.il/bravo_circus"


def _font(size):
    return ImageFont.truetype(str(FONT), size, layout_engine=ImageFont.Layout.BASIC)


def _rtl(t):
    from bidi.algorithm import get_display
    return get_display(t)


def _text(d, W, y, text, size, fill, stroke=(60, 0, 70), sw=4, max_w=None, rtl=True):
    t = _rtl(text) if rtl else text
    f = _font(size)
    while max_w and d.textlength(t, font=f) > max_w and size > 24:
        size -= 2; f = _font(size)
    bb = d.textbbox((0, 0), t, font=f, stroke_width=sw)
    d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y - bb[1]), t, font=f, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return y + (bb[3] - bb[1])


def brand(path: Path, line: str = "חנוכה 2026 · בכל רחבי הארץ") -> Path:
    if not (FONT.exists() and LOGO.exists()):
        return path
    im = Image.open(path).convert("RGB")
    W, H = im.size
    logo = Image.open(LOGO).convert("RGB")
    logo = logo.resize((W, int(logo.height * W / logo.width)), Image.LANCZOS)
    m = Image.new("L", logo.size, 255); md = ImageDraw.Draw(m)
    for i in range(40):
        md.line([(0, logo.height - 1 - i), (W, logo.height - 1 - i)], fill=int(255 * i / 40))
    im.paste(logo, (0, 0), m)
    # footer: dark gradient + gold line + url
    fh = int(H * 0.20)
    grad = Image.new("L", (W, fh)); gd = ImageDraw.Draw(grad)
    for y in range(fh):
        gd.line([(0, y), (W, y)], fill=int(235 * (y / fh) ** 0.8))
    im.paste(Image.new("RGB", (W, fh), (28, 0, 45)), (0, H - fh), grad)
    d = ImageDraw.Draw(im)
    y = _text(d, W, H - int(fh * 0.62), line, int(W * 0.065), (255, 220, 120), max_w=W - 80)
    _text(d, W, y + 14, URL, int(W * 0.042), (255, 255, 255), sw=3, rtl=False)
    im.save(path, "JPEG", quality=92)
    return path
