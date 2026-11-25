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
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("IG_USER_ID", "1"); monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    return q


class FakeIG:
    def __init__(self): self.calls = []
    def me(self): return {"username": "circusbravo"}
    def publish(self, urls, caption, ai_generated=False): self.calls.append(("pub", urls)); return "IG1"
    def recent_media(self, limit=10): return [{"id": "M1", "caption": "פוסט", "permalink": "http://x"}]
    def comments(self, mid):
        return [{"id": "C1", "text": "מתי המופע?", "username": "dana"},
                {"id": "C2", "text": "החזר כספי!!", "username": "yossi"},
                {"id": "C3", "text": "שלי", "username": "circusbravo"}]
    def reply_comment(self, cid, t): self.calls.append(("reply", cid, t))
    def hide_comment(self, cid): self.calls.append(("hide", cid))


class FakeBrain:
    def plan_posts(self, files, today, days, recent, brief):
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
    cfg = m.Config.load()
    m.cmd_plan(cfg, SimpleNamespace(days=7))
    q = store.load_queue(repo)
    assert len(q) == 2 and all(p["approved"] for p in q)  # missing media skipped
    m.cmd_publish(cfg, None)
    q = store.load_queue(repo)
    assert q[0]["status"] == "published" and q[1]["status"] == "scheduled"  # only today's is due
    assert ig.calls[0][1][0].endswith("/media/a.jpg")


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
