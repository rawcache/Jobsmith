"""Commands for trying changes without touching your real Jobsmith.

    jobsmith demo            a practice copy with a made-up person and jobs, at http://127.0.0.1:8766
    jobsmith demo --setup    the same, starting the website setup from step 1 (nothing filled in yet)
    jobsmith demo --keep     reuse the practice copy as you left it instead of starting over
    jobsmith demo stop       stop the practice copy
    jobsmith demo show       a fresh practice copy, then the terminal app plays autopilot on 3 made-up applications
    jobsmith setup           run your real setup again from step 1, in the terminal
    jobsmith setup --web     ... or on the website
    jobsmith dev             (source checkout) the practice copy with live reload: edit web/ or jobsmith/ and see it
    jobsmith check           (source checkout) tests, a dashboard build, and screenshots of every page

The practice copy lives in ~/.jobsmith-demo. In it Jobsmith never opens a job site, syncs a list, reads email or
calls an AI with your keys, so you can click everything.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

DEMO_DIR = Path(os.environ.get("JOBSMITH_DEMO_DATA") or Path.home() / ".jobsmith-demo")
DEMO_PORT = 8766
ROOT = Path(__file__).resolve().parents[1]          # the source checkout, when there is one
PAGES = [("home", "#/"), ("matches", "#/matches"), ("applications", "#/tracker"), ("job", "#/job/demo-acme"),
         ("companies", "#/companies"), ("documents", "#/documents"), ("profile", "#/profile"),
         ("preferences", "#/preferences"), ("skills", "#/skills"), ("voice", "#/voice"), ("outreach", "#/outreach"), ("followups", "#/followups"),
         ("activity", "#/activity"), ("settings", "#/settings"), ("setup", "#/setup/1")]


def _env(port: int = DEMO_PORT) -> dict:
    return dict(os.environ, JOBSMITH_DATA=str(DEMO_DIR), JOBSMITH_DEMO="1", JOBSMITH_PORT=str(port))


def _say(msg: str) -> None:
    print(msg, flush=True)


def _up(port: int) -> bool:
    import httpx
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def stop(port: int = DEMO_PORT) -> bool:
    import httpx
    if not _up(port):
        return False
    try:
        httpx.post(f"http://127.0.0.1:{port}/api/shutdown", timeout=3)
    except httpx.HTTPError:
        pass
    for _ in range(40):
        if not _up(port):
            return True
        time.sleep(0.25)
    return True


def seed_here(setup: bool = False) -> None:
    """Runs inside the practice copy (JOBSMITH_DATA points at it): fill it with a made-up person and jobs."""
    import asyncio
    from . import db, match, outcomes, profile
    from .config import DEMO
    assert DEMO, "seed_here only runs in the practice copy"
    resume = Path(__file__).parent / "demo_data" / "resume.tex"
    shutil.copy(resume, DEMO_DIR / "Alex_Rivera_resume.tex")     # to upload yourself when testing setup
    pdf = resume_pdf(resume, DEMO_DIR / "Alex_Rivera_resume.pdf")
    db.conn()
    outcomes._ensure()
    if setup:
        db.set_settings({"onboarded": False, "setup_step": "", "auto_run": False})
        return
    asyncio.run(profile.ingest_document(resume))
    asyncio.run(profile.ingest_document(pdf, "resume_pdf"))     # so autofill has a file to attach
    for k in ("first_name", "last_name", "email", "phone", "work_authorized_us", "needs_sponsorship"):
        a = profile.answers().get(k)
        if a and a["value"]:
            profile.set_answer(k, a["value"], confirmed=True)
    now = time.time()
    db.set_settings({"onboarded": True, "setup_step": "done", "goals": ["internship", "newgrad"], "prefs_saved": True,
                     "auto_run": True, "auto_last_run": now, "autonomy": "autopilot", "values": ["Hard technical problems", "Path to a full-time offer"],
                     "location_choices": ["Boston", "New York", "Remote"], "llm_backend": "auto"})
    for url, n in (("https://github.com/SimplifyJobs/Summer2027-Internships", 17249), ("https://github.com/SimplifyJobs/New-Grad-Positions", 19600)):
        db.x("INSERT OR REPLACE INTO sources(url, kind, active, last_synced, last_count) VALUES(?,?,?,?,?)",
             (url, "simplify_github", 1, now - 1800, n))
    rows = json.loads((Path(__file__).parent / "demo_data" / "jobs.json").read_text())
    for i, j in enumerate(rows):
        _add_job(j, now - 3600 * (i + 1))
    rnd = random.Random(7)
    cos = ["Lumen Robotics", "Quarry Labs", "Brightwave", "Northstar Silicon", "Tessellate", "Kestrel AI", "Halcyon Systems",
           "Orbital Freight", "Pinecone Health", "Ridgeline Data", "Cobalt Motors", "Fathom Bio", "Gridlock Energy",
           "Marrow", "Vantage Chips", "Juniper Pay", "Sable Security", "Tidewater", "Ember Analytics", "Foundry Works",
           "Atlas Mapping", "Cirrus Cloud", "Driftwood Games", "Lattice Quant", "Meridian Space"]
    roles = [("Software Engineering Intern", "Software", "Summer 2027"), ("Hardware Engineering Intern", "Hardware", "Summer 2027"),
             ("Machine Learning Intern", "AI/ML/Data", "Summer 2027"), ("New Grad Software Engineer", "Software", "New Grad"),
             ("Embedded Software Engineer, New Grad", "Hardware", "New Grad"), ("Data Engineering Intern", "AI/ML/Data", "Summer 2027"),
             ("Product Management Intern", "Product", "Summer 2027"), ("Quant Developer Intern", "Quant", "Summer 2027")]
    places = ["Boston, MA", "New York, NY", "San Francisco, CA", "Seattle, WA", "Austin, TX", "Remote in USA", "Atlanta, GA"]
    for n in range(48):
        title, cat, term = rnd.choice(roles)
        co = cos[n % len(cos)]
        pay = rnd.choice(["$40 - $52/hr", "$45/hr", "$120,000 - $150,000 per year", ""])
        _add_job({"id": f"demo-m{n}", "company": co, "title": title, "category": cat, "terms": [term],
                  "locations": [rnd.choice(places)], "status": "new",
                  "description": f"{co} is hiring a {title}.\n\nRequirements\n- Python or C++\n- Git and Linux\n\n"
                                 f"Responsibilities\n- Ship features with a small team\n\n" + (f"Pay: {pay}." if pay else "")},
                 now - 86400 * rnd.randint(0, 40))
    from . import network
    network.import_csv("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                       "Priya,Natarajan,https://www.linkedin.com/in/example-priya,,Acme Robotics,Senior Robotics Engineer,01 Mar 2025\n"
                       "Marcus,Lee,https://www.linkedin.com/in/example-marcus,,Acme Robotics,University Recruiter,12 Jan 2026\n"
                       "Dana,Okafor,https://www.linkedin.com/in/example-dana,,Northwind,Hardware Engineer,05 Sep 2024\n"
                       "Sam,Ibarra,https://www.linkedin.com/in/example-sam,,Wayne Enterprises,Software Engineer II,20 Jun 2025\n"
                       "Lena,Fischer,https://www.linkedin.com/in/example-lena,,Lumen Robotics,Engineering Manager,02 Feb 2026\n")
    for jid, kind, subj, days in (("demo-northwind", "interview", "Next steps: interview with Northwind", 1),
                                  ("demo-initech", "rejected", "Your application to Initech", 3),
                                  ("demo-stark", "received", "Thanks for applying to Stark Industries", 9),
                                  ("demo-soylent", "assessment", "Soylent Systems online assessment", 2)):
        db.x("INSERT INTO outcomes(job_id, kind, subject, sender, received_at, message_id) VALUES(?,?,?,?,?,?)",
             (jid, kind, subj, "recruiting@example.com", now - 86400 * days, f"demo-{jid}"))
    db.x("UPDATE runs SET started_at=?, finished_at=? WHERE job_id IN ('demo-globex','demo-stark')", (now - 10 * 86400, now - 10 * 86400))
    from .skills import voice
    voice.add_file(Path(__file__).parent / "demo_data" / "writing.md")
    from . import draft
    fields = [{"field": "first_name", "label": "First Name", "qtype": "text", "required": True},
              {"field": "email", "label": "Email", "qtype": "text", "required": True},
              {"field": "resume", "label": "Resume/CV", "qtype": "file", "required": True},
              {"field": "authorized", "label": "Are you legally authorized to work in the United States?", "qtype": "select",
               "required": True, "options": ["Yes", "No"]},
              {"field": "why", "label": "Why Acme?", "qtype": "textarea", "required": True},
              {"field": "project", "label": "Tell us about a robotics project you're proud of.", "qtype": "textarea", "required": False}]
    draft.save_results("demo-acme", fields, {
        "first_name": {"kind": "standard", "answer": "Alex", "confidence": 1, "rationale": "From your profile"},
        "email": {"kind": "standard", "answer": "alex.rivera@example.com", "confidence": 1, "rationale": "From your profile"},
        "resume": {"kind": "file", "answer": "Alex_Rivera_resume.pdf", "confidence": 1, "rationale": "Your resume"},
        "authorized": {"kind": "answer_bank", "answer": "Yes", "confidence": 1, "rationale": "You set this in your profile"},
        "why": {"kind": "generated", "answer": "I want to work on hardware and software that has to be fast and has to be right. Acme's "
                "autonomy team ships perception to real robots, and at Northwind I built an image pipeline that handled 600,000+ images "
                "with 94% duplicate-detection precision. I'd love to bring that to a team where a few milliseconds matter.",
                "confidence": 0.52, "issues": ["Says 'a few milliseconds matter' but the posting doesn't mention latency. Check it fits."],
                "rationale": "From your Northwind internship and your own writing", "model": "gemini"},
        "project": {"kind": "voice", "answer": "Ember started as a weekend idea with two friends from my robotics club. I owned the vision "
                    "side: I trained the detector, squeezed it onto an NVIDIA Jetson Nano, and kept tuning until inference ran under 200 "
                    "milliseconds at 30 frames per second.", "confidence": 0.85, "rationale": "Your own words, from writing.md"},
    })
    match.rescore()


def resume_pdf(tex: Path, out: Path) -> Path:
    """A plain one-page PDF of a LaTeX resume, so the practice copy has a file to attach without a TeX install.
    Built from the same parse the profile uses, so it says exactly what the .tex says."""
    from fpdf import FPDF
    from .letters import _latin1
    from .profile import parse_latex
    parsed = parse_latex(tex.read_text())
    ident = parsed["identity"]
    pdf = FPDF(format="Letter")
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 9, _latin1(ident.get("name", "")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    contact = " | ".join(ident[k] for k in ("location", "phone", "email", "linkedin", "github", "work_status") if ident.get(k))
    pdf.multi_cell(0, 5, _latin1(contact), align="C", new_x="LMARGIN", new_y="NEXT")
    for sec in parsed["sections"]:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11.5)
        pdf.cell(0, 6, _latin1(sec["title"].upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)
        for e in sec["entries"]:
            pdf.set_font("Helvetica", "B", 10)
            pdf.multi_cell(0, 5, _latin1(e["heading"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            for b in e["bullets"]:
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(0, 5, _latin1(f"- {b}"), new_x="LMARGIN", new_y="NEXT")
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return out


def _add_job(j: dict, when: float) -> None:
    from . import db
    db.x("""INSERT INTO jobs(id, company, title, url, ats, locations, terms, category, date_posted, description, status, error,
            created_at, updated_at, hold_reason, outcome) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (j["id"], j["company"], j["title"], j.get("url") or f"https://boards.greenhouse.io/example/jobs/{abs(hash(j['id'])) % 10**7}",
          j.get("ats", "greenhouse"), json.dumps(j.get("locations", [])), json.dumps(j.get("terms", [])), j.get("category", "Software"),
          when, j.get("description", ""), j.get("status", "new"), j.get("error"), when, when, j.get("hold_reason"), j.get("outcome")))
    if j.get("status") == "submitted":
        db.x("INSERT INTO runs(job_id, kind, status, started_at, finished_at, log) VALUES(?,?,?,?,?,?)",
             (j["id"], "submit", "done", when, when, "Submitted (demo)."))


def demo(setup: bool = False, keep: bool = False, port: int = DEMO_PORT, open_browser: bool = True) -> str:
    stop(port)
    if not keep or not DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR, ignore_errors=True)
        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, "-m", "jobsmith", "demo-seed"] + (["--setup"] if setup else []),
                           env=_env(port), capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"Couldn't make the practice copy:\n{r.stderr[-2000:]}")
    log = open(DEMO_DIR / "server.log", "a")
    kw: dict = {"stdout": log, "stderr": log, "stdin": subprocess.DEVNULL, "env": _env(port)}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "jobsmith", "serve", "--no-open", "--port", str(port)], **kw)
    for _ in range(80):
        if _up(port):
            break
        time.sleep(0.25)
    else:
        raise SystemExit(f"The practice copy didn't start. See {DEMO_DIR / 'server.log'}")
    url = f"http://127.0.0.1:{port}/" + ("#/setup/1" if setup else "#/")
    if open_browser:
        webbrowser.open(url)
    return url


def dev(real: bool = False) -> None:
    if not (ROOT / "web" / "package.json").exists():
        raise SystemExit("`jobsmith dev` works in a source checkout: git clone https://github.com/rawcache/Jobsmith")
    if not shutil.which("npm"):
        raise SystemExit("`jobsmith dev` needs Node.js for the dashboard's live reload: https://nodejs.org")
    port = 8765 if real else DEMO_PORT
    if not real:
        stop(port)
        shutil.rmtree(DEMO_DIR, ignore_errors=True)
        DEMO_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "jobsmith", "demo-seed"], env=_env(port), check=True)
    env = os.environ.copy() if real else _env(port)
    env["JOBSMITH_API"] = f"http://127.0.0.1:{port}"
    engine = subprocess.Popen([sys.executable, "-m", "uvicorn", "jobsmith.api:app", "--port", str(port), "--reload",
                               "--reload-dir", str(ROOT / "jobsmith"), "--loop", "asyncio", "--http", "h11", "--log-level", "warning"],
                              env=env, cwd=ROOT)
    if not (ROOT / "web" / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=ROOT / "web", check=True)
    _say(f"Engine: http://127.0.0.1:{port} ({'your real data' if real else 'practice copy'}), reloads when jobsmith/ changes.")
    _say("Dashboard with live reload: http://127.0.0.1:5173  (Ctrl+C stops both)")
    try:
        subprocess.run(["npm", "run", "dev", "--", "--open"], cwd=ROOT / "web", env=env)
    except KeyboardInterrupt:
        pass
    finally:
        engine.terminate()


def screenshots(port: int = DEMO_PORT, out: Path | None = None) -> Path:
    """Every page, wide and phone-sized, into one gallery page."""
    import asyncio
    from playwright.async_api import async_playwright
    out = out or DEMO_DIR / "shots"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    errors: dict[str, list[str]] = {}

    async def go():
        async with async_playwright() as pw:
            exe = os.environ.get("JOBSMITH_CHROMIUM_PATH")
            b = await pw.chromium.launch(**({"executable_path": exe} if exe else {}))
            for size, vp in (("wide", {"width": 1440, "height": 900}), ("phone", {"width": 390, "height": 844})):
                p = await b.new_page(viewport=vp)
                p.on("pageerror", lambda e, k=size: errors.setdefault(k, []).append(str(e)))
                await p.route("**/s2/favicons**", lambda r: r.abort())
                for name, frag in PAGES:
                    await p.goto(f"http://127.0.0.1:{port}/{frag}")
                    await p.wait_for_timeout(1200)
                    await p.screenshot(path=str(out / f"{name}-{size}.png"), full_page=size == "wide")
                await p.close()
            await b.close()
    asyncio.run(go())
    cells = "".join(f'<figure><figcaption>{n} <a href="http://127.0.0.1:{port}/{f}">open</a></figcaption>'
                    f'<a href="{n}-wide.png"><img src="{n}-wide.png" loading="lazy"></a>'
                    f'<a href="{n}-phone.png"><img class="ph" src="{n}-phone.png" loading="lazy"></a></figure>' for n, f in PAGES)
    errs = "".join(f"<li>{k}: {e}</li>" for k, es in errors.items() for e in es)
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Jobsmith screenshots</title><style>body{font:14px system-ui;margin:24px;background:#f2f0ec}"
        "figure{display:grid;grid-template-columns:1fr 160px;gap:12px;margin:0 0 28px}figcaption{grid-column:1/-1;font-weight:600}"
        "img{width:100%;border:1px solid #ddd;background:#fff}.err{color:#b91c1c}</style>"
        f"<h1>Every page, {time.strftime('%b %d %H:%M')}</h1>" + (f"<ul class=err>{errs}</ul>" if errs else "<p>No page errors.</p>") + cells)
    return out / "index.html"


def check() -> int:
    if not (ROOT / "tests").exists():
        raise SystemExit("`jobsmith check` works in a source checkout: git clone https://github.com/rawcache/Jobsmith")
    steps = [("Tests", [sys.executable, "-m", "pytest", "-q"], ROOT)]
    if shutil.which("npm") and (ROOT / "web" / "package.json").exists():
        steps.append(("Dashboard build", ["npm", "run", "build"], ROOT / "web"))
    failed = 0
    for label, cmd, cwd in steps:
        _say(f"\n== {label}")
        r = subprocess.run(cmd, cwd=cwd)
        if r.returncode:
            failed += 1
            _say(f"!! {label} failed")
    _say("\n== Screenshots of every page (practice copy)")
    demo(open_browser=False)
    try:
        gallery = screenshots()
        _say(f"Open {gallery}")
        webbrowser.open(gallery.as_uri())
    finally:
        stop()
    _say("\nAll good." if not failed else f"\n{failed} step(s) failed; see above.")
    return 1 if failed else 0


def main(argv: list[str]) -> None:
    cmd, rest = argv[0], argv[1:]
    if cmd == "demo-seed":
        seed_here(setup="--setup" in rest)
    elif cmd == "demo":
        if rest[:1] == ["stop"]:
            _say("Stopped the practice copy." if stop() else "The practice copy wasn't running.")
            return
        if rest[:1] == ["show"]:
            # Always a fresh practice copy of our own: pointing the terminal at a port with nothing on it
            # would make it start a real engine there.
            url = demo(open_browser=False)
            from . import tuiapp
            tuiapp.run(url.split("/#")[0].rstrip("/"), splash=False, start="show")
            _say("The practice copy is still running. Stop it with: jobsmith demo stop")
            return
        setup = "--setup" in rest
        url = demo(setup=setup, keep="--keep" in rest)
        _say(f"Practice copy running at {url}\nA made-up person (Alex Rivera) and made-up jobs. Nothing real is opened, "
             "synced or sent.\n"
             + (f"Their resume to upload while testing setup: {DEMO_DIR / 'Alex_Rivera_resume.tex'}\n" if setup
                else "Watch autopilot: jobsmith demo show\n")
             + "Stop it with: jobsmith demo stop")
    elif cmd == "dev":
        dev(real="--real" in rest)
    elif cmd == "check":
        raise SystemExit(check())
    elif cmd == "shots":
        _say(str(screenshots()))
