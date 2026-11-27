"""Offline tests – no real Instagram/Claude calls."""
import datetime as dt
from types import SimpleNamespace

import pytest

from agent import main as m
from agent import store
from agent.brain import _json


@pytest.fixture
def repo(tmp_path, monkeypatch):
    media = tmp_path / "media"; media.mkdir()
    (media / "a.jpg").write_bytes(b"x"); (media / "b.jpg").write_bytes(b"y")
    q = tmp_path / "queue.yaml"
    monkeypatch.setattr(m, "MEDIA_DIR", media)
    monkeypatch.setattr(store, "QUEUE_FILE", q)
    monkeypatch.setattr(store, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(m, "load_queue", lambda: store.load_queue(q))
    monkeypatch.setattr(m, "save_queue", lambda p: store.save_queue(p, q))
    from agent import tour
    monkeypatch.setattr(tour, "TOUR_FILE", tmp_path / "no-tour.yaml")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)   # never touch the real repo from tests
    monkeypatch.setattr(m, "notify", lambda cfg, lines: None)
    monkeypatch.setenv("IG_USER_ID", "1"); monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    return q


class FakeIG:
    def __init__(self): self.calls = []
    def me(self): return {"username": "circusbravo"}
    def publish(self, urls, caption, ai_generated=False): self.calls.append(("pub", urls)); return "IG1"
    def publish_story(self, url): self.calls.append(("story", url)); return "S1"
    def publish_facebook(self, urls, caption): self.calls.append(("fb", urls)); return "F1"
    def recent_media(self, limit=10): return [{"id": "M1", "caption": "פוסט", "permalink": "http://x"}]
    def comments(self, mid):
        return [{"id": "C1", "text": "מתי המופע?", "username": "dana"},
                {"id": "C2", "text": "החזר כספי!!", "username": "yossi"},
                {"id": "C3", "text": "שלי", "username": "circusbravo"}]
    def reply_comment(self, cid, t): self.calls.append(("reply", cid, t))
    def hide_comment(self, cid): self.calls.append(("hide", cid))


class FakeBrain:
    def plan_posts(self, files, today, days, recent, brief, ai_images=False, skip_dates=None, tour=""):
        if ai_images:
            d = dt.date.fromisoformat(today)
            return [{"date": str(d + dt.timedelta(days=i)), "time": "00:00", "media": [],
                     "image_prompt": f"circus tent {i}", "caption": f"AI {i}"} for i in range(3)]
        d = dt.date.fromisoformat(today)
        return [{"date": str(d + dt.timedelta(days=i)), "time": "00:00", "media": [f.name],
                 "caption": f"פוסט {i}"} for i, f in enumerate(files)] + \
               [{"date": str(d + dt.timedelta(days=5)), "media": ["missing.jpg"], "caption": "x"}]
    def decide_reply(self, kind, text, user, **kw):
        return {"action": "escalate", "reply": "נחזור אליך בפרטי"} if "החזר" in text else {"action": "reply", "reply": "ב-12.12!"}


def test_plan_then_publish(repo, monkeypatch):
    ig = FakeIG()
    monkeypatch.setattr(m, "brain", lambda cfg: FakeBrain())
    monkeypatch.setattr(m, "ig_client", lambda cfg: ig)
    monkeypatch.setenv("GENERAL_POST_TIME", "00:00")
    cfg = m.Config.load()
    m.cmd_plan(cfg, SimpleNamespace(days=7))
    q = store.load_queue(repo)
    assert len(q) == 2 and all(p["approved"] for p in q)  # missing media skipped
    m.cmd_publish(cfg, None)
    q = store.load_queue(repo)
    assert q[0]["status"] == "published" and q[1]["status"] == "scheduled"  # only today's is due
    assert ig.calls[0][1][0].endswith("/media/a.jpg")
    assert ig.calls[1][0] == "story" and q[0]["story_id"] == "S1"


def test_reply_and_escalate(repo, monkeypatch):
    ig = FakeIG(); issues = []
    monkeypatch.setattr(m, "brain", lambda cfg: FakeBrain())
    monkeypatch.setattr(m, "ig_client", lambda cfg: ig)
    monkeypatch.setattr(m, "open_issue", lambda cfg, t, b: issues.append(t))
    cfg = m.Config.load()
    m.cmd_reply(cfg, None)
    replies = [c for c in ig.calls if c[0] == "reply"]
    assert [r[1] for r in replies] == ["C1", "C2"] and replies[0][2].startswith("@dana")
    assert len(issues) == 1
    ig.calls.clear(); m.cmd_reply(cfg, None)
    assert ig.calls == []  # never answers the same comment twice


def test_json_parsing():
    assert _json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert _json('sure: {"action": "reply"}')["action"] == "reply"


def test_tour_posts_day_before_with_poster(repo, monkeypatch, tmp_path):
    from agent import tour as T
    tour_file = tmp_path / "tour.yaml"
    tour_file.write_text(
        "post_time: '09:30'\nshows:\n"
        "  - {date: 2026-12-12, time: '16:00', city: חיפה, venue: אולם אורן, link: https://kupat/haifa}\n"
        "  - {date: 2026-12-12, time: '12:00', city: חיפה, venue: אולם אורן}\n"
        "  - {date: 2026-12-20, time: '17:00', city: אילת}\n", encoding="utf-8")
    monkeypatch.setattr(T, "TOUR_FILE", tour_file)
    monkeypatch.setattr(T, "POSTER_DIR", tmp_path / "media" / "tour")
    monkeypatch.setattr(m, "MEDIA_DIR", tmp_path / "media")
    monkeypatch.delenv("ANTHROPIC_API_KEY")  # template caption, no network
    monkeypatch.setattr(m, "now", lambda cfg: dt.datetime(2026, 12, 11, 6, 0))
    cfg = m.Config.load()
    m.cmd_tour(cfg, SimpleNamespace(days=2))
    m.cmd_tour(cfg, SimpleNamespace(days=2))  # idempotent
    q = store.load_queue(repo)
    assert len(q) == 1
    p = q[0]
    assert p["date"] == "2026-12-11" and p["time"] == "09:30"
    assert "מחר אנחנו מגיעים לחיפה" in p["caption"] and "https://kupat/haifa" in p["caption"]
    assert "12:00 | 16:00" in p["caption"]
    assert (tmp_path / "media" / p["media"][0]).exists()


def test_plan_with_ai_images(repo, monkeypatch):
    from agent import imagegen
    made = []
    def fake_generate(prompt, out, size="1024x1536"):
        out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(b"jpg"); made.append(prompt); return out
    monkeypatch.setenv("OPENAI_API_KEY", "x"); monkeypatch.setenv("USE_AI_IMAGES", "true")
    monkeypatch.setattr(imagegen, "generate", fake_generate)
    monkeypatch.setattr(m, "brain", lambda cfg: FakeBrain())
    cfg = m.Config.load()
    m.cmd_plan(cfg, SimpleNamespace(days=3))
    q = store.load_queue(repo)
    assert len(q) == 3 and len(made) == 3
    assert all(p["ai_generated"] and p["media"][0].startswith("ai/") for p in q)


def test_kupat_merge_keeps_posters(tmp_path):
    from agent import kupat
    import yaml
    old = {"post_time": "10:00", "shows": [
        {"date": "2026-12-01", "city": "חיפה", "venue": "x", "poster": "haifa.jpg"},
        {"date": "2026-12-02", "city": "בוטל", "venue": "y"}]}
    new = [{"date": "2026-12-01", "time": "18:30", "city": "חיפה", "venue": "אודיטוריום חיפה", "link": "L1"},
           {"date": "2026-12-03", "time": "16:30", "city": "ראש העין", "venue": "היכל", "link": "L2"}]
    merged = kupat.merge(new, old)
    assert [s["city"] for s in merged["shows"]] == ["חיפה", "ראש העין"]
    assert merged["shows"][0]["poster"] == "haifa.jpg" and merged["post_time"] == "10:00"
    p = tmp_path / "tour.yaml"; p.write_text("# header\npost_time: '10:00'\n", encoding="utf-8")
    kupat.save_tour(merged, p)
    txt = p.read_text(encoding="utf-8")
    assert txt.startswith("# header") and yaml.safe_load(txt)["shows"][1]["link"] == "L2"


def test_tour_summary_groups_by_city():
    from agent import tour as T
    sched = {"shows": [
        {"date": "2026-12-03", "time": "18:30", "city": "ראש העין", "venue": "היכל"},
        {"date": "2026-12-03", "time": "16:30", "city": "ראש העין", "venue": "היכל"},
        {"date": "2026-12-12", "city": "תל אביב"},
        {"date": "2026-11-01", "time": "10:00", "city": "עבר"},
    ]}
    out = T.summary(sched, dt.date(2026, 11, 27))
    assert "ראש העין – היכל, 16:30 | 18:30" in out
    assert "תל אביב, שעה לא ידועה" in out
    assert "עבר" not in out


def test_decide_reply_accepts_extra_context():
    import inspect
    from agent.brain import Brain
    assert any(p.kind == p.VAR_KEYWORD for p in inspect.signature(Brain.decide_reply).parameters.values())
