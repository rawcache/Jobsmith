# How Jobsmith compares

Three open-source projects are close to Jobsmith, and its roadmap borrows from each. This is the short, honest
version: what each one does, from its own README, checked on **2026-11-02**. Corrections are welcome as issues.

| | Jobsmith | [career-ops](https://github.com/career-ops-hq/career-ops) | [ai-job-search](https://github.com/ai-job-search-dev/ai-job-search) | [please-hire-me](https://github.com/alecswang/please-hire-me) |
|---|---|---|---|---|
| Submits applications itself | Yes, on Greenhouse, Ashby and Lever, within caps; the first on each site waits for you | No: fills forms and drafts every answer, you press Submit | No: writes a tailored CV and cover letter, you send them | Yes, on Greenhouse, Lever and Ashby, after you approve the first |
| Finds jobs | GitHub internship lists; Greenhouse, Lever and Ashby job boards | Ashby, Greenhouse, Lever and Wellfound, 100+ companies preconfigured | Danish job boards, LinkedIn's public guest listings, freehire.me | Greenhouse, Lever and Ashby, plus the SimplifyJobs lists |
| Needs an AI | No: profile, saved answers and your own writing work without one. Gemini's free tier, a local model, Claude or OpenAI for the rest | Yes, run inside your AI coding CLI (Claude Code, Codex and others); local and free models supported; scanning uses no AI | Yes, Claude Code (paid subscription or API credits) | Yes, Claude Code with Claude in Chrome, or Grok Bot |
| Runs where | Your computer: terminal app, dashboard, Chrome extension | Your computer, as a CLI | Your computer, inside Claude Code | Your own Chrome, or Grok Bot's hosted machine |
| Checks against invented facts | Every written answer and number checked against your facts before it's sent; `jobsmith audit` traces what was sent | A CV's numbers and facts checked against your sources | "All claims… are verified against your actual profile" | Missing facts become questions; unsourced terms and numbers rejected |
| Caps | 20 a day and 3 per company a week by default | Not applicable (you submit) | Not applicable (you send) | 3 per run and 2 per company ever by default |
| LinkedIn | Reads your own connections export only | Drafts messages to your contacts; never sends | Searches LinkedIn's public guest job listings (its README warns this is against LinkedIn's terms) | No automation |
| Stack | Python | Node.js, Go dashboard | Python and Bun, in Claude Code | Python and shell, run by Claude Code |
| License · size | MIT · new | MIT · about 80k stars | MIT · about 69k stars | MIT · about 40 stars |

## In one line each

- **career-ops** is the largest and broadest of the four, and deliberately never submits: you press Submit. Pick it if you want an AI to evaluate and draft, and to stay in control of every send.
- **ai-job-search** is a Claude Code workflow for the documents: fit evaluation, a tailored CV, a reviewed cover
  letter and interview prep. It's built for the Danish market and swaps to others.
- **please-hire-me** is closest to Jobsmith: it fills and submits on the same three sites while you sleep, with
  caps and a first-application check, driven by Claude in your own Chrome.
- **Jobsmith** is for students applying to many internships: it submits on its own within caps, keeps working
  with no AI at all for what your profile and own writing answer, and asks you once per missing fact ("Confirm work
  authorization: unblocks 41") instead of once per application.

## What Jobsmith doesn't do yet

Workday stops at the review page; iCIMS fills step 1 of 5 and SmartRecruiters the first page; neither is supported
end to end. The Chrome extension isn't in the Web Store yet. Tailored resumes, reviewed cover letters and full fit
breakdowns are Phase 2 ([docs/ROADMAP.md](../ROADMAP.md)). Its Phase 1 gate (80% of good matches sent without you,
zero invented facts in a 50-application audit) is being measured now: `{{GATE_STATUS}}`.
