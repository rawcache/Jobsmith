"""Jobsmith in your terminal, the way Claude Code works: a conversation, with everything one /command away.

    jobsmith           opens this (after setup)
    jobsmith --plain   the line-by-line prompt instead

Ask anything about your job hunt ("which companies did you apply to in the past few hours, and what's waiting for
me?") and the answer builds up line by line from Jobsmith's own records: instant, offline, no AI. Tell it where to
apply ("apply to nvidia hardware internships", a job link, a GitHub list) and it goes. Applications in progress
animate above the prompt. /review, /matches, /outreach, /followups, /voice and /settings open full-screen views;
the dashboard in your browser (/web) is there for when you'd rather click.

Keys: shift+tab autopilot on/off · ctrl+o board · esc cancel · ↑ history · ctrl+c twice to quit · ? shortcuts
"""
from __future__ import annotations

import json
import random
import time
import webbrowser
from pathlib import Path

import httpx
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Input, Static, TextArea

EMBER = "#7aa2ff"     # cobalt: the accent (named after the forge)
EMBER_HI = "#c7d7ff"
EMBER_LO = "#3554c9"
STEEL = "#8b98b2"
INK = "#e8edf7"
DIM = "#5d6a85"
FAINT = "#2b3a5c"
BG = "#0b1220"
SPARK = "#a5f3fc"
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STAR = "·✢✳✶✻✽✻✶✳✢"
VERBS = ["Forging", "Hammering", "Tempering", "Smelting", "Annealing", "Quenching", "Riveting", "Smithing", "Shaping", "Polishing"]

# The anvil and hammer, in three frames: hammer raised, striking, sparks ("*").
LOGO = [
    ["         ▐██▌━━━━━ ",
     "                   ",
     "▗▄▄▄▄▄▄██████████▖ ",
     "    ▀▀▀▀███████▀▀  ",
     "      ▗███████▖    "],
    ["                   ",
     "         ▐██▌━━━━━ ",
     "▗▄▄▄▄▄▄██████████▖ ",
     "    ▀▀▀▀███████▀▀  ",
     "      ▗███████▖    "],
    ["     *    *    *   ",
     "   *     ▐██▌━━━━━*",
     "▗▄▄▄▄▄▄██████████▖ ",
     "    ▀▀▀▀███████▀▀  ",
     "      ▗███████▖    "],
]
WOOD = "#94a3b8"


def logo_text(frame: int, glint: int = -1) -> Text:
    t = Text()
    rows = LOGO[frame]
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "*":
                t.append(random.choice("✦·✧*"), style=SPARK)
            elif ch == "━":
                t.append(ch, style=WOOD)
            elif r < 2 and ch != " ":
                t.append(ch, style=EMBER)
            elif ch != " ":
                hot = glint >= 0 and abs(c - glint) <= 1
                t.append(ch, style=INK if hot else STEEL)
            else:
                t.append(ch)
        if r < len(rows) - 1:
            t.append("\n")
    return t


def bar(step: int, total: int, width: int = 8) -> Text:
    done = round(width * step / max(1, total))
    return Text.assemble(("▰" * done, EMBER), ("▱" * (width - done), FAINT))


def shimmer(word: str, frame: int) -> Text:
    """A word with a bright band sweeping through it, like Claude Code's 'thinking' line."""
    t = Text()
    pos = frame % (len(word) + 6) - 3
    for i, ch in enumerate(word):
        d = abs(i - pos)
        t.append(ch, style=f"bold {EMBER_HI}" if d == 0 else EMBER if d <= 2 else EMBER_LO)
    return t


COMMANDS: list[tuple[str, str, str]] = [
    ("/help", "", "what you can ask and every command"),
    ("/review", "", "go through applications waiting for you, approve or edit answers, submit"),
    ("/matches", "", "your best-fit roles; enter applies"),
    ("/apply", "<company, link or list>", "apply somewhere: /apply nvidia hardware internships"),
    ("/autopilot", "[on|off]", "apply on its own (shift+tab)"),
    ("/stop", "", "stop everything now"),
    ("/code", "[company]", "paste an emailed verification code"),
    ("/takeover", "[company]", "open an application's page in a window"),
    ("/watch", "[company]", "watch it fill in, live"),
    ("/outreach", "[company]", "people you know, referral asks; you send them"),
    ("/followups", "", "applications gone quiet, with a follow-up for each"),
    ("/voice", "[add <file>]", "what Jobsmith knows about how you write"),
    ("/resume", "<file>", "add or replace your resume"),
    ("/settings", "", "AI, keys, how picky, autopilot"),
    ("/key", "<gemini|anthropic|openai>", "paste an AI key (hidden as you type)"),
    ("/sync", "", "check your job lists for new roles"),
    ("/board", "", "everything at once: live, needs you, bell (ctrl+o)"),
    ("/skills", "", "every skill and whether it's on"),
    ("/web", "", "open the dashboard in your browser"),
    ("/clear", "", "clear the conversation"),
    ("/quit", "", "leave (Jobsmith keeps applying in the background)"),
]


# =========================================================================== small screens
class AskLine(ModalScreen[str]):
    """One line of input: a code, a key (hidden), a value."""
    DEFAULT_CSS = f"""
    AskLine {{ align: center middle; background: {BG} 60%; }}
    #dlg {{ width: 70; height: auto; padding: 1 2; border: round {EMBER}; background: #111a2e; }}
    #hint {{ color: {DIM}; margin-top: 1; }}
    """

    def __init__(self, prompt: str, placeholder: str = "", password: bool = False, hint: str = "enter to save · esc to cancel"):
        super().__init__()
        self.prompt, self.placeholder, self.password, self.hint = prompt, placeholder, password, hint

    def compose(self) -> ComposeResult:
        with Vertical(id="dlg"):
            yield Static(self.prompt)
            yield Input(placeholder=self.placeholder, password=self.password, id="v")
            yield Static(self.hint, id="hint")

    @on(Input.Submitted)
    def done(self, e: Input.Submitted) -> None:
        self.dismiss(e.value.strip())

    def key_escape(self) -> None:
        self.dismiss("")


class EditAnswer(ModalScreen[str | None]):
    DEFAULT_CSS = f"""
    EditAnswer {{ align: center middle; background: {BG} 60%; }}
    #dlg {{ width: 90%; height: 80%; padding: 1 2; border: round {EMBER}; background: #111a2e; }}
    #q {{ margin-bottom: 1; }}
    TextArea {{ height: 1fr; }}
    #hint {{ color: {DIM}; margin-top: 1; }}
    """
    BINDINGS = [Binding("ctrl+s", "save", "Save and approve"), Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, answer: str):
        super().__init__()
        self.question, self.answer = question, answer

    def compose(self) -> ComposeResult:
        with Vertical(id="dlg"):
            yield Static(Text(self.question, style="bold"), id="q")
            yield TextArea(self.answer, id="ta", soft_wrap=True)
            yield Static("ctrl+s save and approve · esc cancel", id="hint")

    def action_save(self) -> None:
        self.dismiss(self.query_one("#ta", TextArea).text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Splash(ModalScreen):
    """smith draws itself in, once. Any key skips it."""
    DEFAULT_CSS = f"""
    Splash {{ align: center middle; background: {BG}; }}
    #art {{ width: auto; height: auto; }}
    #cap {{ width: auto; color: {DIM}; margin-top: 1; }}
    """

    def compose(self) -> ComposeResult:
        from .web_art import SMITH
        self.lines = SMITH.split("\n")
        self.n = 0
        with Vertical():
            yield Static("", id="art")
            yield Static("jobsmith", id="cap")

    def on_mount(self) -> None:
        self.set_interval(0.025, self.tick)

    def tick(self) -> None:
        self.n += 1
        self.query_one("#art", Static).update(Text("\n".join(self.lines[: self.n]), style=INK))
        if self.n > len(self.lines) + 10:
            self.dismiss()

    def on_key(self) -> None:
        self.dismiss()


# =========================================================================== full-screen views
class View(Screen):
    """A full-screen view with a title line, opened by a /command; esc goes back to the conversation."""
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]
    DEFAULT_CSS = f"""
    View {{ background: {BG}; }}
    .title {{ height: 1; padding: 0 1; background: #111a2e; }}
    .panel {{ border: round #1e2a44; border-title-color: {STEEL}; padding: 0 1; background: {BG}; }}
    .panel:focus-within {{ border: round {EMBER}; border-title-color: {EMBER}; }}
    DataTable {{ background: {BG}; height: 1fr; scrollbar-size-horizontal: 0; scrollbar-size-vertical: 1;
                 scrollbar-color: {FAINT}; scrollbar-background: {BG}; }}
    DataTable > .datatable--cursor {{ background: #1b2741; color: #f1f5ff; }}
    DataTable > .datatable--header {{ color: {DIM}; background: {BG}; }}
    .detail {{ height: 1fr; }}
    .fill {{ height: 1fr; }}
    #jobs {{ height: 1fr; }}
    Footer {{ background: #111a2e; }}
    """

    @property
    def http(self) -> httpx.Client:
        return self.app.http

    def get(self, path: str, **params) -> dict:
        try:
            return self.http.get(path, params=params or None).json()
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e)}

    def send(self, method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        try:
            r = self.http.request(method, path, json=body or {}, timeout=timeout)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                return {"error": data.get("detail") or r.text[:200]}
            return data
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e)}

    def heading(self, *parts) -> Text:
        return Text.assemble(("▙ jobsmith  ", f"bold {EMBER}"), *parts)


class Review(View):
    """Applications waiting for you: each one's answers, problems first. Approve, edit, submit, skip."""
    BINDINGS = View.BINDINGS + [
        Binding("a", "approve", "Approve"), Binding("e", "edit", "Edit"), Binding("s", "submit", "Submit"),
        Binding("k", "skip", "Skip job"), Binding("t", "takeover", "Take over"), Binding("c", "code", "Code"),
        Binding("tab", "switch", "Jobs/answers", show=False)]

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        with Horizontal(classes="fill"):
            jobs = DataTable(id="jobs", classes="panel", cursor_type="row")
            jobs.border_title = "Waiting for you"
            jobs.styles.width = 44
            yield jobs
            with Vertical():
                qs = DataTable(id="qs", classes="panel", cursor_type="row")
                qs.border_title = "Answers"
                yield qs
                with VerticalScroll(id="dwrap", classes="panel detail"):
                    yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#jobs", DataTable).add_columns("", "Company", "Why")
        self.query_one("#qs", DataTable).add_columns("", "Question", "Answer")
        self.job: dict = {}
        self.drafts: list[dict] = []
        self.load_jobs()

    @work(thread=True, exclusive=True, group="jobs")
    def load_jobs(self) -> None:
        home = self.get("/api/home")
        self.app.call_from_thread(self.show_jobs, home.get("review", []))

    def show_jobs(self, rows: list[dict]) -> None:
        t = self.query_one("#jobs", DataTable)
        keep = t.cursor_row
        t.clear()
        for r in rows:
            mark = Text("✗", style="red") if r["status"] == "error" else Text("!", style="yellow")
            t.add_row(mark, Text(r["company"][:20], style="bold"), (r.get("hold_reason") or r.get("error") or "ready to submit")[:40], key=r["id"])
        self.query_one("#t", Static).update(self.heading((f"Review  {len(rows)} waiting for you", "bold"),
                                                       ("   a approve · e edit · s submit · k skip · esc back", DIM)))
        if not rows:
            self.query_one("#detail", Static).update(Text("Nothing is waiting for you. Everything is either sent or still being worked on.", style=DIM))
            self.query_one("#qs", DataTable).clear()
            return
        t.move_cursor(row=min(keep, t.row_count - 1))
        t.focus()
        self.load_job(str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value))

    @on(DataTable.RowHighlighted, "#jobs")
    def picked_job(self, e: DataTable.RowHighlighted) -> None:
        if e.row_key and e.row_key.value != self.job.get("id"):
            self.load_job(str(e.row_key.value))

    @work(thread=True, exclusive=True, group="job")
    def load_job(self, jid: str) -> None:
        d = self.get(f"/api/jobs/{jid}")
        if "job" in d:
            self.app.call_from_thread(self.show_job, d)

    @staticmethod
    def _problem(d: dict, blockers: list[str]) -> bool:
        return d["verdict"] != "green" and any(b.startswith(d["label"] + ":") for b in blockers)

    def show_job(self, d: dict) -> None:
        self.job = d["job"]
        blockers = (d.get("readiness") or {}).get("blockers", [])
        self.drafts = sorted(d["drafts"], key=lambda x: (not self._problem(x, blockers), x["qtype"] not in ("textarea", "text"), x["id"]))
        t = self.query_one("#qs", DataTable)
        keep = t.cursor_row
        t.clear()
        for x in self.drafts:
            val = (x.get("final_answer") or x.get("answer") or "").replace("\n", " ")
            mark = (Text("✓", style="green") if x["verdict"] == "green" or x.get("final_answer") else
                    Text("!", style="yellow") if self._problem(x, blockers) else Text("·", style=DIM))
            t.add_row(mark, x["label"][:46], Text(val[:60] or "(empty)", style=INK if val else "italic " + DIM), key=str(x["id"]))
        t.border_title = (f"{self.job['company']} · {self.job['title']}"[:70] +
                          ("   no answers yet" if not self.drafts else f"   {len(blockers)} to check" if blockers else "   ready to submit"))
        if t.row_count:
            t.move_cursor(row=min(keep, t.row_count - 1))
            self.show_detail()
        else:
            why = self.job.get("hold_reason") or self.job.get("error") or ""
            self.query_one("#detail", Static).update(Group(
                Text(why, style="yellow") if why else Text(""), Text(""),
                Text("Jobsmith hasn't drafted answers for this one yet. Press s to fill it in the browser; "
                     "it comes back here if anything needs you.", style=STEEL)))

    @on(DataTable.RowHighlighted, "#qs")
    def picked_q(self, _e) -> None:
        self.show_detail()

    def current(self) -> dict | None:
        t = self.query_one("#qs", DataTable)
        if not t.row_count:
            return None
        key = str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)
        return next((x for x in self.drafts if str(x["id"]) == key), None)

    def show_detail(self) -> None:
        x = self.current()
        if not x:
            return
        val = x.get("final_answer") or x.get("answer") or ""
        parts = [Text(x["label"], style="bold"), Text("")]
        parts.append(Text(val or "(empty)", style=INK if val else "italic " + DIM))
        meta = []
        if x.get("rationale"):
            meta.append(x["rationale"])
        if x.get("confidence") is not None and x["kind"] in ("generated", "voice", "agent"):
            meta.append(f"{round((x['confidence'] or 0) * 100)}% confident")
        if meta:
            parts += [Text(""), Text(" · ".join(meta), style=DIM)]
        for i in x.get("issues") or []:
            parts.append(Text(f"! {i}", style="yellow"))
        if x.get("facts"):
            parts += [Text(""), Text("Based on", style=DIM)] + [Text(f"  {f.get('text', '')[:140]}", style=DIM) for f in x["facts"][:4]]
        self.query_one("#detail", Static).update(Group(*parts))

    def action_switch(self) -> None:
        (self.query_one("#qs") if self.focused and self.focused.id == "jobs" else self.query_one("#jobs")).focus()

    def action_approve(self) -> None:
        x = self.current()
        if x:
            r = self.send("PUT", f"/api/drafts/{x['id']}", {"verdict": "green"})
            self.notify(r["error"], severity="warning") if r.get("error") else self.load_job(self.job["id"])

    def action_edit(self) -> None:
        x = self.current()
        if not x:
            return

        def saved(text: str | None) -> None:
            if text is not None:
                r = self.send("PUT", f"/api/drafts/{x['id']}", {"final_answer": text, "verdict": "green"})
                self.notify(r["error"], severity="warning") if r.get("error") else self.load_job(self.job["id"])
        self.app.push_screen(EditAnswer(x["label"], x.get("final_answer") or x.get("answer") or ""), saved)

    def action_submit(self) -> None:
        if not self.job:
            return
        jid = self.job["id"]
        rd = self.get(f"/api/jobs/{jid}").get("readiness") or {}
        if not self.drafts:
            r = self.send("POST", f"/api/jobs/{jid}/fill", {"submit": False})
            self.notify(f"Filling {self.job['company']}. It comes back here when it's ready." if not r.get("error") else str(r["error"]))
            return
        if rd.get("blockers"):
            self.notify(f"{len(rd['blockers'])} still to check: {rd['blockers'][0]}", severity="warning", timeout=6)
            return
        live = {t["job_id"] for t in self.get("/api/live").get("tabs", [])}
        r = self.send("POST", f"/api/live/{jid}/submit", timeout=120) if jid in live else self.send("POST", f"/api/jobs/{jid}/fill", {"submit": True})
        if r.get("error"):
            self.notify(str(r["error"]), severity="warning")
        else:
            self.notify(f"Submitting to {self.job['company']}.")
            self.app.say(f"Submitting to [b]{self.job['company']}[/] ({self.job['title']}).")
        self.load_jobs()

    def action_skip(self) -> None:
        if self.job:
            self.send("POST", f"/api/jobs/{self.job['id']}/status", {"status": "skipped"})
            self.notify(f"Skipped {self.job['company']}.")
            self.job = {}
            self.load_jobs()

    def action_takeover(self) -> None:
        if self.job:
            r = self.send("POST", f"/api/live/{self.job['id']}/show")
            self.notify("Opened it in a window." if r.get("ok") else "It isn't open in the browser right now. Press s to fill it again.")

    def action_code(self) -> None:
        if self.job:
            self.app.ask_code(self.job["id"], self.job["company"])


class Matches(View):
    BINDINGS = View.BINDINGS + [Binding("enter", "apply", "Apply"), Binding("f", "fill", "Fill, don't submit"),
                                Binding("x", "skip", "Not for me"), Binding("o", "open", "Open posting")]

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        t = DataTable(id="m", classes="panel", cursor_type="row")
        t.border_title = "Best matches"
        yield t
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#m", DataTable).add_columns("Fit", "Company", "Role", "Where", "Pay", "Posted")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        rows = self.get("/api/jobs", status="new,fetched,drafted", limit=80).get("jobs", [])
        self.app.call_from_thread(self.show, rows)

    def show(self, rows: list[dict]) -> None:
        from .ask import ago
        t = self.query_one("#m", DataTable)
        t.clear()
        self.rows = {r["id"]: r for r in rows}
        for j in rows:
            fit = round(j.get("fit_score") or 0)
            t.add_row(Text(f"{fit:>3}", style=EMBER if fit >= 70 else INK if fit >= 50 else DIM), Text(j["company"][:22], style="bold"),
                      j["title"][:46], (j.get("locations") or [""])[0][:22], j.get("pay") or "", ago(j.get("date_posted")), key=j["id"])
        self.query_one("#t", Static).update(self.heading((f"Matches  {len(rows)}", "bold"), ("   enter apply · f fill only · x not for me · o open · esc back", DIM)))
        t.focus()

    def sel(self) -> dict | None:
        t = self.query_one("#m", DataTable)
        if not t.row_count:
            return None
        return self.rows.get(str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value))

    def action_apply(self) -> None:
        if j := self.sel():
            r = self.send("POST", "/api/jobs/batch", {"action": "autopilot", "ids": [j["id"]]})
            self.notify(f"Applying to {j['company']}." if r.get("started") else f"Couldn't start: {r.get('error') or 'already running'}")
            self.app.say(f"Applying to [b]{j['company']}[/] · {j['title']}")

    def action_fill(self) -> None:
        if j := self.sel():
            self.send("POST", "/api/jobs/batch", {"action": "fill", "ids": [j["id"]]})
            self.notify(f"Filling {j['company']}; it'll wait in /review.")

    def action_skip(self) -> None:
        if j := self.sel():
            self.send("POST", f"/api/jobs/{j['id']}/verdict", {"verdict": "red"})
            self.load()

    def action_open(self) -> None:
        if j := self.sel():
            webbrowser.open(j.get("url") or f"{self.app.base}/#/job/{j['id']}")


class Outreach(View):
    """People you know at companies you're applying to. Draft, copy, mark sent. Jobsmith never sends."""
    BINDINGS = View.BINDINGS + [Binding("r", "draft('referral')", "Referral ask"), Binding("n", "draft('recruiter')", "Recruiter note"),
                                Binding("y", "copy", "Copy"), Binding("s", "sent", "I sent it")]

    def __init__(self, company: str = ""):
        super().__init__()
        self.company = company.lower()

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        with Horizontal():
            t = DataTable(id="p", classes="panel", cursor_type="row")
            t.border_title = "People you know"
            yield t
            with VerticalScroll(classes="panel detail"):
                yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#p", DataTable).add_columns("Company", "Person", "Role", "")
        self.last: dict = {}
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        self.app.call_from_thread(self.show, self.get("/api/outreach"))

    def show(self, d: dict) -> None:
        t = self.query_one("#p", DataTable)
        keep = t.cursor_row
        t.clear()
        self.rows = {}
        for c in d.get("companies", []):
            if self.company and self.company not in c["company"].lower():
                continue
            for p in c["people"]:
                name = f"{p['first_name']} {p['last_name']}".strip()
                dr = next((x for x in c["drafts"] if x["person"] == name), None)
                k = f"{c['job_id']}|{name}"
                self.rows[k] = {"company": c["company"], "job_id": c["job_id"], "person": p, "draft": dr}
                status = Text("sent", style="green") if dr and dr["sent_at"] else Text("drafted", style=EMBER) if dr else Text("")
                t.add_row(Text(c["company"][:22], style="bold"), name, (p.get("position") or "")[:34], status, key=k)
        self.query_one("#t", Static).update(self.heading(("Outreach", "bold"), ("   r referral ask · n recruiter note · y copy · s I sent it · esc back", DIM)))
        if not self.rows:
            self.query_one("#detail", Static).update(Text("No connections at the companies you're applying to." +
                                                          ("" if d.get("network") else " Add your LinkedIn export with /web → Profile."), style=DIM))
            return
        t.move_cursor(row=min(keep, t.row_count - 1))
        t.focus()
        self.show_detail()

    def sel(self) -> dict | None:
        t = self.query_one("#p", DataTable)
        if not t.row_count:
            return None
        return self.rows.get(str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value))

    @on(DataTable.RowHighlighted)
    def show_detail(self, _e=None) -> None:
        r = self.sel()
        if not r:
            return
        dr = self.last if self.last.get("person") == f"{r['person']['first_name']} {r['person']['last_name']}".strip() else r["draft"]
        body = [Text(f"{r['person']['first_name']} {r['person']['last_name']}", style="bold"),
                Text(f"{r['person'].get('position') or ''} at {r['company']}", style=DIM), Text("")]
        body.append(Text(dr["text"]) if dr else Text("Press r for a referral ask or n for a note to a recruiter.", style=DIM))
        if dr:
            body += [Text(""), Text("y copies it. Jobsmith never sends messages; press s once you've sent it yourself.", style=DIM)]
        self.query_one("#detail", Static).update(Group(*body))

    @work(thread=True)
    def action_draft(self, kind: str) -> None:
        r = self.sel()
        if not r:
            return
        self.app.call_from_thread(self.query_one("#detail", Static).update, Text("Drafting…", style=EMBER))
        d = self.send("POST", "/api/outreach/draft", {"job_id": r["job_id"], "person": r["person"], "kind": kind}, timeout=120)
        self.last = d if not d.get("error") else {}
        self.app.call_from_thread(self.load)

    def _draft(self) -> dict | None:
        r = self.sel()
        if not r:
            return None
        name = f"{r['person']['first_name']} {r['person']['last_name']}".strip()
        return self.last if self.last.get("person") == name else r["draft"]

    def action_copy(self) -> None:
        if d := self._draft():
            self.app.copy_to_clipboard(d["text"])
            self.notify("Copied. Paste it into LinkedIn or email.")

    def action_sent(self) -> None:
        if (d := self._draft()) and d.get("id"):
            self.send("POST", f"/api/outreach/{d['id']}/sent", {"sent": True})
            self.last = {}
            self.load()


class Followups(View):
    BINDINGS = View.BINDINGS + [Binding("y", "copy", "Copy"), Binding("d", "mark('done')", "Done"), Binding("z", "mark('snooze')", "Snooze a week")]

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        with Horizontal():
            t = DataTable(id="f", classes="panel", cursor_type="row")
            t.border_title = "Gone quiet"
            yield t
            with VerticalScroll(classes="panel detail"):
                yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#f", DataTable).add_columns("Company", "Role", "Quiet")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        self.app.call_from_thread(self.show, self.get("/api/followups"))

    def show(self, b: dict) -> None:
        t = self.query_one("#f", DataTable)
        t.clear()
        self.rows = {q["id"]: q for q in b.get("quiet", [])}
        for q in b.get("quiet", []):
            t.add_row(Text(q["company"], style="bold"), q["title"][:44], f"{q['days']} days", key=q["id"])
        self.query_one("#t", Static).update(self.heading((f"Follow-ups  {len(self.rows)} due", "bold"),
                                                       (f"   {b.get('waiting', 0)} waiting on a reply · y copy · d done · z snooze · esc back", DIM)))
        if not self.rows:
            self.query_one("#detail", Static).update(Text("Nothing has gone quiet long enough to follow up.", style=DIM))
            return
        t.focus()
        self.show_detail()

    def sel(self) -> dict | None:
        t = self.query_one("#f", DataTable)
        return self.rows.get(str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)) if t.row_count else None

    @on(DataTable.RowHighlighted)
    def show_detail(self, _e=None) -> None:
        if q := self.sel():
            self.query_one("#detail", Static).update(Group(Text(f"{q['company']} · {q['title']}", style="bold"), Text(""), Text(q["draft"])))

    def action_copy(self) -> None:
        if q := self.sel():
            self.app.copy_to_clipboard(q["draft"])
            self.notify("Copied. Send it to the recruiter or the email that confirmed your application.")

    def action_mark(self, action: str) -> None:
        if q := self.sel():
            self.send("POST", f"/api/followups/{q['id']}", {"action": action})
            self.load()


class Settings(View):
    """The settings that matter most, changed with a key press."""
    BINDINGS = View.BINDINGS + [Binding("enter", "change", "Change")]
    ROWS = [
        ("llm_backend", "AI that writes", ["auto", "gemini", "smith", "anthropic", "openai", "none"]),
        ("gemini_api_key", "Gemini key", None),
        ("anthropic_api_key", "Claude key", None),
        ("openai_api_key", "OpenAI key", None),
        ("autonomy", "Mode", ["autopilot", "copilot"]),
        ("min_fit_score", "Apply when fit is at least", ["30", "40", "50", "60", "70"]),
        ("autopilot_min_confidence", "Submit when answers are at least", ["0.6", "0.7", "0.8", "0.9"]),
        ("battery_saver", "Battery saver", ["true", "false"]),
    ]

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        t = DataTable(id="s", classes="panel", cursor_type="row")
        t.border_title = "Settings"
        yield t
        yield Static(Text("  Email, LinkedIn and the extension are set up on the dashboard: /web", style=DIM))
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#s", DataTable).add_columns("Setting", "Now", "")
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        self.app.call_from_thread(self.show, self.get("/api/settings"))

    def show(self, s: dict) -> None:
        self.s = s
        t = self.query_one("#s", DataTable)
        keep = t.cursor_row
        t.clear()
        for k, label, opts in self.ROWS:
            v = s.get(k)
            shown = ("set" if v else "not set") if opts is None else str(v if v not in (None, "") else "auto")
            if k == "autopilot_min_confidence" and v not in (None, ""):
                shown = f"{round(float(v) * 100)}% confident"
            t.add_row(Text(label, style="bold"), Text(shown, style=EMBER if opts is None and v else INK), Text("enter to change", style=DIM), key=k)
        t.move_cursor(row=min(keep, t.row_count - 1))
        t.focus()
        self.query_one("#t", Static).update(self.heading(("Settings", "bold"), ("   enter change · esc back", DIM)))

    def action_change(self) -> None:
        t = self.query_one("#s", DataTable)
        key = str(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)
        k, label, opts = next(r for r in self.ROWS if r[0] == key)
        if opts is None:
            def got(v: str) -> None:
                if v:
                    self.send("PUT", "/api/settings", {k: v})
                    self.notify(f"{label} saved on this computer.")
                    self.load()
            self.app.push_screen(AskLine(f"Paste your {label} (hidden as you type). It stays on this computer.", "", password=True), got)
            return
        cur = str(self.s.get(k) if self.s.get(k) not in (None, "") else opts[0])
        nxt = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
        val = {"true": True, "false": False}.get(nxt, nxt)
        if k in ("min_fit_score",):
            val = int(nxt)
        elif k == "autopilot_min_confidence":
            val = float(nxt)
        self.send("PUT", "/api/settings", {k: val})
        self.load()


class Board(View):
    """Everything at once: applying now, what needs you, and the bell."""
    BINDINGS = [Binding("escape", "app.pop_screen", "Back"), Binding("ctrl+o", "app.pop_screen", "Back", show=False),
                Binding("w", "watch", "Watch"), Binding("t", "takeover", "Take over"), Binding("r", "app.open_review", "Review")]

    def compose(self) -> ComposeResult:
        yield Static("", classes="title", id="t")
        with Horizontal():
            live = DataTable(id="live", classes="panel", cursor_type="row")
            live.border_title = "Applying now"
            live.styles.width = "3fr"
            yield live
            with Vertical():
                needs = DataTable(id="needs", classes="panel", cursor_type="row")
                needs.border_title = "Needs you"
                yield needs
                bell = DataTable(id="bell", classes="panel", cursor_type="row")
                bell.border_title = "Bell"
                yield bell
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#live", DataTable).add_columns("", "Company", "Role", "Progress", "Now")
        self.query_one("#needs", DataTable).add_columns("", "Company", "Why")
        self.query_one("#bell", DataTable).add_columns("", "What", "When")
        self.paint()
        self.set_interval(0.5, self.paint)

    def paint(self) -> None:
        st, live, home, notes = (self.app.state.get(k, {}) for k in ("st", "live", "home", "notes"))
        live = live or []
        tabs = {t["job_id"]: t for t in live}
        rows = list(dict.fromkeys(list((st or {}).get("active", {})) + list(tabs)))
        t = self.query_one("#live", DataTable)
        keep = t.cursor_row
        t.clear()
        for jid in rows:
            tab = tabs.get(jid, {})
            pr = (st.get("progress") or {}).get(jid) or {"step": 0, "total": 5, "label": ""}
            ph = tab.get("phase") or st["active"].get(jid, "")
            mark = (Text("✓", style="green") if ph == "submitted" else Text("!", style="yellow") if ph in ("code", "review", "error")
                    else Text(SPIN[self.app.frame % len(SPIN)], style=EMBER))
            company, title = self.app.job_name(jid, tab)
            t.add_row(mark, Text(company, style="bold"), title[:40], bar(pr["step"], pr["total"]),
                      (pr.get("label") or tab.get("phase_label") or "")[:30], key=jid)
        if not rows:
            t.add_row("", Text("Nothing running.", style=DIM), "", "", "")
        t.move_cursor(row=min(keep, max(0, t.row_count - 1)))
        n = self.query_one("#needs", DataTable)
        k2 = n.cursor_row
        n.clear()
        for r in (home or {}).get("review", [])[:30]:
            n.add_row(Text("!", style="yellow"), Text(r["company"], style="bold"), (r.get("hold_reason") or r.get("error") or "ready")[:60], key=r["id"])
        n.move_cursor(row=min(k2, max(0, n.row_count - 1)))
        b = self.query_one("#bell", DataTable)
        k3 = b.cursor_row
        b.clear()
        for it in (notes or {}).get("items", [])[:30]:
            mark = Text("●", style=EMBER) if it.get("urgent") else Text("•", style=EMBER if it.get("unread") else FAINT)
            b.add_row(mark, it["title"][:60], time.strftime("%I:%M", time.localtime(it["at"])).lstrip("0") if it.get("at") else "", key=it["id"])
        b.move_cursor(row=min(k3, max(0, b.row_count - 1)))
        self.query_one("#t", Static).update(self.heading(("Board", "bold"), ("   live from your engine · r review · w watch · t take over · esc back", DIM)))

    def _jid(self) -> str:
        f = self.focused
        if isinstance(f, DataTable) and f.row_count:
            k = str(f.coordinate_to_cell_key(f.cursor_coordinate).row_key.value)
            return k.split(":")[1] if ":" in k else k
        return ""

    def action_watch(self) -> None:
        if jid := self._jid():
            webbrowser.open(f"{self.app.base}/#/watch/{jid}")

    def action_takeover(self) -> None:
        if jid := self._jid():
            self.send("POST", f"/api/live/{jid}/show")


# =========================================================================== the conversation
class Prompt(Input):
    """The input box: ↑/↓ walk your history, tab completes a /command."""
    BINDINGS = [Binding("up", "older", show=False), Binding("down", "newer", show=False), Binding("tab", "complete", show=False)]

    def __init__(self, **kw):
        super().__init__(**kw)
        self.history: list[str] = []
        self.pos = 0

    def action_older(self) -> None:
        if self.app.menu_items and self.value.startswith("/"):
            self.app.menu_move(-1)
            return
        if self.history and self.pos > 0:
            self.pos -= 1
            self.value = self.history[self.pos]
            self.cursor_position = len(self.value)

    def action_newer(self) -> None:
        if self.app.menu_items and self.value.startswith("/"):
            self.app.menu_move(1)
            return
        if self.pos < len(self.history) - 1:
            self.pos += 1
            self.value = self.history[self.pos]
        else:
            self.pos = len(self.history)
            self.value = ""
        self.cursor_position = len(self.value)

    def action_complete(self) -> None:
        if self.app.menu_items:
            name = self.app.menu_items[self.app.menu_sel][0]
            self.value = name + " "
            self.cursor_position = len(self.value)


class Jobsmith(App):
    TITLE = "jobsmith"
    CSS = f"""
    Screen {{ background: {BG}; color: #c3ccdd; layers: base; }}
    #chat {{ height: 1fr; padding: 0 1; scrollbar-size-vertical: 1; scrollbar-color: {FAINT}; scrollbar-background: {BG}; }}
    #welcome {{ height: auto; border: round {EMBER_LO}; border-title-color: {EMBER}; border-title-style: bold; padding: 0 1; margin: 1 0; }}
    #logo {{ width: 21; height: 5; }}
    #hello {{ width: 1fr; height: auto; padding-left: 1; }}
    .you {{ color: {STEEL}; background: #111a2e; padding: 0 1; margin-top: 1; }}
    .blk {{ height: auto; }}
    .gap {{ margin-top: 1; }}
    #think {{ height: auto; padding: 0 1; display: none; }}
    #live {{ height: auto; padding: 0 1; display: none; }}
    #menu {{ height: auto; padding: 0 2; display: none; }}
    #prompt {{ height: 3; border: round #2b3a5c; background: {BG}; margin: 0 1; padding: 0 1; }}
    #prompt:focus {{ border: round {STEEL}; }}
    #status {{ height: 1; padding: 0 2; }}
    """
    BINDINGS = [
        Binding("shift+tab", "autopilot", "Autopilot", priority=True, show=False),
        Binding("ctrl+o", "board", "Board", priority=True, show=False),
        Binding("ctrl+c", "ctrl_c", "Quit", priority=True, show=False),
        Binding("escape", "escape", show=False),
    ]

    def __init__(self, base: str, splash: bool = True, start: str = ""):
        super().__init__()
        self.start = start
        self.base = base.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=8)
        self.frame = 0
        self.state: dict = {}
        self.phases: dict[str, str] = {}
        self.splash = splash
        self.busy_since = 0.0
        self.verb = random.choice(VERBS)
        self.cancel = False
        self.menu_items: list[tuple[str, str, str]] = []
        self.menu_sel = 0
        self.ctrl_c_at = 0.0
        self.strike = 0
        self.connected = None

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat"):
            with Horizontal(id="welcome"):
                yield Static(logo_text(0), id="logo")
                yield Static("", id="hello")
        yield Static("", id="think")
        yield Static("", id="live")
        yield Static("", id="menu")
        yield Prompt(placeholder='Ask about your job hunt, or tell it where to apply.  Try "what needs me?"', id="prompt")
        yield Static("", id="status")

    def on_mount(self) -> None:
        from . import __version__
        self.query_one("#welcome").border_title = f" jobsmith v{__version__} "
        self.paint_hello()
        self.query_one("#prompt", Prompt).focus()
        self.refresh_data()
        self.set_interval(1.5, self.refresh_data)
        self.set_interval(0.1, self.animate)
        self.strike = 6                                   # the hammer comes down a few times to say hello
        if self.splash and not self.start:
            self.push_screen(Splash())
        if self.start == "review":
            self.push_screen(Review())
        elif self.start == "matches":
            self.push_screen(Matches())
        elif self.start == "show":
            self.show_autopilot()

    def paint_hello(self) -> None:
        st, home = self.state.get("st", {}), self.state.get("home", {})
        name = home.get("first_name") or ""
        on = bool(st.get("auto", {}).get("on")) and st.get("autonomy") != "copilot"
        bits = [f"{home.get('applied_today', 0)} sent today", f"{home.get('applied_week', 0)} this week"]
        if st.get("needs_you"):
            bits.append(f"{st['needs_you']} need you")
        nxt = home.get("next_run")
        more = []
        if on and nxt:
            more.append("next run " + time.strftime("%I:%M %p", time.localtime(nxt)).lstrip("0"))
        if home.get("queued"):
            more.append(f"{home['queued']} good matches queued")
        # The practice copy's profile is the made-up Alex Rivera: say so, so nobody thinks it's their own data
        hello = ("Welcome to the practice copy. You're Alex Rivera, a made-up student." if st.get("demo")
                 else f"Welcome back{', ' + name if name else ''}!")
        t = Text.assemble((hello, "bold"), "\n",
                          ("Autopilot " + ("on" if on else "off"), EMBER if on else STEEL), (" · " + " · ".join(bits) if home else "", STEEL), "\n",
                          (" · ".join(more), DIM), "\n",
                          ("Ask anything about your job hunt, or say where to apply.", INK), "\n",
                          ("/help", EMBER), (" commands · ", DIM), ("shift+tab", EMBER), (" autopilot · ", DIM), ("ctrl+o", EMBER), (" board", DIM),
                          ("   practice copy" if st.get("demo") else "", EMBER))
        self.query_one("#hello", Static).update(t)

    # ------------------------------------------------------------------ the conversation
    def mount_block(self, renderable, classes: str = "blk") -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(renderable, classes=classes))
        chat.scroll_end(animate=False)

    def you(self, text: str) -> None:
        self.mount_block(Text.assemble(("> ", DIM), (text, INK)), "you")

    def say(self, markup: str) -> None:
        self.mount_block(Text.assemble(("⏺ ", EMBER), Text.from_markup(markup)), "blk gap")

    def render_block(self, b: dict, first: bool) -> Text | Table:
        t = b.get("t")
        lead = ("  ⎿  " if first else "     ", DIM)
        if t == "head":
            title, _, count = b["text"].partition("  ")
            return Text.assemble(("⏺ ", EMBER), (title, "bold"), (f"  {count}" if count else "", STEEL))
        if t == "item":
            mark = ("! ", "yellow") if b.get("urgent") else (SPIN[self.frame % len(SPIN)] + " ", EMBER) if b.get("live") else ("", "")
            return Text.assemble(lead, mark, (b["text"], "bold " + INK), ("  " + b.get("meta", ""), STEEL) if b.get("meta") else "")
        if t == "stat":
            return Text.assemble(lead, (f"{b['text']:>5}", f"bold {EMBER}"), ("  " + b.get("meta", ""), INK))
        if t == "qa":
            return Text.assemble(lead, (b["text"], "bold"), "\n", ("       " + b.get("meta", "").replace("\n", "\n       "), STEEL))
        if t == "example":
            return Text.assemble(lead, ("“" + b["text"] + "”", EMBER_HI))
        if t == "hint":
            return Text.assemble(("     ", ""), ("› " + b["text"], DIM))
        return Text.assemble(lead, (b.get("text", ""), STEEL))

    def start_busy(self) -> None:
        self.busy_since = time.time()
        self.verb = random.choice(VERBS)
        self.cancel = False
        self.query_one("#think").display = True

    def stop_busy(self) -> None:
        self.busy_since = 0
        self.query_one("#think").display = False

    @work(thread=True, group="ask")
    def ask(self, text: str) -> None:
        self.call_from_thread(self.start_busy)
        n, t0 = 0, time.time()
        self._last_t = ""
        try:
            with self.http.stream("POST", "/api/ask", json={"text": text}, timeout=30) as r:
                for line in r.iter_lines():
                    if self.cancel:
                        break
                    if not line.strip():
                        continue
                    b = json.loads(line)
                    is_first = b["t"] != "head" and n and self._last_t == "head"
                    self._last_t = b["t"]
                    self.call_from_thread(self.mount_block, self.render_block(b, bool(is_first)),
                                          "blk gap" if b["t"] == "head" else "blk")
                    n += 1
                    time.sleep(0.035 if b["t"] != "head" else 0.12)   # let the answer build up, quickly
        except (httpx.HTTPError, ValueError) as e:
            self.call_from_thread(self.say, f"[yellow]Couldn't reach Jobsmith's engine ({e.__class__.__name__}). Is it running?[/]")
        self.call_from_thread(self.stop_busy)
        if self.cancel:
            self.call_from_thread(self.mount_block, Text("  ⎿  Interrupted", style=DIM))
        elif n:
            self.call_from_thread(self.mount_block, Text(f"     {time.time() - t0:.1f}s · from your records, no AI", style=FAINT))

    _last_t = ""

    @work(thread=True, group="cmd")
    def show_autopilot(self) -> None:
        """`jobsmith demo show`: the practice engine plays three made-up applications; this app draws them as usual."""
        time.sleep(1.5)                                   # let the welcome box draw first
        self.call_from_thread(self.say, "[b]Practice copy:[/] showing autopilot on 3 made-up applications. "
                                        "Nothing real is opened, sent or written by an AI.")
        try:
            r = self.http.post("/api/demo/autopilot-show", json={}, timeout=10)
            ok, why = r.status_code == 200, (r.json().get("detail") if r.status_code != 200 else "")
        except (httpx.HTTPError, ValueError) as e:
            ok, why = False, e.__class__.__name__
        if not ok:
            self.call_from_thread(self.say, f"[yellow]Couldn't start the show: {why}[/]")

    @work(thread=True, group="cmd")
    def run_request(self, text: str) -> None:
        self.call_from_thread(self.start_busy)
        try:
            if text == "/sync":
                r = self.http.post("/api/sources/sync", timeout=600).json()
                lines = [f"{x.get('source', '')}: {x.get('error') or str(x.get('added', 0)) + ' new'}" for x in r.get("results", [])]
            else:
                r = self.http.post("/api/command", json={"text": text}, timeout=600).json()
                lines = r.get("log", []) or [r.get("detail", "Done.")]
        except (httpx.HTTPError, ValueError) as ex:
            lines = [f"[yellow]{ex}[/]"]
        self.call_from_thread(self.stop_busy)
        for i, line in enumerate(lines):
            self.call_from_thread(self.mount_block, Text.assemble(("  ⎿  " if i == 0 else "     ", DIM), Text.from_markup(str(line))))
            time.sleep(0.04)

    # ------------------------------------------------------------------ input
    @on(Input.Changed, "#prompt")
    def typing(self, e: Input.Changed) -> None:
        v = e.value
        if v == "?":
            e.input.value = ""
            self.show_help(short=True)
            return
        if v.startswith("/") and " " not in v:
            self.menu_items = [c for c in COMMANDS if c[0].startswith(v.lower())][:9]
            self.menu_sel = 0
        else:
            self.menu_items = []
        self.paint_menu()

    def menu_move(self, d: int) -> None:
        self.menu_sel = (self.menu_sel + d) % max(1, len(self.menu_items))
        self.paint_menu()

    def paint_menu(self) -> None:
        m = self.query_one("#menu", Static)
        if not self.menu_items:
            m.display = False
            return
        t = Text()
        for i, (name, args, what) in enumerate(self.menu_items):
            on_ = i == self.menu_sel
            t.append(f"{name:<12}", style=f"bold {EMBER}" if on_ else INK)
            t.append(f"{args:<26}", style=STEEL if on_ else DIM)
            t.append(what + ("\n" if i < len(self.menu_items) - 1 else ""), style=INK if on_ else DIM)
        m.update(t)
        m.display = True

    @on(Input.Submitted, "#prompt")
    def submitted(self, e: Input.Submitted) -> None:
        text = e.value.strip()
        if self.menu_items and text.startswith("/") and " " not in text and text not in [c[0] for c in COMMANDS]:
            text = self.menu_items[self.menu_sel][0]     # enter on a highlighted menu item runs it
        p = self.query_one("#prompt", Prompt)
        p.value = ""
        self.menu_items = []
        self.paint_menu()
        if not text:
            return
        p.history.append(text)
        p.pos = len(p.history)
        self.you(text)
        if text.startswith("/"):
            self.slash(text)
            return
        from .ask import is_question
        if is_question(text):
            self.ask(text)
        else:
            self.run_request(text)

    def slash(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        arg = arg.strip()
        cmd = cmd.lower()
        if cmd in ("/q", "/quit", "/exit"):
            self.exit()
        elif cmd in ("/help", "/?", "/commands"):
            self.show_help()
        elif cmd == "/clear":
            for w in list(self.query_one("#chat").children)[1:]:
                w.remove()
        elif cmd == "/review":
            self.action_open_review()
        elif cmd == "/matches":
            self.push_screen(Matches())
        elif cmd == "/apply":
            self.run_request(arg if arg.lower().startswith(("apply", "http")) else f"apply to {arg}") if arg else \
                self.say("Say where: [b]/apply nvidia hardware internships[/], a job link, or a GitHub list. Or /matches.")
        elif cmd == "/autopilot":
            self.set_autopilot(None if not arg else arg != "off")
        elif cmd == "/stop":
            r = self._post("/api/stop", {"everything": True})
            self.say(f"[b]Stopped everything[/]: {r.get('stopped', 0)} applications, the browser" + (", smith" if r.get("unloaded") else "") + ". Autopilot is off.")
        elif cmd == "/code":
            self.ask_code(self._find(arg, need="code"), arg)
        elif cmd in ("/takeover", "/watch"):
            jid = self._find(arg)
            if not jid:
                self.say("Nothing is open right now." if not arg else f"No open application at {arg}.")
            elif cmd == "/watch":
                webbrowser.open(f"{self.base}/#/watch/{jid}")
                self.say("Opened the live view in your browser.")
            else:
                r = self._post(f"/api/live/{jid}/show")
                self.say("Opened it in a window for you." if r.get("ok") else "[yellow]It isn't open in the browser now.[/]")
        elif cmd == "/outreach":
            self.push_screen(Outreach(arg))
        elif cmd == "/followups":
            self.push_screen(Followups())
        elif cmd == "/voice":
            self.voice(arg)
        elif cmd == "/resume":
            self.upload(arg, "/api/profile/upload", "resume")
        elif cmd == "/settings":
            self.push_screen(Settings())
        elif cmd == "/key":
            self.key(arg)
        elif cmd == "/sync":
            self.run_request("/sync")
        elif cmd in ("/board", "/panels"):
            self.action_board()
        elif cmd == "/skills":
            self.skills()
        elif cmd in ("/web", "/dashboard"):
            webbrowser.open(self.base)
            self.say(f"Opened the dashboard: {self.base}")
        else:
            close = [c[0] for c in COMMANDS if c[0].startswith(cmd[:3])]
            self.say(f"[{STEEL}]No command {cmd}." + (f" Did you mean {', '.join(close)}?" if close else " /help lists them.") + "[/]")

    def show_help(self, short: bool = False) -> None:
        if short:
            self.mount_block(Text.assemble(("  shift+tab ", EMBER), ("autopilot on/off   ", DIM), ("ctrl+o ", EMBER), ("board   ", DIM),
                                           ("/ ", EMBER), ("commands   ", DIM), ("↑ ", EMBER), ("history   ", DIM), ("esc ", EMBER), ("cancel   ", DIM),
                                           ("ctrl+c ", EMBER), ("twice to quit", DIM)), "blk gap")
            return
        self.say("[b]Ask[/] anything about your job hunt. Answers come from your records, instantly, with no AI:")
        from .ask import EXAMPLES
        for i, ex in enumerate(EXAMPLES[:6]):
            self.mount_block(Text.assemble(("  ⎿  " if i == 0 else "     ", DIM), ("“" + ex + "”", EMBER_HI)))
        self.say("[b]Tell it where to apply[/]: a company and role, a job link, or a GitHub list.")
        t = Table.grid(padding=(0, 2))
        t.add_column(style=EMBER, no_wrap=True)
        t.add_column(style=STEEL, no_wrap=True)
        t.add_column(style=INK)
        for name, args, what in COMMANDS:
            t.add_row(name, args, what)
        self.mount_block(t, "blk gap")
        self.show_help(short=True)

    # ------------------------------------------------------------------ commands that answer in the conversation
    def _post(self, path: str, body: dict | None = None, timeout: float = 60) -> dict:
        try:
            r = self.http.post(path, json=body or {}, timeout=timeout)
            return r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e)}

    def _find(self, company: str, need: str = "") -> str:
        """An application that's open in the browser, by company (or the first one waiting, if none named)."""
        tabs = self.state.get("live", []) or []
        if company:
            tabs = [t for t in tabs if company.lower() in (t.get("company") or "").lower()]
        if need == "code":
            tabs = [t for t in tabs if t.get("needs_code")] or tabs
        return tabs[0]["job_id"] if tabs else ""

    def ask_code(self, jid: str, company: str = "") -> None:
        if not jid:
            self.say(f"[{STEEL}]Nothing is waiting for a code.[/]")
            return
        name = next((t.get("company") for t in self.state.get("live", []) if t["job_id"] == jid), company or "The company")

        def got(code: str) -> None:
            if code:
                r = self._post(f"/api/live/{jid}/code", {"code": code})
                self.say("Code entered" + (" and submitted." if r.get("submitted") else ".") if r.get("ok") else f"[yellow]{r.get('message') or r.get('error')}[/]")
        self.push_screen(AskLine(f"[b]{name}[/] emailed you a code. Paste it and press enter.", "the code"), got)

    def key(self, provider: str) -> None:
        field = {"gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "claude": "anthropic_api_key", "openai": "openai_api_key"}.get(provider.lower())
        if not field:
            self.say("Which one? [b]/key gemini[/] (free at aistudio.google.com/apikey), [b]/key anthropic[/] or [b]/key openai[/].")
            return

        def got(v: str) -> None:
            if v:
                self._put_settings({field: v, "llm_backend": provider.lower().replace("claude", "anthropic")})
                self.say(f"Saved your {provider} key on this computer. Jobsmith writes with it now.")
        self.push_screen(AskLine(f"Paste your {provider} key. It's hidden as you type and stays on this computer.", "", password=True), got)

    def _put_settings(self, body: dict) -> dict:
        try:
            return self.http.put("/api/settings", json=body).json()
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e)}

    @work(thread=True)
    def upload(self, path: str, endpoint: str, what: str) -> None:
        if not path:
            self.call_from_thread(self.say, f"Give the file: [b]/{'resume' if what == 'resume' else 'voice add'} ~/Documents/{'resume.pdf' if what == 'resume' else 'essay.md'}[/]")
            return
        p = Path(path.strip("'\"")).expanduser()
        if not p.is_file():
            self.call_from_thread(self.say, f"[yellow]No file at {p}[/]")
            return
        self.call_from_thread(self.start_busy)
        try:
            with p.open("rb") as fh:
                r = self.http.post(endpoint, files={"file": (p.name, fh)}, timeout=300)
            d = r.json() if r.content else {}
            ok = r.status_code < 400
        except (httpx.HTTPError, ValueError) as e:
            d, ok = {"detail": str(e)}, False
        self.call_from_thread(self.stop_busy)
        if not ok:
            self.call_from_thread(self.say, f"[yellow]Couldn't read {p.name}: {d.get('detail')}[/]")
        elif what == "resume":
            n = d.get("facts_added")
            self.call_from_thread(self.say, f"Read [b]{p.name}[/]" + (f": {n} facts about you." if n else ".") + " Matches are re-scored.")
        else:
            self.call_from_thread(self.say, f"Added {d.get('added', 0)} passages from [b]{p.name}[/]. "
                                            f"{sum(1 for c in d.get('coverage', []) if c['have'])} of {len(d.get('coverage', []))} stories covered.")

    def voice(self, arg: str) -> None:
        if arg.startswith("add"):
            self.upload(arg[3:].strip(), "/api/voice/upload", "voice")
        else:
            self.ask("how is my voice")

    @work(thread=True)
    def skills(self) -> None:
        try:
            d = self.http.get("/api/skills").json()
        except (httpx.HTTPError, ValueError):
            d = {}
        items = d.get("skills", d) if isinstance(d, dict) else d
        self.call_from_thread(self.say, "[b]Skills[/]")
        for i, s in enumerate(items or []):
            status = "planned" if s.get("soon") else "on" if s.get("enabled") else "off"
            self.call_from_thread(self.mount_block, Text.assemble(("  ⎿  " if i == 0 else "     ", DIM), (f"{s['name']:<22}", "bold"),
                                                                  (f"{status:<9}", EMBER if status == "on" else DIM), (s["what"].split(". ")[0][:70], STEEL)))

    # ------------------------------------------------------------------ keys
    def set_autopilot(self, on: bool | None) -> None:
        if on is None:
            on = not (self.state.get("st", {}).get("auto", {}).get("on") and self.state.get("st", {}).get("autonomy") != "copilot")
        r = self._post("/api/autopilot", {"on": on})
        st = self.state.setdefault("st", {})
        st.setdefault("auto", {})["on"] = on
        st["autonomy"] = "autopilot" if on else "copilot"
        self.say("Autopilot [b]on[/]: it applies to your best matches on its own and holds anything it isn't sure about." if on else
                 "Autopilot [b]off[/]" + (f": stopped {r.get('stopped')} in progress." if r.get("stopped") else "."))
        self.paint_status()
        self.refresh_data()

    def action_autopilot(self) -> None:
        if isinstance(self.screen, (Splash,)):
            return
        self.set_autopilot(None)

    def action_board(self) -> None:
        if isinstance(self.screen, Board):
            self.pop_screen()
        elif not isinstance(self.screen, ModalScreen):
            self.push_screen(Board())

    def action_open_review(self) -> None:
        if isinstance(self.screen, Board):
            self.pop_screen()
        self.push_screen(Review())

    def action_escape(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        if self.busy_since:
            self.cancel = True
        elif self.menu_items:
            self.menu_items = []
            self.paint_menu()
        else:
            self.query_one("#prompt", Prompt).value = ""

    def action_ctrl_c(self) -> None:
        p = self.query_one("#prompt", Prompt)
        if self.screen is self.screen_stack[0] and p.value:
            p.value = ""
            return
        if time.time() - self.ctrl_c_at < 1.5:
            self.exit()
            return
        self.ctrl_c_at = time.time()
        self.paint_status()

    # ------------------------------------------------------------------ live data
    @work(thread=True, exclusive=True, group="poll")
    def refresh_data(self) -> None:
        try:
            st = self.http.get("/api/status").json()
            live = self.http.get("/api/live").json().get("tabs", [])
            home = self.http.get("/api/home").json()
            notes = self.http.get("/api/notifications").json()
        except (httpx.HTTPError, ValueError):
            self.call_from_thread(self.lost)
            return
        self.call_from_thread(self.apply_state, st, live, home, notes)

    def lost(self) -> None:
        if self.connected is not False:
            self.connected = False
            self.say(f"[yellow]Lost Jobsmith's engine at {self.base}. Retrying…[/]")
        self.paint_status()

    def apply_state(self, st: dict, live: list, home: dict, notes: dict) -> None:
        try:
            self._paint_state(st, live, home, notes)
        except NoMatches:          # the app is closing and its widgets are already gone: skip this update
            pass

    def _paint_state(self, st: dict, live: list, home: dict, notes: dict) -> None:
        if self.connected is False:
            self.say("[green]Back in touch with the engine.[/]")
        self.connected = True
        self.state = {"st": st, "live": live, "home": home, "notes": notes}
        tabs = {t["job_id"]: t for t in live}
        for jid in list(dict.fromkeys(list(st.get("active", {})) + list(tabs))):   # tell you when something changes
            tab = tabs.get(jid, {})
            ph = tab.get("phase") or st["active"].get(jid, "")
            if jid in self.phases and self.phases[jid] != ph:
                who = self.job_name(jid, tab)[0]
                msg = {"submitted": f"[b]{who}[/] [green]submitted ✓[/]", "code": f"[b]{who}[/] [yellow]emailed you a code[/] · /code",
                       "review": f"[b]{who}[/] [yellow]is filled and waiting for you[/] · /review", "error": f"[b]{who}[/] [yellow]couldn't finish[/] · /review"}.get(ph)
                if msg:
                    self.say(msg)
                    if ph == "submitted":
                        self.strike = 6
            self.phases[jid] = ph
        self.paint_hello()
        self.paint_status()

    def job_name(self, jid: str, tab: dict | None = None) -> tuple[str, str]:
        """Company and title for a job: from its browser tab, else the job record (before a tab exists), else the id."""
        tab = tab or {}
        rec = (self.state.get("st", {}).get("names") or {}).get(jid) or {}
        return (tab.get("company") or rec.get("company") or jid), (tab.get("title") or rec.get("title") or "")

    def paint_status(self) -> None:
        st, notes = self.state.get("st", {}), self.state.get("notes", {})
        on = bool(st.get("auto", {}).get("on")) and st.get("autonomy") != "copilot"
        left = Text.assemble(("⏵⏵ autopilot on", f"bold {EMBER}") if on else ("⏸ autopilot off", STEEL), (" (shift+tab to toggle)", DIM))
        right = []
        if time.time() - self.ctrl_c_at < 1.5:
            right = [("Press ctrl+c again to exit", "yellow")]
        else:
            if st.get("needs_you"):
                right += [(f"▲ {st['needs_you']} need you", "yellow"), ("  ", "")]
            if notes.get("unread"):
                right += [(f"● {notes['unread']} new", EMBER), ("  ", "")]
            if self.connected is False:
                right += [("engine offline", "red"), ("  ", "")]
            if st.get("demo"):
                right += [("practice copy", EMBER), ("  ", "")]
            right += [("? for shortcuts", DIM)]
        r = Text.assemble(*right)
        w = max(10, self.size.width - 4 - len(left) - len(r))
        self.query_one("#status", Static).update(Text.assemble(left, " " * w, r))

    def animate(self) -> None:
        try:
            self._tick()
        except NoMatches:          # a last tick while the app closes, after its widgets are removed
            pass

    def _tick(self) -> None:
        self.frame += 1
        st = self.state.get("st", {})
        tabs = {t["job_id"]: t for t in self.state.get("live", [])}
        rows = list(dict.fromkeys(list(st.get("active", {})) + list(tabs)))
        running = [j for j in rows if (tabs.get(j, {}).get("phase") or st.get("active", {}).get(j, "")) not in ("submitted", "code", "review", "error")]
        # the hammer: strikes while there's work, rests otherwise
        if self.strike or running or self.busy_since:
            seq = [0, 0, 1, 2, 2, 0]
            f = seq[(self.frame // 2) % len(seq)]
            if self.strike and f == 2 and self.frame % 2 == 0:
                self.strike -= 1
            self.query_one("#logo", Static).update(logo_text(f))
        elif self.frame % 40 == 0:
            self.glint = 0
        if getattr(self, "glint", -1) >= 0:
            self.glint += 1
            self.query_one("#logo", Static).update(logo_text(0, self.glint))
            if self.glint > 20:
                self.glint = -1
                self.query_one("#logo", Static).update(logo_text(0))
        # the thinking line
        if self.busy_since:
            secs = int(time.time() - self.busy_since)
            self.query_one("#think", Static).update(Text.assemble((STAR[self.frame % len(STAR)] + " ", EMBER), shimmer(self.verb + "…", self.frame),
                                                                  (f"  ({secs}s · esc to cancel)", DIM)))
        # applications in progress, above the prompt
        live = self.query_one("#live", Static)
        if rows:
            t = Text.assemble((STAR[self.frame % len(STAR)] + " ", EMBER), shimmer(f"Applying to {len(running)}" if running else "Waiting on you", self.frame // 1),
                              (f"  · {len(rows)} open" if len(rows) != len(running) else "", DIM))
            for i, jid in enumerate(rows[:6]):
                tab = tabs.get(jid, {})
                pr = (st.get("progress") or {}).get(jid) or {"step": 0, "total": 5, "label": ""}
                ph = tab.get("phase") or st.get("active", {}).get(jid, "")
                mark = (("✓", "green") if ph == "submitted" else ("!", "yellow") if ph in ("code", "review", "error")
                        else (SPIN[(self.frame + i) % len(SPIN)], EMBER))
                t.append("\n")
                t.append_text(Text.assemble(("  ⎿  " if i == 0 else "     ", DIM), mark, " ", (f"{self.job_name(jid, tab)[0][:22]:<23}", "bold " + INK),
                                            bar(pr["step"], pr["total"]), "  ", ((pr.get("label") or tab.get("phase_label") or ph or "")[:40], STEEL)))
            if len(rows) > 6:
                t.append(f"\n     … and {len(rows) - 6} more · ctrl+o", style=DIM)
            live.update(t)
            live.display = True
        else:
            live.display = False


def run(base: str, splash: bool = True, start: str = "") -> None:
    Jobsmith(base, splash=splash, start=start).run()
