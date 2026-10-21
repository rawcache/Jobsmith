---
name: jobsmith-apply
description: Find internships and new-grad roles the user qualifies for and apply to them from their real resume with Jobsmith. Use when the user asks to apply to jobs, a company, a job link, or a GitHub job list, or asks what's waiting for them.
title: Apply
status: ready
core: true
order: 10
page: #/matches
command: jobsmith apply
---

# Apply

Autopilot for applications. Jobsmith checks the user qualifies, fills each form in a real browser on their
computer, and submits only what every answer is sure about. Everything else waits for the user. The Chrome
extension adds a panel on any posting the user opens themselves: autofill, resume match, who they know there,
the cover letter, and "Write with Jobsmith" beside open questions.

## In the terminal

```
jobsmith                                  full-screen view: live applications, what needs you, the bell
jobsmith "apply to nvidia hardware internships"
jobsmith apply https://boards.greenhouse.io/acme/jobs/123
/apply   /jobs   /watch   /review   /autopilot on|off   /stop
```

## For an AI agent (Jobsmith's MCP server)

Tools: `jobsmith_status`, `jobsmith_find_jobs`, `jobsmith_job`, `jobsmith_add_jobs`, `jobsmith_apply`,
`jobsmith_pending_questions`, `jobsmith_save_answers`.

1. `jobsmith_status` first: what's running, what's held, what needs the user.
2. To apply: `jobsmith_find_jobs` (or `jobsmith_add_jobs` with a company, link or list), then `jobsmith_apply`.
3. Written questions Jobsmith couldn't answer on its own come back from `jobsmith_pending_questions`, each with
   the posting, the user's relevant facts and examples of their own writing. Write each answer **only from
   those facts**, in the user's voice (match the examples: their sentence length, their words), and send them
   with `jobsmith_save_answers` citing the fact ids you used. Jobsmith checks them and continues.

Rules: never invent experience, numbers, employers or dates. Never answer demographic or work-authorization
questions yourself; those come from the user's profile. Never type passwords, solve CAPTCHAs or create accounts.
