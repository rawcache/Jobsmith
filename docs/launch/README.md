# Launch drafts

Drafts only. Nothing here has been posted, and nothing in Jobsmith posts it: each one is posted by hand, from the
maintainer's own account, after the checks below.

| File | Where |
|---|---|
| [show-hn.md](show-hn.md) | Hacker News, "Show HN" |
| [reddit-cscareerquestions.md](reddit-cscareerquestions.md) | r/cscareerquestions |
| [reddit-csmajors.md](reddit-csmajors.md) | r/csMajors |
| [reddit-internships.md](reddit-internships.md) | r/internships |
| [comparison.md](comparison.md) | Linked from the posts and the README; the short "how is this different" answer |

## Before posting any of them

0. **Only after the Phase 1 gate passes.** In [docs/ROADMAP.md](../ROADMAP.md) the gate is also the public launch:
   80% of good matches sent without you and zero invented facts in a 50-application audit, both from
   `jobsmith report` on real applications.
1. **Fill in the numbers** marked `{{…}}` from `jobsmith report` on your own data, the day you post. Don't round up:
   every number in a post should be one you could show.
2. **Check every site claim** against `ats.SUPPORTED` and the README's "Supported sites" table that day. Today:
   Greenhouse, Ashby and Lever end to end. Workday stops at review, iCIMS fills step 1 of 5, SmartRecruiters fills
   the first page.
3. **Re-read the comparison** against the three projects' READMEs. Theirs change weekly; the dates in
   `comparison.md` say when it was last checked.
4. **Read each subreddit's rules** and sidebar on the day. Some allow tools only in a weekly thread, or only from
   accounts that take part in the sub. If a post doesn't fit the rules, don't post it there.
5. **The demo GIF** (README placeholder) should exist first: people click through to the README.
6. **Be there for the first few hours** to answer questions. Answer criticism of auto-applying directly (see the
   "hard questions" below); don't argue.

## Hard questions to expect, with honest answers

- **"Auto-apply tools spam recruiters."** Jobsmith applies only at or above your fit threshold, leaves out roles too
  senior, asking for more experience than you have or paying under your minimum before any browser opens, skips
  roles whose citizenship, sponsorship or degree requirements you don't meet, caps you at 20 a day and 3 per company
  a week by default, and won't send where the employer says no AI or automation. It's built to send fewer, better applications, and to tell you
  when it can't.
- **"It'll make things up."** Every written answer is checked against your resume, profile and own writing before
  it's sent, and `jobsmith audit` checks sent applications and prints each answer with what it traces to. Work
  authorization, sponsorship and demographics come only from what you confirmed. Phase 1's gate is zero invented facts in a 50-application audit:
  quote where that stands (`{{AUDIT_RESULT}}`).
- **"Is this against the job sites' terms?"** It fills the same public application forms a person fills, in a
  browser on your computer, within your daily caps. It never creates accounts, types passwords, solves CAPTCHAs
  or touches LinkedIn. You're responsible for what's sent in your name; say so.
- **"Why not just use career-ops / ai-job-search / please-hire-me?"** See `comparison.md`. They're good, and much
  bigger; credit them.
- **"What does it cost?"** Nothing. Gemini's free tier (Jobsmith stays under a daily budget), a local model, or no AI
  at all for what your profile and own writing can answer.
