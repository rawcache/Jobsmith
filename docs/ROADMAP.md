# Jobsmith roadmap

Jobsmith becomes the one open-source app for the whole job hunt. It does everything please-hire-me, ai-job-search
and career-ops do, adds Simplify's extension and Cluely's notes, and runs as one app with or without AI.

## Principles (a feature that breaks one doesn't ship)

1. Never invent anything about the user. Every claim and number comes from their real facts and is checked before
   anything is sent.
2. Quality over volume. Autopilot submits only when every answer passes; anything uncertain waits for the user. We
   measure interviews, not applications.
3. Local-first. Data stays on the user's computer. No telemetry, no Jobsmith servers.
4. Works with no AI, or any AI.

## What we take from each

- **please-hire-me:** submitting on companies' own forms without the user (first one supervised), caps, a record
  of every submission, blocking AI traps in postings, real-Chrome submissions, a map of checked job boards read
  through public listing data, signed-in portals, emailed codes, skipping companies you're interviewing with.
- **ai-job-search:** fit evaluation with deal-breakers and batch ranking, tailored resume and cover letter critiqued
  by a second reviewer, PDF layout and parser-text checks, outcomes and follow-up drafts, inbox status proposed for
  approval, interview prep packs per stage, skill-gap plans, add-your-own boards and templates.
- **career-ops:** scoring where to apply, broad job sources, contacts and outreach, story bank, offer comparison and
  negotiation.
- **Simplify:** autofill extension on any posting, job board with match scores, a tracker that fills itself.
- **Cluely:** background notes and talking points, used only with consent and in practice sessions.
- **Only in Jobsmith:** a real app (dashboard, terminal, extension), no AI required, one install on six kinds of
  computer, rules enforced by tests.

**Never:** sending messages for the user, automating LinkedIn, typing passwords or creating accounts, solving
CAPTCHAs, writing facts the user doesn't have.

## Phases (each ends at a gate it must pass before the next starts)

### Phase 0 · Go public (Oct 22–31, 2026) — done except the demo video

Gate passed: clean install to the practice copy in 25 seconds. Left: the 30-second demo video.

### Phase 1 · Autopilot you can trust (November 2026) — please-hire-me layer

Detail: [PHASE1.md](PHASE1.md).

Guardrails; posting traps; confirmed submissions + stats/audit; skill extraction fix (#20); public listing data;
Greenhouse dropdowns; Ashby, Lever, SmartRecruiters, Workday, iCIMS; frames; weekly canary, "Report this form",
behaviour page, no-AI CI proof.

**Gate (also the public launch):** 80% of good matches submitted without the user, zero invented facts in a
50-application audit.

### Phase 2 · Applications that win (December 2026) — ai-job-search layer

Fit evaluation on five dimensions with deal-breakers and batch ranking feeding autopilot; full fit breakdown UI;
tailored resume per job (relevant work first, nothing outside the user's facts, PDF layout and parser-text
checked); cover letters drafted, critiqued by a second reviewer, checked for stock phrases and unsourced claims;
company research cache; salary benchmarks from user data; any OpenAI-compatible AI; dashboard test setup (Vitest).

**Gate:** 20 tailored applications in a row with zero unsupported claims, every resume readable by a job-site
parser.

### Phase 3 · Every job and every reply (January 2027) — Simplify + career-ops layer

Extension in the Chrome Web Store, autofill on any site, hand submissions logged; job board with match scores;
sources: company career pages, Wellfound, VC portfolio boards, RSS; contact discovery for outreach drafts; inbox
status changes proposed for approval, emailed codes read with an app password the user stores, follow-up drafts
never sent for the user; skip companies the user is interviewing with; learning from outcomes with a funnel report;
import from career-ops and ai-job-search folders.

**Gate:** autofill fills 90% of fields on the top 10 application systems, and the tracker misses no reply over 30
days.

### Phase 4 · Interviews and offers (February 2027)

Prep pack per interview stage from the exact posting, resume and letter sent; local transcription; notes, questions
asked and a thank-you draft; mock interviews with live talking points for practice; debriefs into the story bank;
skill-gap report with a learning plan; offer comparison with negotiation notes.

**Gate:** posting to prep notes to offer comparison without leaving Jobsmith.

### Phase 5 · Platform (March–April 2027)

Desktop app installer; plugins anyone can add (job sites, sources, resume templates, skills) with a community
directory; job-board packs for other countries; run on an always-on computer of the user's own; signed releases;
optional encrypted sync.

**Gate:** 20+ outside contributors have shipped a skill or adapter.

## Metrics

North star: interviews per hour of the user's time.

Also: good matches submitted without the user (80% by end of Phase 1), invented facts in audits (always zero),
confirmed-submission rate, reply rate vs. the user's manual rate, minutes from install to first application (under
10), outside contributors per month (5 by February 2027). Measured on the user's computer only.

## Risks

- Scope creep: phase gates.
- Low-quality submissions: answer checks, fit gate, audits.
- Job sites blocking automation: human pace, the user handles sign-ins and CAPTCHAs, canary.
- Submissions marked as bots: confirmation logging; drive the user's own Chrome if the confirmed rate is low.
- Wrong legal answers: only from the confirmed profile.
- A bigger project adding submitting: lead on the app, no-AI, import, collaborate.
- AI costs: the no-AI path.
- Maintainer burnout: co-maintainers.
