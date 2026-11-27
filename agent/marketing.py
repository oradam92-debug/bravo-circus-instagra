"""Marketing-plan agent – builds a full seasonal campaign for a product.

  python -m agent.main marketing --campaign wipark [--brief "..."] [--visuals]

Reads   campaigns/<campaign>/brief.yaml   (facts; "[להשלים]" = unknown, never invented)
Writes  campaigns/<campaign>/plan.json            raw plan (the source of truth for the others)
        campaigns/<campaign>/plan.md              the marketing plan
        campaigns/<campaign>/graphic-language.md  the visual identity guide
        campaigns/<campaign>/calendar.yaml        week-by-week content & media calendar
        campaigns/<campaign>/style-board.html     visual board: palette, type, motifs, timeline
        campaigns/<campaign>/visuals/*.jpg        key-visual backgrounds (with --visuals + OPENAI_API_KEY)

The season skeleton (weeks, holidays, quiet days) is computed here, not by the model,
so dates are always right; Claude fills in strategy, creative and the weekly content.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
from pathlib import Path

import yaml

from .config import ROOT

log = logging.getLogger(__name__)
CAMPAIGNS_DIR = ROOT / "campaigns"

# Israeli calendar moments, Feb–Jun 2027 (5787). kind: peak = big family-outing days,
# holiday = themed moment, quiet = memorial day (no festive posts / no paid media).
HOLIDAYS_2027 = [
    {"date": "2027-02-07", "name": "יום המשפחה", "kind": "holiday"},
    {"date": "2027-03-10", "name": "עיד אל-פיטר (משוער)", "kind": "holiday"},
    {"date": "2027-03-23", "name": "פורים", "kind": "peak"},
    {"date": "2027-03-24", "name": "שושן פורים", "kind": "holiday"},
    {"date": "2027-04-15", "name": "תחילת חופשת פסח (משוער – לאמת מול משרד החינוך)", "kind": "peak"},
    {"date": "2027-04-21", "name": "ערב פסח – ליל הסדר", "kind": "holiday"},
    {"date": "2027-04-22", "name": "פסח", "kind": "holiday"},
    {"date": "2027-04-23", "name": "חול המועד פסח (23–27.4)", "kind": "peak"},
    {"date": "2027-04-28", "name": "שביעי של פסח", "kind": "holiday"},
    {"date": "2027-05-04", "name": "יום השואה", "kind": "quiet"},
    {"date": "2027-05-11", "name": "יום הזיכרון", "kind": "quiet"},
    {"date": "2027-05-12", "name": "יום העצמאות", "kind": "peak"},
    {"date": "2027-05-16", "name": "עיד אל-אדחא (משוער)", "kind": "holiday"},
    {"date": "2027-05-25", "name": "ל\"ג בעומר", "kind": "holiday"},
    {"date": "2027-06-10", "name": "ערב שבועות", "kind": "holiday"},
    {"date": "2027-06-11", "name": "שבועות – סיום העונה", "kind": "peak"},
]

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# ---------------------------------------------------------------- inputs
def campaign_dir(campaign: str) -> Path:
    return CAMPAIGNS_DIR / campaign


def load_brief(campaign: str) -> dict:
    p = campaign_dir(campaign) / "brief.yaml"
    if not p.exists():
        raise SystemExit(f"Missing {p} – create a brief first (see campaigns/wipark/brief.yaml)")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _date(v) -> dt.date:
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


def season_skeleton(brief: dict) -> dict:
    """Weeks (Sunday-based, Israeli week) + the holidays inside the season window."""
    season = brief.get("season") or {}
    start, end = _date(season["start"]), _date(season["end"])
    first = _date(season.get("teaser_start") or start)
    holidays = [h for h in (brief.get("holidays") or HOLIDAYS_2027) if first <= _date(h["date"]) <= end]
    week = first - dt.timedelta(days=(first.weekday() + 1) % 7)   # back to Sunday
    weeks = []
    while week <= end:
        wend = week + dt.timedelta(days=6)
        weeks.append({
            "week_start": week.isoformat(),
            "week_end": wend.isoformat(),
            "pre_launch": wend < start,
            "moments": [h["name"] for h in holidays if week <= _date(h["date"]) <= wend],
            "quiet_days": [h["date"] for h in holidays if h["kind"] == "quiet" and week <= _date(h["date"]) <= wend],
        })
        week += dt.timedelta(days=7)
    return {"teaser_start": first.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "holidays": holidays, "weeks": weeks}


def unknowns(brief, path: str = "") -> list[str]:
    """Every field still marked [להשלים] – the plan must list these as open questions."""
    out = []
    if isinstance(brief, dict):
        for k, v in brief.items():
            out += unknowns(v, f"{path}.{k}" if path else str(k))
    elif isinstance(brief, list):
        for i, v in enumerate(brief):
            out += unknowns(v, f"{path}[{i}]")
    elif isinstance(brief, str) and "[להשלים" in brief:
        out.append(path)
    return out


# ---------------------------------------------------------------- the model
SCHEMA = """{
 "title": "שם התוכנית",
 "summary": "תקציר מנהלים – 4-6 משפטים",
 "big_idea": {"name": "שם הקונספט", "tagline": "סלוגן קצר בעברית", "description": "הרעיון הגדול"},
 "audiences": [{"name": "", "insight": "", "message": "", "channels": [""]}],
 "phases": [{"key": "teaser|launch|...", "name": "", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD",
             "goal": "", "message": "", "tactics": [""], "kpis": [""]}],
 "product_adaptation": [{"moment": "פורים / פסח / ...", "date": "YYYY-MM-DD", "adaptation": "מה משתנה במוצר עצמו",
                         "offer_idea": "", "ops_notes": "תפעול, כוח אדם, עומסים"}],
 "graphic_language": {
   "concept": "", "palette": [{"name": "", "hex": "#RRGGBB", "use": ""}],
   "fonts": [{"name": "פונט עם תמיכה בעברית (Google Fonts)", "use": ""}],
   "motifs": [""], "mascot": {"name": "", "description": ""},
   "layout_rules": [""], "dos": [""], "donts": [""],
   "image_style_prompt": "English prompt prefix for AI images in this look (no text in image)",
   "key_visuals": [{"name": "", "format": "feed 4:5 | story 9:16 | billboard", "headline": "כותרת בעברית",
                    "prompt": "English scene description"}]},
 "channels": [{"channel": "", "role": "", "budget_share": "אחוז מהתקציב"}],
 "weekly_calendar": [{"week_start": "YYYY-MM-DD", "phase": "key", "theme": "",
                      "posts": ["רעיון לפוסט/רילס/סטורי"], "paid": "", "offline": ""}],
 "kpis": [""], "risks": [{"risk": "", "mitigation": ""}], "open_questions": [""]
}"""


def build_prompt(brief: dict, skeleton: dict, extra: str = "") -> tuple[str, str]:
    system = (
        "אתה סמנכ\"ל שיווק ומנהל קריאייטיב בכיר של חברת ההפקות בראבו. אתה בונה תוכנית שיווק עונתית מלאה, "
        "שפה גרפית ותוכנית התאמת מוצר לעונה ולחגים – בעברית, מעשית, מדויקת ומלאת השראה. "
        "כללי ברזל: לא ממציאים מחירים, שעות, מתקנים, הנחות, כתובות או נתונים שלא בתדריך. "
        "כל פרט שמסומן [להשלים] נכנס לרשימת open_questions, ובטקסט כותבים 'לפי המחירון' / 'יעודכן' במקום מספר. "
        "תקציב: רק באחוזים, אלא אם התדריך נותן סכום. ימי זיכרון (quiet) – בלי תוכן חגיגי ובלי מדיה ממומנת. "
        "לא נותנים קודי הנחה."
    )
    prompt = f"""תדריך המוצר (YAML):
{yaml.safe_dump(brief, allow_unicode=True, sort_keys=False)}

שלד העונה (מחושב – התאריכים כאן נכונים, אל תשנה אותם):
{json.dumps(skeleton, ensure_ascii=False, indent=1)}

שדות שעדיין לא ידועים: {', '.join(unknowns(brief)) or 'אין'}
{('הנחיות נוספות: ' + extra) if extra else ''}

בנה:
1. אסטרטגיה: רעיון גדול, קהלים (כולל תוכן בערבית לקהל מהמשולש), ושלבי קמפיין שמכסים את כל העונה
   מ-{skeleton['teaser_start']} (טיזר) דרך הפתיחה ב-{skeleton['start']} ועד {skeleton['end']} (שבועות – פינאלה).
2. התאמת המוצר: לכל רגע בלוח (פורים, חופשת פסח, יום העצמאות, ל"ג בעומר, שבועות, חגי המוסלמים) – מה משתנה בפארק עצמו
   (תוכן, פעילויות, מופעים, תפאורה, שעות פעילות מומלצות, חבילות), ושיקולי תפעול ועומסים.
3. שפה גרפית "מגניבה" וייחודית – לא קלישאה: קונספט, פלטה של 6-8 צבעים ב-HEX, פונטים עבריים מ-Google Fonts,
   מוטיבים, קמע, כללי עימוד, עשה/אל תעשה, פרומפט סגנון לתמונות AI, ו-4-6 קי-ויז'ואלים.
4. ערוצים וחלוקת תקציב, KPI, סיכונים.
5. weekly_calendar: שורה אחת לכל שבוע בשלד בדיוק (week_start זהה), 3-5 רעיונות תוכן לשבוע, ממומן ואופליין.

החזר JSON בלבד בפורמט:
{SCHEMA}"""
    return system, prompt


def _json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def ask_plan(api_key: str, model: str, system: str, prompt: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(2):
        # long answer → streaming (the SDK refuses very large non-streaming requests)
        with client.messages.stream(model=model, max_tokens=32000, system=system, messages=messages) as s:
            text = "".join(b.text for b in s.get_final_message().content if b.type == "text")
        try:
            return _json(text)
        except ValueError:
            log.warning("plan JSON invalid (attempt %d)", attempt + 1)
            messages = [{"role": "user", "content": prompt + "\n\nקצר יותר: עד 3 רעיונות לשבוע, JSON תקין בלבד."}]
    raise RuntimeError("the model did not return a valid JSON plan")


# ---------------------------------------------------------------- validation
def clean_plan(plan: dict, skeleton: dict, brief: dict) -> dict:
    """Keep the plan honest: real weeks only, valid colours, every unknown listed as an open question."""
    gl = plan.setdefault("graphic_language", {})
    gl["palette"] = [c for c in gl.get("palette") or [] if HEX.match(str(c.get("hex", "")))]
    by_week = {str(w.get("week_start")): w for w in plan.get("weekly_calendar") or []}
    cal = []
    for w in skeleton["weeks"]:
        row = dict(by_week.get(w["week_start"]) or {"theme": "", "posts": [], "paid": "", "offline": ""})
        row.update(week_start=w["week_start"], week_end=w["week_end"], moments=w["moments"])
        if w["quiet_days"]:
            row["quiet_days"] = w["quiet_days"]
        cal.append(row)
    plan["weekly_calendar"] = cal
    plan["open_questions"] = [q for q in plan.get("open_questions") or [] if not str(q).startswith("להשלים בתדריך:")]
    plan["missing_fields"] = unknowns(brief)   # recomputed every run – shrinks as the brief is filled
    plan["season"] = {k: skeleton[k] for k in ("teaser_start", "start", "end")}
    plan["holidays"] = skeleton["holidays"]
    return plan


# ---------------------------------------------------------------- rendering
def _ul(items) -> str:
    return "\n".join(f"- {i}" for i in items or []) or "-"


def _d(s: str) -> str:
    d = _date(s)
    return f"{d.day}.{d.month}"


def render_plan_md(plan: dict, brief: dict) -> str:
    bi = plan.get("big_idea") or {}
    s = plan["season"]
    out = [f"# {plan.get('title') or brief.get('name', '')}",
           f"> {brief.get('name', '')} · {(brief.get('location') or {}).get('venue', '')} · "
           f"טיזר מ-{_d(s['teaser_start'])} · פתיחה {_d(s['start'])} · סיום {_d(s['end'])} (שבועות)",
           "", "## תקציר", plan.get("summary", ""),
           "", f"## הרעיון הגדול – {bi.get('name', '')}", f"**{bi.get('tagline', '')}**", "", bi.get("description", ""),
           "", "## קהלי יעד"]
    for a in plan.get("audiences") or []:
        out += [f"### {a.get('name', '')}", f"- **תובנה:** {a.get('insight', '')}",
                f"- **מסר:** {a.get('message', '')}", f"- **ערוצים:** {', '.join(a.get('channels') or [])}"]
    out += ["", "## שלבי הקמפיין", "| שלב | תאריכים | מטרה | מסר |", "|---|---|---|---|"]
    for p in plan.get("phases") or []:
        out.append(f"| **{p.get('name', '')}** | {_d(p['start'])}–{_d(p['end'])} | {p.get('goal', '')} | {p.get('message', '')} |")
    for p in plan.get("phases") or []:
        out += ["", f"### {p.get('name', '')} ({_d(p['start'])}–{_d(p['end'])})", "**טקטיקות:**", _ul(p.get("tactics")),
                "**מדדים:**", _ul(p.get("kpis"))]
    out += ["", "## התאמת המוצר לעונה ולחגים", "| רגע | תאריך | מה משתנה בפארק | הצעה | תפעול |", "|---|---|---|---|---|"]
    for a in plan.get("product_adaptation") or []:
        out.append(f"| **{a.get('moment', '')}** | {_d(a['date']) if a.get('date') else ''} | {a.get('adaptation', '')} | "
                   f"{a.get('offer_idea', '')} | {a.get('ops_notes', '')} |")
    out += ["", "## ערוצים ותקציב", "| ערוץ | תפקיד | חלק מהתקציב |", "|---|---|---|"]
    for c in plan.get("channels") or []:
        out.append(f"| {c.get('channel', '')} | {c.get('role', '')} | {c.get('budget_share', '')} |")
    out += ["", "## לוח תוכן שבועי (מלא ב-`calendar.yaml`)", "| שבוע | רגעים | נושא | ממומן |", "|---|---|---|---|"]
    for w in plan["weekly_calendar"]:
        q = " 🕯️ יום זיכרון – בלי תוכן חגיגי" if w.get("quiet_days") else ""
        out.append(f"| {_d(w['week_start'])}–{_d(w['week_end'])} | {', '.join(w['moments'])}{q} | {w.get('theme', '')} | {w.get('paid', '')} |")
    out += ["", "## מדדי הצלחה", _ul(plan.get("kpis")), "", "## סיכונים", "| סיכון | מענה |", "|---|---|"]
    out += [f"| {r.get('risk', '')} | {r.get('mitigation', '')} |" for r in plan.get("risks") or []]
    out += ["", "## ❓ שאלות פתוחות", _ul(plan.get("open_questions"))]
    if plan.get("missing_fields"):
        out += ["", "**שדות שעדיין מסומנים [להשלים] ב-`brief.yaml`:** " + ", ".join(f"`{f}`" for f in plan["missing_fields"])]
    out += [
            "", "---", "_נוצר על ידי סוכן השיווק של בראבו מתוך `brief.yaml`. השפה הגרפית: `graphic-language.md` · לוח ויזואלי: `style-board.html`._"]
    return "\n".join(out) + "\n"


def render_graphic_md(plan: dict) -> str:
    gl = plan["graphic_language"]
    m = gl.get("mascot") or {}
    out = ["# השפה הגרפית", "", f"**קונספט:** {gl.get('concept', '')}", "", "## פלטת צבעים",
           "| צבע | HEX | שימוש |", "|---|---|---|"]
    out += [f"| {c.get('name', '')} | `{c['hex']}` | {c.get('use', '')} |" for c in gl["palette"]]
    out += ["", "## טיפוגרפיה"] + [f"- **{f.get('name', '')}** – {f.get('use', '')}" for f in gl.get("fonts") or []]
    out += ["", "## מוטיבים", _ul(gl.get("motifs"))]
    if m:
        out += ["", f"## הקמע – {m.get('name', '')}", m.get("description", "")]
    out += ["", "## כללי עימוד", _ul(gl.get("layout_rules")), "", "## ✅ עושים", _ul(gl.get("dos")),
            "", "## ⛔ לא עושים", _ul(gl.get("donts")), "", "## פרומפט סגנון לתמונות AI", f"```\n{gl.get('image_style_prompt', '')}\n```",
            "", "## קי-ויז'ואלים"]
    for k in gl.get("key_visuals") or []:
        out += [f"### {k.get('name', '')} ({k.get('format', '')})", f"**כותרת:** {k.get('headline', '')}", "",
                f"סצנה: {k.get('prompt', '')}"]
    return "\n".join(out) + "\n"


def render_calendar_yaml(plan: dict) -> str:
    head = "# לוח התוכן השבועי – נוצר מ-plan.json. שבוע = ראשון עד שבת.\n"
    return head + yaml.safe_dump({"season": plan["season"], "weeks": plan["weekly_calendar"]},
                                 allow_unicode=True, sort_keys=False, width=1000)


def render_style_board(plan: dict, brief: dict) -> str:
    """A self-contained visual board: palette, fonts, motifs, season timeline."""
    e = html.escape
    gl = plan["graphic_language"]
    pal = gl["palette"] or [{"name": "", "hex": "#00B3B8"}]
    # strong colours only for fills that carry white text
    strong = [p for p in pal if _lum(p["hex"]) < 0.6] or pal
    c = lambda i: strong[i % len(strong)]["hex"]  # noqa: E731
    rng = lambda a, b: f'<span dir="ltr">{_d(a)}–{_d(b)}</span>'  # noqa: E731
    fonts = [f.get("name", "") for f in gl.get("fonts") or []][:3]
    fam = "|".join(f.replace(" ", "+") + ":wght@400;700;900" for f in fonts if re.fullmatch(r"[A-Za-z0-9 ]+", f))
    head_font = fonts[0] if fonts else "Secular One"
    body_font = fonts[1] if len(fonts) > 1 else "Rubik"
    s = plan["season"]
    t0, t1 = _date(s["teaser_start"]), _date(s["end"])
    span = max((t1 - t0).days, 1)
    pos = lambda d: 100 * (_date(d) - t0).days / span  # noqa: E731
    phases = "".join(
        f'<div class="ph" style="right:{pos(p["start"]):.2f}%;width:{max(pos(p["end"]) - pos(p["start"]), 1.5):.2f}%;'
        f'background:{c(i)}"><b>{e(p.get("name", ""))}</b><small>{rng(p["start"], p["end"])}</small></div>'
        for i, p in enumerate(plan.get("phases") or []))
    pins = "".join(
        f'<div class="pin {h["kind"]}" style="right:{pos(h["date"]):.2f}%;height:{28 + 26 * (i % 3)}px">'
        f'<span>{i + 1}</span></div>' for i, h in enumerate(plan["holidays"]))
    legend = "".join(f'<li class="{h["kind"]}"><b>{i + 1}</b> <span dir="ltr">{_d(h["date"])}</span> {e(h["name"])}</li>'
                     for i, h in enumerate(plan["holidays"]))
    swatches = "".join(
        f'<div class="sw"><div class="chip" style="background:{p["hex"]}"></div><b>{e(p.get("name", ""))}</b>'
        f'<code dir="ltr">{p["hex"]}</code><small>{e(p.get("use", ""))}</small></div>' for p in pal)
    motifs = "".join(f"<li>{e(x)}</li>" for x in gl.get("motifs") or [])
    dos = "".join(f"<li>{e(x)}</li>" for x in gl.get("dos") or [])
    donts = "".join(f"<li>{e(x)}</li>" for x in gl.get("donts") or [])
    kvs = "".join(
        f'<div class="kv" style="background:linear-gradient(to top,rgba(0,0,0,.45),transparent 55%),linear-gradient(160deg,{c(i)},{c(i + 2)})"><small>{e(k.get("format", ""))}</small>'
        f'<h3>{e(k.get("headline", ""))}</h3><p>{e(k.get("name", ""))}</p></div>'
        for i, k in enumerate(gl.get("key_visuals") or []))
    bi = plan.get("big_idea") or {}
    sample = bi.get("tagline") or brief.get("name", "")
    mascot = gl.get("mascot") or {}
    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(brief.get('name', 'קמפיין'))} – שפה גרפית</title>
{f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{"&".join("family=" + x for x in fam.split("|"))}&display=swap">' if fam else ''}
<style>
:root{{--a:{c(0)};--b:{c(1)};--c:{c(2)};--d:{c(3)};--ink:#14213D;--paper:#FFF8EC;--card:#ffffff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--ink:#FFF8EC;--paper:#0F1730;--card:#18224A}}}}
:root[data-theme="dark"]{{--ink:#FFF8EC;--paper:#0F1730;--card:#18224A}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:'{e(body_font)}',system-ui,sans-serif;line-height:1.55}}
h1,h2,h3{{font-family:'{e(head_font)}',system-ui,sans-serif;margin:0 0 .4em}}
.hero{{padding:56px 16px 72px;text-align:center;color:#fff;background:radial-gradient(circle at 80% 10%,var(--c) 0 14%,transparent 15%),linear-gradient(135deg,var(--a),var(--b));
 position:relative;overflow:hidden}}
.hero h1{{font-size:clamp(40px,9vw,96px);line-height:1;text-shadow:4px 4px 0 rgba(0,0,0,.18)}}
.hero p{{font-size:clamp(18px,3vw,26px);margin:.3em 0 0}}
.wave{{display:block;width:100%;height:40px;margin-top:-40px;position:relative}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}}
section{{margin:40px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:14px}}
.sw{{background:var(--card);border-radius:18px;padding:10px;display:flex;flex-direction:column;gap:2px;box-shadow:0 2px 10px rgba(0,0,0,.07)}}
.chip{{height:84px;border-radius:12px;margin-bottom:6px}}
.sw code{{font-size:13px;opacity:.75}}.sw small{{font-size:13px;opacity:.85}}
.type{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}}
.type div{{background:var(--card);border-radius:18px;padding:18px}}
.tl{{position:relative;height:190px;margin:10px 14px 0}}
.tl .ph{{top:auto;bottom:30px}}
.ph{{position:absolute;top:84px;height:74px;border-radius:14px;color:#fff;padding:6px 8px;overflow:hidden;font-size:13px;display:flex;flex-direction:column;border:2px solid var(--paper)}}
.ph small{{opacity:.9}}
.pin{{position:absolute;bottom:106px;width:0;border-right:2px dashed currentColor}}
.pin span{{position:absolute;top:-20px;right:-10px;width:20px;height:20px;border-radius:50%;background:currentColor;font-size:11px;font-weight:700;display:grid;place-items:center}}
.pin{{color:var(--ink)}}.pin.peak{{color:var(--b)}}.pin.quiet{{color:#8a8f9c}}
.pin span{{background:var(--ink);color:var(--paper)}}.pin.peak span{{background:var(--b);color:#fff}}.pin.quiet span{{background:#8a8f9c;color:#fff}}
.legend{{list-style:none;padding:0;margin:8px 0 0;display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px}}
.legend b{{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:var(--ink);color:var(--paper);font-size:11px}}
.legend .peak b{{background:var(--b);color:#fff}}.legend .quiet b{{background:#8a8f9c;color:#fff}}
.tlwrap{{overflow-x:auto}}.tlwrap .tl{{min-width:900px}}
.kvs{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}}
.kv{{aspect-ratio:4/5;border-radius:22px;padding:18px;color:#fff;display:flex;flex-direction:column;justify-content:flex-end;text-shadow:0 2px 8px rgba(0,0,0,.25)}}
.kv h3{{font-size:26px;line-height:1.1}}.kv p{{margin:0;opacity:.9}}
.two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}}
.card{{background:var(--card);border-radius:18px;padding:18px}}
</style></head><body>
<header class="hero"><h1>{e(bi.get('name') or brief.get('name', ''))}</h1><p>{e(bi.get('tagline', ''))}</p>
<p style="font-size:16px;opacity:.9">{e((brief.get('location') or {}).get('venue', ''))} · {rng(s['start'], s['end'])}</p></header>
<svg class="wave" viewBox="0 0 1200 40" preserveAspectRatio="none" aria-hidden="true"><path d="M0 20 Q150 0 300 20 T600 20 T900 20 T1200 20 V40 H0Z" fill="var(--paper)"/></svg>
<main>
<section><h2>הקונספט</h2><p>{e(gl.get('concept', ''))}</p></section>
<section><h2>פלטת צבעים</h2><div class="grid">{swatches}</div></section>
<section><h2>טיפוגרפיה</h2><div class="type">{''.join(f'<div><h3 style="font-family:{chr(39)}{e(f)}{chr(39)}">{e(f)}</h3><p style="font-family:{chr(39)}{e(f)}{chr(39)};font-size:22px">{e(sample)}</p></div>' for f in fonts)}</div></section>
<section><h2>ציר העונה</h2><div class="tlwrap"><div class="tl">{pins}{phases}</div></div><ul class="legend">{legend}</ul></section>
<section><h2>קי-ויז'ואלים</h2><div class="kvs">{kvs}</div></section>
<section class="two"><div class="card"><h2>מוטיבים</h2><ul>{motifs}</ul></div>
<div class="card"><h2>הקמע – {e(mascot.get('name', ''))}</h2><p>{e(mascot.get('description', ''))}</p></div></section>
<section class="two"><div class="card"><h2>✅ עושים</h2><ul>{dos}</ul></div><div class="card"><h2>⛔ לא עושים</h2><ul>{donts}</ul></div></section>
</main></body></html>
"""


def _lum(hexcol: str) -> float:
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def write_outputs(campaign: str, plan: dict, brief: dict) -> list[Path]:
    d = campaign_dir(campaign)
    d.mkdir(parents=True, exist_ok=True)
    files = {
        "plan.json": json.dumps(plan, ensure_ascii=False, indent=1) + "\n",
        "plan.md": render_plan_md(plan, brief),
        "graphic-language.md": render_graphic_md(plan),
        "calendar.yaml": render_calendar_yaml(plan),
        "style-board.html": render_style_board(plan, brief),
    }
    out = []
    for name, text in files.items():
        (d / name).write_text(text, encoding="utf-8")
        out.append(d / name)
    return out


def make_visuals(campaign: str, plan: dict) -> list[Path]:
    from . import imagegen
    gl = plan["graphic_language"]
    style = (gl.get("image_style_prompt") or "").strip() + " No text, letters or logos in the image. Scene: "
    refs_dir = campaign_dir(campaign) / "style"   # optional reference images for this campaign
    refs = sorted(p for p in refs_dir.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:4] if refs_dir.exists() else []
    out = []
    for i, kv in enumerate(gl.get("key_visuals") or []):
        story = "9:16" in str(kv.get("format", ""))
        path = campaign_dir(campaign) / "visuals" / f"kv-{i + 1}.jpg"
        try:
            imagegen.generate(kv.get("prompt", ""), path, size="1024x1536", style=style, refs=refs,
                              fit=(1080, 1920) if story else (1080, 1350))
            out.append(path)
        except Exception as ex:   # one failed image must not lose the whole plan
            log.warning("key visual %d failed: %s", i + 1, ex)
    return out


def run(campaign: str, api_key: str, model: str, extra: str = "", visuals: bool = False) -> list[Path]:
    brief = load_brief(campaign)
    skeleton = season_skeleton(brief)
    system, prompt = build_prompt(brief, skeleton, extra)
    plan = clean_plan(ask_plan(api_key, model, system, prompt), skeleton, brief)
    files = write_outputs(campaign, plan, brief)
    if visuals:
        files += make_visuals(campaign, plan)
    return files


def rerender(campaign: str) -> list[Path]:
    """Rebuild md/yaml/html from an edited plan.json – no model call."""
    brief = load_brief(campaign)
    plan = json.loads((campaign_dir(campaign) / "plan.json").read_text(encoding="utf-8"))
    return write_outputs(campaign, clean_plan(plan, season_skeleton(brief), brief), brief)
