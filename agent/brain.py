"""The 'brain' – Claude writes content and decides how to answer people."""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

import anthropic

from .config import BRAND_FILE

log = logging.getLogger(__name__)

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _brand() -> str:
    return BRAND_FILE.read_text(encoding="utf-8")


def _json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    start = min([i for i in (raw.find("{"), raw.find("[")) if i != -1], default=0)
    return json.loads(raw[start:])


class Brain:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _ask(self, system: str, content, max_tokens: int = 4000) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return "".join(b.text for b in msg.content if b.type == "text")

    # ---------- content planning ----------
    def plan_posts(self, media_files: list[Path], today: str, days: int,
                   recent_captions: list[str], extra_brief: str = "") -> list[dict]:
        system = (
            "אתה מנהל הסושיאל של קרקס בראבו. אתה כותב פוסטים לאינסטגרם בעברית, "
            "לפי מדריך המותג הבא. אסור להמציא עובדות (מחירים, תאריכים, אולמות, משתתפים) "
            "שלא מופיעים במדריך.\n\n" + _brand()
        )
        content: list[dict] = []
        for i, f in enumerate(media_files):
            content.append({"type": "text", "text": f"קובץ מדיה #{i}: {f.name}"})
            mt = IMAGE_TYPES.get(f.suffix.lower())
            if mt and f.stat().st_size < 4_500_000:
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": mt,
                    "data": base64.b64encode(f.read_bytes()).decode()}})
        content.append({"type": "text", "text": f"""
היום {today}. תכנן פוסטים ל-{days} הימים הקרובים (פוסט אחד ליום לכל היותר, אפשר פחות אם אין מספיק מדיה).
השתמש רק בקבצי המדיה שלמעלה. אפשר לחבר כמה תמונות לקרוסלה.
פוסטים אחרונים שכבר עלו (לא לחזור עליהם): {json.dumps(recent_captions[:10], ensure_ascii=False)}
{('הנחיות נוספות לשבוע הזה: ' + extra_brief) if extra_brief else ''}

החזר JSON בלבד – מערך של אובייקטים:
[{{"date": "YYYY-MM-DD", "time": "HH:MM", "media": ["file.jpg"], "caption": "טקסט הפוסט כולל האשטגים", "idea": "תיאור קצר של הרעיון"}}]
"""})
        return _json(self._ask(system, content))

    # ---------- replying ----------
    def decide_reply(self, kind: str, text: str, username: str, post_caption: str = "",
                     thread: list[str] | None = None) -> dict:
        system = (
            "אתה עונה בשם קרקס בראבו לאנשים באינסטגרם. ענה בעברית (או בשפה שבה פנו), "
            "בחום, בקצרה (1-3 משפטים), בלי להמציא מידע. אם התשובה לא במדריך – הפנה לאתר/לקופה "
            "או בקש שישלחו הודעה פרטית, ואל תנחש.\n\n" + _brand()
        )
        prompt = f"""סוג: {kind}
משתמש: @{username}
{('הפוסט שעליו הגיבו: ' + post_caption[:500]) if post_caption else ''}
{('היסטוריית שיחה (מהישן לחדש): ' + json.dumps(thread, ensure_ascii=False)) if thread else ''}
ההודעה: {text}

החלט מה לעשות והחזר JSON בלבד:
{{"action": "reply" | "escalate" | "hide" | "ignore",
  "reply": "התשובה (אם action=reply; גם ב-escalate אפשר לשים תשובה מנומסת קצרה, אחרת ריק)",
  "reason": "למה"}}

כללים:
- reply: שאלות על המופע, כרטיסים, תאריכים, מיקום, גילאים, מחמאות, אימוג'ים חיוביים.
- escalate: תלונה, בקשת החזר כספי, בעיה בתשלום/כרטיס, פנייה עסקית/תקשורתית, משהו רגיש או לא בטוח.
- hide: ספאם, פרסומות, קישורים חשודים, קללות/פגיעה.
- ignore: תגובה שאין מה לענות עליה (למשל תיוג חבר בלבד)."""
        try:
            return _json(self._ask(system, prompt, max_tokens=800))
        except Exception as e:  # never reply with garbage – escalate instead
            log.warning("decide_reply failed: %s", e)
            return {"action": "escalate", "reply": "", "reason": f"model error: {e}"}

    # ---------- tour: "tomorrow we arrive at ..." ----------
    def tour_caption(self, stop: dict) -> str:
        system = (
            "אתה מנהל הסושיאל של קרקס בראבו וכותב פוסט לאינסטגרם בעברית לפי מדריך המותג. "
            "אסור להמציא מחירים, שעות, אולמות או אמנים – השתמש רק בפרטים שנמסרו לך ובמדריך.\n\n"
            + _brand()
        )
        prompt = f"""כתוב פוסט קצר ומרגש לקראת ההופעה של מחר.
עיר: {stop['city']}
תאריך: {stop['date']}
שעות: {', '.join(stop['times']) or 'לא צוין'}
אולם: {stop.get('venue') or 'לא צוין'}
{('הערה: ' + stop['note']) if stop.get('note') else ''}
קישור לכרטיסים בקופת תל אביב: {stop['link']}

חובה:
- לפתוח ב"מחר אנחנו מגיעים ל{stop['city']}!" (אפשר עם אימוג'ים).
- לציין תאריך, שעות ואולם בדיוק כפי שנמסרו.
- לכתוב "כרטיסים בקופת תל אביב – קישור בביו" ולהדביק את הקישור המלא בשורה נפרדת.
- 5-10 האשטגים בסוף, כולל עם שם העיר.
החזר רק את טקסט הפוסט, בלי הסברים."""
        text = self._ask(system, prompt, max_tokens=1200).strip()
        if stop["link"] not in text:
            text += f"\n\n🎟️ כרטיסים בקופת תל אביב:\n{stop['link']}"
        return text
