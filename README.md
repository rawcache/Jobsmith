# Jobsmith

**Applies to jobs for you, and never makes anything up.** Open source, runs on your computer, works with your own AI.

Point it at a GitHub job list, a company ("apply to NVIDIA hardware internships") or job links. Jobsmith checks you actually qualify, researches the company, answers every question from your real resume, fills the application in a browser and submits it. Anything it isn't sure about waits for one click from you.

```
$ jobsmith
› apply to nvidia and amd hardware internships
  Found 14 roles. 9 fit, 2 skipped (active clearance required).
  ✓ NVIDIA  ASIC Design Intern           submitted
  ✓ AMD     Silicon Validation Intern    submitted
  ! AMD     GPU Architecture Intern      held: "Why AMD?" needs you   /review
```

## Install

macOS or Linux:

```bash
curl -LsSf https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.sh | sh
jobsmith
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/rawcache/Jobsmith/main/install.ps1 | iex"
jobsmith
```

The first run asks what you're applying for and which AI to use (arrow keys, pick as many as you like), then opens the dashboard for your resume and details. The terminal shows each one as it arrives. Then autopilot starts, and you can watch any application being filled in a real browser window.

## Two ways to use it

**Terminal.** `jobsmith` opens a prompt. Type what to apply to and watch it work.

| | |
|---|---|
| `jobsmith` | the prompt (sets you up the first time) |
| `jobsmith "apply to ramp"` | one request, then watch it |
| `jobsmith --autopilot "..."` | submit whatever it's confident about without asking, this run only |
| `jobsmith status` / `watch` / `review` | what's running, follow along, go through held answers |
| `jobsmith watch` | live view; press a row's number to watch that form fill in the browser |
| `jobsmith smith` | set up smith, the free AI that runs on your computer |
| `jobsmith extension` | add Jobsmith to Chrome |
| `jobsmith web` | open the dashboard |

**Dashboard** at http://127.0.0.1:8765: matches with resume fit and who you know at each company, a live view of every application being filled (take over any time), a tracker, your documents, and your profile.

**Chrome extension** (`extension/`): on any job site, fill the application you're looking at from your profile (Alt+J), or send the posting to autopilot. It never submits. See [extension/README.md](extension/README.md).

## AI

Setup recommends **Gemini's free tier**: it writes well, can research companies on the web, and a key takes a minute at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). On the free tier Google may use your prompts to improve its models; a paid key or smith avoids that. If the free daily limit runs out, Jobsmith switches to smith for the rest of the day when smith is installed.

**smith** is Jobsmith's own AI, fully private: an open model (Qwen3) running on your computer through [Ollama](https://ollama.com). Pick it during setup (or run `jobsmith smith`) and Jobsmith installs Ollama into your user folder (no admin), starts it, downloads the model that fits your memory, and writes a sample answer so you can judge it:

| Memory | Model | Download |
|---|---|---|
| 32 GB or more | qwen3:30b-a3b (instruct) | 19 GB |
| 24 GB | qwen3:14b | 9.3 GB |
| 16 GB | qwen3:8b | 5.2 GB |
| 8 GB | qwen3:4b (instruct) | 2.5 GB (works, slower) |

smith can't search the web, so research uses the posting itself. To run it on another computer, like a Mac mini, set `OLLAMA_HOST=http://mac-mini.local:11434`.

Also supported: an Anthropic or OpenAI API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` are picked up automatically). You can use one AI for writing and another for research. The Stats page shows the tokens each application used.

## What it won't do

- **Make things up.** Every written answer cites facts from your resume and profile. Contact details, work authorization and demographics only ever come from what you entered.
- **Apply where you don't qualify, unless you say so.** Required citizenship or clearance, sponsorship, degree level, graduation window and years of experience are checked first; autopilot skips those, and "Apply anyway" overrides it.
- **Message anyone.** It shows people you know at a company (from your LinkedIn connections export) so you can ask for a referral yourself.
- **Automate LinkedIn Easy Apply** or type your passwords. Sign-ins, CAPTCHAs and emailed codes come to you.
- **Leave your computer.** Your data lives in `~/.jobsmith` (or `./data` in a source checkout). The only things sent anywhere are your applications, to the employers, and prompts to the AI you chose.

You're responsible for what's submitted in your name. There are no daily or per-company caps unless you set them in Settings.

## How it applies

1. Reads the posting and the form's questions (straight from Greenhouse, Lever and Ashby where possible, otherwise from the page).
2. Checks eligibility, then researches the company (reused for 14 days).
3. Answers each question: your profile first, then answers you approved before, then AI with citations. A checker rejects unknown facts and numbers that aren't in your profile.
4. Fills the form in a real Chrome window that stays minimized, attaches your resume (optionally reordered for the role), and submits when every answer is trusted. Otherwise it holds it for you.
5. Watches for the confirmation page, emailed verification codes and CAPTCHAs, and notifies you.
6. Learns: approvals get reused, edits become style examples, rejection reasons become rules, and replies from employers (read-only Gmail, optional) shift what ranks highest.

Supported: Greenhouse, Lever, Ashby, SmartRecruiters, Workable and most single-page forms. Workday, iCIMS, Oracle, Taleo and SuccessFactors work page by page (beta), stopping at review.

## Contributing

```bash
git clone https://github.com/rawcache/Jobsmith && cd Jobsmith
uv sync && uv run playwright install chromium
uv run pytest                          # includes real-browser tests against recorded forms
cd web && npm install && npm run dev   # dashboard with hot reload (proxies /api to :8765)
```

Adding support for a job site is the most useful contribution: a filler lives in `jobsmith/fill/`, with a saved copy of the site's form in `tests/fixtures/` to test against.

Code map: `profile` (facts and answers), `sources` (job lists), `commands` (plain-language requests), `match` and `eligibility` (fit), `draft` (research, writing, validation), `learn` (feedback), `runner` (browser), `fill/` (site fillers), `scheduler`, `outcomes` (Gmail), `tailor` (resume), `tui` (terminal app), `smith` (local AI setup). `web/` is the React dashboard, built into `jobsmith/web_dist`.

## License

MIT
