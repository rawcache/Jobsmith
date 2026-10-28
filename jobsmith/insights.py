"""Things the dashboard shows about you and each job: resume keyword match, your public GitHub and
Devpost, company pages, and every document Jobsmith has made or sent."""
from __future__ import annotations

import html
import json
import re
import time
from collections import Counter
from pathlib import Path

from . import db, network, profile
from .config import DATA_DIR, RUNS_DIR

# --------------------------------------------------------------------------- resume match
# Skills come from a vocabulary for the kind of role the posting is (engineering, sales, design, product, data,
# marketing), picked from its title. Fixed lists keep the match free (no AI tokens) and explainable. Words that are
# skills in engineering and plain English elsewhere ("networking", "performance", "communication") are only in the
# engineering list, so a sales posting's networking events never count. The company's own name never counts.
def _words(s: str) -> list[str]:
    return [k.strip() for k in s.replace("\n", "").split("|") if k.strip()]


VOCAB = {
    "engineering": _words("""
Python|Java|C++|C#|C|Go|Golang|Rust|Kotlin|Swift|Scala|Ruby|PHP|R|MATLAB|Julia|TypeScript|JavaScript|SQL|Bash|Perl|Haskell|
Verilog|SystemVerilog|VHDL|Chisel|HLS|Assembly|CUDA|OpenCL|Triton|
React|Angular|AngularJS|Vue|Next.js|Node.js|Express|Django|Flask|FastAPI|Spring|Rails|.NET|GraphQL|REST|gRPC|HTML|CSS|
AWS|GCP|Azure|Kubernetes|Docker|Terraform|Linux|Unix|Git|CI/CD|Jenkins|GitHub Actions|Kafka|Spark|Hadoop|Airflow|dbt|
Snowflake|Databricks|BigQuery|Redshift|PostgreSQL|MySQL|MongoDB|Redis|Cassandra|DynamoDB|Elasticsearch|SQLite|
PyTorch|TensorFlow|JAX|Keras|scikit-learn|Pandas|NumPy|OpenCV|Hugging Face|LLM|LLMs|NLP|computer vision|deep learning|
machine learning|reinforcement learning|transformers|MLOps|data pipelines|ETL|data engineering|data science|statistics|
distributed systems|operating systems|compilers|computer architecture|embedded systems|firmware|RTOS|FPGA|ASIC|RTL|
microcontrollers|ARM|RISC-V|x86|PCB|Altium|Cadence|Synopsys|SPICE|LTspice|circuit design|analog|digital design|
signal processing|DSP|power electronics|thermal|validation|verification|UVM|timing analysis|physical design|
networking|TCP/IP|security|cryptography|robotics|ROS|ROS 2|SLAM|controls|Simulink|CAD|SolidWorks|
object oriented|object-oriented|data structures|algorithms|APIs|API|microservices|backend|frontend|full stack|mobile|iOS|Android|
testing|unit testing|automated testing|deployment|cloud|concurrency|multithreading|performance|low latency|
agile|Scrum|Jira|Figma|Excel|Tableau|Power BI|A/B testing|product management|communication|leadership"""),
    "sales": _words("""
enterprise sales|SaaS|B2B|quota|pipeline generation|pipeline|prospecting|prospect|lead generation|cold calling|outbound|
discovery|value selling|solution selling|consultative selling|MEDDIC|MEDDPICC|Challenger|sales methodology|
deal qualification|closing|negotiation|forecasting|account planning|account plans|territory planning|book of business|
new business|expansion|upsell|renewals|customer success|account management|C-level|executive relationships|
multi-threading|multi-threaded|sales cycles|sales process|Force Management|mid-market|Salesforce|HubSpot|Outreach|
Salesloft|Gong|CRM|ZoomInfo|RFP|channel partners|go-to-market|demos|Excel"""),
    "design": _words("""
Figma|Sketch|Adobe XD|Photoshop|Illustrator|InDesign|After Effects|Creative Cloud|Framer|prototyping|prototypes|
wireframing|wireframes|user research|usability testing|interaction design|visual design|UI design|UX design|
product design|design systems|typography|accessibility|WCAG|information architecture|journey mapping|user flows|
motion design|branding|portfolio|HTML|CSS|design thinking|design critiques|design principles|front-end development"""),
    "product": _words("""
roadmap|product strategy|product requirements|PRDs|user research|customer discovery|A/B testing|experimentation|
metrics|KPIs|OKRs|SQL|analytics|Amplitude|Mixpanel|Looker|Jira|prioritization|go-to-market|user stories|agile|Scrum|
wireframes|prototyping|Figma|market research|competitive analysis|stakeholder management|product launches"""),
    "data": _words("""
SQL|Python|R|Tableau|Power BI|Looker|Excel|statistics|statistical modeling|regression|experimentation|A/B testing|
causal inference|dbt|Airflow|Snowflake|BigQuery|Redshift|data visualization|dashboards|machine learning|forecasting|
ETL|data modeling|Pandas|NumPy|Spark|scikit-learn|Jupyter"""),
    "marketing": _words("""
SEO|SEM|content marketing|social media|email marketing|Google Analytics|Google Ads|HubSpot|Marketo|Salesforce|
campaigns|copywriting|paid acquisition|lifecycle marketing|demand generation|marketing automation|market research|
product marketing|positioning|messaging|go-to-market|analytics|A/B testing"""),
}
KEYWORDS = sorted(set().union(*VOCAB.values()))
# Which vocabularies a posting gets, from its title. A title can be two ("Sales Engineer"); none means engineering.
ROLES = [(name, re.compile(p, re.I)) for name, p in (
    ("sales", r"\b(?:account executive|sales|business development|account manager|SDRs?|BDRs?|customer success|"
              r"partnerships?)\b"),
    ("design", r"\b(?:designer|UX|UI|user experience|visual design|product design)\b"),
    ("product", r"\b(?:product manager|product management|product owner|APM|program manager)\b"),
    ("data", r"\b(?:data analyst|data scientist|data science|analytics|business intelligence|business analyst)\b"),
    ("marketing", r"\b(?:marketing|growth|content|brand|SEO)\b"),
    ("engineering", r"\b(?:engineer\w*|developer|programmer|firmware|SWE|devops|SRE|research scientist)\b"),
)]
# Fields an engineering role is often in, but that a sales or product title can name too ("Software Sales", "AI
# Product Manager"): engineering too, unless the title is for one of those business roles.
TECH_FIELD = re.compile(r"\b(?:software|hardware|robotics|machine learning|ML|AI|quant\w*)\b", re.I)
BUSINESS = {"sales", "product", "marketing", "design"}
CATEGORY_ROLE = {"Product": "product"}
# Words that are common English too: only count them in their exact case.
CASE_SENSITIVE = {"C", "R", "Go", "ARM", "Spark", "Swift", "Rust", "Express", "REST", "API", "APIs", "Excel", "Julia",
                  "Spring", "Rails", "Triton", "Chisel", "LLM", "LLMs", "ROS", "DSP", "CAD", "thermal", "analog",
                  "testing", "cloud", "mobile", "performance", "validation", "verification", "security",
                  "communication", "leadership", "backend", "frontend", "controls", "statistics", "deployment",
                  "networking", "concurrency", "agile", "Outreach", "Gong", "Challenger", "Sketch", "Framer",
                  "Illustrator", "Looker"}


def _pattern(k: str) -> re.Pattern:
    flags = 0 if k in CASE_SENSITIVE else re.I
    # "value selling" also reads "value-selling"
    body = re.escape(k).replace(r"\ ", r"[\s-]+").replace(r"\-", r"[\s-]+")
    return re.compile(r"(?<![A-Za-z0-9+#.])" + body + r"(?![A-Za-z0-9+#])", flags)


_PATTERNS = {k: _pattern(k) for k in KEYWORDS}
SAME = {"Golang": "Go", "object-oriented": "object oriented", "AngularJS": "Angular", "LLMs": "LLM", "APIs": "API",
        "ROS 2": "ROS", "prospect": "prospecting", "account plans": "account planning", "prototypes": "prototyping",
        "wireframes": "wireframing", "multi-threaded": "multi-threading"}


def roles(job: dict) -> list[str]:
    """The kinds of role this posting is, for picking which skills to look for."""
    title = job.get("title") or ""
    found = [name for name, pat in ROLES if pat.search(title)]
    if "engineering" not in found and TECH_FIELD.search(title) and not BUSINESS & set(found):
        found.append("engineering")
    return found or [CATEGORY_ROLE.get(job.get("category") or "", "engineering")]


def _own_name(company: str) -> set[str]:
    """The company's name as a skill would read it: "Figma, Inc." is "figma"."""
    norm = lambda s: re.sub(r"[^a-z0-9+#]", "", s.lower())
    name = re.sub(r"[,.]?\s+(?:inc|llc|ltd|corp|corporation|co|gmbh|plc|technologies|labs)\.?$", "", (company or "").strip(),
                  flags=re.I)
    words = name.split()
    return {n for n in (norm(name), norm(words[0]) if len(words) > 1 else "") if n}


def resume_text() -> str:
    doc = db.q1("SELECT text FROM documents WHERE kind IN ('resume','resume_pdf') ORDER BY kind='resume' DESC, created_at DESC")
    facts = " ".join(f["text"] for f in profile.facts())
    return f"{doc['text'] if doc else ''}\n{facts}"


def keyword_match(job: dict, resume: str | None = None, top: int = 16) -> dict:
    """Which of the posting's key skills your resume shows. Like a recruiter's quick skim."""
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    own = _own_name(job.get("company") or "")
    words = list(dict.fromkeys(k for r in roles(job) for k in VOCAB[r]))   # a fixed order, so ties break the same way
    counts: Counter = Counter()
    for k in words:
        if re.sub(r"[^a-z0-9+#]", "", k.lower()) in own:
            continue                                     # Figma's own name isn't a skill its posting asks for
        n = len(_PATTERNS[k].findall(text))
        if n:
            counts[SAME.get(k, k)] += n
    # skills named in the title count double
    for k in list(counts):
        if _PATTERNS.get(k) and _PATTERNS[k].search(job.get("title", "")):
            counts[k] += 2
    wanted = [k for k, _ in counts.most_common(top)]
    if not wanted:
        return {"score": None, "matched": [], "missing": [], "total": 0}
    resume = resume if resume is not None else resume_text()
    def has(k: str) -> bool:
        alts = [k] + [a for a, b in SAME.items() if b == k]
        return any(_PATTERNS[a].search(resume) for a in alts if a in _PATTERNS)
    matched = [k for k in wanted if has(k)]
    missing = [k for k in wanted if k not in matched]
    score = round(100 * len(matched) / len(wanted))
    return {"score": score, "matched": matched, "missing": missing, "total": len(wanted),
            "label": "High" if score >= 70 else "Fair" if score >= 45 else "Low"}


# --------------------------------------------------------------------------- your links
def _cache_table() -> None:
    db.x("CREATE TABLE IF NOT EXISTS link_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL, at REAL NOT NULL)")


def _cache_get(key: str, ttl: float) -> dict | None:
    _cache_table()
    r = db.q1("SELECT data, at FROM link_cache WHERE key=?", (key,))
    return json.loads(r["data"]) if r and time.time() - r["at"] < ttl else None


def _cache_put(key: str, data: dict) -> None:
    _cache_table()
    db.x("INSERT INTO link_cache(key, data, at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data, at=excluded.at",
         (key, json.dumps(data), time.time()))


def _user_from(url: str, host: str) -> str | None:
    m = re.search(rf"{host}/([A-Za-z0-9_.-]+)", url or "", re.I)
    return m.group(1) if m and m.group(1).lower() not in ("in", "software", "settings") else None


async def github(url: str, refresh: bool = False) -> dict | None:
    import httpx
    from .config import DEMO
    if DEMO:
        return None
    user = _user_from(url, r"github\.com")
    if not user:
        return None
    key = f"github:{user.lower()}"
    if not refresh and (hit := _cache_get(key, 12 * 3600)):
        return hit
    async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "jobsmith"}) as c:
        u = await c.get(f"https://api.github.com/users/{user}")
        if u.status_code != 200:
            return {"user": user, "url": url, "error": f"GitHub said {u.status_code}"}
        repos = await c.get(f"https://api.github.com/users/{user}/repos", params={"sort": "pushed", "per_page": 30})
    ud = u.json()
    rs = [r for r in (repos.json() if repos.status_code == 200 else []) if not r.get("fork")]
    rs.sort(key=lambda r: (r.get("stargazers_count", 0), r.get("pushed_at") or ""), reverse=True)
    data = {"user": user, "url": ud.get("html_url") or url, "name": ud.get("name"), "bio": ud.get("bio"),
            "avatar": ud.get("avatar_url"), "public_repos": ud.get("public_repos"), "followers": ud.get("followers"),
            "repos": [{"name": r["name"], "url": r["html_url"], "description": r.get("description") or "",
                       "language": r.get("language"), "stars": r.get("stargazers_count", 0),
                       "pushed_at": r.get("pushed_at")} for r in rs[:8]],
            "languages": [l for l, _ in Counter(r.get("language") for r in rs if r.get("language")).most_common(6)]}
    _cache_put(key, data)
    return data


def parse_devpost(page: str) -> dict:
    """Projects from a Devpost portfolio page (public HTML; Devpost has no public API)."""
    clean = lambda t: " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())
    projects, seen = [], set()
    for m in re.finditer(r'href="(https://devpost\.com/software/[a-z0-9-]+)"(.*?)</a>', page, re.S):
        link, inner = m.group(1), m.group(2)
        title = re.search(r"<h5[^>]*>(.*?)</h5>", inner, re.S)
        if link in seen or not title:
            continue
        seen.add(link)
        tag = re.search(r'class="[^"]*tagline[^"]*"[^>]*>(.*?)</p>', inner, re.S)
        projects.append({"name": clean(title.group(1)), "url": link, "tagline": clean(tag.group(1)) if tag else "",
                         "winner": bool(re.search(r"entry-badge[^>]*>\s*Winner", inner))})
    name = re.search(r'id="portfolio-user-name"[^>]*>(.*?)<small', page, re.S) or re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    bio = re.search(r'id="portfolio-user-bio"[^>]*>(.*?)</p>', page, re.S)
    return {"projects": projects[:10], "name": clean(name.group(1)) if name else "",
            "bio": clean(bio.group(1)) if bio else ""}


async def devpost(url: str, refresh: bool = False) -> dict | None:
    import httpx
    from .config import DEMO
    if DEMO:
        return None
    user = _user_from(url, r"devpost\.com")
    if not user:
        return None
    key = f"devpost:{user.lower()}"
    if not refresh and (hit := _cache_get(key, 12 * 3600)):
        return hit
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Jobsmith"}) as c:
        r = await c.get(f"https://devpost.com/{user}")
    if r.status_code != 200:
        return {"user": user, "url": url, "error": f"Devpost said {r.status_code}"}
    data = dict(parse_devpost(r.text), user=user, url=f"https://devpost.com/{user}")
    _cache_put(key, data)
    return data


async def links(refresh: bool = False) -> dict:
    ans = profile.answers()
    v = lambda k: (ans.get(k) or {}).get("value", "")
    out: dict = {"linkedin": {"url": v("linkedin")} if v("linkedin") else None, "github": None, "devpost": None,
                 "website": v("website") or None}
    for k, fn in (("github", github), ("devpost", devpost)):
        if v(k):
            try:
                out[k] = await fn(v(k), refresh)
            except Exception as e:
                out[k] = {"url": v(k), "error": f"Couldn't reach it ({e.__class__.__name__})"}
    return out


def add_link_facts(data: dict) -> int:
    """Turn your public repos and Devpost projects into facts answers may cite."""
    n = 0
    have = {f["text"] for f in profile.facts()}
    for r in (data.get("github") or {}).get("repos", []):
        if not r.get("description"):
            continue
        text = f"{r['name']} (GitHub): {r['description']}" + (f" Built with {r['language']}." if r.get("language") else "")
        if text not in have:
            profile.add_fact("project", text, r["name"], "github")
            n += 1
    for p in (data.get("devpost") or {}).get("projects", []):
        if not p.get("tagline"):
            continue
        text = f"{p['name']} (Devpost{' winner' if p.get('winner') else ''}): {p['tagline']}"
        if text not in have:
            profile.add_fact("project", text, p["name"], "devpost")
            n += 1
    return n


# --------------------------------------------------------------------------- companies
def domain_guess(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", network.norm_company(company).split(" ")[0] if network.norm_company(company) else "") + ".com"


def company(name: str) -> dict:
    jobs = [db.decode(r) for r in db.q("""SELECT id, company, title, url, ats, locations, terms, category, fit_score,
                                          status, outcome, date_posted, research FROM jobs
                                          WHERE company = ? COLLATE NOCASE ORDER BY fit_score DESC""", (name,))]
    research = next((j["research"] for j in jobs if j.get("research") and j["research"].get("summary")), {})
    for j in jobs:
        j.pop("research", None)
    applied = [j for j in jobs if j["status"] in ("submitted",)]
    return {"name": jobs[0]["company"] if jobs else name, "domain": domain_guess(name), "jobs": jobs,
            "research": research, "connections": network.at_company(name),
            "applied": len(applied), "open": sum(1 for j in jobs if j["status"] not in ("submitted", "skipped"))}


# --------------------------------------------------------------------------- documents
VIEWABLE = {".pdf", ".png", ".jpg", ".txt", ".tex", ".json", ".md"}


def documents() -> dict:
    uploads = db.q("SELECT id, kind, filename, created_at FROM documents ORDER BY created_at DESC")
    per_job = []
    if RUNS_DIR.exists():
        dirs = sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
        jobs = {r["id"]: r for r in db.q("SELECT id, company, title, status FROM jobs")}
        for d in dirs[:200]:
            jid = d.name.rsplit("-", 1)[0]
            files = []
            for f in sorted(d.iterdir()):
                if f.suffix.lower() not in VIEWABLE or f.name.endswith((".aux", ".log")):
                    continue
                kind = ("tailored resume" if f.suffix == ".pdf" else "resume source" if f.suffix == ".tex"
                        else "cover letter" if f.name.startswith("cover_letter") else "answers sent" if f.name == "answers.json"
                        else "confirmation" if f.name.startswith("confirmation") else "filled form" if f.name.startswith("filled")
                        else "error" if f.name.startswith("error") else "file")
                files.append({"name": f.name, "kind": kind, "path": str(f.relative_to(DATA_DIR)),
                              "size": f.stat().st_size})
            if files:
                j = jobs.get(jid, {})
                per_job.append({"job_id": jid, "company": j.get("company", ""), "title": j.get("title", ""),
                                "status": j.get("status", ""), "at": d.stat().st_mtime, "files": files})
    return {"uploads": uploads, "per_job": per_job}


def safe_data_file(rel: str) -> Path | None:
    p = (DATA_DIR / rel).resolve()
    runs = RUNS_DIR.resolve()
    if runs not in p.parents or not p.is_file() or p.suffix.lower() not in VIEWABLE:
        return None
    return p


# --------------------------------------------------------------------------- posting sections
_SECTION_RE = re.compile(
    r"^(what you'?ll do|what you will do|responsibilities|the role|about the role|your role|in this role|what we'?re looking for|"
    r"what we look for|requirements|minimum qualifications|basic qualifications|qualifications|required qualifications|"
    r"preferred qualifications|nice to have|bonus points|desired qualifications|who you are|you have|you'll need|"
    r"benefits|perks|compensation|pay|salary|about us|about the team|the team)\b", re.I)
_KIND = [("responsibilities", re.compile(r"do|responsib|role|in this role", re.I)),
         ("preferred", re.compile(r"prefer|nice|bonus|desired", re.I)),
         ("requirements", re.compile(r"look|require|qualif|who you are|you have|need", re.I)),
         ("pay", re.compile(r"compens|pay|salary", re.I)),
         ("benefits", re.compile(r"benefit|perk", re.I))]


def posting_sections(description: str) -> list[dict]:
    """Split a posting into the parts people scan: requirements, responsibilities, preferred, pay."""
    lines = [l.strip(" \t•·-*–") for l in (description or "").splitlines()]
    out: list[dict] = []
    cur = None
    for line in lines:
        if not line:
            continue
        if len(line) < 70 and not line.endswith(".") and _SECTION_RE.match(line.rstrip(":")):
            kind = next((k for k, rx in _KIND if rx.search(line)), "other")
            cur = {"heading": line.rstrip(":"), "kind": kind, "items": []}
            out.append(cur)
        elif cur is not None and len(cur["items"]) < 14:
            cur["items"].append(line)
    return [s for s in out if s["items"] and s["kind"] != "other"]


# --------------------------------------------------------------------------- the facts row on a job page
PAY = re.compile(r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK]|\d{2,3}(?:\.\d{1,2})?)"
                 r"(?:\s*(?:-|–|—|to)\s*\$?\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK]|\d{2,3}(?:\.\d{1,2})?))?"
                 r"\s*(?:USD\s*)?(?:/|per\s+|an?\s+)?\s*(hour|hr|year|yr|annually|annum)?", re.I)
LEVELS = [("Intern", r"\bintern(ship)?\b|\bco-?op\b"), ("New grad", r"new ?grad|university grad|early career|entry[- ]level|\bgraduate\b"),
          ("Principal", r"\bprincipal\b"), ("Staff", r"\bstaff\b"), ("Senior", r"\bsenior\b|\bsr\.?\b"), ("Lead", r"\blead\b")]


def _money(x: str) -> float:
    x = x.replace(",", "").replace(" ", "")
    return float(x[:-1]) * 1000 if x[-1:] in "kK" else float(x)


def _fmt(v: float, hourly: bool) -> str:
    return f"${v:,.0f}" if hourly or v < 1000 else f"${v / 1000:,.0f}k"


def pay_of(text: str) -> str:
    """'$45 - $55/hr' or '$140k - $180k/yr' from a posting, or ''. Ignores small amounts like '$5 credit'."""
    for m in PAY.finditer(text or ""):
        lo = _money(m.group(1))
        hi = _money(m.group(2)) if m.group(2) else None
        unit = (m.group(3) or "").lower()
        hourly = unit in ("hour", "hr") or (not unit and lo < 300)
        if hourly and not (12 <= lo <= 300):
            continue
        if not hourly and lo < 20000:
            continue
        rng = _fmt(lo, hourly) + (f" - {_fmt(hi, hourly)}" if hi and hi > lo else "")
        return rng + ("/hr" if hourly else "/yr")
    return ""


def job_facts(job: dict) -> dict:
    """Pay, level, where and how, degree and sponsorship: what Simplify shows in a row under the title."""
    text = job.get("description") or ""
    title = job.get("title") or ""
    level = next((name for name, pat in LEVELS if re.search(pat, title, re.I)), "")
    if not level and any("new grad" in t.lower() for t in job.get("terms") or []):
        level = "New grad"
    if not level and job.get("terms"):
        level = "Intern"
    locs = job.get("locations") or []
    hay = " ".join(locs) + " " + text[:3000]
    mode = ("Remote" if re.search(r"\bremote\b", " ".join(locs), re.I) else
            "Hybrid" if re.search(r"\bhybrid\b", hay, re.I) else
            "Remote" if re.search(r"\bfully remote\b|\bremote[- ]first\b", hay, re.I) else
            "In person" if locs else "")
    spons = job.get("sponsorship") or ""
    if not spons and re.search(r"(not|unable to|cannot|won't|will not)\s+(provide\s+|offer\s+)?(visa\s+)?sponsor", text, re.I):
        spons = "No visa sponsorship"
    if re.search(r"u\.?s\.? citizen(ship)? (is )?required|must be a u\.?s\.? citizen", text, re.I):
        spons = "U.S. citizens only"
    degrees = job.get("degrees") or []
    return {"pay": pay_of(text), "level": level, "mode": mode, "category": job.get("category") or "",
            "sponsorship": spons, "degree": ", ".join(degrees[:2]) if isinstance(degrees, list) else str(degrees)}
