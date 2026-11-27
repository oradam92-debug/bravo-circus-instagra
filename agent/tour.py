"""Tour posts: every day, a post for tomorrow's city – "מחר אנחנו מגיעים ל..." –
with an auto-generated poster and the Kupat Tel Aviv sales link for that city.

The schedule lives in content/tour.yaml.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
from collections import OrderedDict
from pathlib import Path

import yaml

from .config import MEDIA_DIR, ROOT

log = logging.getLogger(__name__)

TOUR_FILE = ROOT / "content" / "tour.yaml"
POSTER_DIR = MEDIA_DIR / "tour"
FONTS_DIR = ROOT / "brand" / "fonts"
DEFAULT_LINK = "https://tickets.kupat.co.il/booking/features/3013?display=list"
WEEKDAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # Monday=0

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


# ---------------------------------------------------------------- schedule
def load_tour(path: Path | None = None) -> dict:
    path = path or TOUR_FILE
    if not path.exists():
        return {"shows": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("shows", [])
    return data


def stops_for(date: dt.date, tour: dict) -> list[dict]:
    """All shows on `date`, grouped into one 'stop' per city."""
    stops: "OrderedDict[str, dict]" = OrderedDict()
    for s in tour.get("shows") or []:
        if str(s.get("date")) != date.isoformat() or not s.get("city"):
            continue
        city = str(s["city"]).strip()
        stop = stops.setdefault(city, {
            "date": date.isoformat(), "city": city, "venue": s.get("venue", ""),
            "times": [], "link": s.get("link") or tour.get("default_link") or DEFAULT_LINK,
            "poster": s.get("poster"), "note": s.get("note", ""),
        })
        if s.get("time"):
            stop["times"].append(str(s["time"]))
        if s.get("poster") and not stop["poster"]:
            stop["poster"] = s["poster"]
    for st in stops.values():
        st["times"] = sorted(set(st["times"]))
    return list(stops.values())


def summary(tour: dict, start: dt.date, days: int = 45) -> str:
    """Upcoming shows as short Hebrew lines (one per city per day) for the content planner."""
    lines = []
    for i in range(days + 1):
        for st in stops_for(start + dt.timedelta(days=i), tour):
            times = " | ".join(st["times"]) or "שעה לא ידועה"
            venue = f" – {st['venue']}" if st.get("venue") else ""
            lines.append(f"{st['date']} ({he_date(st['date'])}): {st['city']}{venue}, {times}")
    return "\n".join(lines)


def he_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"יום {WEEKDAYS[d.weekday()]}, {d.day}.{d.month}"


def fallback_caption(stop: dict) -> str:
    times = " | ".join(stop["times"])
    lines = [
        f"🎪✨ מחר אנחנו מגיעים ל{stop['city']}! ✨🎪",
        "",
        "קרקס החלומות מבית בראבו מגיע אליכם – מופע קרקס משפחתי מלא קסם ושמחה 🤹‍♀️",
        "",
        f"📅 {he_date(stop['date'])}" + (f" · 🕐 {times}" if times else ""),
    ]
    if stop.get("venue"):
        lines.append(f"📍 {stop['venue']}")
    lines += [
        "",
        "🎟️ כרטיסים בקופת תל אביב (קישור בביו):",
        stop["link"],
        "",
        "מחכים לכם! 🎉",
        "",
        "#קרקסבראבו #קרקסהחלומות #חנוכה #מופעלילדים #בילוילדים #קרקס "
        f"#{stop['city'].replace(' ', '').replace('-', '')}",
    ]
    return "\n".join(lines)


def ai_background_prompt(stop: dict) -> str:
    """Prompt for an AI background; the Hebrew text is drawn on top by make_poster."""
    return (
        "A magical circus big-top tent at dusk with red and gold stripes, glowing string lights, "
        "confetti and stars, Hanukkah candles glowing softly, festive and joyful mood. "
        "Keep the lower half of the image calm and darker so text can be placed over it. "
        f"Subtle feeling of the Israeli town {stop['city']} (landscape only, no signs)."
    )


# ---------------------------------------------------------------- poster
# Hebrew fonts often lack digits/symbols (Noto Sans Hebrew has no 0-9, ★, ·, |),
# so every character the main font can't draw is drawn with a fallback font.
FALLBACK_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load(paths: list[str], size: int):
    from PIL import ImageFont
    for path in paths:
        if Path(path).exists():
            # BASIC layout + python-bidi gives correct Hebrew on every machine (no libraqm needed).
            return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)
    return None


class _Font:
    """Main font + fallback for missing glyphs."""

    def __init__(self, size: int):
        from PIL import ImageFont
        custom = sorted(FONTS_DIR.glob("*.[ot]tf")) if FONTS_DIR.exists() else []
        self.main = _load([str(p) for p in custom] + FONT_CANDIDATES, size) or ImageFont.load_default(size)
        self.fallback = _load(FALLBACK_CANDIDATES, size)
        self._cache: dict[str, bool] = {}
        try:
            self._notdef = bytes(self.main.getmask("\uE000"))
        except Exception:
            self._notdef = None

    def has(self, ch: str) -> bool:
        if ch.isspace() or self._notdef is None or self.fallback is None:
            return True
        if ch not in self._cache:
            self._cache[ch] = bytes(self.main.getmask(ch)) != self._notdef
        return self._cache[ch]

    def runs(self, text: str) -> list[tuple[str, object]]:
        out: list[tuple[str, object]] = []
        for ch in text:
            f = self.main if self.has(ch) else self.fallback
            if out and out[-1][1] is f:
                out[-1] = (out[-1][0] + ch, f)
            else:
                out.append((ch, f))
        return out

    def width(self, draw, visual: str, stroke: int = 0) -> float:
        return sum(draw.textlength(t, font=f) for t, f in self.runs(visual)) + 2 * stroke


def _font(size: int) -> _Font:
    return _Font(size)


def _rtl(text: str) -> str:
    from bidi.algorithm import get_display
    return get_display(text)


def _fit(draw, text: str, max_w: int, size: int, min_size: int = 28) -> _Font:
    while size > min_size:
        f = _font(size)
        if f.width(draw, _rtl(text)) <= max_w:
            return f
        size -= 4
    return _font(min_size)


def _centered(draw, y: int, text: str, font: _Font, fill, width: int, stroke=0, stroke_fill=None) -> int:
    t = _rtl(text)
    # Height from the main font so lines stay evenly spaced; all runs share one baseline.
    top, bottom = font.main.getbbox("אבגדהלק", anchor="ls")[1], font.main.getbbox("אבגדהלק", anchor="ls")[3]
    x = (width - font.width(draw, t, stroke)) / 2 + stroke
    base = y - top + stroke
    for run, f in font.runs(t):
        draw.text((x, base), run, font=f, fill=fill, anchor="ls",
                  stroke_width=stroke, stroke_fill=stroke_fill)
        x += draw.textlength(run, font=f)
    return y + (bottom - top) + 2 * stroke


def _background(W: int, H: int, base: Path | None):
    from PIL import Image, ImageDraw, ImageOps
    if base and base.exists():
        img = ImageOps.fit(Image.open(base).convert("RGB"), (W, H), Image.LANCZOS)
        return img
    # Generated circus background: deep purple→red gradient, tent stripes, stars.
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    top, bot = (38, 8, 74), (160, 16, 48)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
    stripes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripes)
    cx, n = W / 2, 14
    for i in range(n):
        if i % 2:
            continue
        x0, x1 = -W + i * (3 * W / n), -W + (i + 1) * (3 * W / n)
        sd.polygon([(cx, -40), (x0, H), (x1, H)], fill=(255, 255, 255, 18))
    img.paste(stripes, (0, 0), stripes)
    rnd = random.Random(7)
    for _ in range(90):
        x, y, r = rnd.randint(0, W), rnd.randint(0, int(H * 0.55)), rnd.choice([1, 2, 2, 3])
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 236, 170))
    return img


def make_poster(stop: dict, out: Path, base: Path | None = None) -> Path:
    """1080x1350 (Instagram 4:5) JPG poster for one tour stop."""
    from PIL import Image, ImageDraw
    W, H = 1080, 1350
    img = _background(W, H, base)
    gold, white, red = (255, 205, 64), (255, 255, 255), (200, 20, 50)

    # Darken the lower part so the text is always readable on top of any photo.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    start = int(H * (0.42 if base else 0.30))
    for y in range(start, H):
        a = int(215 * min(1, (y - start) / (H * 0.22)))
        sd.line([(0, y), (W, y)], fill=(12, 0, 24, a))
    img = Image.alpha_composite(img.convert("RGBA"), shade)
    d = ImageDraw.Draw(img)

    if not base:
        _centered(d, 110, "קרקס החלומות", _font(120), gold, W, stroke=4, stroke_fill=(90, 0, 20))
        _centered(d, 260, "מבית בראבו", _font(64), white, W)
        _centered(d, 380, "★ ★ ★", _font(60), gold, W)

    y = int(H * 0.56)
    y = _centered(d, y, "מחר אנחנו מגיעים", _font(70), white, W, stroke=2, stroke_fill=(0, 0, 0)) + 26
    y = _centered(d, y, f"ל{stop['city']}!", _fit(d, f"ל{stop['city']}!", W - 120, 150),
                  gold, W, stroke=5, stroke_fill=(90, 0, 20)) + 40
    line = he_date(stop["date"]) + (f"  |  {'  ·  '.join(stop['times'])}" if stop["times"] else "")
    y = _centered(d, y, line, _fit(d, line, W - 120, 52), white, W) + 22
    if stop.get("venue"):
        y = _centered(d, y, stop["venue"], _fit(d, stop["venue"], W - 120, 40), (235, 225, 255), W) + 30

    # Call-to-action button
    cta = "כרטיסים בקופת תל אביב – קישור בביו"
    f = _fit(d, cta, W - 220, 42)
    bw = f.width(d, _rtl(cta)) + 90
    by = max(y + 10, H - 150)
    d.rounded_rectangle([(W - bw) / 2, by, (W + bw) / 2, by + 86], radius=43, fill=red,
                        outline=gold, width=4)
    _centered(d, by + 22, cta, f, white, W)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=92)
    return out


def insta_fit(src: Path, out: Path) -> Path:
    """Instagram feed accepts 4:5 to 1.91:1. Taller/wider posters are not cropped –
    they're placed on a blurred, darkened copy of themselves at 4:5 (1080x1350)."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    img = Image.open(src).convert("RGB")
    ratio = img.width / img.height
    if 0.8 <= ratio <= 1.91:
        if src.suffix.lower() in {".jpg", ".jpeg"}:
            return src
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "JPEG", quality=94)
        return out
    W, H = (1080, 1350) if ratio < 0.8 else (1080, 566)
    bg = ImageOps.fit(img, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    fg = ImageOps.contain(img, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    bg.save(out, "JPEG", quality=94)
    return out


def slug(stop: dict) -> str:
    import hashlib
    return f"{stop['date']}-{hashlib.md5(stop['city'].encode()).hexdigest()[:8]}"
