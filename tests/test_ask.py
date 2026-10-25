"""Asking Jobsmith about your job hunt in plain words, answered from its records with no AI."""
from jobsmith import ask, db
from jobsmith.skills import outreach


def _job(jid, company, status="new", title="Software Intern", fit=50, **kw):
    now = db.now()
    db.x("""INSERT INTO jobs(id, company, title, url, ats, status, fit_score, created_at, updated_at, error) VALUES(?,?,?,?,?,?,?,?,?,?)""",
         (jid, company, title, f"https://x/{jid}", "greenhouse", status, fit, now, now, kw.get("error")))
    if kw.get("hold"):
        db.x("UPDATE jobs SET hold_reason=? WHERE id=?", (kw["hold"], jid))


def _sent(jid, hours_ago):
    t = db.now() - hours_ago * 3600
    db.x("INSERT INTO runs(job_id, kind, status, started_at, finished_at) VALUES(?,?,?,?,?)", (jid, "submit", "done", t, t))


def _blocks(q, **kw):
    return list(ask.answer(q, **kw))


def test_time_windows():
    now = db.now()
    since, until, label = ask.window("in the past few hours", now)
    assert round((now - since) / 3600) == 6 and until is None and label == "in the past 6 hours"
    assert ask.window("last 2 days", now)[2] == "in the past 2 days"
    assert ask.window("past hour", now)[2] == "in the past hour"
    assert ask.window("what did you do today", now)[2] == "today"
    s, u, lab = ask.window("yesterday", now)
    assert u - s == 86400 and lab == "yesterday"
    assert ask.window("last week", now)[2] == "last week"
    assert ask.window("whatever", now) == (None, None, "")


def test_the_two_part_question():
    db.conn()
    _job("a", "Acme Robotics", "submitted")
    _sent("a", 2)
    _job("g", "Globex", "submitted")
    _sent("g", 30)                                     # outside "the past few hours"
    _job("w", "Wayne Enterprises", "filled", hold="Why Wayne? wasn't sure")
    outreach._ensure()
    db.x("INSERT INTO outreach(job_id, person, kind, text, created_at) VALUES(?,?,?,?,?)", ("a", "Priya Natarajan", "referral", "Hi", db.now()))
    out = _blocks("in the past few hours, which companies did you apply to and what is waiting for me to send?",
                  attention=[{"job_id": "w", "company": "Wayne Enterprises", "kind": "code", "message": "Wayne emailed you a code."}])
    heads = [b["text"] for b in out if b["t"] == "head"]
    items = [b["text"] for b in out if b["t"] == "item"]
    assert heads[0].startswith("Applied in the past 6 hours")
    assert "Acme Robotics" in items and "Globex" not in items[:1]
    assert any(h.startswith("Only you can do") for h in heads)
    assert any(h.startswith("Messages drafted, not sent") for h in heads) and "Priya Natarajan" in items


def _sections(blocks) -> dict[str, list[str]]:
    """Each heading's items, by heading without its count."""
    out, head = {}, None
    for b in blocks:
        if b["t"] == "head":
            head = b["text"].rsplit("  ", 1)[0]
            out[head] = []
        elif b["t"] == "item" and head:
            out[head].append(b["text"])
    return out


def test_an_emailed_code_is_only_you_can_do():
    """An application waiting on an emailed code can't be submitted until you get it: it goes under "Only you can
    do", once, not under "Filled, waiting for you to submit". Whether its tab is live (attention) or only its hold
    reason says so, as with the practice copy's Wayne Enterprises."""
    db.conn()
    _job("w", "Wayne Enterprises", "filled", hold="Emailed verification code needed")
    _job("s", "Stark Industries", "filled", hold="Why Stark? wasn't sure")
    _job("l", "Lumon", "filled", hold="Why Lumon? wasn't sure")
    live = [{"job_id": "l", "company": "Lumon", "kind": "code", "message": "Lumon emailed you a verification code."}]
    for q in ("what needs me?", "any verification codes?"):
        got = _sections(_blocks(q, attention=live))
        assert sorted(got["Only you can do" if q == "what needs me?" else "Codes, CAPTCHAs and sign-ins"]) == \
            ["Lumon", "Wayne Enterprises"], (q, got)
        if q == "what needs me?":
            assert got["Filled, waiting for you to submit"] == ["Stark Industries"]
    at_wayne = _sections(_blocks("what needs me at wayne enterprises?"))
    assert at_wayne == {"Only you can do": ["Wayne Enterprises"]}


def test_company_counts_and_unknowns():
    db.conn()
    _job("a", "Acme Robotics", "submitted")
    _sent("a", 5)
    _job("b", "Acme Robotics", "error", title="Hardware Intern", error="Page not found")
    out = _blocks("what failed at acme robotics?")
    assert out[0]["text"].startswith("Couldn't finish at Acme Robotics") and out[1]["text"] == "Acme Robotics"
    stats = {b["meta"]: b["text"] for b in _blocks("how many applications this week?") if b["t"] == "stat"}
    assert stats["applications sent"] == "1"
    nope = _blocks("tell me a joke")
    assert nope[0]["text"].startswith("I can't answer") and sum(b["t"] == "example" for b in nope) >= 3
    assert not ask.is_question("apply to nvidia hardware internships") and ask.is_question("what needs me?")


def test_stream_endpoint():
    import json
    from fastapi.testclient import TestClient
    from jobsmith.api import app
    db.conn()
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"text": "what are my best matches?"})
        blocks = [json.loads(line) for line in r.text.splitlines() if line]
    assert blocks[0]["t"] == "head" and blocks[0]["text"].startswith("Best matches")
