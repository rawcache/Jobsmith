# r/cscareerquestions draft

Check the rules first: this sub is strict about self-promotion. If tools are only allowed in a weekly or
"projects" thread, post a shortened version there instead, or skip it.

**Title:**

> I built an open-source tool for my own internship search that applies for me, and refuses to make things up

**Body:**

Like a lot of you, I was sending the same name, school, links and "why this company" answers into Greenhouse forms
over and over. So I built Jobsmith for my own search, and it's open source (MIT): https://github.com/rawcache/Jobsmith

What it does:

- Reads job lists (GitHub internship lists, company Greenhouse, Lever and Ashby boards), scores each role against
  your resume, and leaves out roles too senior, asking for more experience than you have, or paying under your
  minimum.
- Fills and submits the application on Greenhouse, Ashby and Lever, within caps (20 a day, 3 per company a week by
  default). The first one on each site waits for you to check.
- Writes in your words: answers you've saved go in as you wrote them, then your own past writing, then the AI you
  pick, and every claim or number is checked against your resume before anything is sent. Work authorization and
  sponsorship come only from what you confirmed.
- When it's missing something, it asks once: "Confirm work authorization: unblocks 41", not 41 separate
  applications waiting.

It runs on your laptop, with no Jobsmith account or server. It's free with Gemini's free tier or a local model, and a lot
of it works with no AI at all.

What it doesn't do (yet): Workday stops at the review page, and iCIMS and SmartRecruiters only get their first page
filled. The Chrome extension isn't in the Web Store yet. And I'm still measuring it on my own applications:
{{SUBMITTED}} sent so far, {{SENT_WITHOUT_ME_PCT}} of good matches without me doing anything.

I know auto-apply tools have a bad reputation for spamming. This one is built to send fewer, better applications:
it skips roles you don't qualify for, respects postings that say no AI, and holds anything it isn't sure of. I'd
genuinely like to hear where you'd draw the line.
