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
    text = BRAND_FILE.read_text(encoding="utf-8")
    try:  # the live tour schedule (synced from Kupat) is part of what the agent knows
        import datetime as _dt
        from .tour import load_tour
        tour = load_tour()
        today = _dt.date.today().isoformat()
        rows = [s for s in tour.get("shows") or [] if str(s.get("date")) >= today]
        if rows:
            lines = [f"- {s['date']} {s.get('time', '')} | {s.get('city', '')} | {s.get('venue', '')}"
                     f" | {s.get('link') or tour.get('default_link', '')}" for s in rows]
            text += ("\n\n## לוח ההופעות העדכני (מקופת תל אביב) – זה המקור הקובע לתאריכים, שעות ואולמות\n"
                     + "\n".join(lines))
    except Exception:
        pass
    return text


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
                   recent_captions: list[str], extra_brief: str = "",
                   ai_images: bool = False, skip_dates: list[str] | None = None,
                   tour: str = "") -> list[dict]:
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
        if ai_images:
            media_rule = (
                "לכל פוסט אפשר להשתמש בקבצי המדיה שלמעלה (אם יש), או לבקש תמונה חדשה שתיווצר ב-AI "
                "בשדה image_prompt. העדף פוסט אחד ליום, כל יום.\n"
                "כללים ל-image_prompt (באנגלית, מפורט): איור/אמנות דיגיטלית צבעונית וחגיגית בסגנון קרקס קסום "
                "(אוהל פסים אדום-זהב, אורות, כוכבים, ליצנים מאוירים, להטוטנים, אקרובטים, בלונים, חנוכה); "
                "בלי שום טקסט/אותיות/לוגו בתמונה; בלי אנשים אמיתיים ובלי דמויות מוכרות; "
                "לא להציג כאילו זה צילום אמיתי מהמופע. ריבוע/פורטרט, קומפוזיציה שבולטת בפיד."
            )
            schema = ('[{"date": "YYYY-MM-DD", "time": "HH:MM", "media": [] , "image_prompt": "...", '
                      '"caption": "טקסט הפוסט כולל האשטגים", "idea": "תיאור קצר"}]  '
                      '(או media עם שמות קבצים ובלי image_prompt)')
        else:
            media_rule = "השתמש רק בקבצי המדיה שלמעלה. אפשר לחבר כמה תמונות לקרוסלה. אפשר פחות פוסטים אם אין מספיק מדיה."
            schema = ('[{"date": "YYYY-MM-DD", "time": "HH:MM", "media": ["file.jpg"], '
                      '"caption": "טקסט הפוסט כולל האשטגים", "idea": "תיאור קצר של הרעיון"}]')
        content.append({"type": "text", "text": f"""
היום {today}. תכנן פוסטים ל-{days} הימים הקרובים (פוסט אחד ליום לכל היותר).
{media_rule}
גוון בין סוגי הפוסטים שבמדריך. {('''
לוח ההופעות הקרוב (זה המידע העדכני – הוא גובר על המדריך):
''' + tour + '''
- ביום שיש בו הופעה, אפשר להזכיר שהיום אנחנו בעיר הזו (עם השעות). לא לכתוב "מחר" על הופעה – לזה יש פוסט נפרד.
- כשמזכירים את חנוכה – זה סיבוב הופעות בכל הארץ, לא רק תל אביב. אפשר להפנות ל"כל המועדים בקישור בביו".
- להשתמש רק בתאריכים/ערים/אולמות/שעות מהלוח. שעה חסרה = לא לציין שעה.''') if tour else ''}
{('אל תתכנן פוסטים בתאריכים האלה (כבר תפוסים): ' + ', '.join(skip_dates)) if skip_dates else ''}
פוסטים אחרונים שכבר עלו (לא לחזור עליהם): {json.dumps(recent_captions[:10], ensure_ascii=False)}
{('הנחיות נוספות לשבוע הזה: ' + extra_brief) if extra_brief else ''}

החזר JSON בלבד – מערך של אובייקטים:
{schema}
"""})
        return _json(self._ask(system, content))

    # ---------- replying ----------
    def decide_reply(self, kind: str, text: str, username: str, post_caption: str = "",
                     thread: list[str] | None = None, **_ignored) -> dict:
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

    # ---------- Kupat schedule parsing ----------
    def parse_kupat(self, page_text: str, links: list[dict], default_link: str) -> list[dict]:
        system = "אתה מחלץ נתונים מדויקים מעמוד מכירת כרטיסים. לעולם אל תמציא מועדים שלא מופיעים בטקסט."
        prompt = f"""זה הטקסט של עמוד "קרקס החלומות" באתר קופת תל אביב, ואחריו רשימת הקישורים שבו.
חלץ את כל ההופעות העתידיות.

טקסט העמוד:
{page_text[:60000]}

קישורים (text -> href):
{json.dumps(links[:400], ensure_ascii=False)[:40000]}

החזר JSON בלבד – מערך:
[{{"date": "YYYY-MM-DD", "time": "HH:MM", "city": "עיר בעברית", "venue": "שם האולם", "link": "קישור ההזמנה של המועד הזה"}}]
- הופעה אחת לכל שורה (כמה שעות באותו יום = כמה שורות).
- link: הקישור הספציפי של אותו מועד מתוך רשימת הקישורים (בדרך כלל עם prsntId). אם אין – "{default_link}".
- city: שם העיר בלבד (למשל "חיפה", "ראשון לציון"). השנה: אם לא כתובה, הסק מההקשר (נובמבר-דצמבר 2026 / 2027).
- אם אין מועדים בטקסט – החזר []."""
        try:
            rows = _json(self._ask(system, prompt, max_tokens=8000))
        except Exception as e:
            log.warning("parse_kupat failed: %s", e)
            return []
        good = []
        for r in rows if isinstance(rows, list) else []:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("date", ""))) and r.get("city"):
                good.append(r)
        return good
