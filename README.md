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

The first run asks four questions (your goal, which AI, your resume, autopilot or copilot), then fills your first application in front of you without submitting it. If you don't have an AI key, it sets up **smith** for you (below) while you answer the rest.

## Two ways to use it

**Terminal.** `jobsmith` opens a prompt. Type what to apply to and watch it work.

| | |
|---|---|
| `jobsmith` | the prompt (sets you up the first time) |
| `jobsmith "apply to ramp"` | one request, then watch it |
| `jobsmith --autopilot "..."` | submit whatever it's confident about without asking, this run only |
| `jobsmith status` / `watch` / `review` | what's running, follow along, go through held answers |
| `jobsmith smith` | set up smith, the free AI that runs on your computer |
| `jobsmith web` | open the dashboard |

**Dashboard** at http://127.0.0.1:8765: matches with resume fit and who you know at each company, a live view of every application being filled (take over any time), a tracker, your documents, and your profile.

## AI: smith, or bring your own

**smith** is Jobsmith's own AI: a small open model (Qwen3) that runs on your computer through [Ollama](https://ollama.com). It's free, and what you write never leaves your machine. You don't install anything yourself: pick smith during setup (or run `jobsmith smith`) and Jobsmith
1. finds Ollama, or installs it into your user folder (no admin rights),
2. starts it,
3. downloads the model that fits your memory, with a progress bar:

| Memory | Model | Download |
|---|---|---|
| 16 GB or more | qwen3:8b | 5.2 GB |
| 8 GB | qwen3:4b | 2.5 GB (works, slower) |
| less | qwen3:1.7b | 1.4 GB |

You keep using Jobsmith while it downloads. To run smith on another computer, like a Mac mini, set `OLLAMA_HOST=http://mac-mini.local:11434` and Jobsmith uses that one instead. smith can't search the web, so company research uses the posting itself unless you add a key for research.

Or use your own key:

| Option | Cost | Notes |
|---|---|---|
| Anthropic API key | pay per use | `ANTHROPIC_API_KEY` is picked up automatically |
| OpenAI API key | pay per use | `OPENAI_API_KEY`; separate from a ChatGPT subscription |
| Gemini API key (Google AI Studio) | free tier | `GEMINI_API_KEY` |

Jobsmith uses the first one it finds (an API key, then smith), and you can pick separately for writing and for research. The Stats page shows exactly how many tokens each application used.

## What it won't do

- **Make things up.** Every written answer cites facts from your resume and profile. Contact details, work authorization and demographics only ever come from what you entered.
- **Apply where you don't qualify.** Required citizenship or clearance, sponsorship, degree level, graduation window and years of experience are checked first.
- **Message anyone.** It shows people you know at a company (from your LinkedIn connections export) so you can ask for a referral yourself.
- **Automate LinkedIn Easy Apply** or type your passwords. Sign-ins, CAPTCHAs and emailed codes come to you.
- **Leave your computer.** Your data lives in `~/.jobsmith` (or `./data` in a source checkout). The only things sent anywhere are your applications, to the employers, and prompts to the AI you chose.

You're responsible for what's submitted in your name. Daily and per-company limits are on by default.

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
