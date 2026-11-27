"""CLI entry point.

  python -m agent.main check      # verify tokens & account
  python -m agent.main plan       # Claude writes the next week of daily posts into content/queue.yaml
  python -m agent.main publish    # publish today's due post(s)
  python -m agent.main reply      # answer comments (and DMs if ENABLE_DMS=true)
  python -m agent.main tour       # queue "מחר אנחנו מגיעים ל..." posts (poster + Kupat link) from content/tour.yaml
  python -m agent.main sync       # update content/tour.yaml from the Kupat Tel Aviv site
  python -m agent.main refresh    # extend the Instagram token by 60 days
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from zoneinfo import ZoneInfo

import requests

from .config import MEDIA_DIR, Config
from .instagram import Instagram, InstagramError
from .store import load_queue, load_state, save_queue, save_state

log = logging.getLogger("agent")
MEDIA_EXT = {".jpg", ".jpeg", ".mp4", ".mov"}


def now(cfg: Config) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(cfg.timezone))


def ig_client(cfg: Config) -> Instagram:
    cfg.require("ig_user_id", "ig_access_token")
    return Instagram(cfg.ig_user_id, cfg.ig_access_token, cfg.graph_version, cfg.dry_run,
                     host=cfg.graph_host, page_id=cfg.fb_page_id)


def brain(cfg: Config):
    from .brain import Brain
    cfg.require("anthropic_api_key")
    return Brain(cfg.anthropic_api_key, cfg.model)


# ---------------------------------------------------------------- check
def cmd_check(cfg: Config, _args) -> None:
    print(ig_client(cfg).me())
    print("DRY_RUN =", cfg.dry_run, "| ENABLE_DMS =", cfg.enable_dms)


# ---------------------------------------------------------------- plan
def cmd_plan(cfg: Config, args) -> None:
    queue = load_queue()
    today = now(cfg).date()
    planned_dates = {str(p["date"]) for p in queue if p.get("status") != "published"}
    # Days before a show belong to the "מחר אנחנו מגיעים" tour post – keep them free.
    from .tour import load_tour, summary
    tour = load_tour()
    for s in tour.get("shows") or []:
        try:
            planned_dates.add((dt.date.fromisoformat(str(s["date"])) - dt.timedelta(days=1)).isoformat())
        except (KeyError, ValueError):
            pass

    from . import imagegen
    ai = imagegen.enabled()
    media = sorted(f for f in MEDIA_DIR.glob("*") if f.suffix.lower() in MEDIA_EXT | {".png", ".webp"})
    if not media and not ai:
        raise SystemExit("אין קבצים בתיקיית media/ ואין OPENAI_API_KEY – העלו תמונות או הוסיפו מפתח ליצירת תמונות ב-AI.")
    used = {m for p in queue for m in p.get("media", [])}
    # Prefer media that hasn't been posted yet; reuse old media only if needed.
    fresh = [f for f in media if f.name not in used]
    pool = (fresh + ([] if ai else [f for f in media if f.name in used]))[:12]

    recent = [p["caption"] for p in reversed(queue) if p.get("status") == "published"]
    upcoming = sorted(d for d in planned_dates if d >= today.isoformat())
    posts = brain(cfg).plan_posts(pool, today.isoformat(), args.days, recent,
                                  os.getenv("WEEKLY_BRIEF", ""), ai_images=ai, skip_dates=upcoming,
                                  tour=summary(tour, today))
    auto = os.getenv("AUTO_APPROVE", "true").lower() == "true"
    added = 0
    for p in posts:
        date = str(p.get("date", ""))
        if not date or date in planned_dates or date < today.isoformat():
            continue
        files = list(p.get("media") or [])
        is_ai = False
        if not files and p.get("image_prompt") and ai:
            out = MEDIA_DIR / "ai" / f"{date}-{abs(hash(p['image_prompt'])) % 10**8:08d}.jpg"
            try:
                imagegen.generate(p["image_prompt"], out)
            except Exception as e:
                log.warning("AI image failed for %s: %s", date, e)
                continue
            files, is_ai = [str(out.relative_to(MEDIA_DIR))], True
        if not files or not all((MEDIA_DIR / m).exists() for m in files):
            log.warning("skip post with missing media: %s", files)
            continue
        item = {
            "date": date, "time": p.get("time", "18:00"),
            "media": files, "caption": p["caption"], "idea": p.get("idea", ""),
            "approved": auto, "status": "scheduled",
        }
        if is_ai:
            item.update(ai_generated=True, image_prompt=p["image_prompt"])
        queue.append(item)
        planned_dates.add(date)
        added += 1
        print(f"נוסף פוסט: {date} {'(תמונת AI) ' if is_ai else ''}{files[0]}")
    queue.sort(key=lambda p: (str(p["date"]), str(p.get("time", ""))))
    save_queue(queue)
    print(f"נוספו {added} פוסטים לתור (approved={auto}).")


# ---------------------------------------------------------------- publish
def cmd_publish(cfg: Config, _args) -> None:
    ig = ig_client(cfg)
    queue = load_queue()
    t = now(cfg)
    stamp = t.strftime("%Y-%m-%d %H:%M")
    done = 0
    for p in queue:
        if p.get("status") == "published" or not p.get("approved"):
            continue
        if f"{p['date']} {p.get('time', '00:00')}" > stamp:
            continue
        for m in p["media"]:
            if not m.lower().endswith(tuple(MEDIA_EXT)):
                raise SystemExit(f"{m}: אינסטגרם מקבל רק JPG לתמונות ו-MP4 לסרטונים")
        urls = [f"{cfg.media_base_url}/{m}" for m in p["media"]]
        try:
            ig_id = ig.publish(urls, p["caption"], ai_generated=bool(p.get("ai_generated")))
        except InstagramError as e:
            log.error("publish failed for %s: %s", p["date"], e)
            p["last_error"] = str(e)[:300]
            continue
        if cfg.dry_run:
            print(f"[DRY_RUN] היה מתפרסם: {p['date']} {p['media']}")
            continue
        p.update(status="published", ig_id=ig_id, published_at=t.isoformat(timespec="minutes"))
        p.pop("last_error", None)
        # Same image as an Instagram Story
        if os.getenv("ALSO_STORY", "true").lower() == "true" and p.get("story", True):
            try:
                p["story_id"] = ig.publish_story(urls[0])
            except InstagramError as e:
                log.warning("story failed for %s: %s", p["date"], e)
        # Same post on the Facebook Page
        if os.getenv("CROSSPOST_FACEBOOK", "true").lower() == "true" and cfg.fb_page_id:
            try:
                p["fb_id"] = ig.publish_facebook(urls, p["caption"])
            except InstagramError as e:
                log.warning("facebook cross-post failed for %s: %s", p["date"], e)
        done += 1
        print(f"פורסם: {p['date']} -> {ig_id}")
    save_queue(queue)
    if done == 0:
        print("אין פוסט שמגיע לפרסום כרגע.")


# ---------------------------------------------------------------- reply
def open_issue(cfg: Config, title: str, body: str) -> None:
    if not cfg.github_token:
        log.warning("ESCALATION (no GITHUB_TOKEN): %s\n%s", title, body)
        return
    r = requests.post(
        f"https://api.github.com/repos/{cfg.github_repo}/issues",
        headers={"Authorization": f"Bearer {cfg.github_token}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body}, timeout=30)
    if r.status_code >= 300:
        log.warning("could not open issue: %s %s", r.status_code, r.text[:200])


def cmd_reply(cfg: Config, _args) -> None:
    ig = ig_client(cfg)
    me = ig.me()
    my_name = me.get("username", "")
    handled: list[str] = load_state("handled", [])
    seen = set(handled)
    b = brain(cfg)
    stats = {"reply": 0, "escalate": 0, "hide": 0, "ignore": 0}

    def act(key: str, kind: str, text: str, user: str, do_reply, do_hide=None, **ctx):
        d = b.decide_reply(kind, text, user, **ctx)
        action = d.get("action", "escalate")
        stats[action] = stats.get(action, 0) + 1
        reply = (d.get("reply") or "").strip()
        log.info("%s @%s: %r -> %s %r", kind, user, text[:80], action, reply[:80])
        if action in {"reply", "escalate"} and reply:
            do_reply(reply)
        if action == "hide" and do_hide:
            do_hide()
        if action == "escalate":
            open_issue(cfg, f"[אינסטגרם] פנייה שדורשת טיפול – @{user}",
                       f"**סוג:** {kind}\n**משתמש:** @{user}\n**הודעה:**\n> {text}\n\n"
                       f"**סיבה:** {d.get('reason', '')}\n**נענה אוטומטית:** {reply or '—'}\n"
                       f"{ctx.get('link', '')}")
        if not cfg.dry_run:
            seen.add(key)
            handled.append(key)

    # comments on recent posts
    for media in ig.recent_media(limit=10):
        for c in ig.comments(media["id"]):
            key = f"c:{c['id']}"
            if key in seen or c.get("username") == my_name:
                continue
            if any(r.get("username") == my_name for r in c.get("replies", {}).get("data", [])):
                continue  # already answered manually
            act(key, "תגובה לפוסט", c.get("text", ""), c.get("username", "?"),
                lambda txt, cid=c["id"], u=c.get("username", ""): ig.reply_comment(cid, f"@{u} {txt}"),
                lambda cid=c["id"]: ig.hide_comment(cid),
                post_caption=media.get("caption", ""), link=media.get("permalink", ""))

    # comments on the Facebook Page
    if cfg.fb_page_id and os.getenv("REPLY_FACEBOOK", "true").lower() == "true":
        try:
            fb_posts = ig.fb_recent_posts()
        except InstagramError as e:
            log.warning("facebook comments skipped: %s", e)
            fb_posts = []
        for post in fb_posts:
            for c in post.get("comments", {}).get("data", []):
                key = f"fb:{c['id']}"
                author = c.get("from", {}) or {}
                if key in seen or author.get("id") == cfg.fb_page_id:
                    continue
                if any((r.get("from") or {}).get("id") == cfg.fb_page_id
                       for r in c.get("comments", {}).get("data", [])):
                    continue  # already answered by the page
                act(key, "תגובה לפוסט בפייסבוק", c.get("message", ""), author.get("name", "?"),
                    lambda txt, cid=c["id"]: ig.fb_reply_comment(cid, txt),
                    lambda cid=c["id"]: ig.fb_hide_comment(cid),
                    post_caption=post.get("message", ""), link=post.get("permalink_url", ""))

    # direct messages (only inside Instagram's 24h reply window)
    if cfg.enable_dms:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=23)
        for conv in ig.conversations():
            msgs = conv.get("messages", {}).get("data", [])
            if not msgs:
                continue
            last = msgs[0]  # newest first
            sender = last.get("from", {})
            if sender.get("username") == my_name or f"m:{last['id']}" in seen:
                continue
            created = dt.datetime.fromisoformat(last["created_time"].replace("+0000", "+00:00"))
            if created < cutoff:
                continue
            thread = [f"{m.get('from', {}).get('username')}: {m.get('message', '')}" for m in reversed(msgs)]
            act(f"m:{last['id']}", "הודעה פרטית", last.get("message", ""), sender.get("username", "?"),
                lambda txt, rid=sender.get("id"): ig.send_dm(rid, txt), thread=thread)

    save_state("handled", handled[-5000:])
    print("סיכום:", stats, "(DRY_RUN)" if cfg.dry_run else "")


# ---------------------------------------------------------------- tour
def cmd_tour(cfg: Config, args) -> None:
    from . import imagegen
    from . import tour as T
    schedule = T.load_tour()
    queue = load_queue()
    have = {p.get("tour_key") for p in queue if p.get("tour_key")}
    today = now(cfg).date()
    post_time = os.getenv("TOUR_POST_TIME") or schedule.get("post_time") or "10:00"
    base_name = schedule.get("poster_base") or ""
    base = MEDIA_DIR / base_name if base_name else None
    b = None
    added = 0
    # A post goes up the day BEFORE each show day ("מחר ...").
    for offset in range(1, args.days + 1):
        show_day = today + dt.timedelta(days=offset)
        for stop in T.stops_for(show_day, schedule):
            key = f"{stop['date']}|{stop['city']}"
            if key in have:
                continue
            if stop.get("poster"):
                media = [stop["poster"]]
                if not (MEDIA_DIR / stop["poster"]).exists():
                    log.warning("poster %s not found in media/ – generating one", stop["poster"])
                    media = []
            else:
                media = []
            ai_bg = False
            own = [m for m in schedule.get("default_posters") or [] if (MEDIA_DIR / m).exists()]
            if not media and own:  # rotate through the brand's own posters – no new images
                media = [own[dt.date.fromisoformat(stop["date"]).toordinal() % len(own)]]
            if not media:
                out = T.POSTER_DIR / f"{T.slug(stop)}.jpg"
                bg = base
                if not (base and base.exists()) and imagegen.enabled():
                    try:
                        bg = imagegen.generate(T.ai_background_prompt(stop),
                                               T.POSTER_DIR / f"{T.slug(stop)}-bg.jpg")
                        ai_bg = True
                    except Exception as e:
                        log.warning("AI background failed (%s) – using drawn background", e)
                        bg = base
                T.make_poster(stop, out, bg)
                media = [str(out.relative_to(MEDIA_DIR))]
            caption = ""
            if cfg.anthropic_api_key:
                try:
                    b = b or brain(cfg)
                    caption = b.tour_caption(stop)
                except Exception as e:  # never skip the post because of the model
                    log.warning("tour caption via Claude failed (%s) – using template", e)
            caption = caption or T.fallback_caption(stop)
            queue.append({
                "date": (show_day - dt.timedelta(days=1)).isoformat(), "time": post_time,
                "media": media, "caption": caption, "idea": f"מחר מגיעים ל{stop['city']}",
                "approved": os.getenv("AUTO_APPROVE", "true").lower() == "true",
                "status": "scheduled", "tour_key": key,
                **({"ai_generated": True} if ai_bg else {}),
            })
            have.add(key)
            added += 1
            print(f"נוסף פוסט סיבוב: {key} -> {media[0]}")
    queue.sort(key=lambda p: (str(p["date"]), str(p.get("time", ""))))
    save_queue(queue)
    print(f"נוספו {added} פוסטים של 'מחר אנחנו מגיעים'.")


# ---------------------------------------------------------------- sync (Kupat)
def cmd_sync(cfg: Config, _args) -> None:
    from . import kupat
    n = kupat.sync(brain(cfg))
    print(f"לוח ההופעות עודכן מקופת תל אביב: {n} מועדים.")


# ---------------------------------------------------------------- refresh
def cmd_refresh(cfg: Config, _args) -> None:
    data = ig_client(cfg).refresh_token()
    if data.get("never_expires"):
        print("הטוקן הוא טוקן מערכת (System User) – הוא לא פג, אין צורך לחדש.")
        return
    days = int(data.get("expires_in", 0)) // 86400
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        print(f"::add-mask::{data['access_token']}")
        with open(out, "a") as f:
            f.write(f"token={data['access_token']}\n")
    print(f"הטוקן חודש, בתוקף לעוד {days} ימים.")


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("plan")
    p.add_argument("--days", type=int, default=7)
    sub.add_parser("publish")
    sub.add_parser("reply")
    t = sub.add_parser("tour")
    t.add_argument("--days", type=int, default=2, help="כמה ימים קדימה לבדוק בלוח")
    sub.add_parser("sync")
    sub.add_parser("refresh")
    args = ap.parse_args(argv)
    cfg = Config.load()
    {"check": cmd_check, "plan": cmd_plan, "publish": cmd_publish,
     "reply": cmd_reply, "tour": cmd_tour, "sync": cmd_sync, "refresh": cmd_refresh}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
