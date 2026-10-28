# Saved job-board responses

Trimmed copies of real public job boards, saved 2026-10-28 with read-only GET requests (no sign-in), for
`tests/test_boards.py`. Each keeps the board API's own shape; only a handful of roles were kept, chosen to cover
internships, new grad roles, senior titles, postings asking for years of experience, and stated pay. Email
addresses in posting text are replaced with `[email removed]`; Greenhouse's internal ids and compliance fields are
dropped. No applicant data.

| File | Source |
| --- | --- |
| `greenhouse_figma.json` | `boards-api.greenhouse.io/v1/boards/figma/jobs?content=true&pay_transparency=true` |
| `lever_palantir.json` | `api.lever.co/v0/postings/palantir?mode=json` |
| `ashby_ramp.json` | `api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true` |
