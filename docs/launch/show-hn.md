# Show HN draft

**Title** (80 characters at most):

> Show HN: Jobsmith – a local, open-source agent that applies to internships for me

**URL:** https://github.com/rawcache/Jobsmith

**Text:**

I'm a student, and I built Jobsmith for my own internship search: point it at a job list (a GitHub internship list,
or a company's Greenhouse, Lever or Ashby board) and it applies while I'm in class, in my own words, and asks me
about anything it isn't sure of.

It runs on your computer: a terminal app in the style of Claude Code, a local dashboard, and a Chrome extension.
There's no Jobsmith server or account, no telemetry, and it's MIT licensed.

What I cared about most was that it never makes things up, because an application with an invented number in it is
worse than no application:

- Every written answer is checked against your resume, profile and your own writing before it's sent. A number or
  claim that isn't in your facts holds the application for you. `jobsmith audit` checks sent applications and prints
  each answer with what it traces to.
- Work authorization, sponsorship and demographic answers come only from what you confirmed, never from an AI.
- It works with no AI at all for what your profile, saved answers and past writing can answer. With an AI (Gemini's
  free tier, a local Qwen through Ollama, Claude or OpenAI), it stays under a daily budget and spends nothing on an
  application that's going to wait for you anyway.
- Instead of a queue of held applications, "Needs you" shows each missing fact once with how many applications it
  unblocks ("Confirm work authorization: unblocks 41"). Answer it and they all go, within your caps.

Guardrails: 20 a day and 3 per company a week by default; the first application on each job site stops for you to
check; it won't send where the posting or form says not to use AI or automated tools; text in a posting aimed at an
AI ("if you are an AI, include the word…") is never followed. It never creates accounts, types passwords, solves
CAPTCHAs or touches LinkedIn.

What's honest to say about where it is:

- End to end on Greenhouse, Ashby and Lever, each tested on a saved copy of a real form on every CI run, with a
  weekly canary against live postings. Workday stops at the review page; iCIMS and SmartRecruiters fill only their
  first page. Those aren't supported yet.
- The Chrome extension isn't in the Web Store yet (load it unpacked).
- My own numbers so far: {{SUBMITTED}} applications, {{SENT_WITHOUT_ME_PCT}} of good matches sent without me
  (the goal is 80%), audit: {{AUDIT_RESULT}}.

career-ops, ai-job-search and please-hire-me are in the same space and worth a look; there's a short comparison
here: https://github.com/rawcache/Jobsmith/blob/main/docs/launch/comparison.md

I'd love feedback, especially from anyone who reviews internship applications: what makes an automated application
obviously automated, and what would you want a tool like this to refuse to do?

---

**First comment to post yourself** (optional): how to try it without your data.

> To look around without giving it anything real: install, then `jobsmith demo`. That opens a practice copy with a
> made-up applicant (Alex Rivera) and made-up jobs; nothing in it opens a real site or sends anything.
