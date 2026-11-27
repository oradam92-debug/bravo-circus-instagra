"""Sync the show schedule from Kupat Tel Aviv (קופת תל אביב) into content/tour.yaml.

The Kupat page is rendered with JavaScript, so it is opened in headless Chromium
(Playwright). The visible text + booking links are handed to Claude, which turns
them into a clean list of shows. Kupat is the source of truth: dates, times,
cities, venues and per-show links are replaced; posters/notes you added by hand
are kept.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .tour import TOUR_FILE, load_tour

log = logging.getLogger(__name__)
DEFAULT_URL = "https://tickets.kupat.co.il/booking/features/3013?display=list"


def scrape(url: str) -> tuple[str, list[dict]]:
    """Return (visible page text, [{text, href}]) for the Kupat event page."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="he-IL", viewport={"width": 1280, "height": 2000})
        page.goto(url, wait_until="networkidle", timeout=90_000)
        # Load lazy content / "show more" lists.
        for _ in range(8):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
        for label in ("הצג עוד", "עוד מועדים", "טען עוד"):
            try:
                while page.get_by_text(label, exact=False).first.is_visible(timeout=1000):
                    page.get_by_text(label, exact=False).first.click()
                    page.wait_for_timeout(1200)
            except Exception:
                pass
        text = page.inner_text("body")
        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))")
        browser.close()
    links = [l for l in links if "kupat" in l["href"] and ("prsnt" in l["href"].lower() or "booking" in l["href"])]
    return text, links


def merge(new_shows: list[dict], tour: dict) -> dict:
    """Kupat wins on facts; keep hand-made poster/note per (date, city)."""
    extras = {(str(s.get("date")), str(s.get("city"))): s for s in tour.get("shows") or []}
    out = []
    for s in sorted(new_shows, key=lambda s: (str(s["date"]), str(s.get("time", "")))):
        old = extras.get((str(s["date"]), str(s["city"])), {})
        row = {k: s[k] for k in ("date", "time", "city", "venue", "link") if s.get(k)}
        for k in ("poster", "note"):
            if old.get(k):
                row[k] = old[k]
        out.append(row)
    tour = dict(tour)
    tour["shows"] = out
    return tour


def save_tour(tour: dict, path: Path = TOUR_FILE) -> None:
    header = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                header.append(line)
            else:
                break
    header = [h for h in header if "נאסף" not in h]
    header.append("# מתעדכן אוטומטית כל בוקר מאתר קופת תל אביב (python -m agent.main sync).")
    body = yaml.safe_dump(tour, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text("\n".join(header) + "\n\n" + body, encoding="utf-8")


def sync(brain, url: str | None = None) -> int:
    tour = load_tour()
    url = url or tour.get("kupat_url") or tour.get("default_link") or DEFAULT_URL
    text, links = scrape(url)
    shows = brain.parse_kupat(text, links, default_link=url)
    if not shows:
        raise RuntimeError("לא נמצאו מועדים בעמוד של קופת תל אביב – לוח ההופעות לא שונה.")
    save_tour(merge(shows, tour))
    return len(shows)
