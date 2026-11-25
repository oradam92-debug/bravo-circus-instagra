"""Small file-based state (committed back to the repo by the workflows)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .config import QUEUE_FILE, STATE_DIR


def load_queue(path: Path = QUEUE_FILE) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("posts", [])


def save_queue(posts: list[dict], path: Path = QUEUE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# תור הפוסטים של הסוכן.\n"
        "# approved: true  -> הסוכן יפרסם בתאריך ובשעה שנקבעו.\n"
        "# approved: false -> טיוטה, לא יפורסם.\n"
        "# status: published + ig_id נכתבים אוטומטית אחרי הפרסום.\n"
    )
    body = yaml.safe_dump({"posts": posts}, allow_unicode=True, sort_keys=False, width=1000)
    path.write_text(header + body, encoding="utf-8")


def load_state(name: str, default):
    p = STATE_DIR / f"{name}.json"
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(name: str, data) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
